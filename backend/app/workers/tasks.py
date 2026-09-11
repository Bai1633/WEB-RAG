"""Celery tasks for document processing and background jobs."""

from __future__ import annotations

import contextlib
import logging
import uuid
from uuid import UUID

from celery import Task

from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

# Module-level singleton engine to avoid per-task engine creation
_sync_engine = None
_Session = None


def _get_sync_session():
    """Get or create the module-level sync engine and session factory."""
    global _sync_engine, _Session
    if _sync_engine is None:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from app.config import get_settings

        settings = get_settings()
        _sync_engine = create_engine(settings.database_url_sync, pool_pre_ping=True)
        _Session = sessionmaker(bind=_sync_engine, expire_on_commit=False)
    return _Session()


class SQLAlchemyTask(Task):
    """Base Celery task class that manages DB session lifecycle."""

    _db_session = None

    def __call__(self, *args, **kwargs):  # type: ignore
        self._db_session = _get_sync_session()
        try:
            return self.run(*args, **kwargs)
        finally:
            self._db_session.close()


@celery_app.task(
    base=SQLAlchemyTask,
    bind=True,
    name="app.workers.tasks.process_document",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=3,
    acks_late=True,
    reject_on_worker_lost=True,
)
def process_document(self, doc_id_str: str, kb_id_str: str) -> dict:
    """Process a document: parse -> chunk -> embed -> insert into pgvector.

    Args:
        doc_id_str: Document UUID as string.
        kb_id_str: Knowledge base UUID as string.

    Returns:
        Dict with processing results.
    """
    import json

    from sqlalchemy import text

    from app.config import get_settings
    from app.core.chunking import TextChunker
    from app.core.document_parser import DocumentParser
    from app.core.embedding import get_embedding_provider
    from app.core.index_manager import VectorIndexManager
    from app.db.models import Document, DocumentStatus

    session = self._db_session
    settings = get_settings()
    doc_id = UUID(doc_id_str)
    kb_id = UUID(kb_id_str)

    # ===== Idempotency check =====
    doc = session.get(Document, doc_id)
    if not doc:
        # The API commits before enqueueing, but retries/edge cases can still
        # land here while the row is invisible to this connection
        # (READ COMMITTED). Retry with backoff instead of returning an error:
        # returning made Celery mark the task as *succeeded*, so autoretry never
        # fired and the document stayed in `queued` with no self-healing path.
        logger.warning(f"Document {doc_id} not visible yet, scheduling retry")
        raise self.retry(countdown=2, max_retries=3)

    # If already completed, skip
    if doc.status == DocumentStatus.COMPLETED:
        logger.info(f"Document {doc_id} already processed, skipping")
        return {"status": "already_completed", "doc_id": str(doc_id)}

    # If currently processing by another (non-stale) task, skip
    if (
        doc.status == DocumentStatus.PROCESSING
        and doc.task_id
        and doc.task_id != self.request.id
    ):
        logger.info(f"Document {doc_id} already being processed by another task")
        return {"status": "already_processing", "doc_id": str(doc_id)}

    # Update status to processing
    doc.status = DocumentStatus.PROCESSING
    doc.progress = 0
    doc.error = ""
    doc.task_id = self.request.id
    session.commit()

    try:
        # ===== Step 1: Parse document =====
        logger.info(f"Parsing document {doc_id}: {doc.filename}")
        parser = DocumentParser()
        parsed = parser.parse(doc.file_path, doc.mime_type)
        doc.progress = 20
        session.commit()

        if not parsed.text or not parsed.text.strip():
            raise ValueError("Document has no extractable text content")

        # ===== Step 2: Chunk text =====
        logger.info(f"Chunking document {doc_id}")
        chunker = TextChunker(
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
        )
        chunk_metadata = {
            "doc_id": str(doc_id),
            "kb_id": str(kb_id),
            "filename": doc.filename,
            "source": doc.filename,
        }
        chunk_metadata.update(parsed.metadata)

        chunks = chunker.chunk_text(parsed.text, metadata=chunk_metadata)
        doc.chunk_count = len(chunks)
        doc.progress = 40
        session.commit()

        if not chunks:
            raise ValueError("No chunks generated from document")

        logger.info(f"Generated {len(chunks)} chunks for doc {doc_id}")

        # ===== Step 3: Get embeddings =====
        logger.info(f"Generating embeddings for {len(chunks)} chunks")
        embed_provider = get_embedding_provider()
        texts = [chunk.text for chunk in chunks]
        embeddings = embed_provider.get_embeddings(texts)
        doc.progress = 70
        session.commit()

        # ===== Step 4: Insert vectors into pgvector =====
        logger.info(f"Inserting {len(embeddings)} vectors into pgvector")

        table_name = VectorIndexManager.table_name_from_str(str(kb_id))

        # Validate table name
        if not table_name.isidentifier():
            raise ValueError(f"Invalid table name: {table_name}")

        # Bulk insert
        insert_sql = f"""
            INSERT INTO {table_name} (chunk_id, doc_id, kb_id, text, metadata, embedding)
            VALUES (
                :chunk_id, :doc_id, :kb_id, :text,
                CAST(:metadata AS jsonb),
                CAST(:embedding AS vector)
            )
        """

        batch_size = 50
        for i in range(0, len(chunks), batch_size):
            batch_chunks = chunks[i : i + batch_size]
            batch_embeddings = embeddings[i : i + batch_size]
            records = []
            for chunk, embedding in zip(batch_chunks, batch_embeddings, strict=False):
                records.append(
                    {
                        "chunk_id": str(uuid.uuid4()),
                        "doc_id": str(doc_id),
                        "kb_id": str(kb_id),
                        "text": chunk.text,
                        "metadata": json.dumps(chunk.metadata),
                        "embedding": f"[{','.join(str(v) for v in embedding)}]",
                    }
                )

            for record in records:
                session.execute(text(insert_sql), record)

            session.flush()

            progress = 70 + int(30 * (i + len(batch_chunks)) / len(chunks))
            doc.progress = min(progress, 99)
            session.commit()

        # ===== Step 5: Mark completed =====
        doc.status = DocumentStatus.COMPLETED
        doc.progress = 100
        session.commit()

        logger.info(f"Document {doc_id} processed successfully: {len(chunks)} chunks")
        return {
            "status": "completed",
            "doc_id": str(doc_id),
            "chunk_count": len(chunks),
        }

    except Exception as e:
        logger.error(f"Error processing document {doc_id}: {e}", exc_info=True)
        # The failing statement aborted the transaction; roll back before any
        # further DB access, otherwise Postgres raises InFailedSqlTransaction.
        session.rollback()
        try:
            failed_doc = session.get(Document, doc_id)
            if failed_doc is not None:
                failed_doc.status = DocumentStatus.FAILED
                failed_doc.error = str(e)[:1000]
                session.commit()
        except Exception:
            session.rollback()
            logger.exception(f"Failed to mark document {doc_id} as failed")

        # Retry logic handled by Celery autoretry_for
        # But we re-raise so Celery knows it failed
        if self.request.retries < self.max_retries:
            self.retry(exc=e)
        raise


@celery_app.task(
    base=SQLAlchemyTask,
    bind=True,
    name="app.workers.tasks.cleanup_stuck_documents",
    acks_late=True,
)
def cleanup_stuck_documents(self) -> dict:
    """Periodic task: re-queue documents that never reached a terminal state.

    Two distinct failure modes are covered:

    1. Stuck in ``processing`` — the worker was killed mid-task (crash, OOM,
       deploy). Covered by ``document_processing_timeout``.
    2. Stuck in ``queued`` — the task was lost *before* any worker picked it up
       (broker restart, dropped message, or the historical "enqueue before
       commit" race). Nothing else in the system ever looks at a ``queued``
       document, so without this branch it would stay there forever.
       Covered by ``document_queued_timeout``.
    """
    import datetime

    from app.config import get_settings
    from app.db.models import Document, DocumentStatus

    session = self._db_session
    settings = get_settings()
    now = datetime.datetime.now(datetime.UTC)

    # 1) processing too long -> mark failed, then requeue
    processing_cutoff = now - datetime.timedelta(seconds=settings.document_processing_timeout)
    stuck_processing = (
        session.query(Document)
        .filter(
            Document.status == DocumentStatus.PROCESSING,
            Document.updated_at < processing_cutoff,
        )
        .all()
    )
    for doc in stuck_processing:
        logger.warning(f"Found document stuck in processing: {doc.id}, requeuing")
        doc.status = DocumentStatus.FAILED
        doc.error = (
            f"Processing timed out after {settings.document_processing_timeout}s, auto-requeuing"
        )

    # 2) queued too long -> the task never ran, requeue as-is
    queued_cutoff = now - datetime.timedelta(seconds=settings.document_queued_timeout)
    stuck_queued = (
        session.query(Document)
        .filter(
            Document.status == DocumentStatus.QUEUED,
            Document.updated_at < queued_cutoff,
        )
        .all()
    )
    for doc in stuck_queued:
        logger.warning(
            f"Found document stuck in queued for {settings.document_queued_timeout}s: "
            f"{doc.id}, requeuing"
        )
        doc.error = f"Still queued after {settings.document_queued_timeout}s, auto-requeuing"

    stale_docs = stuck_processing + stuck_queued

    # Cancel the previous task before dispatching a new one, so a late-running
    # duplicate cannot race the replacement. terminate=False: never kill a task
    # that is genuinely still working on the document.
    for doc in stale_docs:
        if doc.task_id:
            with contextlib.suppress(Exception):
                celery_app.control.revoke(doc.task_id, terminate=False)

    # Commit BEFORE enqueueing — same READ COMMITTED race as document_service:
    # the target task looks the document up on its own connection.
    session.commit()

    recovered = 0
    for doc in stale_docs:
        task = celery_app.send_task(
            "app.workers.tasks.process_document",
            args=[str(doc.id), str(doc.kb_id)],
        )
        doc.task_id = task.id
        recovered += 1

    if stale_docs:
        session.commit()

    return {
        "stuck_processing": len(stuck_processing),
        "stuck_queued": len(stuck_queued),
        "recovered": recovered,
    }


@celery_app.task(
    base=SQLAlchemyTask,
    bind=True,
    name="app.workers.tasks.delete_document_vectors",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=60,
    max_retries=2,
    acks_late=True,
)
def delete_document_vectors(self, doc_id_str: str, kb_id_str: str) -> dict:
    """Delete all vectors for a document (asynchronous cleanup)."""
    from sqlalchemy import text

    from app.core.index_manager import VectorIndexManager

    session = self._db_session
    kb_id = UUID(kb_id_str)
    doc_id = UUID(doc_id_str)

    table_name = VectorIndexManager.table_name_from_str(str(kb_id))
    if not table_name.isidentifier():
        return {"error": "Invalid table name"}

    try:
        result = session.execute(
            text(f"DELETE FROM {table_name} WHERE doc_id = :doc_id"),
            {"doc_id": doc_id},
        )
        session.commit()
        return {"deleted": result.rowcount, "doc_id": doc_id_str}
    except Exception as e:
        logger.error(f"Error deleting vectors for doc {doc_id_str}: {e}")
        return {"error": str(e)}


@celery_app.task(
    base=SQLAlchemyTask,
    bind=True,
    name="app.workers.tasks.cleanup_expired_refresh_tokens",
    acks_late=True,
)
def cleanup_expired_refresh_tokens(self) -> dict:
    """Periodic task: purge expired refresh tokens.

    Without regular cleanup, revoked/expired ``refresh_tokens`` rows accumulate
    indefinitely. Run on a schedule (e.g. daily) to keep the table bounded.
    """
    import datetime

    from sqlalchemy import delete

    from app.db.models import RefreshToken

    session = self._db_session
    now = datetime.datetime.now(datetime.UTC)

    result = session.execute(delete(RefreshToken).where(RefreshToken.expires_at < now))
    session.commit()
    return {"deleted": result.rowcount}

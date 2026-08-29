"""Chat service - business logic for RAG Q&A."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from functools import lru_cache
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.rag_engine import RAGEngine, RAGResponse
from app.db.repositories.chat_repo import ChatRepository
from app.db.repositories.document_repo import DocumentRepository

settings = get_settings()
logger = structlog.get_logger()


@lru_cache(maxsize=1)
def _get_rag_engine() -> RAGEngine:
    """Singleton RAGEngine instance."""
    return RAGEngine()


class ChatService:
    """Chat service for RAG Q&A."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.chat_repo = ChatRepository(db)
        self.doc_repo = DocumentRepository(db)
        self.rag_engine = _get_rag_engine()

    async def chat(
        self,
        kb_id: UUID,
        user_id: UUID,
        question: str,
        stream: bool = False,
        history: list[dict[str, str]] | None = None,
        conversation_id: str | None = None,
    ) -> RAGResponse | AsyncGenerator[str, None]:
        """Ask a question and get a RAG response.

        Args:
            kb_id: Knowledge base ID.
            user_id: User ID.
            question: User question.
            stream: Whether to stream the response.
            history: Previous conversation messages for multi-turn context.
            conversation_id: Session identifier. When set, only this session's
                history is used for context and new records are tagged with it.

        Returns:
            RAGResponse if stream=False, async generator if stream=True.
        """
        # Build history from DB if not provided (multi-turn context, last N rounds)
        if history is None:
            history = await self._build_history(kb_id, user_id, conversation_id)

        if stream:
            return self._chat_stream(kb_id, user_id, question, history, conversation_id)
        else:
            result = await self.rag_engine.query(
                db=self.db,
                kb_id=kb_id,
                question=question,
                stream=False,
                history=history,
            )
            assert isinstance(result, RAGResponse)

            # Save chat history
            await self._save_history(kb_id, user_id, question, result, conversation_id)

            return result

    async def _build_history(
        self, kb_id: UUID, user_id: UUID, conversation_id: str | None = None
    ) -> list[dict[str, str]]:
        """Build LLM-compatible history messages from the last N rounds.

        When conversation_id is provided, only records from that session are
        used.  Otherwise, all recent (user, kb) history is included.
        """
        try:
            records = await self.chat_repo.list_by_user_and_kb(
                user_id=user_id,
                kb_id=kb_id,
                skip=0,
                limit=settings.chat_history_rounds,
                conversation_id=conversation_id,
            )
        except Exception as e:
            logger.error("build_history_failed", error=str(e), kb_id=str(kb_id), user_id=str(user_id))
            return []

        if not records:
            return []

        messages: list[dict[str, str]] = []
        # Records are returned in DESC order (newest first). Reverse to chronological.
        for record in reversed(records):
            messages.append({"role": "user", "content": record.question})
            messages.append({"role": "assistant", "content": record.answer})

        return messages

    async def _chat_stream(
        self,
        kb_id: UUID,
        user_id: UUID,
        question: str,
        history: list[dict[str, str]] | None = None,
        conversation_id: str | None = None,
    ) -> AsyncGenerator[str, None]:
        """Stream chat response and save history when done.

        History is saved in a ``finally`` block so that a client disconnect
        (GeneratorExit raised at the yield point) still persists whatever
        partial answer was generated before the stream broke.
        """
        full_answer = ""
        sources_data: list = []
        final_data: dict = {}

        stream_gen = await self.rag_engine.query(
            db=self.db,
            kb_id=kb_id,
            question=question,
            stream=True,
            history=history,
        )

        assert hasattr(stream_gen, "__aiter__")

        try:
            async for chunk in stream_gen:
                try:
                    data = json.loads(chunk)
                    msg_type = data.get("type")

                    if msg_type == "sources":
                        sources_data = data.get("data", [])
                    elif msg_type == "content":
                        full_answer += data.get("data", "")
                    elif msg_type == "done":
                        final_data = data.get("data", {})
                    elif msg_type == "error":
                        logger.error("chat_stream_error", error=data.get("data"))
                except json.JSONDecodeError:
                    pass

                yield chunk
        finally:
            # Runs on normal completion AND on client disconnect (GeneratorExit).
            await self._save_stream_history(
                kb_id, user_id, question, full_answer, sources_data, final_data, conversation_id
            )

    async def _save_stream_history(
        self,
        kb_id: UUID,
        user_id: UUID,
        question: str,
        full_answer: str,
        sources_data: list,
        final_data: dict,
        conversation_id: str | None,
    ) -> None:
        """Build a RAGResponse from accumulated stream state and persist it."""
        if not full_answer:
            # Nothing generated (e.g. disconnected before the first token) —
            # saving an empty Q/A pair would pollute multi-turn history.
            return
        try:
            from app.core.rag_engine import RetrievedChunk

            # Build minimal RAGResponse for history
            sources = [
                RetrievedChunk(
                    chunk_id=s.get("chunk_id", ""),
                    doc_id=s.get("doc_id", ""),
                    text=s.get("text_preview", ""),
                    score=s.get("score", 0),
                    source=s.get("source", ""),
                )
                for s in sources_data
            ]

            result = RAGResponse(
                answer=full_answer,
                sources=sources,
                confidence=final_data.get("confidence", 0),
                tokens_used=final_data.get("tokens_used", 0),
                latency_ms=final_data.get("latency_ms", 0),
                refused=not sources_data,
                refusal_reason="no_sources" if not sources_data else "",
            )

            await self._save_history(kb_id, user_id, question, result, conversation_id)
        except Exception as e:
            logger.error("failed_to_save_chat_history", error=str(e))

    async def _save_history(
        self,
        kb_id: UUID,
        user_id: UUID,
        question: str,
        result: RAGResponse,
        conversation_id: str | None = None,
    ) -> None:
        """Save chat history to database."""
        try:
            sources_json = [
                {
                    "chunk_id": s.chunk_id,
                    "doc_id": s.doc_id,
                    "source": s.source,
                    "score": s.score,
                }
                for s in result.sources
            ]

            await self.chat_repo.create(
                kb_id=kb_id,
                user_id=user_id,
                question=question,
                answer=result.answer,
                sources=sources_json,
                tokens=result.tokens_used,
                latency_ms=result.latency_ms,
                conversation_id=conversation_id,
            )
        except Exception as e:
            logger.error("save_chat_history_failed", error=str(e))

    async def get_history(
        self,
        kb_id: UUID,
        user_id: UUID,
        skip: int = 0,
        limit: int = 50,
        conversation_id: str | None = None,
    ):
        """Get chat history for a user and KB. Returns (items, total_count)."""
        items = await self.chat_repo.list_by_user_and_kb(
            user_id=user_id,
            kb_id=kb_id,
            skip=skip,
            limit=limit,
            conversation_id=conversation_id,
        )
        total = await self.chat_repo.count_by_user_and_kb(
            user_id=user_id, kb_id=kb_id, conversation_id=conversation_id,
        )
        return items, total

    async def list_conversations(
        self, kb_id: UUID, user_id: UUID
    ) -> list[dict]:
        """List all conversation sessions for a user and KB."""
        return await self.chat_repo.list_conversation_ids(user_id=user_id, kb_id=kb_id)

    async def delete_conversation(
        self, kb_id: UUID, user_id: UUID, conversation_id: str
    ) -> int:
        """Delete all history entries for a specific conversation."""
        return await self.chat_repo.delete_by_conversation_id(
            user_id=user_id, kb_id=kb_id, conversation_id=conversation_id,
        )

"""Document API routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status

from app.api.deps import (
    CurrentUser,
    DBSession,
    UploadRateLimit,
    require_kb_editor,
    require_kb_viewer,
)
from app.schemas.common import make_paginated_response
from app.schemas.document import (
    DocumentResponse,
    DocumentRetryResponse,
    DocumentUploadResponse,
)
from app.services.document_service import DocumentService

router = APIRouter(prefix="/api/knowledge-bases/{kb_id}/documents", tags=["documents"])


def get_doc_service(db: DBSession) -> DocumentService:
    return DocumentService(db)


@router.get("")
async def list_documents(
    kb_id: str,
    current_user: CurrentUser,
    db: DBSession,
    doc_status: str | None = Query(None, alias="status"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    _: None = Depends(require_kb_viewer),
):
    """List documents in a knowledge base."""
    service = get_doc_service(db)
    docs = await service.list_documents(
        UUID(kb_id), status=doc_status, skip=skip, limit=limit
    )
    total = await service.count_documents(UUID(kb_id), status=doc_status)
    items = [DocumentResponse.model_validate(d) for d in docs]
    return make_paginated_response(items, total=total, skip=skip, limit=limit)


@router.post(
    "/upload",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    kb_id: str,
    current_user: CurrentUser,
    db: DBSession,
    file: Annotated[UploadFile, File()],
    rl: UploadRateLimit,
    _: None = Depends(require_kb_editor),
) -> DocumentUploadResponse:
    """Upload a document for processing."""
    service = get_doc_service(db)
    try:
        doc = await service.upload_document(UUID(kb_id), file)
        return DocumentUploadResponse(
            document_id=doc.id,
            task_id=doc.task_id or "",
            status=doc.status,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e


@router.get("/{doc_id}", response_model=DocumentResponse)
async def get_document(
    kb_id: str,
    doc_id: str,
    current_user: CurrentUser,
    db: DBSession,
    _: None = Depends(require_kb_viewer),
) -> DocumentResponse:
    """Get a document by ID."""
    service = get_doc_service(db)
    doc = await service.get_document(UUID(doc_id))
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )
    if str(doc.kb_id) != kb_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found in this knowledge base",
        )
    return DocumentResponse.model_validate(doc)


@router.delete("/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    kb_id: str,
    doc_id: str,
    current_user: CurrentUser,
    db: DBSession,
    _: None = Depends(require_kb_editor),
) -> None:
    """Delete a document and its vectors."""
    service = get_doc_service(db)
    doc = await service.get_document(UUID(doc_id))
    if not doc or str(doc.kb_id) != kb_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )
    deleted = await service.delete_document(UUID(doc_id))
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )


@router.post("/{doc_id}/retry", response_model=DocumentRetryResponse)
async def retry_document(
    kb_id: str,
    doc_id: str,
    current_user: CurrentUser,
    db: DBSession,
    _: None = Depends(require_kb_editor),
) -> DocumentRetryResponse:
    """Retry processing a failed document."""
    service = get_doc_service(db)
    try:
        doc = await service.retry_document(UUID(doc_id))
        if str(doc.kb_id) != kb_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found in this knowledge base",
            )
        return DocumentRetryResponse(
            document_id=doc.id,
            task_id=doc.task_id or "",
            status=doc.status,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e


@router.get("/{doc_id}/status")
async def get_document_status(
    kb_id: str,
    doc_id: str,
    current_user: CurrentUser,
    db: DBSession,
    _: None = Depends(require_kb_viewer),
) -> dict:
    """Get processing status of a document."""
    service = get_doc_service(db)
    try:
        return await service.get_processing_status(UUID(doc_id))
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e

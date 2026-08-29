"""Chat API routes - SSE streaming RAG Q&A."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from app.api.deps import ChatRateLimit, CurrentUser, DBSession, require_kb_viewer
from app.schemas.chat import ChatHistoryItem, ChatRequest, ChatResponse
from app.schemas.common import make_paginated_response
from app.services.chat_service import ChatService

router = APIRouter(prefix="/api/knowledge-bases/{kb_id}/chat", tags=["chat"])


def get_chat_service(db: DBSession) -> ChatService:
    return ChatService(db)


@router.post("")
async def chat(
    kb_id: UUID,
    body: ChatRequest,
    current_user: CurrentUser,
    db: DBSession,
    rl: ChatRateLimit,
    _: None = Depends(require_kb_viewer),
):
    """Ask a question to the knowledge base.

    Supports both streaming (SSE) and non-streaming responses.
    """
    service = get_chat_service(db)

    if body.stream:
        # Streaming response via SSE
        async def event_stream():
            stream = await service.chat(
                kb_id=kb_id,
                user_id=current_user.id,
                question=body.question,
                stream=True,
                history=body.history,
                conversation_id=body.conversation_id,
            )
            async for chunk in stream:
                yield f"data: {chunk}\n\n"

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    else:
        # Non-streaming response
        from app.core.rag_engine import RAGResponse

        result = await service.chat(
            kb_id=kb_id,
            user_id=current_user.id,
            question=body.question,
            stream=False,
            history=body.history,
            conversation_id=body.conversation_id,
        )
        assert isinstance(result, RAGResponse)
        return ChatResponse(
            answer=result.answer,
            sources=[
                {
                    "chunk_id": s.chunk_id,
                    "doc_id": s.doc_id,
                    "source": s.source,
                    "score": s.score,
                    "text_preview": s.text[:200],
                }
                for s in result.sources
            ],
            confidence=result.confidence,
            tokens_used=result.tokens_used,
            latency_ms=result.latency_ms,
            refused=result.refused,
            refusal_reason=result.refusal_reason,
        )


@router.get("/history")
async def get_chat_history(
    kb_id: UUID,
    current_user: CurrentUser,
    db: DBSession,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    conversation_id: str | None = Query(None, description="Filter by conversation session"),
    _: None = Depends(require_kb_viewer),
):
    """Get chat history for the current user and knowledge base."""
    service = get_chat_service(db)
    history, total = await service.get_history(
        kb_id=kb_id,
        user_id=current_user.id,
        skip=skip,
        limit=limit,
        conversation_id=conversation_id,
    )
    items = [ChatHistoryItem.model_validate(h) for h in history]
    return make_paginated_response(items, total=total, skip=skip, limit=limit)


@router.get("/conversations")
async def list_conversations(
    kb_id: UUID,
    current_user: CurrentUser,
    db: DBSession,
    _: None = Depends(require_kb_viewer),
):
    """List all conversation sessions for the current user and knowledge base."""
    service = get_chat_service(db)
    conversations = await service.list_conversations(kb_id=kb_id, user_id=current_user.id)
    return {"data": conversations}


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    kb_id: UUID,
    conversation_id: str,
    current_user: CurrentUser,
    db: DBSession,
    _: None = Depends(require_kb_viewer),
):
    """Delete all chat history for a specific conversation."""
    service = get_chat_service(db)
    deleted = await service.delete_conversation(
        kb_id=kb_id, user_id=current_user.id, conversation_id=conversation_id,
    )
    return {"deleted": deleted}

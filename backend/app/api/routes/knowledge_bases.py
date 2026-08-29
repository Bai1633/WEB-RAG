"""Knowledge base API routes."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import (
    CurrentUser,
    DBSession,
    require_kb_owner,
    require_kb_viewer,
)
from app.schemas.common import make_paginated_response
from app.schemas.knowledge_base import (
    KBCreate,
    KBMemberAdd,
    KBMemberResponse,
    KBMemberUpdate,
    KBResponse,
    KBUpdate,
)
from app.services.kb_service import KBService

router = APIRouter(prefix="/api/knowledge-bases", tags=["knowledge-bases"])


def get_kb_service(db: DBSession) -> KBService:
    return KBService(db)


@router.get("")
async def list_kbs(
    current_user: CurrentUser,
    db: DBSession,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
):
    """List all knowledge bases accessible by the current user."""
    service = get_kb_service(db)
    items = await service.list_user_kbs_with_stats(current_user.id, skip=skip, limit=limit)
    total = await service.count_user_kbs(current_user.id)
    return make_paginated_response(items, total=total, skip=skip, limit=limit)


@router.post("", response_model=KBResponse, status_code=status.HTTP_201_CREATED)
async def create_kb(
    body: KBCreate,
    current_user: CurrentUser,
    db: DBSession,
) -> KBResponse:
    """Create a new knowledge base."""
    service = get_kb_service(db)
    kb = await service.create_kb(
        owner_id=current_user.id,
        name=body.name,
        description=body.description,
        embed_model=body.embed_model,
        embed_dim=body.embed_dim,
    )
    return KBResponse.model_validate(kb)


@router.get("/{kb_id}", response_model=KBResponse)
async def get_kb(
    kb_id: str,
    current_user: CurrentUser,
    db: DBSession,
    _: None = Depends(require_kb_viewer),
) -> KBResponse:
    """Get a knowledge base by ID."""
    service = get_kb_service(db)
    kb = await service.get_kb(UUID(kb_id))
    if not kb:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge base not found",
        )
    doc_counts = await service.count_documents(UUID(kb_id))
    member_counts = await service.count_members(UUID(kb_id))
    return KBResponse.model_validate(kb).model_copy(
        update={"doc_count": doc_counts, "member_count": member_counts}
    )


@router.patch("/{kb_id}", response_model=KBResponse)
async def update_kb(
    kb_id: str,
    body: KBUpdate,
    current_user: CurrentUser,
    db: DBSession,
    _: None = Depends(require_kb_owner),
) -> KBResponse:
    """Update a knowledge base."""
    service = get_kb_service(db)
    kb = await service.update_kb(
        UUID(kb_id),
        name=body.name,
        description=body.description,
    )
    if not kb:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge base not found",
        )
    return KBResponse.model_validate(kb)


@router.delete("/{kb_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_kb(
    kb_id: str,
    current_user: CurrentUser,
    db: DBSession,
    _: None = Depends(require_kb_owner),
) -> None:
    """Delete a knowledge base and all its data."""
    service = get_kb_service(db)
    deleted = await service.delete_kb(UUID(kb_id))
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge base not found",
        )


# ===== Member (RBAC) routes =====


@router.get("/{kb_id}/members", response_model=list[KBMemberResponse])
async def list_members(
    kb_id: str,
    current_user: CurrentUser,
    db: DBSession,
    _: None = Depends(require_kb_viewer),
) -> list[KBMemberResponse]:
    """List all members of a knowledge base."""
    service = get_kb_service(db)
    members = await service.list_members(UUID(kb_id))
    return [KBMemberResponse.model_validate(m) for m in members]


@router.post("/{kb_id}/members", response_model=KBMemberResponse, status_code=status.HTTP_201_CREATED)
async def add_member(
    kb_id: str,
    body: KBMemberAdd,
    current_user: CurrentUser,
    db: DBSession,
    _: None = Depends(require_kb_owner),
) -> KBMemberResponse:
    """Add a member to a knowledge base."""
    service = get_kb_service(db)
    try:
        user_id, role = await service.add_member(
            UUID(kb_id),
            user_email=body.user_email,
            role=body.role,
        )
        return KBMemberResponse(
            kb_id=UUID(kb_id),
            user_id=user_id,
            role=role,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e


@router.patch("/{kb_id}/members/{user_id}", response_model=KBMemberResponse)
async def update_member(
    kb_id: str,
    user_id: str,
    body: KBMemberUpdate,
    current_user: CurrentUser,
    db: DBSession,
    _: None = Depends(require_kb_owner),
) -> KBMemberResponse:
    """Update a member's role."""
    service = get_kb_service(db)
    role = await service.update_member_role(UUID(kb_id), UUID(user_id), body.role)
    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Member not found",
        )
    return KBMemberResponse(
        kb_id=UUID(kb_id),
        user_id=UUID(user_id),
        role=role,
    )


@router.delete("/{kb_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    kb_id: str,
    user_id: str,
    current_user: CurrentUser,
    db: DBSession,
    _: None = Depends(require_kb_owner),
) -> None:
    """Remove a member from a knowledge base."""
    service = get_kb_service(db)
    try:
        removed = await service.remove_member(UUID(kb_id), UUID(user_id))
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Member not found",
        )

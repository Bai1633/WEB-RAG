"""Common response schemas for API standardization."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PaginationMeta(BaseModel):
    """Pagination metadata."""

    total: int = Field(description="Total number of items")
    skip: int = Field(description="Number of items skipped")
    limit: int = Field(description="Page size limit")
    has_more: bool = Field(description="Whether there are more items after this page")


def make_paginated_response(
    items: list[Any],
    total: int,
    skip: int,
    limit: int,
) -> dict[str, Any]:
    """Build a paginated response dict.

    Args:
        items: List of items for the current page.
        total: Total number of items.
        skip: Number of items skipped.
        limit: Page size limit.

    Returns:
        Dict with 'data' and 'pagination' keys.
    """
    return {
        "data": items,
        "pagination": {
            "total": total,
            "skip": skip,
            "limit": limit,
            "has_more": (skip + limit) < total,
        },
    }

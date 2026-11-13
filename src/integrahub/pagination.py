"""Pagination primitives shared by all list endpoints."""

import math
from dataclasses import dataclass

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


@dataclass(frozen=True)
class Pagination:
    """Validated page/page_size pair (1-based pages)."""

    page: int = 1
    page_size: int = DEFAULT_PAGE_SIZE

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size


def page_meta(total: int, pagination: Pagination) -> dict[str, int]:
    """Metadata describing a page of results."""
    pages = math.ceil(total / pagination.page_size) if total else 0
    return {
        "total": total,
        "page": pagination.page,
        "page_size": pagination.page_size,
        "pages": pages,
    }

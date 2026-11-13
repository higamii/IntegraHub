"""Base class and shared types for integration adapters."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, ClassVar, TypeVar

from pydantic import BaseModel, ValidationError

from integrahub.exceptions import UpstreamInvalidResponseError
from integrahub.http_client import ResilientHTTPClient

ModelT = TypeVar("ModelT", bound=BaseModel)


class NormalizedRecord(BaseModel):
    """Provider-independent representation of a fetched item."""

    external_id: str
    record_type: str
    data: dict[str, Any]


@dataclass(frozen=True)
class FetchResult:
    """What an integration returns from a single fetch."""

    records: list[NormalizedRecord]
    attempts: int


class BaseIntegration(ABC):
    """Contract implemented by every external API adapter."""

    name: ClassVar[str]
    display_name: ClassVar[str]
    description: ClassVar[str]

    def __init__(self, client: ResilientHTTPClient, base_url: str) -> None:
        self._client = client
        self.base_url = base_url.rstrip("/")

    @abstractmethod
    async def fetch(self) -> FetchResult:
        """Fetch, validate and normalize data from the external API.

        Raises:
            UpstreamError: on timeouts, HTTP errors or invalid responses.
        """

    def _validate(self, model: type[ModelT], payload: object) -> ModelT:
        """Validate an upstream JSON payload, translating failures to ``UpstreamError``."""
        try:
            return model.model_validate(payload)
        except ValidationError as exc:
            problems = "; ".join(
                f"{'.'.join(str(part) for part in err['loc'])}: {err['msg']}"
                for err in exc.errors()[:3]
            )
            raise UpstreamInvalidResponseError(
                f"{self.name}: unexpected response shape ({problems})"
            ) from exc

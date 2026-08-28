from typing import Protocol

from pydantic import Field

from app.domain.common import DomainModel


class HttpResponse(DomainModel):
    status_code: int = Field(ge=100, le=599)
    body: str
    headers: dict[str, str] = Field(default_factory=dict)


class HttpClient(Protocol):
    def get(
        self,
        url: str,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        timeout_seconds: float = 10.0,
    ) -> HttpResponse:
        """Run a GET request and return a structured response."""

    def post(
        self,
        url: str,
        body: str,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        timeout_seconds: float = 10.0,
    ) -> HttpResponse:
        """Run a POST request and return a structured response."""

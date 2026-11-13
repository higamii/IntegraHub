"""GitHub integration: public repository metadata (stars, forks, issues)."""

import datetime as dt
from collections.abc import Sequence

from pydantic import BaseModel, Field

from integrahub.http_client import ResilientHTTPClient
from integrahub.integrations.base import BaseIntegration, FetchResult, NormalizedRecord


class GitHubRepository(BaseModel):
    id: int
    full_name: str
    html_url: str
    description: str | None = None
    language: str | None = None
    stargazers_count: int = Field(ge=0)
    forks_count: int = Field(ge=0)
    open_issues_count: int = Field(ge=0)
    pushed_at: dt.datetime | None = None
    archived: bool = False


class GitHubIntegration(BaseIntegration):
    name = "github"
    display_name = "GitHub Repositories"
    description = "Public repository metadata from the GitHub REST API (token optional)."

    def __init__(
        self,
        client: ResilientHTTPClient,
        *,
        base_url: str,
        repositories: Sequence[str],
        token: str | None = None,
    ) -> None:
        super().__init__(client, base_url)
        self._repositories = list(repositories)
        self._headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            self._headers["Authorization"] = f"Bearer {token}"

    async def fetch(self) -> FetchResult:
        records: list[NormalizedRecord] = []
        attempts = 0
        for full_name in self._repositories:
            result = await self._client.get_json(
                f"{self.base_url}/repos/{full_name}",
                headers=self._headers,
                source=self.name,
            )
            attempts += result.attempts
            payload = self._validate(GitHubRepository, result.data)
            records.append(self.normalize(payload))
        return FetchResult(records=records, attempts=attempts)

    @staticmethod
    def normalize(repo: GitHubRepository) -> NormalizedRecord:
        return NormalizedRecord(
            external_id=repo.full_name.lower(),
            record_type="github_repository",
            data={
                "full_name": repo.full_name,
                "url": repo.html_url,
                "description": repo.description,
                "language": repo.language,
                "stars": repo.stargazers_count,
                "forks": repo.forks_count,
                "open_issues": repo.open_issues_count,
                "archived": repo.archived,
                "pushed_at": repo.pushed_at.isoformat() if repo.pushed_at else None,
            },
        )

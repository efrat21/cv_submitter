"""Lookup and registration for supported job-board adapters."""

from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import urlparse

from job_agent.adapters.base import BoardAdapter


class AdapterRegistry:
    """Resolve adapters by their stable board name or site domain."""

    def __init__(self) -> None:
        self._adapters: dict[str, BoardAdapter] = {}
        self._domains: dict[str, BoardAdapter] = {}

    def register(
        self,
        adapter: BoardAdapter,
        *,
        domains: Iterable[str] | None = None,
    ) -> None:
        """Register an adapter, rejecting duplicate names or domains."""
        name = adapter.board_name.casefold()
        if name in self._adapters:
            raise ValueError(f"Adapter already registered: {adapter.board_name}")

        normalized_domains = tuple(
            dict.fromkeys(
                self._normalize_domain(domain)
                for domain in (domains if domains is not None else adapter.domains)
            )
        )
        duplicates = [domain for domain in normalized_domains if domain in self._domains]
        if duplicates:
            raise ValueError(f"Adapter domains already registered: {', '.join(duplicates)}")

        self._adapters[name] = adapter
        for domain in normalized_domains:
            self._domains[domain] = adapter

    def get(self, board_name: str) -> BoardAdapter:
        """Return the adapter for a board name."""
        try:
            return self._adapters[board_name.casefold()]
        except KeyError as exc:
            raise KeyError(f"No adapter registered for board: {board_name}") from exc

    def for_url(self, url: str) -> BoardAdapter:
        """Return an exact or explicitly wildcard-registered hostname match."""
        hostname = (urlparse(url).hostname or "").casefold().removeprefix("www.")
        adapter = self._domains.get(hostname)
        if adapter is not None:
            return adapter

        wildcard_domains = sorted(
            (
                domain
                for domain in self._domains
                if domain.startswith("*.") and hostname.endswith(domain[1:])
            ),
            key=len,
            reverse=True,
        )
        if wildcard_domains:
            return self._domains[wildcard_domains[0]]
        raise KeyError(f"No adapter registered for URL: {url}")

    @staticmethod
    def _normalize_domain(domain: str) -> str:
        normalized = domain.casefold().rstrip(".")
        if normalized.startswith("*."):
            return f"*.{normalized[2:].removeprefix('www.')}"
        return normalized.removeprefix("www.")


def create_default_registry() -> AdapterRegistry:
    """Create the registry containing the supported board adapters."""
    from job_agent.adapters.devbg_adapter import DevBgAdapter
    from job_agent.adapters.jobsbg_adapter import JobsBgAdapter
    from job_agent.adapters.linkedin_adapter import LinkedInAdapter

    registry = AdapterRegistry()
    registry.register(DevBgAdapter())
    registry.register(JobsBgAdapter())
    registry.register(LinkedInAdapter(), domains=("linkedin.com", "*.linkedin.com"))
    return registry

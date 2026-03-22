"""BaseProvider abstract base class."""

from abc import ABC, abstractmethod


class BaseProvider(ABC):
    """Abstract base class for configuration providers.

    Every provider must implement read() -> dict. The pipeline calls
    providers in order, layering each result onto the config instance.
    """

    @abstractmethod
    def read(self) -> dict:
        """Return config data as a flat or nested dict."""

    @property
    def source_name(self) -> str:
        """Human-readable label for source tracking."""
        return self.__class__.__name__

    @property
    def watchable(self) -> bool:
        """Whether this provider supports hot-reload watching."""
        return False

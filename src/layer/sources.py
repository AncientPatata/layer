"""Source history tracking for layerconfig fields."""

from dataclasses import dataclass
from dataclasses import field as dc_field
from typing import Any


@dataclass
class SourceEntry:
    """One mutation event for a single field."""

    source: str  # e.g. "config.yml", "env:AK_ENDPOINT", "cli", "set()"
    value: Any  # the value that was set
    # Optionally track timestamp if needed later:
    # timestamp: float = dc_field(default_factory=time.time)


@dataclass
class SourceHistory:
    """Full history stack for a single field."""

    entries: list[SourceEntry] = dc_field(default_factory=list)

    def push(self, source: str, value: Any):
        self.entries.append(SourceEntry(source=source, value=value))

    @property
    def current(self) -> str:
        """The most recent source tag (backward-compatible with old _sources[name])."""
        return self.entries[-1].source if self.entries else "default"

    @property
    def current_value(self) -> Any:
        return self.entries[-1].value if self.entries else None

    def all_sources(self) -> list[str]:
        """Return list of source tags in chronological order."""
        return [e.source for e in self.entries]

    def __repr__(self):
        return f"SourceHistory({self.all_sources()})"

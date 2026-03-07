"""Memory system errors."""


class MemoryReadOnlyError(Exception):
    """Raised when attempting to mutate a read-only memory version."""

    def __init__(self, name: str, version: int, source: str) -> None:
        self.name = name
        self.version = version
        self.source = source
        super().__init__(
            f"memory '{name}' version {version} is read-only (source={source})"
        )

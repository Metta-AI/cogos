"""CapabilitiesDirectory — discovery interface for process capabilities."""

from __future__ import annotations

from cogos.capabilities.base import Capability


class CapabilitiesDirectory:
    """Directory of capabilities available to the current process.

    Usage:
        capabilities.list()          # list all (up to max)
        capabilities.count()         # total number of capabilities
        capabilities.search("email") # search by keyword
        capabilities.help()          # describe the directory itself
    """

    def __init__(self, entries: dict[str, Capability]) -> None:
        self._entries = entries

    def list(self, max: int = 10) -> list[str]:
        """List capability names with a one-line description each."""
        results: list[str] = []
        for name, cap in sorted(self._entries.items()):
            if len(results) >= max:
                break
            doc = type(cap).__doc__
            summary = doc.strip().split("\n")[0] if doc else ""
            results.append(f"{name}: {summary}")
        return results

    def count(self) -> int:
        """Return the total number of available capabilities."""
        return len(self._entries)

    def search(self, query: str) -> list[str]:
        """Search capabilities by keyword. Returns matching help texts."""
        q = query.lower()
        results: list[str] = []
        for name, cap in sorted(self._entries.items()):
            help_text = cap.help()
            if q in name.lower() or q in help_text.lower():
                results.append(f"## {name}\n{help_text}")
        return results

    def help(self) -> str:
        """Describe the CapabilitiesDirectory and how to use it."""
        return (
            "CapabilitiesDirectory — discover available capabilities\n"
            "\n"
            "  capabilities.list(max=10)    -> list[str]   names with one-line descriptions\n"
            "  capabilities.count()         -> int         total number of capabilities\n"
            "  capabilities.search(query)   -> list[str]   search by keyword, returns help texts\n"
            "\n"
            "Each capability supports .help() for full method signatures and IO schemas.\n"
            "Example:\n"
            "  print(files.help())\n"
            "  print(capabilities.search('email'))"
        )

    def __repr__(self) -> str:
        names = ", ".join(sorted(self._entries.keys()))
        return f"<CapabilitiesDirectory [{names}]>"

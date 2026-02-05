"""Base classes for log parsers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class LogSection:
    """A parsed section of a log file."""

    name: str
    display_name: str
    content: str | None = None
    error: str | None = None


class LogParser(ABC):
    """Base class for log parsers."""

    @abstractmethod
    def name(self) -> str:
        """Return the parser name."""
        pass

    @abstractmethod
    def detect(self, log_lines: list[str]) -> bool:
        """
        Detect if this parser applies to the given log.

        Args:
            log_lines: Lines of the log file

        Returns:
            True if this parser should be used for the log
        """
        pass

    @abstractmethod
    def parse(self, log_lines: list[str]) -> dict[str, LogSection]:
        """
        Parse log and return structured sections.

        Args:
            log_lines: Lines of the log file

        Returns:
            Dictionary mapping section names to LogSection objects
        """
        pass

    @abstractmethod
    def get_section_names(self) -> list[str]:
        """
        Return list of section names this parser provides.

        Returns:
            List of section identifiers (e.g., ['slow', 'warnings', 'coverage'])
        """
        pass

    @abstractmethod
    def get_section_display_name(self, section_name: str) -> str:
        """
        Get display name for a section.

        Args:
            section_name: Internal section identifier

        Returns:
            Human-readable display name
        """
        pass


class DefaultParser(LogParser):
    """Default parser that just shows raw log."""

    def name(self) -> str:
        return "default"

    def detect(self, log_lines: list[str]) -> bool:
        # Always matches as fallback
        return True

    def parse(self, log_lines: list[str]) -> dict[str, LogSection]:
        return {}

    def get_section_names(self) -> list[str]:
        return []

    def get_section_display_name(self, section_name: str) -> str:
        return section_name.title()

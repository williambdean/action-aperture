"""Log parser plugins for various CI/CD tools."""

from __future__ import annotations

from .base import DefaultParser, LogParser, LogSection
from .pytest import PytestParser

__all__ = [
    "LogParser",
    "LogSection",
    "DefaultParser",
    "PytestParser",
    "AVAILABLE_PARSERS",
]

AVAILABLE_PARSERS: list[type[LogParser]] = [
    PytestParser,
    # Future parsers can be added here
]


def detect_parser(log_lines: list[str]) -> LogParser:
    """
    Auto-detect appropriate parser for log content.

    Args:
        log_lines: Lines from the log file

    Returns:
        LogParser instance that best matches the log content
    """
    for parser_class in AVAILABLE_PARSERS:
        parser = parser_class()
        if parser.detect(log_lines):
            return parser
    return DefaultParser()

"""Pytest log parser."""

from __future__ import annotations

import re

from .base import LogParser, LogSection

# Pytest-specific patterns
SLOWEST_START_PATTERN = re.compile(r"=+ slowest \d+ durations =+")
SLOWEST_SEPARATOR_PATTERN = re.compile(r"====")
SLOWEST_TIME_PATTERN = re.compile(r"(\d+\.\d+)s ")

WARNINGS_START_PATTERN = re.compile(r"=+ warnings summary =+")
# Warnings section ends with a line that starts with "==" and has text (new section marker)
# This is more specific than just "any line with equals"
WARNINGS_END_PATTERN = re.compile(r"^=+\s+\w+")

COVERAGE_START_PATTERN = re.compile(r"=+ tests coverage =+")
SEPARATOR_PATTERN = re.compile(r"={10,}")

DATETIME_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d*Z ")
LOG_PREFIX_PATTERN = re.compile(
    r"^.*?\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d*)?Z\s*"
)


def strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences from text."""
    ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
    return ansi_escape.sub("", text)


def trim_up_to_match(pattern: re.Pattern, string: str) -> str:
    """Trim string up to (but not including) pattern match."""
    match = pattern.search(string)
    if not match:
        return ""
    return string[match.start() :]


def trim_through_match(pattern: re.Pattern, string: str) -> str:
    """Trim string up to and including pattern match."""
    match = pattern.search(string)
    if not match:
        return ""
    return string[match.end() :]


def trim(
    pattern: re.Pattern, lines: list[str], *, including: bool = False
) -> list[str]:
    """Trim pattern from all lines."""
    _trim = trim_through_match if including else trim_up_to_match
    return [_trim(pattern, line) for line in lines]


def extract_section(
    lines: list[str],
    start_pattern: re.Pattern,
    end_pattern: re.Pattern,
    *,
    drop_last: bool = False,
) -> list[str]:
    """Extract a section from log lines between two patterns."""
    section: list[str] = []
    in_section = False
    for line in lines:
        detect_start = start_pattern.search(line)
        detect_end = end_pattern.search(line)

        if detect_start:
            in_section = True

        if in_section:
            section.append(line)

        if not detect_start and in_section and detect_end:
            break
    if drop_last and section:
        return section[:-1]
    return section


def format_slowest_lines(lines: list[str]) -> list[str]:
    """Format slowest test lines."""
    if not lines:
        return []
    parts: list[str] = []
    parts.extend(trim(SLOWEST_SEPARATOR_PATTERN, lines[:1]))
    if len(lines) > 2:
        parts.extend(trim(SLOWEST_TIME_PATTERN, lines[1:-1]))
    parts.extend(
        [strip_ansi(line) for line in trim(SLOWEST_SEPARATOR_PATTERN, lines[-1:])]
    )
    return parts


def parse_slowest_lines(lines: list[str]) -> str | None:
    """Parse slowest tests section from log."""
    section = extract_section(lines, SLOWEST_START_PATTERN, SLOWEST_SEPARATOR_PATTERN)
    if not section:
        return None
    formatted = format_slowest_lines(section)
    if not formatted:
        return None
    return "\n".join(formatted).strip()


def format_warnings_lines(lines: list[str]) -> list[str]:
    """Format warnings lines."""
    if not lines:
        return []
    # First line is the header (=== warnings summary ===)
    # Last line would be the end marker, but we drop it with drop_last=True
    # Just return all lines as-is since prefixes are already stripped
    return lines


def parse_warnings_lines(lines: list[str]) -> str | None:
    """Parse warnings section from log."""
    section = extract_section(
        lines, WARNINGS_START_PATTERN, WARNINGS_END_PATTERN, drop_last=True
    )
    if not section:
        return None
    formatted = format_warnings_lines(section)
    if not formatted:
        return None
    return "\n".join(formatted).strip()


def parse_coverage_lines(lines: list[str]) -> str | None:
    """Parse coverage section from log."""
    section = extract_section(
        lines, COVERAGE_START_PATTERN, SEPARATOR_PATTERN, drop_last=True
    )
    if not section:
        return None
    return "\n".join(section).strip()


class PytestParser(LogParser):
    """Parser for pytest test logs."""

    def name(self) -> str:
        return "pytest"

    def detect(self, log_lines: list[str]) -> bool:
        """
        Detect if log is from pytest.

        Looks for pytest-specific markers like slowest tests section,
        warnings summary, or coverage reports.

        Checks both the beginning and end of the log since pytest output
        often appears at the end after setup steps.
        """
        # Check first 500 and last 1000 lines (pytest output is usually at the end)
        lines_to_check = log_lines[:500] + log_lines[-1000:]

        # Strip ANSI codes before checking patterns
        cleaned_lines = [strip_ansi(line) for line in lines_to_check]
        log_text = "\n".join(cleaned_lines)

        return bool(
            SLOWEST_START_PATTERN.search(log_text)
            or WARNINGS_START_PATTERN.search(log_text)
            or COVERAGE_START_PATTERN.search(log_text)
        )

    def parse(self, log_lines: list[str]) -> dict[str, LogSection]:
        """Parse pytest log and extract sections."""
        sections: dict[str, LogSection] = {}

        # Strip log prefixes (timestamps, step names) from ALL lines first
        # This makes pattern matching much more reliable
        cleaned_lines = [LOG_PREFIX_PATTERN.sub("", line) for line in log_lines]

        # Parse slowest tests
        slow_text = parse_slowest_lines(cleaned_lines)
        sections["slow"] = LogSection(
            name="slow",
            display_name="Slowest durations",
            content=slow_text,
            error=None if slow_text else "No slowest block detected in the log.",
        )

        # Parse warnings
        warnings_text = parse_warnings_lines(cleaned_lines)
        sections["warnings"] = LogSection(
            name="warnings",
            display_name="Warnings summary",
            content=warnings_text,
            error=None if warnings_text else "No warnings summary detected in the log.",
        )

        # Parse coverage
        coverage_text = parse_coverage_lines(cleaned_lines)
        sections["coverage"] = LogSection(
            name="coverage",
            display_name="Test coverage",
            content=coverage_text,
            error=None if coverage_text else "No coverage block detected in the log.",
        )

        return sections

    def get_section_names(self) -> list[str]:
        """Return section names provided by pytest parser."""
        return ["slow", "warnings", "coverage"]

    def get_section_display_name(self, section_name: str) -> str:
        """Get display name for a section."""
        display_names = {
            "slow": "Slowest durations",
            "warnings": "Warnings summary",
            "coverage": "Test coverage",
        }
        return display_names.get(section_name, section_name.title())

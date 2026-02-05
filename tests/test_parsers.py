"""Tests for log parsers."""

from pathlib import Path

import pytest

from aperture.parsers import detect_parser
from aperture.parsers.pytest import PytestParser

# Get fixtures directory
FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def pymc_marketing_log():
    """Load pymc-marketing test log."""
    log_file = FIXTURES_DIR / "pymc-marketing-test.log"
    if not log_file.exists():
        pytest.skip(f"Fixture not found: {log_file}")
    with open(log_file) as f:
        return f.read()


@pytest.fixture
def conjugate_log():
    """Load conjugate test log."""
    log_file = FIXTURES_DIR / "conjugate-test.log"
    if not log_file.exists():
        pytest.skip(f"Fixture not found: {log_file}")
    with open(log_file) as f:
        return f.read()


@pytest.fixture
def latent_calendar_log():
    """Load latent-calendar test log."""
    log_file = FIXTURES_DIR / "latent-calendar-test.log"
    if not log_file.exists():
        pytest.skip(f"Fixture not found: {log_file}")
    with open(log_file) as f:
        return f.read()


class TestPytestParser:
    """Test pytest parser."""

    def test_detection_pymc_marketing(self, pymc_marketing_log):
        """Test pytest detection on pymc-marketing log."""
        lines = pymc_marketing_log.splitlines()
        parser = detect_parser(lines)
        assert isinstance(parser, PytestParser)
        assert parser.name() == "pytest"

    def test_detection_conjugate(self, conjugate_log):
        """Test parser detection on conjugate log."""
        lines = conjugate_log.splitlines()
        parser = detect_parser(lines)
        # May or may not be pytest, just ensure detection works
        assert parser is not None

    def test_detection_latent_calendar(self, latent_calendar_log):
        """Test parser detection on latent-calendar log."""
        lines = latent_calendar_log.splitlines()
        parser = detect_parser(lines)
        # May or may not be pytest, just ensure detection works
        assert parser is not None

    def test_warnings_parsing_pymc_marketing(self, pymc_marketing_log):
        """Test warnings section parsing on pymc-marketing log."""
        lines = pymc_marketing_log.splitlines()
        parser = PytestParser()
        sections = parser.parse(lines)

        assert "warnings" in sections
        warnings_section = sections["warnings"]

        # Should have content
        assert warnings_section.content is not None
        assert len(warnings_section.content) > 0

        # Should contain key warning markers
        assert "warnings summary" in warnings_section.content
        # Should have actual warnings
        assert (
            "Warning" in warnings_section.content
            or "warning" in warnings_section.content
        )

        # Should end with the docs link
        assert "https://docs.pytest.org" in warnings_section.content

        # Print for manual inspection
        print("\n" + "=" * 80)
        print("WARNINGS SECTION CONTENT:")
        print("=" * 80)
        print(warnings_section.content)
        print("=" * 80)
        print(f"Content length: {len(warnings_section.content)} characters")
        print(f"Number of lines: {len(warnings_section.content.splitlines())}")

    def test_slowest_parsing_pymc_marketing(self, pymc_marketing_log):
        """Test slowest section parsing on pymc-marketing log."""
        lines = pymc_marketing_log.splitlines()
        parser = PytestParser()
        sections = parser.parse(lines)

        assert "slow" in sections
        slow_section = sections["slow"]

        # Should have content
        assert slow_section.content is not None
        assert len(slow_section.content) > 0

        # Should contain slowest durations marker
        assert "slowest" in slow_section.content.lower()

        print("\n" + "=" * 80)
        print("SLOWEST SECTION CONTENT:")
        print("=" * 80)
        print(slow_section.content)
        print("=" * 80)

    def test_coverage_parsing_pymc_marketing(self, pymc_marketing_log):
        """Test coverage section parsing on pymc-marketing log."""
        lines = pymc_marketing_log.splitlines()
        parser = PytestParser()
        sections = parser.parse(lines)

        assert "coverage" in sections
        coverage_section = sections["coverage"]

        # Should have content
        assert coverage_section.content is not None
        assert len(coverage_section.content) > 0

        # Should contain coverage markers
        assert "coverage" in coverage_section.content.lower()
        assert (
            "Stmts" in coverage_section.content or "Cover" in coverage_section.content
        )

        print("\n" + "=" * 80)
        print("COVERAGE SECTION CONTENT:")
        print("=" * 80)
        print(coverage_section.content[:1000])  # First 1000 chars
        print("...")
        print("=" * 80)

    def test_no_log_prefixes_in_output(self, pymc_marketing_log):
        """Ensure log prefixes are stripped from parsed output."""
        lines = pymc_marketing_log.splitlines()
        parser = PytestParser()
        sections = parser.parse(lines)

        for section_name, section in sections.items():
            if section.content:
                # Should not contain timestamps
                assert "2026-02-05T" not in section.content, (
                    f"Section '{section_name}' contains timestamp prefixes"
                )
                # Should not contain UNKNOWN STEP
                assert "UNKNOWN STEP" not in section.content, (
                    f"Section '{section_name}' contains step prefixes"
                )


class TestWarningsExtraction:
    """Detailed tests for warnings section extraction."""

    def test_warnings_contains_all_warning_types(self, pymc_marketing_log):
        """Verify all warning types are captured."""
        lines = pymc_marketing_log.splitlines()
        parser = PytestParser()
        sections = parser.parse(lines)

        warnings_content = sections["warnings"].content
        assert warnings_content is not None

        # Check for specific warnings we know exist
        assert "FutureWarning" in warnings_content
        assert (
            "DeprecationWarning" in warnings_content
            or "PydanticDeprecatedSince20" in warnings_content
        )
        assert "UserWarning" in warnings_content

    def test_warnings_ends_correctly(self, pymc_marketing_log):
        """Verify warnings section ends at the right place."""
        lines = pymc_marketing_log.splitlines()
        parser = PytestParser()
        sections = parser.parse(lines)

        warnings_content = sections["warnings"].content
        assert warnings_content is not None

        # Should end with the docs link
        assert warnings_content.strip().endswith(
            "https://docs.pytest.org/en/stable/how-to/capture-warnings.html"
        )

        # Should NOT include coverage section
        assert "tests coverage" not in warnings_content.lower()
        assert "Stmts   Miss  Cover" not in warnings_content

"""Custom widgets for Action Aperture."""

from __future__ import annotations

from textual.widgets import ListItem, Static

from ..core import JobInfo, RunInfo


class JobListItem(ListItem):
    """List item for displaying job information."""

    def __init__(self, job: JobInfo) -> None:
        text = f"{job.name} ({job.duration_str})"
        super().__init__(Static(text, expand=False))
        self.job = job


class WorkflowListItem(ListItem):
    """List item for displaying workflow name."""

    def __init__(self, name: str) -> None:
        super().__init__(Static(name))
        self.workflow_name = name


class RunListItem(ListItem):
    """List item for displaying run information."""

    def __init__(self, run: RunInfo) -> None:
        # Format: "#123 • main • 2024-01-15 14:30 • user123 • commit message"
        parts = []
        if run.run_number:
            parts.append(f"#{run.run_number}")
        if run.head_branch:
            parts.append(run.head_branch)
        parts.append(run.formatted_date)
        if run.actor:
            parts.append(f"@{run.actor}")
        parts.append(run.short_sha)

        # Truncate display title if too long
        title = run.display_title
        if len(title) > 60:
            title = title[:57] + "..."
        parts.append(title)

        text = " • ".join(parts)
        super().__init__(Static(text))
        self.run = run


def fuzzy_match(pattern: str, text: str) -> bool:
    """Perform fuzzy matching on text."""
    pattern = pattern.lower()
    text = text.lower()
    p_idx, t_idx = 0, 0
    while p_idx < len(pattern) and t_idx < len(text):
        if pattern[p_idx] == text[t_idx]:
            p_idx += 1
        t_idx += 1
    return p_idx == len(pattern)

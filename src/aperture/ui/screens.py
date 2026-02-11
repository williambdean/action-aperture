"""Screen components for Action Aperture."""

from __future__ import annotations

import asyncio
import subprocess
from itertools import cycle
from typing import Literal, cast

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Label, ListView, Static

from ..core import JobInfo, RunInfo, fetch_job_log
from ..parsers import detect_parser
from ..parsers.pytest import LOG_PREFIX_PATTERN
from .widgets import JobListItem, RunListItem, WorkflowListItem, fuzzy_match

DetailMode = Literal["slow", "warnings", "coverage", "raw"]


class LoadingScreen(Screen):
    """Loading screen displayed during async operations."""

    CSS = """
    LoadingScreen {
        align: center middle;
    }

    #loading-label {
        text-align: center;
    }
    """

    def __init__(self, message: str = "Loading") -> None:
        super().__init__()
        self.message = message
        self._spinner_symbols = cycle("⠋⠙⠹⠸⠼⠴⠦⠧")
        self._spinner_frame = next(self._spinner_symbols)

    def compose(self) -> ComposeResult:
        yield Label(f"{self._spinner_frame} {self.message}…", id="loading-label")

    async def on_mount(self) -> None:
        """Start spinner animation when screen is mounted."""
        self.set_interval(0.1, self._advance_spinner)

    def _advance_spinner(self) -> None:
        """Advance loading spinner animation."""
        self._spinner_frame = next(self._spinner_symbols)
        loading_label = self.query_one("#loading-label", Label)
        loading_label.update(f"{self._spinner_frame} {self.message}…")

    def update_message(self, message: str) -> None:
        """Update the loading message."""
        self.message = message
        loading_label = self.query_one("#loading-label", Label)
        loading_label.update(f"{self._spinner_frame} {message}…")


class ConfirmationScreen(Screen[bool]):
    """Confirmation dialog screen."""

    CSS = """
    ConfirmationScreen {
        align: center middle;
    }

    #confirm-dialog {
        width: 60;
        height: auto;
        border: solid $accent;
        background: $surface;
        padding: 2;
    }

    #confirm-message {
        text-align: center;
        width: 100%;
        padding-bottom: 2;
    }

    #confirm-buttons {
        align: center middle;
        height: auto;
    }

    #confirm-buttons Button {
        margin: 0 1;
    }
    """

    BINDINGS = [
        ("y", "confirm_yes", "Yes"),
        ("n", "confirm_no", "No"),
        ("escape", "confirm_no", "Cancel"),
    ]

    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-dialog"):
            yield Label(self.message, id="confirm-message")
            with Horizontal(id="confirm-buttons"):
                yield Button("Yes (y)", variant="primary", id="btn-yes")
                yield Button("No (n)", variant="default", id="btn-no")

    def action_confirm_yes(self) -> None:
        self.dismiss(True)

    def action_confirm_no(self) -> None:
        self.dismiss(False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-yes":
            self.dismiss(True)
        elif event.button.id == "btn-no":
            self.dismiss(False)


class WorkflowPickerScreen(Screen[str]):
    """Screen for selecting a workflow."""

    CSS = """
    WorkflowPickerScreen {
        align: center middle;
    }

    #picker-container {
        width: 80%;
        height: 80%;
        border: solid $accent;
        background: $surface;
    }

    .picker-label {
        padding: 1;
        text-align: center;
        width: 100%;
        text-style: bold;
    }

    #workflow-search {
        margin: 0 1;
        width: auto;
    }

    #workflow-list {
        height: 1fr;
        margin-top: 1;
        border: none;
    }
    """

    def __init__(self, workflows: list[str], repo: str) -> None:
        super().__init__()
        self.workflows = workflows
        self.repo = repo

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="picker-container"):
            yield Label(
                f"Select a workflow for {self.repo}:",
                classes="picker-label",
            )
            yield Input(placeholder="Search workflows...", id="workflow-search")
            yield ListView(
                *[WorkflowListItem(w) for w in self.workflows], id="workflow-list"
            )
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#workflow-search").focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        pattern = event.value
        filtered = [w for w in self.workflows if fuzzy_match(pattern, w)]

        list_view = self.query_one("#workflow-list", ListView)
        list_view.clear()
        for w in filtered:
            list_view.append(WorkflowListItem(w))

        if filtered:
            list_view.index = 0

    def on_input_submitted(self, event: Input.Submitted) -> None:
        list_view = self.query_one("#workflow-list", ListView)
        if list_view.children:
            # Select current index if available, otherwise first item
            index = list_view.index if list_view.index is not None else 0
            if index < len(list_view.children):
                item = list_view.children[index]
                if isinstance(item, WorkflowListItem):
                    self.dismiss(item.workflow_name)

    def on_key(self, event) -> None:
        if event.key in ("down", "up", "enter", "j", "k"):
            list_view = self.query_one("#workflow-list", ListView)
            if not list_view.children:
                return

            if event.key in ("down", "j"):
                if list_view.index is None:
                    list_view.index = 0
                else:
                    list_view.index = min(
                        len(list_view.children) - 1, list_view.index + 1
                    )
            elif event.key in ("up", "k"):
                if list_view.index is None:
                    list_view.index = len(list_view.children) - 1
                else:
                    list_view.index = max(0, list_view.index - 1)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if isinstance(event.item, WorkflowListItem):
            self.dismiss(event.item.workflow_name)


class RunPickerScreen(Screen[RunInfo | None]):
    """Screen for selecting a workflow run."""

    CSS = """
    RunPickerScreen {
        align: center middle;
    }

    #run-picker-container {
        width: 90%;
        height: 80%;
        border: solid $accent;
        background: $surface;
    }

    .run-picker-label {
        padding: 1;
        text-align: center;
        width: 100%;
        text-style: bold;
    }

    #run-list {
        height: 1fr;
        margin-top: 1;
        border: none;
    }
    """

    BINDINGS = [
        ("escape", "go_back", "Back"),
        ("j", "move_down", "Next"),
        ("k", "move_up", "Previous"),
    ]

    def __init__(self, runs: list[RunInfo], repo: str, workflow: str) -> None:
        super().__init__()
        self.runs = runs
        self.repo = repo
        self.workflow = workflow

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="run-picker-container"):
            yield Label(
                f"Select a run from '{self.workflow}' workflow ({self.repo}):",
                classes="run-picker-label",
            )
            yield ListView(*[RunListItem(r) for r in self.runs], id="run-list")
        yield Footer()

    def on_mount(self) -> None:
        list_view = self.query_one("#run-list", ListView)
        if self.runs:
            list_view.index = 0
        list_view.focus()

    def action_go_back(self) -> None:
        self.dismiss(None)

    def action_move_down(self) -> None:
        list_view = self.query_one("#run-list", ListView)
        if not list_view.children:
            return
        if list_view.index is None:
            list_view.index = 0
        else:
            list_view.index = min(len(list_view.children) - 1, list_view.index + 1)

    def action_move_up(self) -> None:
        list_view = self.query_one("#run-list", ListView)
        if not list_view.children:
            return
        if list_view.index is None:
            list_view.index = len(list_view.children) - 1
        else:
            list_view.index = max(0, list_view.index - 1)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if isinstance(event.item, RunListItem):
            self.dismiss(event.item.run)


class JobListView(ListView):
    """Custom ListView for jobs."""

    pass


class JobViewScreen(Screen):
    """Main screen for viewing job logs and details."""

    CSS = """
    JobViewScreen {
        background: $surface;
    }

    #job-list {
        border: solid $accent;
        width: 25%;
    }

    #detail-panel {
        border: solid $secondary;
        padding: 1 1;
        width: 75%;
    }

    #mode-buttons {
        padding-bottom: 0;
        margin-bottom: 0;
        align: center top;
        height: auto;
    }

    Button.mode-active {
        background: $primary;
        color: $text;
        text-style: bold;
        border: none;
    }

    Button.mode-inactive {
        background: $surface;
        color: $text-muted;
        border: none;
    }

    #detail-scroll-container {
        height: 100%;
        width: 100%;
        overflow: auto;
    }

    #detail-log {
        height: auto;
        width: auto;
        text-wrap: nowrap;
    }

    Vertical#detail-panel.fullscreen {
        width: 100%;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh jobs"),
        ("enter", "fetch", "Refresh details"),
        ("t", "toggle", "Toggle mode"),
        ("T", "toggle_back", "Toggle mode back"),
        ("j", "move_down", "Next job"),
        ("k", "move_up", "Previous job"),
        ("left", "mode_left", "Previous mode"),
        ("right", "mode_right", "Next mode"),
        ("h", "mode_left", "Previous mode"),
        ("l", "mode_right", "Next mode"),
        ("F", "toggle_detail_view", "Toggle sidebar"),
        ("escape", "go_back", "Back to runs"),
        ("up", "scroll_or_move_up", "Scroll/Move up"),
        ("down", "scroll_or_move_down", "Scroll/Move down"),
        ("u", "page_up", "Page up"),
        ("d", "page_down", "Page down"),
        ("c", "copy_log", "Copy log"),
    ]

    def __init__(
        self,
        run_id: str,
        run_url: str,
        jobs: list[JobInfo],
        repo: str,
        run_info: RunInfo | None = None,
        initial_job: JobInfo | None = None,
    ) -> None:
        super().__init__()
        self.run_id = run_id
        self.run_url = run_url
        self.repo = repo
        self.run_info = run_info
        self.jobs = jobs
        self.initial_job = initial_job
        self.detail_mode: DetailMode = "slow"
        self.detail_log = Static(id="detail-log", markup=False)
        self.detail_log.can_focus = False
        self.selected_job: JobInfo | None = None
        self.pending_fetches: dict[tuple[int, str], asyncio.Task[None]] = {}
        self._spinner_symbols = cycle("⠋⠙⠹⠸⠼⠴⠦⠧")
        self._spinner_frame = next(self._spinner_symbols)
        self.detail_fullscreen = True
        self._detail_panel: Vertical | None = None
        self.mode_buttons: dict[str, Button] = {}
        self.available_modes: list[str] = []
        self._updating_buttons = False
        self._last_parser_name: str | None = None
        # Store scroll positions per job per mode: {job_id: {mode: (scroll_x, scroll_y)}}
        self._scroll_positions: dict[int, dict[str, tuple[int, int]]] = {}

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal():
            self.list_view = JobListView(
                *[JobListItem(job) for job in self.jobs],
                id="job-list",
            )
            yield self.list_view
            with Vertical(id="detail-panel") as detail_panel:
                with Horizontal(id="mode-buttons"):
                    # We'll dynamically create buttons based on parser
                    pass
                with Vertical(id="detail-scroll-container"):
                    yield self.detail_log
            self._detail_panel = detail_panel
        yield Footer()

    async def on_mount(self) -> None:
        if self.initial_job:
            await self.select_job(self.initial_job)
        elif self.jobs:
            await self.focus_job(0)
        self.set_interval(0.1, self._advance_spinner)
        if not self._detail_panel:
            self._detail_panel = self.query_one("#detail-panel", Vertical)

        self.list_view.styles.display = "none" if self.detail_fullscreen else None
        if self._detail_panel:
            self._detail_panel.set_class(self.detail_fullscreen, "fullscreen")

        scroll_container = self.query_one("#detail-scroll-container", Vertical)
        scroll_container.can_focus = True

    async def focus_job(self, index: int) -> None:
        self.list_view.index = index
        await self.select_current_job()

    async def select_current_job(self) -> None:
        if not self.list_view.children:
            return
        if self.list_view.index is None:
            return
        selected = self.list_view.children[self.list_view.index]
        if isinstance(selected, JobListItem):
            await self.select_job(selected.job)

    async def select_job(self, job: JobInfo) -> None:
        # Save scroll position of current job before switching
        self._save_scroll_position()

        self.selected_job = job
        self.detail_log.update(f"Fetching data for {job.name}…")
        await self.fetch_and_parse_log(job)
        self.render_detail(job)

    async def fetch_and_parse_log(self, job: JobInfo) -> None:
        """Fetch and parse log if not already done."""
        if job.raw_log is not None and job.raw_log != "":
            # Already fetched - recreate buttons for this job
            if (
                hasattr(job, "parser_name")
                and job.parser_name
                and hasattr(job, "parsed_sections")
            ):
                # Recreate parser to update buttons
                from ..parsers import detect_parser

                lines = job.raw_log.splitlines()
                parser = detect_parser(lines)
                self.available_modes = parser.get_section_names()

                # Always update buttons when switching jobs
                self._update_mode_buttons(parser)
                self._last_parser_name = parser.name()

                # Validate current mode is available for this parser
                valid_modes = self.available_modes + ["raw"]
                if self.detail_mode not in valid_modes:
                    # Reset to first available mode or raw
                    self.detail_mode = cast(
                        DetailMode,
                        self.available_modes[0] if self.available_modes else "raw",
                    )
            return

        key = (job.id, "fetch")
        if key in self.pending_fetches:
            # Already fetching
            return

        fetch_task = asyncio.create_task(self._fetch_and_parse(job))
        self.pending_fetches[key] = fetch_task

    async def _fetch_and_parse(self, job: JobInfo) -> None:
        """Fetch log and parse with appropriate parser."""
        key = (job.id, "fetch")
        try:
            raw_log = await asyncio.to_thread(
                fetch_job_log, job.id, self.run_id, self.repo
            )
            job.raw_log = raw_log

            # Detect and apply parser
            lines = raw_log.splitlines()
            parser = detect_parser(lines)
            job.parser_name = parser.name()
            job.parsed_sections = parser.parse(lines)

            # Update available modes for this job's parser
            self.available_modes = parser.get_section_names()
            self._update_mode_buttons(parser)
            self._last_parser_name = parser.name()

            # Default to first available mode or raw
            if self.available_modes and self.detail_mode not in self.available_modes + [
                "raw"
            ]:
                self.detail_mode = cast(DetailMode, self.available_modes[0])

        except Exception as e:
            # Store error state
            job.raw_log = ""
            job.parsed_sections = {}
            self.detail_log.update(f"Error fetching log: {e}")

        finally:
            self.pending_fetches.pop(key, None)
            if self.selected_job is job:
                self.render_detail(job)

    def _update_mode_buttons(self, parser) -> None:
        """Update mode buttons based on parser capabilities."""
        try:
            button_container = self.query_one("#mode-buttons", Horizontal)

            # Clear tracking dict and remove all children
            self.mode_buttons.clear()

            # Remove all existing children
            children_snapshot = list(button_container.children)
            for child in children_snapshot:
                try:
                    child.remove()
                except Exception:
                    pass

            # Create buttons for parser-specific sections (NO IDs!)
            for section_name in parser.get_section_names():
                display_name = parser.get_section_display_name(section_name)
                button = Button(
                    display_name,
                    # NO ID - this is what causes all the duplicate ID problems!
                    classes="mode-active"
                    if section_name == self.detail_mode
                    else "mode-inactive",
                )
                # Store section_name as data attribute
                button.section_name = section_name
                button_container.mount(button)
                self.mode_buttons[section_name] = button

            # Always add raw mode (NO ID!)
            raw_button = Button(
                "Raw log",
                # NO ID!
                classes="mode-active" if self.detail_mode == "raw" else "mode-inactive",
            )
            raw_button.section_name = "raw"
            button_container.mount(raw_button)
            self.mode_buttons["raw"] = raw_button
        except Exception:
            # Log any errors but don't crash
            pass

    async def _update_mode_buttons_async(self, parser) -> None:
        """Async version of update mode buttons to ensure proper removal."""
        # Just call the sync version - removal and mounting don't need to be async
        self._update_mode_buttons(parser)

    def render_detail(self, job: JobInfo) -> None:
        """Render job details in the detail panel."""
        run_link = f"{self.run_url}/jobs/{job.id}"
        detail_text = Text()

        # Display run information if available
        if self.run_info:
            detail_text.append(
                f"Run: #{self.run_info.run_number or self.run_id}", style="bold"
            )
            detail_text.append(" • ")
            detail_text.append(self.run_info.head_branch or "unknown", style="cyan")
            detail_text.append(" • ")
            detail_text.append(self.run_info.short_sha, style="dim")
            if self.run_info.actor:
                detail_text.append(f" • @{self.run_info.actor}", style="dim")
            detail_text.append("\n")
            if self.run_info.display_title:
                detail_text.append(self.run_info.display_title, style="dim")
                detail_text.append("\n")

        detail_text.append(f"Job: {job.name}\n")
        detail_text.append(f"Duration: {job.duration_str}\n")
        detail_text.append("Link: ")
        detail_text.append("Open job logs on GitHub", style=f"link {run_link}")
        detail_text.append("\n")
        if job.parser_name:
            detail_text.append(f"Parser: {job.parser_name}\n")
        detail_text.append(f"Mode: {self.detail_mode.title()}\n\n")

        # Check if still loading
        is_loading = (job.id, "fetch") in self.pending_fetches

        if is_loading:
            detail_text.append(f"Loading… {self._spinner_frame}")
            self.detail_log.update(detail_text)
            return

        # Display content based on mode
        if self.detail_mode == "raw":
            if job.raw_log:
                text = "\n".join(
                    LOG_PREFIX_PATTERN.sub("", line)
                    for line in job.raw_log.splitlines()
                )
                detail_text.append(text)
            else:
                detail_text.append("Log is empty.")
        else:
            # Display parsed section
            if job.parsed_sections and self.detail_mode in job.parsed_sections:
                section = job.parsed_sections[self.detail_mode]
                if section.error:
                    detail_text.append(f"Error: {section.error}")
                elif section.content:
                    detail_text.append(section.content)
                else:
                    detail_text.append("No data found.")
            else:
                detail_text.append(f"No {self.detail_mode} section available.")

        self.detail_log.update(detail_text)

        # Restore scroll position after rendering
        self._restore_scroll_position()

    def _save_scroll_position(self) -> None:
        """Save current scroll position for the current job and mode."""
        if not self.selected_job:
            return

        try:
            scroll_container = self.query_one("#detail-scroll-container", Vertical)
            job_id = self.selected_job.id

            # Initialize job's scroll positions dict if needed
            if job_id not in self._scroll_positions:
                self._scroll_positions[job_id] = {}

            # Save current position
            self._scroll_positions[job_id][self.detail_mode] = (
                scroll_container.scroll_x,
                scroll_container.scroll_y,
            )
        except Exception:
            # Ignore errors during scroll save (e.g., widget not ready)
            pass

    def _restore_scroll_position(self) -> None:
        """Restore scroll position for the current job and mode."""
        if not self.selected_job:
            return

        try:
            scroll_container = self.query_one("#detail-scroll-container", Vertical)
            job_id = self.selected_job.id

            # Check if we have a saved position for this job/mode combination
            if (
                job_id in self._scroll_positions
                and self.detail_mode in self._scroll_positions[job_id]
            ):
                scroll_x, scroll_y = self._scroll_positions[job_id][self.detail_mode]
                # Use call_after_refresh to ensure content is rendered before scrolling
                self.call_after_refresh(
                    lambda: scroll_container.scroll_to(
                        scroll_x, scroll_y, animate=False
                    )
                )
        except Exception:
            # Ignore errors during scroll restore (e.g., widget not ready)
            pass

    def _advance_spinner(self) -> None:
        """Advance loading spinner animation."""
        self._spinner_frame = next(self._spinner_symbols)
        if (
            self.selected_job
            and (self.selected_job.id, "fetch") in self.pending_fetches
        ):
            self.render_detail(self.selected_job)

    async def action_refresh(self) -> None:
        """Refresh jobs list."""
        from ..core import fetch_jobs

        self.jobs = fetch_jobs(self.run_id, self.repo)
        self.list_view.clear()
        for job in self.jobs:
            self.list_view.append(JobListItem(job))
        if self.jobs:
            await self.focus_job(0)

    async def action_fetch(self) -> None:
        """Refresh currently selected job."""
        if self.selected_job:
            await self.select_job(self.selected_job)

    def action_quit(self) -> None:
        self.app.exit()

    def action_go_back(self) -> None:
        """Go back to run picker with confirmation."""

        def handle_confirmation(confirmed: bool) -> None:
            if confirmed:
                self.dismiss()

        self.app.push_screen(
            ConfirmationScreen("Go back to run selection?"), handle_confirmation
        )

    def action_scroll_log_up(self) -> None:
        self.query_one("#detail-scroll-container").scroll_up()

    def action_scroll_log_down(self) -> None:
        self.query_one("#detail-scroll-container").scroll_down()

    async def action_scroll_or_move_up(self) -> None:
        """Scroll log up if in fullscreen, otherwise move cursor up."""
        if self.detail_fullscreen:
            self.action_scroll_log_up()
        else:
            await self.action_move_up()

    async def action_scroll_or_move_down(self) -> None:
        """Scroll log down if in fullscreen, otherwise move cursor down."""
        if self.detail_fullscreen:
            self.action_scroll_log_down()
        else:
            await self.action_move_down()

    def action_page_up(self) -> None:
        """Page up in the log viewer."""
        scroll_container = self.query_one("#detail-scroll-container")
        scroll_container.scroll_page_up()

    def action_page_down(self) -> None:
        """Page down in the log viewer."""
        scroll_container = self.query_one("#detail-scroll-container")
        scroll_container.scroll_page_down()

    def action_copy_log(self) -> None:
        """Copy the currently displayed log content to clipboard."""
        if not self.selected_job:
            self.notify("No job selected", severity="warning")
            return

        # Get the content based on current mode
        content: str | None = None
        if self.detail_mode == "raw":
            if self.selected_job.raw_log:
                content = "\n".join(
                    LOG_PREFIX_PATTERN.sub("", line)
                    for line in self.selected_job.raw_log.splitlines()
                )
        else:
            if (
                self.selected_job.parsed_sections
                and self.detail_mode in self.selected_job.parsed_sections
            ):
                section = self.selected_job.parsed_sections[self.detail_mode]
                content = section.content

        if not content:
            self.notify("No content to copy", severity="warning")
            return

        # Try to copy to clipboard
        try:
            # Try pbcopy (macOS)
            result = subprocess.run(
                ["pbcopy"],
                input=content,
                text=True,
                capture_output=True,
                check=False,
            )
            if result.returncode == 0:
                self.notify(
                    f"Copied {self.detail_mode} log to clipboard",
                    severity="information",
                )
                return

            # Try xclip (Linux)
            result = subprocess.run(
                ["xclip", "-selection", "clipboard"],
                input=content,
                text=True,
                capture_output=True,
                check=False,
            )
            if result.returncode == 0:
                self.notify(
                    f"Copied {self.detail_mode} log to clipboard",
                    severity="information",
                )
                return

            # Try wl-copy (Wayland)
            result = subprocess.run(
                ["wl-copy"],
                input=content,
                text=True,
                capture_output=True,
                check=False,
            )
            if result.returncode == 0:
                self.notify(
                    f"Copied {self.detail_mode} log to clipboard",
                    severity="information",
                )
                return

            # If all fail, notify user
            self.notify(
                "Could not copy to clipboard (no clipboard tool found)",
                severity="error",
            )

        except FileNotFoundError:
            self.notify(
                "Could not copy to clipboard (no clipboard tool found)",
                severity="error",
            )
        except Exception as e:
            self.notify(f"Failed to copy: {e}", severity="error")

    async def action_mode_left(self) -> None:
        await self._cycle_mode(-1)

    async def action_mode_right(self) -> None:
        await self._cycle_mode(1)

    async def _cycle_mode(self, direction: int) -> None:
        """Cycle through available modes."""
        modes = self.available_modes + ["raw"]
        if not modes:
            modes = ["raw"]

        try:
            current_index = modes.index(self.detail_mode)
        except ValueError:
            current_index = 0
        new_index = (current_index + direction) % len(modes)
        await self.set_mode(modes[new_index])

    async def action_toggle(self) -> None:
        await self._cycle_mode(1)

    async def action_toggle_back(self) -> None:
        await self._cycle_mode(-1)

    async def action_move_down(self) -> None:
        await self._move_cursor(1)

    async def action_move_up(self) -> None:
        await self._move_cursor(-1)

    async def _move_cursor(self, offset: int) -> None:
        if not self.jobs:
            return
        if self.list_view.index is None:
            return
        new_index = max(0, min(len(self.jobs) - 1, self.list_view.index + offset))
        await self.focus_job(new_index)

    async def set_mode(self, mode: str) -> None:
        """Set the current detail mode."""
        if mode == self.detail_mode:
            return

        # Save scroll position before switching modes
        self._save_scroll_position()

        self.detail_mode = mode  # type: ignore
        self.update_mode_buttons()
        if self.selected_job:
            self.render_detail(self.selected_job)

    def update_mode_buttons(self) -> None:
        """Update button styles to reflect current mode."""
        for mode_name, button in self.mode_buttons.items():
            if mode_name == self.detail_mode:
                button.set_class(True, "mode-active")
                button.set_class(False, "mode-inactive")
            else:
                button.set_class(False, "mode-active")
                button.set_class(True, "mode-inactive")

    async def action_toggle_detail_view(self) -> None:
        """Toggle between fullscreen detail view and split view."""
        self.detail_fullscreen = not self.detail_fullscreen
        self.list_view.styles.display = "none" if self.detail_fullscreen else None
        if self._detail_panel:
            self._detail_panel.set_class(self.detail_fullscreen, "fullscreen")
        self.query_one("#detail-scroll-container").focus()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses for mode switching."""
        # Use section_name attribute instead of ID
        if hasattr(event.button, "section_name"):
            mode = event.button.section_name
            await self.set_mode(mode)

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        if isinstance(event.item, JobListItem):
            await self.select_job(event.item.job)

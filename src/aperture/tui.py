"""Action Aperture - Terminal UI for inspecting GitHub Actions logs."""

from __future__ import annotations

import argparse
import asyncio

from textual.app import App

from .core import (
    RunInfo,
    derive_run_id,
    fetch_jobs,
    fetch_runs,
    fetch_workflows,
    resolve_repo,
)
from .ui import JobViewScreen, LoadingScreen, RunPickerScreen, WorkflowPickerScreen


class ApertureApp(App):
    """Main application for Action Aperture."""

    def __init__(
        self,
        repo: str,
        run_id: str | None = None,
        run_url: str | None = None,
        job_id: int | None = None,
        workflow: str | None = None,
        latest: bool = False,
    ) -> None:
        super().__init__()
        self.repo = repo
        self.run_id = run_id
        self.run_url = run_url
        self.job_id = job_id
        self.workflow = workflow
        self.latest = latest
        self.selected_workflow: str | None = None

    def on_mount(self) -> None:
        self.push_screen(LoadingScreen())
        if self.run_id or self.run_url:
            # Direct run ID/URL provided
            self.run_worker(self._load_run_and_jobs(workflow_name=None))
        elif self.workflow and self.latest:
            # Auto-select latest run for specified workflow
            self.selected_workflow = self.workflow
            self.run_worker(self._load_latest_run_and_jobs(self.workflow))
        elif self.workflow:
            # Skip workflow picker, go directly to run picker for specified workflow
            self.selected_workflow = self.workflow
            self.run_worker(self._load_runs(self.workflow))
        else:
            # Need to pick a workflow
            self.run_worker(self._load_workflows())

    async def _load_workflows(self) -> None:
        """Load available workflows for the repository."""
        workflows = await asyncio.to_thread(fetch_workflows, self.repo)
        if not workflows:
            self.exit(message=f"No workflows found for {self.repo}")
            return

        def handle_workflow_selection(workflow_name: str | None) -> None:
            if workflow_name:
                self.selected_workflow = workflow_name
                self.push_screen(LoadingScreen())
                self.run_worker(self._load_runs(workflow_name))
            else:
                self.exit()

        self.push_screen(
            WorkflowPickerScreen(workflows, self.repo), handle_workflow_selection
        )

    async def _load_runs(self, workflow_name: str) -> None:
        """Load runs for the selected workflow."""
        try:
            runs = await asyncio.to_thread(
                fetch_runs, self.repo, workflow_name, limit=10
            )
            if not runs:
                self.exit(
                    message=f"No successful runs found for workflow '{workflow_name}'"
                )
                return
        except Exception as e:
            self.exit(message=f"Failed to fetch runs: {e}")
            return

        def handle_run_selection(run: RunInfo | None) -> None:
            if run:
                self.push_screen(LoadingScreen())
                self.run_worker(self._load_jobs(run, workflow_name))
            else:
                # User pressed ESC, go back to workflow picker
                self.push_screen(LoadingScreen())
                self.run_worker(self._load_workflows())

        self.push_screen(
            RunPickerScreen(runs, self.repo, workflow_name), handle_run_selection
        )

    async def _load_jobs(self, run: RunInfo, workflow_name: str) -> None:
        """Load jobs for the selected run."""
        try:
            jobs = await asyncio.to_thread(fetch_jobs, str(run.id), self.repo)
        except Exception as e:
            self.exit(message=f"Failed to fetch jobs: {e}")
            return

        initial_job = (
            next((job for job in jobs if job.id == self.job_id), None)
            if self.job_id
            else None
        )

        def handle_job_screen_dismiss(result: None = None) -> None:
            # User pressed ESC from job view, go back to run picker
            self.push_screen(LoadingScreen())
            self.run_worker(self._load_runs(workflow_name))

        self.push_screen(
            JobViewScreen(str(run.id), run.url, jobs, self.repo, run, initial_job),
            handle_job_screen_dismiss,
        )

    async def _load_run_and_jobs(self, workflow_name: str | None) -> None:
        """Load a specific run and its jobs (when run ID/URL is provided directly)."""
        try:
            run_id, run_url = await asyncio.to_thread(
                derive_run_id, self.run_id, self.run_url, self.repo, workflow_name
            )
            jobs = await asyncio.to_thread(fetch_jobs, run_id, self.repo)
        except Exception as e:
            self.exit(message=str(e))
            return

        initial_job = (
            next((job for job in jobs if job.id == self.job_id), None)
            if self.job_id
            else None
        )
        self.push_screen(
            JobViewScreen(run_id, run_url, jobs, self.repo, None, initial_job)
        )

    async def _load_latest_run_and_jobs(self, workflow_name: str) -> None:
        """Load the latest successful run and its jobs for a specified workflow."""
        try:
            runs = await asyncio.to_thread(
                fetch_runs, self.repo, workflow_name, limit=1
            )
            if not runs:
                self.exit(
                    message=f"No successful runs found for workflow '{workflow_name}'"
                )
                return

            # Get the latest run (first in the list)
            latest_run = runs[0]
            jobs = await asyncio.to_thread(fetch_jobs, str(latest_run.id), self.repo)
        except Exception as e:
            self.exit(message=f"Failed to fetch latest run: {e}")
            return

        initial_job = (
            next((job for job in jobs if job.id == self.job_id), None)
            if self.job_id
            else None
        )

        def handle_job_screen_dismiss(result: None = None) -> None:
            # User pressed ESC from job view, go back to run picker for this workflow
            self.push_screen(LoadingScreen())
            self.run_worker(self._load_runs(workflow_name))

        self.push_screen(
            JobViewScreen(
                str(latest_run.id),
                latest_run.url,
                jobs,
                self.repo,
                latest_run,
                initial_job,
            ),
            handle_job_screen_dismiss,
        )


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Action Aperture - Interactive viewer for GitHub Actions logs"
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--run-id", help="Workflow run ID to inspect")
    group.add_argument("--run-url", help="Workflow run URL to inspect")
    parser.add_argument("--job-id", type=int, help="Job ID to pre-select")
    parser.add_argument(
        "--workflow", help="Workflow name to select (skips workflow picker)"
    )
    parser.add_argument(
        "--latest",
        action="store_true",
        help="Auto-select latest successful run (requires --workflow)",
    )
    parser.add_argument(
        "--repo",
        help="Repository owner/name (e.g., owner/repo)",
    )
    parser.add_argument(
        "repo_positional",
        nargs="?",
        help="Repository owner/name (e.g., owner/repo)",
    )
    return parser.parse_args()


def main() -> None:
    """Main entry point for Action Aperture."""
    args = parse_args()

    # Validate argument combinations
    if args.latest and not args.workflow:
        print("Error: --latest requires --workflow to be specified")
        return

    repo_arg = args.repo_positional or args.repo
    repo = resolve_repo(repo_arg)

    app = ApertureApp(
        repo=repo,
        run_id=args.run_id,
        run_url=args.run_url,
        job_id=args.job_id,
        workflow=args.workflow,
        latest=args.latest,
    )
    app.run()


if __name__ == "__main__":
    main()

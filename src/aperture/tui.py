"""Action Aperture - Terminal UI for inspecting GitHub Actions logs."""

from __future__ import annotations

import asyncio

import typer
from rich.console import Console
from textual.app import App
from typer import Context

from .core import (
    RunInfo,
    derive_run_id,
    fetch_jobs,
    fetch_runs,
    fetch_workflows,
    resolve_repo,
)
from .ui import JobViewScreen, LoadingScreen, RunPickerScreen, WorkflowPickerScreen

app = typer.Typer(help="Action Aperture - GitHub Actions log viewer")
console = Console()


@app.callback(
    invoke_without_command=True, context_settings={"allow_interspersed_args": False}
)
def main(
    ctx: Context,
    repo: str | None = typer.Argument(
        None,
        help="Repository owner/name (e.g., owner/repo). If omitted, auto-detected from git.",
    ),
    run_id: str | None = typer.Option(
        None, "--run-id", help="Workflow run ID to inspect"
    ),
    run_url: str | None = typer.Option(
        None, "--run-url", help="Workflow run URL to inspect"
    ),
    job_id: int | None = typer.Option(None, "--job-id", help="Job ID to pre-select"),
    workflow: str | None = typer.Option(
        None, "--workflow", help="Workflow name to select (skips workflow picker)"
    ),
    latest: bool = typer.Option(
        False,
        "--latest",
        help="Auto-select latest successful run (requires --workflow)",
    ),
) -> None:
    """
    Action Aperture - GitHub Actions log viewer.

    If no subcommand is provided, launches the interactive TUI.
    """
    if ctx.invoked_subcommand is None:
        if latest and not workflow:
            console.print(
                "[red]Error:[/red] --latest requires --workflow to be specified"
            )
            raise typer.Exit(1)

        resolved_repo = resolve_repo(repo)

        aperture_app = ApertureApp(
            repo=resolved_repo,
            run_id=run_id,
            run_url=run_url,
            job_id=job_id,
            workflow=workflow,
            latest=latest,
        )
        aperture_app.run()


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


@app.command()
def tui(
    repo: str | None = typer.Argument(
        None,
        help="Repository owner/name (e.g., owner/repo). If omitted, auto-detected from git.",
    ),
    run_id: str | None = typer.Option(
        None, "--run-id", help="Workflow run ID to inspect"
    ),
    run_url: str | None = typer.Option(
        None, "--run-url", help="Workflow run URL to inspect"
    ),
    job_id: int | None = typer.Option(None, "--job-id", help="Job ID to pre-select"),
    workflow: str | None = typer.Option(
        None, "--workflow", help="Workflow name to select (skips workflow picker)"
    ),
    latest: bool = typer.Option(
        False,
        "--latest",
        help="Auto-select latest successful run (requires --workflow)",
    ),
) -> None:
    """
    Launch the interactive TUI for inspecting GitHub Actions logs.
    """
    if latest and not workflow:
        console.print("[red]Error:[/red] --latest requires --workflow to be specified")
        raise typer.Exit(1)

    resolved_repo = resolve_repo(repo)

    aperture_app = ApertureApp(
        repo=resolved_repo,
        run_id=run_id,
        run_url=run_url,
        job_id=job_id,
        workflow=workflow,
        latest=latest,
    )
    aperture_app.run()


if __name__ == "__main__":
    app()

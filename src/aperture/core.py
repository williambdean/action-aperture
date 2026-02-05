"""Core functionality for interacting with GitHub Actions."""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime

REPO_ENV_VARS = (
    "APERTURE_REPO",
    "TUI_REPO",
    "REPO",
    "GITHUB_REPOSITORY",
    "GH_REPOSITORY",
)


def detect_git_repo() -> str | None:
    """Detect repository from git remote URL."""
    try:
        # Check if inside git repo
        subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            check=True,
            capture_output=True,
        )
        # Get remote URL
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return None

        url = result.stdout.strip()
        # Parse owner/repo from SSH or HTTPS URL
        match = re.search(r"github\.com[:/]([\w-]+)/([\w.-]+?)(?:\.git)?$", url)
        if match:
            return f"{match.group(1)}/{match.group(2)}"
        return None
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None


def resolve_repo(cli_repo: str | None) -> str:
    """Resolve repository with precedence: CLI > Env > Git > Error."""
    if cli_repo:
        return cli_repo
    for env_var in REPO_ENV_VARS:
        value = os.environ.get(env_var)
        if value:
            return value

    detected = detect_git_repo()
    if detected:
        return detected

    raise SystemExit(
        "Repository not specified and could not be detected from git remote.\n"
        "Please specify a repository:\n"
        "  actap owner/repo\n"
        "  or set APERTURE_REPO environment variable"
    )


def gh_command(repo: str, *args: str) -> list[str]:
    """Build a gh command with repo context."""
    return ["gh", "--repo", repo, *args]


def run_command(*args: str, capture_output: bool = True) -> str:
    """Run a command and return stdout."""
    try:
        result = subprocess.run(
            args,
            check=True,
            capture_output=capture_output,
            text=True,
        )
    except FileNotFoundError as exc:
        raise SystemExit(
            "The `gh` CLI is required but not installed or not in PATH"
        ) from exc
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() if exc.stderr else ""
        raise SystemExit(f"Command {exc.cmd} failed: {stderr}")
    return result.stdout


def parse_iso_timestamp(value: str | None) -> datetime | None:
    """Parse ISO timestamp string."""
    if not value:
        return None
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


def format_duration(start: str | None, end: str | None) -> float | None:
    """Calculate duration between two timestamps."""
    started = parse_iso_timestamp(start)
    completed = parse_iso_timestamp(end)
    if not started or not completed:
        return None
    return (completed - started).total_seconds()


@dataclass
class RunInfo:
    """Information about a workflow run."""

    id: int
    display_title: str
    created_at: str | None
    head_branch: str | None
    head_sha: str | None
    status: str | None
    conclusion: str | None
    actor: str | None
    run_number: int | None
    url: str

    @property
    def short_sha(self) -> str:
        if not self.head_sha:
            return "unknown"
        return self.head_sha[:7]

    @property
    def formatted_date(self) -> str:
        if not self.created_at:
            return "unknown date"
        dt = parse_iso_timestamp(self.created_at)
        if not dt:
            return "unknown date"
        return dt.strftime("%Y-%m-%d %H:%M")


@dataclass
class JobInfo:
    """Information about a workflow job."""

    id: int
    name: str
    started_at: str | None
    completed_at: str | None
    duration_seconds: float | None
    raw_log: str | None = None
    parsed_sections: dict | None = None
    parser_name: str | None = None

    @property
    def duration_str(self) -> str:
        if self.duration_seconds is None:
            return "n/a"
        minutes, seconds = divmod(int(self.duration_seconds), 60)
        if minutes:
            return f"{minutes}m {seconds}s"
        return f"{seconds}s"


def fetch_jobs(run_id: str, repo: str) -> list[JobInfo]:
    """Fetch jobs for a workflow run."""
    stdout = run_command(
        *gh_command(repo, "run", "view", str(run_id), "--json", "jobs"),
    )
    payload = json.loads(stdout)
    jobs: list[JobInfo] = []
    for job in payload.get("jobs", []):
        duration = format_duration(job.get("startedAt"), job.get("completedAt"))
        jobs.append(
            JobInfo(
                id=job["databaseId"],
                name=job["name"],
                started_at=job.get("startedAt"),
                completed_at=job.get("completedAt"),
                duration_seconds=duration,
            )
        )
    jobs.sort(key=lambda j: (j.duration_seconds or 0), reverse=True)
    return jobs


def fetch_workflows(repo: str) -> list[str]:
    """Fetch list of workflows in a repository."""
    stdout = run_command(*gh_command(repo, "workflow", "list", "--json", "name"))
    data = json.loads(stdout)
    return [w["name"] for w in data]


def fetch_runs(repo: str, workflow: str, limit: int = 10) -> list[RunInfo]:
    """Fetch recent successful workflow runs."""
    stdout = run_command(
        *gh_command(
            repo,
            "run",
            "list",
            "--workflow",
            workflow,
            "--status",
            "success",
            "--limit",
            str(limit),
            "--json",
            "databaseId,displayTitle,createdAt,headBranch,headSha,status,conclusion,number,url",
        )
    )
    data = json.loads(stdout)
    runs: list[RunInfo] = []
    for run in data:
        runs.append(
            RunInfo(
                id=run["databaseId"],
                display_title=run.get("displayTitle", ""),
                created_at=run.get("createdAt"),
                head_branch=run.get("headBranch"),
                head_sha=run.get("headSha"),
                status=run.get("status"),
                conclusion=run.get("conclusion"),
                actor=None,  # actor not available in gh run list output
                run_number=run.get("number"),
                url=run.get("url", ""),
            )
        )
    return runs


def fetch_job_log(job_id: int, run_id: str, repo: str) -> str:
    """Fetch raw log for a specific job."""
    log_cmd = gh_command(repo, "run", "view", run_id, "--job", str(job_id), "--log")
    try:
        log_proc = subprocess.run(log_cmd, capture_output=True, text=True, check=True)
        return log_proc.stdout
    except subprocess.CalledProcessError as exc:
        cmd_repr = " ".join(log_cmd)
        error_msg = exc.stderr.strip() or "<no stderr>"
        raise Exception(f"gh run view failed: {error_msg} ({cmd_repr})") from exc


def derive_run_id(
    run_id: str | None, run_url: str | None, repo: str, workflow: str | None = None
) -> tuple[str, str]:
    """Derive run ID and URL from various inputs."""
    if run_id:
        return (
            run_id,
            f"https://github.com/{repo}/actions/runs/{run_id}",
        )
    if run_url:
        match = re.search(r"actions/runs/(\d+)", run_url)
        if match:
            run_id_str = match.group(1)
            return run_id_str, run_url.rstrip("/")
        raise SystemExit("Could not parse run id from the provided URL")

    target_workflow = workflow or "Test"
    stdout = run_command(
        *gh_command(
            repo,
            "run",
            "list",
            "--workflow",
            target_workflow,
            "--status",
            "success",
            "--limit",
            "1",
            "--json",
            "databaseId",
        ),
    )
    data = json.loads(stdout)
    if not data:
        raise SystemExit(f"No successful '{target_workflow}' run found")
    run_id_str = str(data[0]["databaseId"])
    return run_id_str, f"https://github.com/{repo}/actions/runs/{run_id_str}"

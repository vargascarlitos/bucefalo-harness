"""Configuration loader for the GitHub Actions review-agent.

Stack-agnostic. Reads GitHub Actions environment variables, an optional
`config.yaml` next to this file, and (optionally) a project conventions file and the
PR's linked ticket spec. No project/stack specifics are hard-coded here — everything
product-specific is supplied via config.yaml or the env.
"""

from __future__ import annotations

import glob
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

# Resolve repo root from GITHUB_WORKSPACE (set by Actions) or two levels up from here.
AGENT_DIR = Path(__file__).resolve().parent
REPO_ROOT = Path(os.environ.get("GITHUB_WORKSPACE", AGENT_DIR.parents[2]))

DEFAULT_MODELS = {
    "orchestrator": "claude-sonnet-4-6",
    "correctness": "claude-sonnet-4-6",
    "security": "claude-sonnet-4-6",
    "tests": "claude-haiku-4-5-20251001",
}
DEFAULT_SPECIALISTS = ["correctness", "security", "tests"]


@dataclass
class Config:
    # GitHub context
    owner: str
    repo: str
    pr_number: int
    api_url: str
    github_token: str
    # Anthropic
    anthropic_api_key: str
    anthropic_base_url: str | None
    # Review tuning (from config.yaml)
    models: dict = field(default_factory=lambda: dict(DEFAULT_MODELS))
    specialists: list = field(default_factory=lambda: list(DEFAULT_SPECIALISTS))
    max_diff_chars: int = 150_000
    # Optional project context
    conventions: str = ""
    spec_content: str = ""
    pr_title: str = ""
    head_branch: str = ""
    ticket_id: str | None = None

    def validate(self) -> None:
        missing = []
        if not self.anthropic_api_key:
            missing.append("ANTHROPIC_API_KEY")
        if not self.github_token:
            missing.append("GITHUB_TOKEN")
        if not self.pr_number:
            missing.append("a pull-request number (GITHUB_EVENT_PATH or PR_NUMBER)")
        if missing:
            raise SystemExit("review-agent: missing required config: " + ", ".join(missing))


def _load_yaml() -> dict:
    path = AGENT_DIR / "config.yaml"
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text()) or {}


def _event_payload() -> dict:
    path = os.environ.get("GITHUB_EVENT_PATH")
    if path and Path(path).exists():
        try:
            return json.loads(Path(path).read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _pr_number(event: dict) -> int:
    if os.environ.get("PR_NUMBER"):
        return int(os.environ["PR_NUMBER"])
    pr = event.get("pull_request") or {}
    if pr.get("number"):
        return int(pr["number"])
    # `issue_comment` / other events nest it differently
    if event.get("number"):
        return int(event["number"])
    return 0


def _read_if_exists(rel_path: str) -> str:
    if not rel_path:
        return ""
    p = REPO_ROOT / rel_path
    return p.read_text() if p.exists() else ""


def _find_spec(spec_glob: str, ticket_id: str | None) -> str:
    """Best-effort: locate the work-item spec for this PR's ticket.

    `spec_glob` may contain `{ticket}`; if so it is substituted with the ticket id.
    Returns the first matching file's content, or "".
    """
    if not spec_glob:
        return ""
    pattern = spec_glob.replace("{ticket}", ticket_id or "*")
    for match in sorted(glob.glob(str(REPO_ROOT / pattern))):
        try:
            return Path(match).read_text()
        except OSError:
            continue
    return ""


def load_config() -> Config:
    yml = _load_yaml()
    event = _event_payload()
    pr = event.get("pull_request") or {}

    repo_full = os.environ.get("GITHUB_REPOSITORY", "/")
    owner, _, repo = repo_full.partition("/")

    pr_title = pr.get("title", "") or os.environ.get("PR_TITLE", "")
    head_branch = (pr.get("head") or {}).get("ref", "") or os.environ.get("HEAD_BRANCH", "")

    # Extract a ticket id from the PR title or head branch (e.g. "TASK-42").
    ticket_re = yml.get("ticket_id_regex", r"[A-Z][A-Z0-9]+-\d+")
    ticket_id = None
    for hay in (pr_title, head_branch):
        m = re.search(ticket_re, hay)
        if m:
            ticket_id = m.group(0)
            break

    models = dict(DEFAULT_MODELS)
    models.update(yml.get("models", {}) or {})

    cfg = Config(
        owner=owner,
        repo=repo,
        pr_number=_pr_number(event),
        api_url=os.environ.get("GITHUB_API_URL", "https://api.github.com"),
        github_token=os.environ.get("GITHUB_TOKEN", ""),
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
        anthropic_base_url=os.environ.get("ANTHROPIC_BASE_URL") or None,
        models=models,
        specialists=yml.get("specialists", DEFAULT_SPECIALISTS) or DEFAULT_SPECIALISTS,
        max_diff_chars=int(yml.get("max_diff_chars", 150_000)),
        conventions=_read_if_exists(yml.get("conventions_file", "")),
        spec_content=_find_spec(yml.get("spec_glob", ""), ticket_id),
        pr_title=pr_title,
        head_branch=head_branch,
        ticket_id=ticket_id,
    )
    cfg.validate()
    return cfg

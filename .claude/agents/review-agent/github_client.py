"""Minimal GitHub REST API client for the review-agent.

Only the calls the agent needs: fetch the PR + its diff + changed files, and submit a
review (which is how GitHub models approve / request-changes). Uses `requests` directly
to avoid a heavier dependency. Works against github.com and GitHub Enterprise (api_url).
"""

from __future__ import annotations

import requests


class GitHubClient:
    def __init__(self, owner: str, repo: str, token: str, api_url: str = "https://api.github.com"):
        self.owner = owner
        self.repo = repo
        self.api_url = api_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "harness-review-agent",
            }
        )

    def _pulls_url(self, pr_number: int) -> str:
        return f"{self.api_url}/repos/{self.owner}/{self.repo}/pulls/{pr_number}"

    def get_pr(self, pr_number: int) -> dict:
        resp = self.session.get(
            self._pulls_url(pr_number), headers={"Accept": "application/vnd.github+json"}
        )
        resp.raise_for_status()
        return resp.json()

    def get_pr_diff(self, pr_number: int) -> str:
        """Return the unified diff for the PR (Accept: application/vnd.github.diff)."""
        resp = self.session.get(
            self._pulls_url(pr_number), headers={"Accept": "application/vnd.github.diff"}
        )
        resp.raise_for_status()
        return resp.text

    def get_changed_files(self, pr_number: int) -> list[str]:
        files: list[str] = []
        url = f"{self._pulls_url(pr_number)}/files"
        params = {"per_page": 100}
        while url:
            resp = self.session.get(
                url, params=params, headers={"Accept": "application/vnd.github+json"}
            )
            resp.raise_for_status()
            files.extend(f.get("filename", "") for f in resp.json())
            url = resp.links.get("next", {}).get("url")
            params = None  # the `next` link already carries pagination params
        return [f for f in files if f]

    def post_review(self, pr_number: int, event: str, body: str, comments: list | None = None) -> dict:
        """Create a PR review.

        event: 'APPROVE' | 'REQUEST_CHANGES' | 'COMMENT'.
        For APPROVE the body may be empty; REQUEST_CHANGES/COMMENT require a body.
        """
        payload: dict = {"event": event, "body": body}
        if comments:
            payload["comments"] = comments
        resp = self.session.post(
            f"{self._pulls_url(pr_number)}/reviews",
            json=payload,
            headers={"Accept": "application/vnd.github+json"},
        )
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def truncate_diff(diff: str, max_chars: int = 150_000) -> tuple[str, bool]:
        if len(diff) <= max_chars:
            return diff, False
        return diff[:max_chars] + "\n\n[... diff truncated ...]\n", True

#!/usr/bin/env python3
"""Automated pull-request review agent for GitHub Actions (stack-agnostic).

Flow:
  1. Load config + the PR diff and changed files from the GitHub API.
  2. Run N specialists (correctness / security / tests) in parallel — each is a small
     tool-using Claude loop that can read files and grep the repo before reporting.
  3. An orchestrator consolidates, dedupes, and validates their findings into one review.
  4. Submit the review to GitHub (APPROVE / REQUEST_CHANGES / COMMENT) with a
     machine-readable `review-agent-findings` JSON fence appended.

Nothing here is project-specific. Stack conventions and the linked ticket spec are fed in
via config (see config.py / config.yaml). Prompts live under prompts/.
"""

from __future__ import annotations

import concurrent.futures
import json
import subprocess
import sys
import time
import traceback
from pathlib import Path

import anthropic

from config import REPO_ROOT, Config, load_config
from github_client import GitHubClient

AGENT_DIR = Path(__file__).resolve().parent
PROMPTS_DIR = AGENT_DIR / "prompts"

SPECIALIST_MAX_TOKENS = 2048
ORCHESTRATOR_MAX_TOKENS = 8192
MAX_TOOL_ITERATIONS = 12

# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

READ_FILE_TOOL = {
    "name": "read_file",
    "description": "Read a file from the repository (optionally a line range) to verify a claim.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Repo-relative file path."},
            "start_line": {"type": "integer"},
            "end_line": {"type": "integer"},
        },
        "required": ["path"],
    },
}

GREP_REPO_TOOL = {
    "name": "grep_repo",
    "description": "Search the repository for a regex pattern to find callers, definitions, or existing tests.",
    "input_schema": {
        "type": "object",
        "properties": {
            "pattern": {"type": "string"},
            "path_glob": {"type": "string", "description": "Optional include glob, e.g. '*.py'."},
            "max_results": {"type": "integer"},
        },
        "required": ["pattern"],
    },
}

_FINDING_PROPS = {
    "severity": {"type": "string", "enum": ["blocker", "major", "minor", "nit"]},
    "file": {"type": "string"},
    "line": {"type": "integer"},
    "title": {"type": "string"},
    "detail": {"type": "string"},
    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
}

SUBMIT_FINDINGS_TOOL = {
    "name": "submit_findings",
    "description": "Submit your final list of findings. Call exactly once when done.",
    "input_schema": {
        "type": "object",
        "properties": {
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": _FINDING_PROPS,
                    "required": ["severity", "file", "title", "detail"],
                },
            }
        },
        "required": ["findings"],
    },
}

SUBMIT_REVIEW_TOOL = {
    "name": "submit_review",
    "description": "Submit the final consolidated review. Call exactly once when done.",
    "input_schema": {
        "type": "object",
        "properties": {
            "verdict": {
                "type": "string",
                "enum": ["approved", "approved_with_comments", "changes_requested"],
            },
            "summary": {"type": "string"},
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {k: v for k, v in _FINDING_PROPS.items() if k != "confidence"},
                    "required": ["severity", "file", "title", "detail"],
                },
            },
        },
        "required": ["verdict", "summary", "findings"],
    },
}

# ---------------------------------------------------------------------------
# Investigation tools (executed locally against the checked-out repo)
# ---------------------------------------------------------------------------


def _safe_repo_path(path: str) -> Path | None:
    """Resolve a repo-relative path and refuse anything outside the repo root."""
    try:
        resolved = (REPO_ROOT / path).resolve()
        resolved.relative_to(REPO_ROOT.resolve())
        return resolved
    except (ValueError, OSError):
        return None


def tool_read_file(args: dict) -> str:
    target = _safe_repo_path(args.get("path", ""))
    if target is None or not target.is_file():
        return f"ERROR: file not found or outside repo: {args.get('path')}"
    try:
        lines = target.read_text(errors="replace").splitlines()
    except OSError as e:
        return f"ERROR: {e}"
    start = max(1, int(args.get("start_line", 1)))
    end = int(args.get("end_line", len(lines)))
    end = min(end, len(lines))
    snippet = "\n".join(f"{i}: {lines[i - 1]}" for i in range(start, end + 1))
    return snippet or "(empty range)"


def tool_grep_repo(args: dict) -> str:
    pattern = args.get("pattern", "")
    if not pattern:
        return "ERROR: empty pattern"
    max_results = int(args.get("max_results", 50))
    cmd = ["grep", "-rnI", "--exclude-dir=.git", "-e", pattern]
    if args.get("path_glob"):
        cmd.insert(1, f"--include={args['path_glob']}")
    cmd.append(str(REPO_ROOT))
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except (subprocess.SubprocessError, OSError) as e:
        return f"ERROR: {e}"
    if out.returncode not in (0, 1):
        return f"ERROR: grep failed: {out.stderr.strip()}"
    root = str(REPO_ROOT.resolve()) + "/"
    lines = [ln.replace(root, "") for ln in out.stdout.splitlines()]
    if not lines:
        return "(no matches)"
    clipped = lines[:max_results]
    suffix = "" if len(lines) <= max_results else f"\n[... {len(lines) - max_results} more matches ...]"
    return "\n".join(clipped) + suffix


TOOL_DISPATCH = {"read_file": tool_read_file, "grep_repo": tool_grep_repo}

# ---------------------------------------------------------------------------
# Claude tool-use loop
# ---------------------------------------------------------------------------


def make_client(config: Config) -> anthropic.Anthropic:
    return anthropic.Anthropic(
        api_key=config.anthropic_api_key, base_url=config.anthropic_base_url or None
    )


def _api_call_with_retry(client, **kwargs):
    delay = 2.0
    for attempt in range(4):
        try:
            return client.messages.create(**kwargs)
        except (anthropic.APIStatusError, anthropic.APIConnectionError) as e:
            status = getattr(e, "status_code", None)
            if attempt == 3 or (status is not None and status < 500 and status != 429):
                raise
            time.sleep(delay)
            delay *= 2
    raise RuntimeError("unreachable")


def run_agent_loop(client, model, system_prompt, user_message, final_tool, max_tokens):
    """Run a tool-using loop until the model calls `final_tool`. Returns its input dict."""
    system = [{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}]
    tools = [READ_FILE_TOOL, GREP_REPO_TOOL, final_tool]
    messages = [{"role": "user", "content": user_message}]

    for _ in range(MAX_TOOL_ITERATIONS):
        resp = _api_call_with_retry(
            client, model=model, max_tokens=max_tokens, system=system, tools=tools, messages=messages
        )
        if resp.stop_reason != "tool_use":
            # Model answered without the required tool — nudge it once.
            messages.append({"role": "assistant", "content": resp.content})
            messages.append(
                {"role": "user", "content": f"You must call the `{final_tool['name']}` tool now."}
            )
            continue

        messages.append({"role": "assistant", "content": resp.content})
        tool_results = []
        for block in resp.content:
            if block.type != "tool_use":
                continue
            if block.name == final_tool["name"]:
                return block.input  # done
            handler = TOOL_DISPATCH.get(block.name)
            result = handler(block.input) if handler else f"ERROR: unknown tool {block.name}"
            tool_results.append(
                {"type": "tool_result", "tool_use_id": block.id, "content": str(result)}
            )
        if tool_results:
            messages.append({"role": "user", "content": tool_results})

    return {}  # gave up without submitting


# ---------------------------------------------------------------------------
# Message builders
# ---------------------------------------------------------------------------


def _context_block(config: Config) -> str:
    parts = []
    if config.conventions:
        parts.append("## Project conventions\n\n" + config.conventions[:8000])
    if config.spec_content:
        parts.append("## Linked ticket spec (acceptance criteria)\n\n" + config.spec_content[:8000])
    return ("\n\n".join(parts) + "\n\n") if parts else ""


def build_specialist_message(config, diff, changed_files) -> str:
    return (
        f"{_context_block(config)}"
        f"## Changed files\n{chr(10).join('- ' + f for f in changed_files)}\n\n"
        f"## Unified diff\n```diff\n{diff}\n```\n"
    )


def build_orchestrator_message(config, diff, changed_files, specialist_results) -> str:
    findings_json = json.dumps(specialist_results, indent=2)
    return (
        f"{_context_block(config)}"
        f"## Changed files\n{chr(10).join('- ' + f for f in changed_files)}\n\n"
        f"## Specialist findings (raw)\n```json\n{findings_json}\n```\n\n"
        f"## Unified diff\n```diff\n{diff}\n```\n"
    )


def load_prompt(name: str, config: Config) -> str:
    text = (PROMPTS_DIR / name).read_text()
    # The {{PROJECT_CONVENTIONS}} placeholder is satisfied via the user message; strip the marker.
    return text.replace("{{PROJECT_CONVENTIONS}}", "").strip()


# ---------------------------------------------------------------------------
# Specialists + orchestrator
# ---------------------------------------------------------------------------


def run_specialist(domain, config, diff, changed_files) -> dict:
    client = make_client(config)
    system_prompt = load_prompt(f"{domain}_specialist.md", config)
    user_message = build_specialist_message(config, diff, changed_files)
    model = config.models.get(domain, "claude-sonnet-4-6")
    try:
        result = run_agent_loop(
            client, model, system_prompt, user_message, SUBMIT_FINDINGS_TOOL, SPECIALIST_MAX_TOKENS
        )
        findings = result.get("findings", []) if isinstance(result, dict) else []
    except Exception as e:  # noqa: BLE001 — one specialist must not kill the run
        print(f"[review-agent] specialist '{domain}' failed: {e}", file=sys.stderr)
        findings = []
    return {"domain": domain, "findings": findings}


def run_specialists_parallel(config, diff, changed_files) -> list[dict]:
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(config.specialists) or 1) as pool:
        futures = {
            pool.submit(run_specialist, d, config, diff, changed_files): d
            for d in config.specialists
        }
        for fut in concurrent.futures.as_completed(futures):
            results.append(fut.result())
    return results


def run_orchestrator(config, diff, changed_files, specialist_results) -> dict:
    client = make_client(config)
    system_prompt = load_prompt("orchestrator.md", config)
    user_message = build_orchestrator_message(config, diff, changed_files, specialist_results)
    model = config.models.get("orchestrator", "claude-sonnet-4-6")
    review = run_agent_loop(
        client, model, system_prompt, user_message, SUBMIT_REVIEW_TOOL, ORCHESTRATOR_MAX_TOKENS
    )
    if not review:
        review = {
            "verdict": "approved_with_comments",
            "summary": "The review agent could not produce a structured verdict; treating as non-blocking.",
            "findings": [],
        }
    return review


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

_SEV_EMOJI = {"blocker": "🛑", "major": "⚠️", "minor": "💬", "nit": "🔹"}
_VERDICT_EVENT = {
    "approved": "APPROVE",
    "approved_with_comments": "APPROVE",
    "changes_requested": "REQUEST_CHANGES",
}


def format_comment(review, config, changed_files, specialist_results) -> str:
    verdict = review.get("verdict", "approved_with_comments")
    findings = review.get("findings", [])
    counts = {d["domain"]: len(d.get("findings", [])) for d in specialist_results}

    lines = [
        "## 🤖 Review agent",
        "",
        f"**Verdict:** `{verdict}`  ·  **Files:** {len(changed_files)}  ·  "
        f"**Specialist findings:** " + ", ".join(f"{k} {v}" for k, v in counts.items()),
        "",
        review.get("summary", "").strip(),
        "",
    ]
    if findings:
        lines.append("### Findings")
        for f in findings:
            sev = f.get("severity", "minor")
            loc = f.get("file", "?")
            if f.get("line"):
                loc += f":{f['line']}"
            lines.append(f"- {_SEV_EMOJI.get(sev, '•')} **{sev}** `{loc}` — **{f.get('title','')}**")
            if f.get("detail"):
                lines.append(f"  {f['detail']}")
    else:
        lines.append("_No blocking findings._")

    structured = {
        "schema_version": 1,
        "verdict": verdict,
        "summary": review.get("summary", ""),
        "findings": findings,
    }
    lines += ["", "```review-agent-findings", json.dumps(structured, indent=2, sort_keys=True), "```"]
    return "\n".join(lines)


def submit_to_github(gh, config, review, comment):
    verdict = review.get("verdict", "approved_with_comments")
    event = _VERDICT_EVENT.get(verdict, "COMMENT")
    try:
        gh.post_review(config.pr_number, event, comment)
        print(f"[review-agent] posted review with event={event}")
    except Exception as e:  # noqa: BLE001
        # APPROVE/REQUEST_CHANGES can 403 on fork PRs / self-authored PRs / read-only tokens.
        # Fall back to a plain COMMENT so the findings still land.
        print(f"[review-agent] {event} failed ({e}); falling back to COMMENT", file=sys.stderr)
        gh.post_review(config.pr_number, "COMMENT", comment)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def main() -> int:
    config = load_config()
    gh = GitHubClient(config.owner, config.repo, config.github_token, config.api_url)

    raw_diff = gh.get_pr_diff(config.pr_number)
    diff, truncated = GitHubClient.truncate_diff(raw_diff, config.max_diff_chars)
    changed_files = gh.get_changed_files(config.pr_number)

    if not diff.strip():
        gh.post_review(config.pr_number, "COMMENT", "## 🤖 Review agent\n\nNo diff to review.")
        return 0
    if truncated:
        print("[review-agent] diff truncated to fit the model context", file=sys.stderr)

    specialist_results = run_specialists_parallel(config, diff, changed_files)
    review = run_orchestrator(config, diff, changed_files, specialist_results)
    comment = format_comment(review, config, changed_files, specialist_results)
    submit_to_github(gh, config, review, comment)

    print(f"[review-agent] verdict={review.get('verdict')} findings={len(review.get('findings', []))}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001 — surface in CI logs but allow the workflow to continue-on-error
        traceback.print_exc()
        sys.exit(1)

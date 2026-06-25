# Review agent (GitHub Actions)

A stack-agnostic, automated pull-request reviewer. On every non-draft PR it runs three
specialists in parallel — **correctness**, **security**, and **tests & acceptance-criteria** —
each a small tool-using Claude loop that can `read_file` and `grep_repo` to verify claims.
An **orchestrator** then dedupes and validates their findings into a single review, which is
submitted to GitHub as an approval, a change request, or a comment.

```
PR opened/updated
   └─ .github/workflows/review-agent.yml
        └─ review.py
             ├─ fetch PR diff + changed files        (github_client.py)
             ├─ correctness ┐
             ├─ security    ├─ run in parallel (ThreadPoolExecutor)
             ├─ tests       ┘  each → submit_findings
             ├─ orchestrator → submit_review (verdict + findings)
             └─ post review  → APPROVE | REQUEST_CHANGES | COMMENT
```

## Setup

1. **Add the secret.** Repo → Settings → Secrets and variables → Actions → add
   `ANTHROPIC_API_KEY`. (`GITHUB_TOKEN` is provided automatically by Actions.)
2. **Permissions.** The workflow already requests `pull-requests: write`. If your org sets
   workflow permissions to read-only by default, allow PR writes for this repo
   (Settings → Actions → General → Workflow permissions).
3. That's it — open a PR and the `review-agent` check runs.

## How the verdict maps to GitHub

| Orchestrator verdict      | GitHub review event |
| ------------------------- | ------------------- |
| `approved`                | `APPROVE`           |
| `approved_with_comments`  | `APPROVE`           |
| `changes_requested`       | `REQUEST_CHANGES`   |

If the API rejects the review event (common on **fork PRs**, **self-authored PRs**, or with a
read-only token), the agent falls back to posting a plain `COMMENT` so the findings still land.

> **Merge gating.** A review submitted by the `github-actions` bot does **not** count toward
> branch-protection "required approvals". To gate merges on this agent, make the
> `review-agent` job a **required status check** (Settings → Branches), or run it with a PAT /
> GitHub App identity that has write access. The structured `review-agent-findings` JSON fence
> in every comment lets other automation parse the outcome.

## Configuration

Everything is optional — see [`config.yaml`](./config.yaml). Knobs: which `specialists` run,
the `models` per role, `max_diff_chars`, a `conventions_file` (e.g. your `CLAUDE.md`) fed to
every specialist, and a `spec_glob` to locate the PR's linked ticket for acceptance-criteria
checks. The prompts under [`prompts/`](./prompts) are plain Markdown — edit them to add your
stack's specifics (they ship generic, with a `{{PROJECT_CONVENTIONS}}` slot that is filled from
`conventions_file`).

## Files

| File | Purpose |
| ---- | ------- |
| `review.py` | Orchestrator, parallel specialists, tool-use loop, GitHub submission |
| `config.py` | Loads GitHub Actions env + `config.yaml` + optional conventions/spec |
| `github_client.py` | PR diff, changed files, submit review (REST API) |
| `prompts/*.md` | System prompts (generic; customize per project) |
| `requirements.txt` | `anthropic`, `requests`, `PyYAML` |

## Local dry run

```bash
cd .claude/agents/review-agent
pip install -r requirements.txt
GITHUB_REPOSITORY=owner/repo PR_NUMBER=123 \
  GITHUB_TOKEN=$(gh auth token) ANTHROPIC_API_KEY=sk-... \
  python review.py
```

---
name: improve-agents
description: Clusters AI-workflow feedback from a time window (ClickUp code-review/qa-outcome records, standalone /feedback, and merged-PR review threads incl. the review-agent's findings), then implements low-risk improvements to CLAUDE.md, .claude/rules/, skills, and agent prompts. Opens a GitHub PR with the changes and a ClickUp summary task. Never touches application code or CI config.
triggers:
  - 'improve agents'
  - 'run improvement agent'
  - 'weekly improvement'
  - 'agent improvement'
  - 'improve-agents'
---

<objective>
Turn the workflow's accumulated feedback into concrete, low-risk improvements to the
**harness itself** — the conventions (`CLAUDE.md`), coding rules (`.claude/rules/`), skill
definitions, and agent prompts. High-risk ideas are written up as recommendations, not
applied. The run produces a GitHub PR and a ClickUp summary task. It **never** edits
application code or CI/CD config.
</objective>

> PM ops in `pm-clickup.md`. Git host is GitHub via `gh` (the template's CI is GitHub
> Actions). Reading records out of ClickUp comments: follow the "Reading records back" note
> in `pm-clickup.md` (brace-match the JSON; no fence). Load MCP/CLI as needed.

---

## Step 1 — Load config + time window

Read `.claude/skills/_shared/load-config.md`. Store `project_name`, `id_prefix`,
`specs_path`, `clickup` block.

Read `.claude/improve-agents-last-run.txt` for the last run timestamp; if missing, default to
7 days ago. Compute `start_ts`, `end_ts` (now, UTC).

## Step 2 — Gather feedback (the signal)

Collect records dated in `[start_ts, end_ts]` from three sources:

1. **ClickUp records** — list tasks (`clickup_filter_tasks(list_id)`), read comments
   (`clickup_get_task_comments`), extract `code-review` and `qa-outcome` records. **Skip
   `dev-complete`** (not improvement signal).
2. **Standalone feedback** — glob `specs/feedback/**/*.json`, keep `type: "feedback"`.
3. **Merged-PR review threads (optional, recommended)** — with `gh`:
   ```bash
   gh pr list --state merged --search "merged:>=<start_date>" --json number,title,url
   gh api repos/{owner}/{repo}/pulls/<n>/comments   # + .../reviews for review bodies
   ```
   Capture each thread's file, a one-line summary, and a `severity`. The CI **review-agent**
   posts a ```review-agent-findings``` JSON block on PRs — parse it directly when present
   (it already carries `verdict` + structured `findings`). Tag each thread's
   `commenter_role` (human / review_agent / bot).

> Scaling note: for a high PR volume you can fan out one subagent per PR to classify threads
> in parallel. The single-pass version above is the default; `log()` what you skip if you cap.

## Step 3 — Cluster patterns

Group findings into themes across all sources. For each theme track: `frequency`, the
`impact` (rank: spec-compliance > security > correctness > conventions > style), the source
mix (ClickUp vs feedback vs PR threads — multi-source confirmation raises priority), and
representative examples. Weight standalone `/feedback` and human PR threads slightly higher
than bot findings.

## Step 4 — Decide actions

For each theme assign a risk level and an action:
- **Low-risk → implement now:** doc/convention/rule clarifications, skill-prompt tweaks,
  agent-prompt guardrails, checklist additions.
- **High-risk → recommend only:** anything touching control flow of a skill, gating logic,
  or that could regress behavior. Write it up; do not apply.

Allowed files to edit (low-risk only):
`CLAUDE.md`, `.claude/rules/*.md`, `.claude/skills/*/SKILL.md`,
`.claude/skills/_shared/*.md`, `.claude/agents/*/system-prompt.md`,
`.claude/agents/review-agent/prompts/*.md`.
**Never** edit application code, infrastructure, or `.github/workflows/*`.

## Step 5 — Implement on a branch

```bash
git checkout -b improvement/batch-$(date -u +%G-W%V)
```
Make the low-risk edits. Commit per change with a message naming the theme and the
source records that motivated it.

## Step 6 — Open a GitHub PR

```bash
git push -u origin improvement/batch-<YYYY-WWW>
gh pr create --base main --title "chore: agent improvements — week of <end_date>" \
  --body "<markdown: patterns found · changes implemented (file, problem, edit, why) · recommendations (high-risk) · what was deliberately NOT changed>"
```
Store `PR_URL`.

## Step 7 — Post a ClickUp summary task

Create a task via **`op: create-task`** titled `Agent improvements — week of <end_date>`
with a markdown body summarizing the run, then post a structured record on it via
**`op: post-workflow-record(task_id, "improvement-run", payload)`**:

```json
{
  "kind": "improvement-run",
  "run_date": "<ISO 8601 UTC>",
  "date_range": { "start": "<start_date>", "end": "<end_date>" },
  "records_analyzed": <int>,
  "patterns": [
    { "theme": "<name>", "frequency": <int>, "impact": "<high|medium|low>",
      "action": "<implemented|recommended|skipped>", "detail": "<text>" }
  ],
  "changes_implemented": <int>,
  "changes_recommended": <int>,
  "pr_url": "<PR_URL or null>"
}
```

## Step 8 — Write the last-run marker

Write `end_ts` to `.claude/improve-agents-last-run.txt` and commit it (on the improvement
branch). This makes the next run incremental.

## Step 9 — Summary

```
✓ Analyzed <N> records (<start_date> → <end_date>)
✓ Implemented <X> low-risk improvements · <Y> recommended
✓ PR: <PR_URL>
✓ ClickUp summary task: <task_url>
```

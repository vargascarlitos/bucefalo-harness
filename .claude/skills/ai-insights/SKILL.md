---
name: ai-insights
description: Aggregates the AI-workflow records posted by /complete-dev, /pr-review, /review-outcome (ClickUp task comments) plus standalone /feedback files, and surfaces a report — verdict distributions, QA kickback rate, correction frequency, common themes — over a chosen time range. Optionally exports the report as a ClickUp Doc.
triggers:
  - 'ai insights'
  - 'workflow insights'
  - 'ai analytics'
  - 'workflow report'
  - 'gather insights'
  - 'ai-insights'
---

<objective>
Read the machine-readable workflow records the core loop emits and turn them into a report.
In the ClickUp edition those per-ticket records live as **task comments** (the
`AI workflow — <kind>` JSON blocks posted via `op: post-workflow-record`), not local files —
so this skill reads ClickUp comments, plus any standalone `/feedback` JSON files.

This skill is read-only on ClickUp except for an optional final export to a ClickUp Doc.
</objective>

> PM ops (`op: load-pm-config`, `op: find-work-item`, etc.) are in `pm-clickup.md`. To read a
> record out of a comment, follow the **"Reading records back"** note there: match the heading
> `AI workflow — <kind>` / the `"kind"` key and brace-match the `{ ... }` JSON from
> `comment_text` (ClickUp strips the markdown fence). Load any ClickUp MCP tool schema with
> ToolSearch (`select:<tool>`) before first use.

---

## Step 1 — Load config

Read `.claude/skills/_shared/load-config.md`. Store `project_name`, `id_prefix`,
`specs_path`, and the `clickup` block (`list_id`, `states`).

## Step 2 — Collect report parameters

`AskUserQuestion`:
- Q1 "Time range?" header "Range" — options
  `["Last 7 days", "Last 30 days", "Last 90 days", "All time"]` (use Other for a custom range).
  Compute `start_date` (or null for all-time) and `end_date` (today).

## Step 3 — Gather records

**3a — ClickUp workflow records.** Get the list's tasks with `clickup_filter_tasks(list_id, …)`
(filter by `date_updated` ≥ `start_date` when set to bound the scan). For each task, call
`clickup_get_task_comments(task_id)` and extract every `AI workflow — <kind>` record. Bucket by
`kind`:
- `dev-complete` → `dev_records[]`
- `code-review`  → `review_records[]`
- `qa-outcome`   → `qa_records[]`

Filter each record by its timestamp (`completed_at` / `reviewed_at`) within `[start_date, end_date]`.

**3b — Standalone feedback.** Glob `specs/feedback/**/*.json`, parse, keep `type: "feedback"`
records whose `recorded_at` falls in range → `standalone_records[]`.

If nothing is found in range, say so and stop.

## Step 4 — Aggregate

Compute and hold:

- **Dev completion** (`dev_records`): count; verify pass vs fail rate (`verify.status`).
- **Code review** (`review_records`): verdict distribution
  (`approved` / `approved_with_comments` / `changes_requested`); `correctness` distribution;
  `logic_errors.severity` counts; `test_coverage` distribution.
- **QA outcomes** (`qa_records`): `verdict` distribution (approved vs `rejected`);
  `bugs.severity` counts; `spec_compliance`; `stability`; `review_rounds` histogram.
- **Workflow rates:** tickets touched; **QA kickback rate** = rejected / total QA;
  **code-review change-request rate** = changes_requested / total reviews.
- **Themes:** recurring topics pulled from free-text fields (`logic_errors.detail`,
  `bugs.detail`, qa `notes`, feedback `detail`/`notes`) and `pattern_type` counts from
  standalone feedback.

## Step 5 — Present the report

Print a markdown report:

```
# AI workflow insights — <project_name>
Range: <start_date or "all time"> → <end_date>   ·   Records: <N>

## Dev completion
- Runs: <n>   ·   Verify pass rate: <pct>

## Code review
- Verdicts: approved <n> · with-comments <n> · changes-requested <n>
- Change-request rate: <pct>
- Correctness: …   ·   Logic errors (sev): …   ·   Test coverage: …

## QA
- Verdicts: approved <n> · rejected <n>   ·   Kickback rate: <pct>
- Bugs (sev): …   ·   Spec compliance: …   ·   Stability: …   ·   Review rounds: …

## Standalone feedback
- By pattern type: …

## Common themes
- <theme> (<count>) — <one-line>
```

## Step 6 — Optional export

Ask: "Export this report as a ClickUp Doc?" If yes, create it with
`clickup_create_document` (or `clickup_create_document_page`) in the workspace/space from
config, titled `AI workflow insights — <project_name> — <range>`, body = the report markdown.
Otherwise finish.

> Confidence-scoring, token-usage tracking, and hole-poking effectiveness metrics are **not**
> part of this template.

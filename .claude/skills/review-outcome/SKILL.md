---
name: review-outcome
description: Logs a QA outcome on a ClickUp work item in Dev Done or QA state. Run by a QA person after functional testing — not the author or code reviewer. Moves the ticket to QA, collects structured findings (bugs, spec compliance, stability, review rounds), posts a structured JSON record comment, and transitions the ticket to Done or back to QA Reject based on verdict.
triggers:
  - 'review outcome'
  - 'log review'
  - 'qa outcome'
  - 'log qa findings'
  - 'post review findings'
  - 'review-outcome'
  - 'log review outcome'
---

<objective>
Capture a QA/reviewer assessment of a ClickUp work item and post it back to ClickUp. This
skill is the QA gate that **follows `/pr-review`**: the code reviewer approves a PR
(ticket → Dev Done), then a QA person picks it up here. Run by a QA person — not the
author or the code reviewer. The workflow:

1. Load project config and verify the ClickUp MCP is reachable
2. Identify the target work item (expected logical state: DEV_DONE or QA)
3. Move the ticket to QA (if it is still in DEV_DONE)
4. Surface code review context for QA
5. Collect structured QA findings via survey
6. Post a structured JSON record comment on the ClickUp ticket
7. Transition the ticket to DONE (if approved) or back to QA_REJECT (if QA fails)
   </objective>

> All PM operations referenced below (`op: find-work-item`, `op: set-status`,
> `op: post-workflow-record`, etc.) are defined in `.claude/skills/_shared/pm-clickup.md`.
> Never call ClickUp MCP tools or hardcode status names directly — go through the named
> operations. Logical states (TODO, IN_PROGRESS, IN_REVIEW, DEV_DONE, QA, QA_REJECT, DONE)
> resolve to ClickUp statuses via `clickup.states` — see the status map in `pm-clickup.md`.

---

## Step 1 — Load config

Read `.claude/skills/_shared/load-config.md` and follow it. Store: `project_name`,
`id_prefix`, `specs_path`, and the `clickup` block (`list_id`, `states`,
`use_custom_task_ids`).

Per `load-config.md`, before the first ClickUp call, verify the MCP is reachable with a
cheap read (e.g. `clickup_get_list(list_id)`). If it fails, tell the user to connect the
ClickUp connector, then stop.

---

## Step 2 — Identify the work item

If the user invoked the command with an argument (e.g. `/review-outcome <id_prefix>-42`),
use that reference directly. Otherwise ask:

> Which work item are you reviewing? (e.g. `<id_prefix>-42`, a task id, or a task URL)

Resolve it via **`op: find-work-item(reference)`** — read
`.claude/skills/_shared/find-work-item.md` and follow it. It returns
`{ task_id, name, status, url, list_id }` and maps the raw ClickUp `status` back to a
logical state via the `clickup.states` reverse lookup.

If no reference resolves, the helper enters its disambiguation flow and asks the user —
never invent an id. If nothing resolves at all, stop.

Store the resolved `task_id`, `name`, `url`, the raw `status`, and the derived
**logical state**. Also Glob `<specs_path>/<id_prefix>-<padded_number>-*.md` to locate the
local spec file (if any) so its frontmatter can be kept in sync.

### State check

The expected logical states here are **DEV_DONE** or **QA**. Check the derived logical
state:

- **DONE:** warn the QA person this ticket was already fully closed and ask if they still
  want to log an outcome. Use `AskUserQuestion` with **Yes, log anyway** / **No, cancel** —
  stop if they cancel.
- **IN_REVIEW:** warn that the PR code review hasn't been completed yet — the code reviewer
  should run `/pr-review` first.

  > This ticket is still in code review (In Review) — the PR hasn't been approved yet. Are
  > you sure you want to log QA findings now?

  Use `AskUserQuestion` with **Yes, proceed anyway** / **No, cancel** — stop if they cancel.

- **IN_PROGRESS / TODO** (or any unstarted/backlog state): warn the QA person the ticket
  hasn't reached QA yet.

  > This ticket is still marked "<status>" — it hasn't completed development and code
  > review yet. Are you sure you want to log QA findings now?

  Use `AskUserQuestion` with **Yes, proceed anyway** / **No, cancel** — stop if they cancel.

- **DEV_DONE** or **QA:** proceed normally — no prompt needed.

---

## Step 2.5 — Move ticket to QA

If the current logical state is **DEV_DONE** (i.e. it has not yet been picked up for QA),
transition it to **QA** now via **`op: set-status(task_id, QA)`**.

If the transition is rejected because the status is invalid (see the note in
`pm-clickup.md` — call `get-task` with `expand_statuses: true` to list the list's real
statuses), warn the user: `⚠ The QA status (clickup.states.qa) is missing in ClickUp —
add it to the list before using this workflow` and stop.

If the ticket is already **QA**, skip this step silently.

If a local spec file was found, update its `state:` frontmatter value to the QA ClickUp
status name (`clickup.states.qa`) with the Edit tool.

---

## Step 3 — Surface context for QA

Surface the code review outcome posted by `/pr-review` so QA can see what the code reviewer
found. Read the prior workflow records on the task via
`clickup_get_task_comments(task_id)` and find the most recent comment whose `comment_text`
contains `"kind": "code-review"` (posted by `/pr-review` via `op: post-workflow-record`).
Parse it by brace-matching the `{ ... }` object in `comment_text` — ClickUp strips the
markdown fence on read, so don't rely on a ` ```json ` block (see the "Reading records
back" note in `pm-clickup.md`).

If found, extract from its payload (fields as posted by `/pr-review`):

- `verdict`
- `correctness`
- `logic_errors` (severity / detail)
- `patterns`
- `test_coverage`

Display the summary:

```
Work item: <id_prefix>-<issue_number> — <name>

Code review outcome:
  Verdict:        <verdict>
  Correctness:    <correctness>
  Logic errors:   <severity>  [<detail if present>]
  Patterns:       <patterns>
  Test coverage:  <test_coverage>
```

If no `code-review` record is found, display "not found" for that section and continue.

---

## Step 4 — Collect QA findings

Use `AskUserQuestion` in logical batches (1–4 questions per call; 2–4 options each — the
tool auto-adds an "Other" option for free text).

### Batch A — Bugs

```
AskUserQuestion:
  Q1: "Did testing reveal any bugs or incorrect behavior?"
      header: "Bugs found"
      options: [
        "None — everything worked as expected",
        "Minor bugs (cosmetic, edge cases with workarounds)",
        "Moderate bugs (functional issues, required fixes before merge)",
        "Major bugs (broke core functionality, significant rework needed)"
      ]
```

If the answer is anything other than "None", follow up with a free-text prompt:

> Briefly describe what you found (type of bug, what had to be fixed):

Collect this as `bugs_detail`.

### Batch B — Spec compliance and stability

```
AskUserQuestion:
  Q2: "Did the implementation match the acceptance criteria?"
      header: "Spec compliance"
      options: [
        "Fully compliant — all criteria met",
        "Mostly compliant — minor gaps or interpretation differences",
        "Partially compliant — some criteria missed or misunderstood",
        "Significantly off — major spec misalignment"
      ]

  Q3: "Did the behaviour suggest any underlying code problems (e.g. crashes, inconsistent data, fragile or unreliable behaviour)?"
      header: "Stability"
      options: [
        "No — behaviour was stable and consistent",
        "Minor — occasional unexpected behaviour, easily reproduced workaround",
        "Moderate — instability that affected testing (e.g. intermittent failures, bad data)",
        "Major — frequent crashes or data corruption"
      ]
```

### Batch C — Review process

```
AskUserQuestion:
  Q4: "How many review iterations were needed before approval?"
      header: "Review rounds"
      options: [
        "1 (approved on first pass)",
        "2",
        "3",
        "4 or more"
      ]

  Q5: "Overall QA verdict"
      header: "Verdict"
      options: [
        "Approved — no changes needed",
        "Approved with minor fixes",
        "Approved after significant fixes",
        "Rejected — sent back for rework"
      ]
```

### Batch D — Notes (optional)

Ask: "Any additional notes about what you found or what had to change? (press Enter or
leave blank to skip)"

> The `/ai-insights` and `/improve-agents` skills aggregate these `qa-outcome` records. A
> free-text "agent-improvement notes" survey field is not collected here — the structured
> fields above are the signal.

---

## Step 5 — Post the QA outcome record

Build the QA outcome payload from all collected answers, normalising survey options to enum
values (e.g. "1 (approved on first pass)" → `"1"`, "None — everything worked as expected"
→ `"none"`):

```json
{
  "kind": "qa-outcome",
  "reviewed_at": "<ISO 8601 date>",
  "work_item": "<id_prefix>-<issue_number>",
  "bugs": {
    "severity": "<none | minor | moderate | major>",
    "detail": "<free text or null>"
  },
  "spec_compliance": "<fully_compliant | mostly_compliant | partially_compliant | significantly_off>",
  "stability": "<stable | minor_instability | moderate_instability | major_instability>",
  "review_rounds": "<1 | 2 | 3 | 4+>",
  "verdict": "<approved | approved_with_minor_fixes | approved_after_significant_fixes | rejected>",
  "notes": "<free text or null>"
}
```

Post it via **`op: post-workflow-record(task_id, "qa-outcome", payload)`** (see
`pm-clickup.md`). This writes a task comment with a `**AI workflow — qa-outcome**` heading
and the JSON in a fenced block so later skills/analytics can parse it.

> The machine-readable record lives entirely in the ClickUp comment — no local per-ticket
> file is written. (`/feedback` writes standalone observations; `/ai-insights` aggregates.)

---

## Step 5.5 — Transition ticket state based on verdict

After posting the record, transition the ticket based on the verdict:

**Approved** (`approved`, `approved_with_minor_fixes`, or
`approved_after_significant_fixes`): **`op: set-status(task_id, DONE)`**

**Rejected** (`rejected`): **`op: set-status(task_id, QA_REJECT)`**

When sending back to QA_REJECT, include this in the displayed summary for the developer:

> The developer should review the QA findings (and the code-review record) before
> addressing them, then resume work via `/start-ticket` / the implement flow.

If a local spec file was found, update its `state:` frontmatter value with the Edit tool:

- Approved → the DONE ClickUp status name (`clickup.states.done`)
- Rejected → the QA_REJECT ClickUp status name (`clickup.states.qa_reject`)

---

## Completion

Display a summary:

```
✓ Ticket moved to QA in ClickUp           ← if it was Dev Done
✓ QA outcome record posted to the ClickUp task
✓ Ticket marked Done in ClickUp           ← if verdict was approved
✓ Ticket returned to QA Reject in ClickUp ← if verdict was rejected
✓ Local spec file updated                 ← if a spec file was found

Summary:
  Bugs:            <severity>
  Spec compliance: <compliance>
  Stability:       <stability>
  Review rounds:   <N>
  Verdict:         <verdict>
```

# Shared: PM operations (ClickUp)

This file is the **single source of truth** for every project-management operation the
harness performs. Skills MUST NOT call ClickUp MCP tools or hardcode status names
directly — they reference the named operations below. To retarget a different PM tool,
rewrite only this file.

All ClickUp access is via the **ClickUp MCP** (account-level claude.ai connector). There
is no CLI, no SQLite cache, no API key in config. If an MCP tool is not yet loaded, load
its schema with ToolSearch (`select:<tool_name>`) before calling it.

## Status mapping

Logical states are fixed across the harness; their ClickUp display names come from
`clickup.states` in `.claude/workflow.json`. **Always resolve through this map** — never
write a literal status string.

| Logical state | Config key | Default ClickUp status | Meaning |
|---------------|-----------|------------------------|---------|
| TODO | `todo` | `Todo` | Ready/backlog, not started |
| IN_PROGRESS | `in_progress` | `In Progress` | Active development |
| IN_REVIEW | `in_review` | `In Review` | Awaiting code review |
| DEV_DONE | `dev_done` | `Dev Done` | Code review passed, awaiting QA |
| QA | `qa` | `QA` | In quality assurance |
| QA_REJECT | `qa_reject` | `QA Reject` | QA failed, back to dev |
| DONE | `done` | `Done` | Complete |

State machine:

```
TODO → IN_PROGRESS → IN_REVIEW → DEV_DONE → QA → DONE
                ↑          │                  │
                └──────────┴── (changes) ─────┘   QA → QA_REJECT → IN_PROGRESS
```

> If `clickup_update_task` rejects a status as invalid, call `clickup_get_task` with
> `expand_statuses: true` to list the list's real statuses, reconcile against
> `clickup.states`, and tell the user which status is missing in ClickUp.

## Operations

### op: load-pm-config
Read `.claude/workflow.json` (see `load-config.md`). Hold `clickup.workspace_id`,
`clickup.space_id`, `clickup.list_id`, `clickup.states`, `clickup.use_custom_task_ids`,
and the top-level `id_prefix`.

### op: resolve-current-user
`clickup_resolve_assignees(assignees: ["me"])` → numeric user ID. Use when a skill must
record or filter by the acting user (the ClickUp edition has no `current_user` in config).

### op: find-work-item(reference)
Delegate to `find-work-item.md`. Returns `{ task_id, name, status, url, list_id }`.
`task_id` is whatever `clickup_get_task`/`clickup_update_task` accept — a native task id,
or a custom id like `TASK-42` when `use_custom_task_ids` is true.

### op: create-task(title, description_markdown, priority?)
```
clickup_create_task(
  list_id: <clickup.list_id>,
  name: title,
  markdown_description: description_markdown,
  priority: priority?,          // 'urgent'|'high'|'normal'|'low' — omit if unknown
  status: resolveStatus(TODO)   // omit to use the list default
)
```
Returns the new task's id and url. Persist both into the local spec frontmatter
(`clickup_id`, `clickup_url`).

### op: get-task(task_id)
```
clickup_get_task(task_id, include: ["description"])
```
Add `expand_statuses: true` when you need to validate a status transition.

### op: get-task-description(task_id)
`get-task(task_id)` then read the full `description` section. Used by the readiness gate
to load the ticket body (Acceptance Criteria, Edge Cases, Scope).

### op: set-status(task_id, LOGICAL_STATE)
```
clickup_update_task(task_id, status: resolveStatus(LOGICAL_STATE))
```
`resolveStatus(X)` = `clickup.states[lowercase_key_of_X]`.

### op: set-description(task_id, description_markdown)
```
clickup_update_task(task_id, markdown_description: description_markdown)
```
Used by the readiness gate to write back an expanded ticket body.

### op: set-priority(task_id, priority)
```
clickup_update_task(task_id, priority: 'urgent'|'high'|'normal'|'low'|'none')
```

### op: add-comment(task_id, markdown)
```
clickup_create_comment(entity_type: "task", entity_id: task_id, comment_text: markdown)
```
Used for human-readable status notes.

### op: post-workflow-record(task_id, kind, payload)
Posts a structured, machine-readable record as a task comment. This is the ClickUp
equivalent of the Plane "ai-workflow" JSON comments — used by `/complete-dev`,
`/pr-review`, `/review-outcome` so later skills/analytics can parse outcomes.

`add-comment(task_id, markdown)` where `markdown` is:
````
**AI workflow — <kind>**

```json
{ "kind": "<kind>", "verdict": "...", "...": "..." }
```
````
`kind` is one of: `dev-complete`, `code-review`, `qa-outcome`.

> **Reading records back.** ClickUp stores comments as rich text, so
> `clickup_get_task_comments` returns the heading **without** the `**` bold markers and the
> JSON **without** the ` ```json ` fence — the reconstructed `comment_text` field holds the
> clean text (heading line `AI workflow — <kind>`, then the raw JSON lines). Do **not** grep
> for the literal `**` / ` ``` ` markers; they won't be there. Locate a record by the
> heading text `AI workflow — <kind>` or by `"kind": "<kind>"`, then brace-match the
> `{ ... }` object out of `comment_text` and `JSON.parse` it.

### op: link-mr(task_id, mr_url)
ClickUp's `clickup_add_task_link` links **task↔task**, not external URLs. To attach an MR:
- **Default (no setup):** `add-comment(task_id, "MR: <mr_url>")`.
- **Optional (if a URL custom field exists):** discover it with `clickup_get_custom_fields(list_id)`,
  then `clickup_update_task(task_id, custom_fields: [{ id: <field_id>, value: mr_url }])`.

### op: link-related-task(task_id, other_task_id)
```
clickup_add_task_link(task_id, links_to: other_task_id)
```
Used to relate tickets (e.g. a follow-up bug to its parent feature).

## Conventions

- **Local spec is the source of truth for the ticket body.** ClickUp holds state + a copy
  of the description; the markdown spec under `specs/work-items/` holds the canonical
  Acceptance Criteria / Edge Cases / Scope. Skills keep them in sync explicitly.
- **Ticket reference forms** the harness accepts: a native ClickUp task id, a custom id
  (`TASK-42`), a task URL, or a local spec filename. `find-work-item.md` normalizes them.
- **Never invent IDs.** If a reference doesn't resolve, enter the disambiguation flow in
  `find-work-item.md` and ask the user.

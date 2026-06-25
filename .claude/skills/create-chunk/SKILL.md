---
name: create-chunk
description: Bootstraps a new feature "chunk" end-to-end — collects chunk metadata and all its tickets upfront, batch-creates ClickUp tasks, writes the chunk + work-item spec files, AI-generates user-prompt.md and orchestration-prompt.md, then invokes /update-plan to write the implementation plan.
triggers:
  - 'create chunk'
  - 'new chunk'
  - 'add chunk'
  - 'chunk creator'
---

<objective>
A "chunk" is a feature-sized unit of work: a set of related tickets, a goal statement, and
a plan. This skill scaffolds one end-to-end. The workflow:

1. Load config + verify the ClickUp MCP is reachable
2. Collect chunk metadata (number, name, goal)
3. Collect the ticket list (from a pre-written file or pasted inline)
4. Optional design reference + cross-layer audit
5. Preview & confirm
6. Batch-create the ClickUp tasks (`op: create-task`)
7. Write chunk spec files + work-item spec files
8. AI-generate `user-prompt.md` and `orchestration-prompt.md`
9. Invoke `/update-plan` to write the implementation plan

PM coupling: never call ClickUp tools directly — use the named ops in
`.claude/skills/_shared/pm-clickup.md`. Stack specifics (layers, build/test commands,
file paths) are **placeholders** — this template is stack-agnostic.
</objective>

---

## Step 1 — Load config

Read `.claude/skills/_shared/load-config.md` and follow it. Store `project_name`,
`id_prefix`, `specs_path`, and the `clickup` block. Derive `chunks_path` = `specs/chunks`.

Before the first ClickUp write, verify the MCP is reachable with a cheap read
(`clickup_get_list(list_id)`). If it fails, tell the user to connect the ClickUp connector
and stop.

---

## Step 2 — Collect chunk metadata

Auto-detect the next chunk number: glob `specs/chunks/` for the highest `NN-` prefix and
propose `NN+1` (zero-padded to 2 digits). Then ask via `AskUserQuestion`:

- Q1 "What is this chunk called?" header "Chunk name" — options `["Enter via Other ↓"]`
- Q2 "Describe this chunk's goal in 1–2 sentences" header "Goal" — options `["Enter via Other ↓"]`
- Q3 "Confirm chunk number (auto-detected as `<proposed>`)" header "Chunk #" —
  options `["<proposed> — looks right", "Use a different number — enter via Other ↓"]`

Derive: `chunk_number`, `chunk_name`, `chunk_goal`, `chunk_slug` (slugified name),
`chunk_dir` = `<chunk_number>-<chunk_slug>`, `chunk_label` = `Chunk <chunk_number> — <chunk_name>`.

---

## Step 3 — Collect the ticket list

**3a — Pre-written file.** Look for `<this skill's dir>/<ChunkName>.md` (case-insensitive).
If present, read it as the ticket source. Otherwise show the user the format in
[`template.md`](./template.md) and ask them to paste the list:

> Q "Enter all tickets for this chunk" header "Tickets" — options `["Paste your list via Other ↓"]`

**3b — Parse.** Each ticket line follows `template.md`:

```
[layer] Title | 1-4 | estimate | one-line description
```

For each, extract and store in `tickets[]`:
- `layer` — the bracket token (free; becomes the chunk sub-directory)
- `title`, `description`, `estimate`
- `moscow_int` (1–4) → `moscow_label` (`1 - Must Have` … `4 - Won't Have`)
- `priority` → ClickUp priority via: 1→`urgent`, 2→`high`, 3→`normal`, 4→`low`
- `slug` — slugified title

> Layers are **not** hard-coded — whatever tokens the user writes (`api`, `web`, `shared`,
> `infra`, …) become the per-layer sub-dirs under the chunk. Adjust the build/validation
> idioms per project (they are placeholders below).

---

## Step 4 — Design reference + cross-layer audit (optional)

**4a — Design reference.** Ask once: "Is there a design reference (URL) for this chunk?"
If yes, collect a `design_url` (and optional frame/node labels). This is generic — wire it
to your design tool of choice per project.

**4b — Cross-layer audit.** If any ticket's description declares it *consumes* a contract
(e.g. an endpoint/event/type) that no sibling ticket *provides*, surface the gap and ask
whether to add a provider ticket now, mark it `(existing)`, or skip. (This mirrors
`/ticket-review` Phase C — the same `Consumes:`/`Provides:` notation.)

---

## Step 5 — Preview & confirm

Show a table: `chunk_label`, `chunk_dir`, goal, and every ticket
(`layer · title · priority · estimate`), plus the layer sub-dirs that will be created.
Ask: "Create all of the above?" — options `["Yes — create everything", "No — revise the list"]`.
On "No", loop back to Step 3.

---

## Step 6 — Batch-create the ClickUp tasks

For each ticket in `tickets[]`, apply **`op: create-task`** (see `pm-clickup.md`):

```
op: create-task(
  title:               "<title>",
  description_markdown: <body from Step 7's work-item schema, frontmatter stripped>,
  priority:            "<priority>"
)
```

Store the returned `clickup_id` and `clickup_url` on the ticket. Determine `issue_number`
for each (the next free `<id_prefix>-NNNN` across `specs_path`, or the custom id number when
`use_custom_task_ids` is true) and `padded_number` (4-digit). If a create call fails, stop
and report — do not write files for tickets that weren't created.

---

## Step 7 — Write the chunk spec files

For each ticket, write `specs/chunks/<chunk_dir>/<layer>/<slug>.md`:

```markdown
# <title>

**Chunk:** <chunk_label>
**Layer:** <layer>
**MoSCoW:** <moscow_label>
**Estimate:** <estimate>

## User Story

<description, expanded to "As a <role>, I want <capability> so that <outcome>." if possible>

## Provides / Consumes

- Provides: <contract this ticket exposes, or "—">
- Consumes: <contract this ticket needs from a sibling, or "—">

## Notes

<design_url and any constraints, or "_None._">
```

---

## Step 8 — Write the work-item spec files

For each ticket, write `<specs_path>/<id_prefix>-<padded_number>-<slug>.md` using the
**same schema as `specs/work-items/_template.md`** (so `/ticket-review` works on it):

```markdown
---
state: Todo
priority: <moscow_label>
estimate: <estimate>
start_date: null
target_date: null
clickup_id: <clickup_id>
clickup_url: <clickup_url>
parent: null
chunk_spec: ../chunks/<chunk_dir>/<layer>/<slug>.md
---

# <id_prefix>-<padded_number>: <title>

## User Story

<user story>

## Acceptance Criteria

_To be filled — run `/ticket-review <id_prefix>-<padded_number>` to expand._

- **Happy path:** Given … When … Then …

## Edge Cases & Error States

_To be filled._

## Scope

**In scope:**

- <from description>

**Out of scope:**

- …

**Dependencies:**

- Consumes: <contract or "—">
- Provides: <contract or "—">

## Design Reference

<design_url as a link, or "_No design reference provided._">
```

> Batch-created tickets ship with stub AC/Edges — they are expanded by `/ticket-review`
> before `/start-ticket` proceeds. The local spec is the canonical body; ClickUp holds a copy.

---

## Step 9 — Generate `user-prompt.md` (AI-written)

Write `specs/chunks/<chunk_dir>/user-prompt.md` — a human-facing brief:

```markdown
# <chunk_label>

<chunk_goal>

## Goal

<3–4 sentences elaborating the goal>

## Features to implement

### <layer>
- **<title>** (`<layer>/<slug>.md`): <description>
  …(group every ticket under its layer)…

## Design references

<design_url / frames, or "_None._">

## Technical constraints

<{{STACK CONSTRAINTS — fill per project: language/framework, data store, key libraries,
responsive/breakpoint rules, etc. Leave generic in the template.}}>

## Dependencies

_TBD_

## Workflow requirements

- Every ticket flows Todo → In Progress → In Review → Dev Done → QA → Done.
- Acceptance criteria are expanded via `/ticket-review` before work starts.

## New additions

_(append future tickets here so `/update-plan` can pick them up incrementally)_
```

---

## Step 10 — Generate `orchestration-prompt.md` (AI-written)

Write `specs/chunks/<chunk_dir>/orchestration-prompt.md` — a build strategy:

```markdown
# <chunk_label>: orchestration strategy

## Team composition

<one builder per distinct layer + one validator. Name them e.g. `<layer>-builder`>

## Task granularity

### Phase 0 — Ticket setup
- Move this chunk's ClickUp tickets to **In Progress** (`op: set-status(..., IN_PROGRESS)`).

### Phase 1+ — Implementation
- One task per ticket. Spec: `<layer>/<slug>.md`. Write tests, then implement.
  …(group by layer; sequence by Consumes/Provides dependencies)…

### Final phase — Validation
- Functional + (if applicable) visual validation against acceptance criteria.

## Dependency structure

```
Phase 0 → Phase 1 (parallel where independent) → Validation
```

## Validation strategy

<{{STACK VALIDATION — fill per project: build/test/typecheck/lint commands. Placeholder.}}>

### Close out
- Move passing tickets to **Done** (`op: set-status(..., DONE)`), or run them through the
  core loop (`/start-ticket` … `/review-outcome`).

## New additions

_(kept in sync by `/update-plan`)_
```

---

## Step 11 — Invoke /update-plan

Run **`/update-plan <chunk_dir>`** as a sub-skill to generate
`specs/plans/chunk-<chunk_dir>-plan.md` from the specs just written.

---

## Step 12 — Confirm & surface

```
✓ Created <chunk_label> with <N> tickets in ClickUp
✓ Chunk specs:      specs/chunks/<chunk_dir>/<layer>/*.md
✓ Work-item specs:  <specs_path>/<id_prefix>-*.md
✓ user-prompt.md / orchestration-prompt.md written
✓ Implementation plan: specs/plans/chunk-<chunk_dir>-plan.md
```

Print the full `user-prompt.md`, `orchestration-prompt.md`, and the plan, then suggest:

> Next: `/ticket-review <id_prefix>-<first_number>` to flesh out acceptance criteria, then
> `/start-ticket <id_prefix>-<first_number>`.

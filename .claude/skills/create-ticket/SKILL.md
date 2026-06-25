---
name: create-ticket
description: Creates a new ClickUp task and writes the matching local work-item spec file (YAML frontmatter + user story + acceptance criteria + scope). The local spec is the source of truth for the ticket body.
triggers:
  - 'create ticket'
  - 'new ticket'
  - 'add ticket'
  - 'create work item'
  - 'new work item'
  - 'add work item'
  - 'create issue'
  - 'new issue'
---

<objective>
Collect details for a new work item, create it in ClickUp, and write the work-item spec
file in the configured specs path. The workflow:

1. Load project config and verify the ClickUp MCP is reachable
2. Collect ticket details from the user via AskUserQuestion
3. Map MoSCoW priority to a ClickUp priority
4. Build the description and create the task in ClickUp (`op: create-task`)
5. Write the work-item spec file from the template (`specs/work-items/_template.md`)
6. Confirm and surface the created task + written file
   </objective>

> **Chunk specs are deferred** — not part of the core-loop template. This skill only
> creates the ClickUp task and the single work-item spec file. (Chunk authoring lived in
> `/create-chunk` / `/update-plan` in the full harness.)

---

## Step 1 — Load config

Read `.claude/skills/_shared/load-config.md` and follow it. Store: `project_name`,
`id_prefix`, `specs_path`, and the `clickup` block (`list_id`, `states`,
`use_custom_task_ids`).

Per `load-config.md`, before the first ClickUp write, verify the MCP is reachable with a
cheap read (e.g. `clickup_get_list(list_id)`). If it fails, tell the user to connect the
ClickUp connector, then stop.

> All PM operations referenced below (`op: create-task`, etc.) are defined in
> `.claude/skills/_shared/pm-clickup.md`. Never call ClickUp MCP tools or hardcode status
> names directly — go through the named operations.

---

## Step 2 — Collect ticket details

AskUserQuestion constraints: 1–4 questions per call; 2–4 options per question (the tool
auto-adds an "Other" option for free text).

### Call A1 — Title + Area

- Q1 "What is the ticket title?" header "Title" — options: `["Enter title via Other ↓", "Skip for now"]`
- Q2 "What area of the codebase does this work target?" header "Area" — options:
  `["Frontend / UI", "Backend / API", "Full stack", "Other — type it"]`
  (areas are stack-specific — adjust labels per project)

### Call A2 — Priority + Estimate

- Q3 "What is the MoSCoW priority?" header "Priority" — options:
  `["1 - Must Have", "2 - Should Have", "3 - Could Have", "4 - Won't Have"]`
- Q4 "What is your time estimate?" header "Estimate" — options:
  `["1-2 Hrs", "2-4 Hrs", "4-8 Hrs", "1-2 Days"]` (use Other for < 1 Hr or > 1 day)

### Call B1 — Story

- Q5 "Write the user story (e.g. 'As a <role>, I want X so that Y')" header "User story" —
  options: `["Enter via Other ↓", "Skip — I'll add it manually"]`

### Call C1 — Design reference

- Q6 "Is there a design reference for this ticket?" header "Design ref" — options:
  `["No design reference", "Yes — I'll provide a link"]`

If Q6 answer is "Yes — I'll provide a link", ask sequentially:

1. "Frame / screen name (e.g. `Detail Page`):"
2. "Design URL (full link to the frame in your design tool):"
3. "Node / element ID (optional — press Enter to skip):"

Store as `design_frame`, `design_url`, `design_node`. (Design-tool specifics are
stack-specific — defined per project.)

### Step 2c — Collect Acceptance Criteria

Use AskUserQuestion to gather one AC at a time, then loop until the user is done. After
each AC ask: "Add another AC?" with options "Add another" / "Done".

For each AC, prompt for:

1. **Category** (multi-choice): Happy Path / Validation / Permission / Integration Failure / Edge Case
2. **Given** (free-text)
3. **When** (free-text)
4. **Then** (free-text)

Require at least one Happy Path AC before allowing "Done".

Accumulate ACs into a markdown bullet list:

- **Happy path:** Given <given> When <when> Then <then>
- **Validation:** Given <given> When <when> Then <then>
- ...

Store as `ac_list`.

### Step 2d — Collect Edge Cases

Free-text prompt: "List edge cases and error states (empty/loading/error/unauthorized
states, validation rules, integration failure modes, idempotency)."

If the user types "none", record `_None — no user-facing edges._` so the readiness gate
sees the section is acknowledged.

Store as `edge_cases`.

### Step 2e — Collect Scope

Three free-text prompts (one AskUserQuestion call each, using the "Enter via Other ↓"
pattern):

1. "**In scope** — bullet what's included:" → store as `in_scope`
2. "**Out of scope** — bullet what's NOT included:" → store as `out_of_scope`
3. "**Dependencies** — what does this consume (existing endpoint/module name or
   `<id_prefix>-### (new)`) and what does it provide?" → store as `dependencies`

Each prompt accepts multi-line input.

---

## Step 3 — Map priority to ClickUp format

| MoSCoW          | ClickUp priority |
| --------------- | ---------------- |
| 1 - Must Have   | `urgent`         |
| 2 - Should Have | `high`           |
| 3 - Could Have  | `normal`         |
| 4 - Won't Have  | `low`            |

Store as `clickup_priority`.

Build the markdown description for the ClickUp task:

```markdown
**User Story:** <user story text>

**Acceptance Criteria:**
<ac_list>

**Edge Cases & Error States:**
<edge_cases>

**Scope:**

_In scope:_
<in_scope>

_Out of scope:_
<out_of_scope>

_Dependencies:_
<dependencies>

**Estimate:** <estimate>
**Area:** <area>
```

---

## Step 4 — Determine title prefix and create the task

Determine the title prefix automatically based on what was provided:

| Area               | ACs provided? | Design provided? | Prefix             |
| ------------------ | ------------- | ---------------- | ------------------ |
| Backend / API      | No            | —                | `Missing Design: ` |
| Backend / API      | Yes           | —                | _(none)_           |
| Frontend / Full    | Yes           | Yes              | _(none)_           |
| Frontend / Full    | Yes           | No               | `Missing Design: ` |
| Frontend / Full    | No            | Yes              | `Missing Design: ` |
| Frontend / Full    | No            | No               | `Draft: `          |

"ACs provided" = at least one Happy Path AC entered in Step 2c. "Design provided" = user
selected "Yes" for Q6. Backend/API-only tickets are not penalised for missing a design
reference (design rules are stack-specific — adjust per project).

Store the computed prefix as `title_prefix` (empty string if none applies).

Create the task via **`op: create-task`** (see `pm-clickup.md`):

```
op: create-task(
  title:               "<title_prefix><title>",
  description_markdown: "<description from Step 3>",
  priority:            "<clickup_priority>"
)
```

`create-task` creates the task in the configured list with status `resolveStatus(TODO)`
and returns the new task's **id** and **url**.

From the result, store:

- `clickup_id` — the returned task id (native id, or custom id like `<id_prefix>-42` if
  `use_custom_task_ids` is true)
- `clickup_url` — the returned task url
- `issue_number` — the numeric part of the custom id when available; otherwise prompt the
  user for / pick a local spec number (next free `<id_prefix>-NNNN` in `specs_path`)
- `padded_number` — `issue_number` zero-padded to 4 digits (e.g. `0042`)

If the create call fails, display the error and **stop** — do not write any files.

---

## Step 5 — Write the work-item spec file

The local spec is the **source of truth** for the ticket body (AC / edges / scope);
ClickUp holds state + a copy of the description.

- Slug: slugify the title (lowercase, spaces → hyphens, strip special chars, max 50 chars)
- Filename: `<specs_path>/<id_prefix>-<padded_number>-<slug>.md`
- Example: `specs/work-items/TASK-0042-browse-items-in-a-gallery.md`

Write the file using the Write tool, based on `specs/work-items/_template.md`:

```markdown
---
state: Todo
priority: <moscow priority>
estimate: <estimate>
start_date: null
target_date: null
clickup_id: <clickup_id>
clickup_url: <clickup_url>
parent: null
chunk_spec: null
---

# <id_prefix>-<padded_number>: <title>

## User Story

<user story text>

## Acceptance Criteria

<ac_list>

## Edge Cases & Error States

<edge_cases>

## Scope

**In scope:**

<in_scope>

**Out of scope:**

<out_of_scope>

**Dependencies:**

<dependencies>

## Design Reference

<if design provided:>
[`<design_frame>`](<design_url>)<if design_node: — node `<design_node>`>
<else:>
_No design reference provided._
```

> `parent` / `chunk_spec` stay `null` in the core-loop template (parent linking and chunk
> specs are deferred — not in core-loop). Link related tasks manually in ClickUp, or use
> `op: link-related-task` if needed.

---

## Step 6 — Confirm and surface

```
✓ Created <id_prefix>-<padded_number> — "<title_prefix><title>" in ClickUp
  <clickup_url>
✓ Work item spec written: <specs_path>/<id_prefix>-<padded_number>-<slug>.md
```

Print the full content of the written spec file, then:

<if title_prefix is "Missing Design: ":>

> ⚠ Ticket marked **Missing Design**. Run `/update-ticket <id_prefix>-<padded_number>` to
> add a design reference / fill in acceptance criteria when ready.

<else if title_prefix is "Draft: ":>

> ⚠ Ticket marked **Draft** (no design reference and no acceptance criteria). Run
> `/update-ticket <id_prefix>-<padded_number>` when you're ready to fill in both.

<else:>

> Ready to start? Run `/ticket-review <id_prefix>-<padded_number>` to check readiness, or
> `/start-ticket <id_prefix>-<padded_number>` to begin work.

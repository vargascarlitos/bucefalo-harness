---
name: update-plan
description: Updates or creates the implementation plan for a chunk. Reads the chunk's user-prompt / orchestration-prompt and its specs, explores the codebase for relevant files, and writes specs/plans/chunk-<dir>-plan.md — appending new tasks if a plan already exists, or writing a full plan from scratch.
triggers:
  - 'update plan'
  - 'create plan'
  - 'generate plan'
  - 'update chunk plan'
---

<objective>
Keep a chunk's implementation plan in sync with its specs. Workflow: load config, resolve
the chunk, detect whether a plan exists, read the chunk docs + specs, explore the codebase
for the files involved, build task entries, then either append to the existing plan
(targeted edits) or write a full plan. Stack specifics (file globs, build/test commands)
are **placeholders** — this template is stack-agnostic.
</objective>

This skill has **no PM coupling** — it reads and writes local files only. It is invoked by
`/create-chunk` and can be re-run any time new specs are added to a chunk.

---

## Step 1 — Load config

Read `.claude/skills/_shared/load-config.md` and follow it. Store `id_prefix`, `specs_path`.

## Step 2 — Resolve the chunk

If invoked with an argument, normalize it: `03` → glob `specs/chunks/03-*`;
`03-public-website` → use directly; `chunk-03-...` → strip the `chunk-` prefix. If no
argument, list `specs/chunks/*/` via `AskUserQuestion` and let the user pick.

Derive `chunk_dir`, `chunk_number`, `chunk_label`, and
`plan_path` = `specs/plans/chunk-<chunk_dir>-plan.md`.

## Step 3 — Detect plan state + read chunk docs

`plan_state` = EXISTS if `plan_path` is on disk, else NEW. Always read:
- `specs/chunks/<chunk_dir>/user-prompt.md` — Features list + `## New additions`
- `specs/chunks/<chunk_dir>/orchestration-prompt.md` — team composition, phases, `## New additions`

If the plan EXISTS, parse it and store `existing_task_ids[]`, `last_task_number`,
`existing_team_members[]`, `existing_relevant_files[]`.

Identify `new_specs[]`: the specs named under `## New additions` (incremental update), or
**all** specs under `specs/chunks/<chunk_dir>/<layer>/*.md` when the plan is NEW. For each,
read and extract `file_path`, `title`, `layer`, `user_story`, `estimate`, the
`Provides`/`Consumes` contracts, and any notes.

## Step 4 — Explore the codebase

Determine the layers involved from `new_specs[]`. For each layer, glob and skim the
project's source directories to learn where new code will live and which files must change.

> **Stack-agnostic:** the source layout is **not** known to the template. Read the project's
> `CLAUDE.md` / `.claude/rules/*` (if present) to learn the layer → directory map and the
> build/test commands, and use those. Where this template shows a `{{PLACEHOLDER}}`, the
> project supplies the real value.

Store `existing_files_to_modify[]` and `new_files_to_create[]` (with inferred paths per the
project's conventions).

## Step 5 — Build task entries

For each spec in `new_specs[]`, construct a task:
- **Task ID** — slugified title
- **Assigned To / Agent Type** — map the spec's `layer` to a builder role (e.g. `<layer>-builder`)
- **Depends On** — scan `existing_task_ids[]` + sibling `Consumes`/`Provides` for predecessors
- **Parallel** — true unless it has an unmet dependency
- **Body** — implementation bullets from the spec, files to create/modify, the test file to
  write, and the command to run those tests (`{{TEST_CMD}}` — from the project's config)

## Step 6 — Write or update the plan

**Case A — plan EXISTS (targeted edits via Edit tool, don't touch unrelated sections):**
append to `## Relevant files` (new + to-modify), insert each new feature's bullets into the
right `## Implementation phases` entry, append new tasks after `last_task_number`, append one
`## Acceptance criteria` line per spec, and append caveats to `## Notes`.

**Case B — plan NEW (write the full file):**

```markdown
# Plan: <chunk_label>

## Task description
<2–3 sentences from the chunk goal>

## Objective
Deliver <goal>.
- <one deliverable bullet per spec>

## Problem statement
<current state of the codebase from Step 4>

## Solution approach
Build in phases following the orchestration strategy:
<phase list from orchestration-prompt.md>

## Relevant files

### Existing files (to modify)
<from existing_files_to_modify[]>

### New files
<grouped by layer, from new_files_to_create[], with their test files>

### Spec reference (read-only)
- `specs/chunks/<chunk_dir>/user-prompt.md`
- `specs/chunks/<chunk_dir>/orchestration-prompt.md`
- `specs/chunks/<chunk_dir>/<layer>/*.md`

## Implementation phases
### Phase 1: <name>
<paragraph + bullets per spec>
### Phase N: Validation
<project's build/test/typecheck/lint commands — {{VALIDATION_CMDS}}>

## Team orchestration
- You operate as team lead; you dispatch tasks and never edit code directly.
### Team members
- Builder: **<layer>-builder** — Agent Type: general-purpose, Resume: true
- Validator: **validator** — Agent Type: verify/general-purpose, Resume: false

## Step by step tasks
### 0. Ticket setup
- Move this chunk's tickets to In Progress (`/start-ticket` or `op: set-status`).
### 1. <title>
- **Task ID / Depends On / Assigned To / Agent Type / Parallel**
- <implementation bullets>
- Write tests in `<test_file>`; run `{{TEST_CMD}}`.
### N. Validation
- Run the full gate; verify acceptance criteria.

## Acceptance criteria
<one per spec, plus "build + tests pass">

## Validation commands
<{{VALIDATION_CMDS}} — from the project's CLAUDE.md / verify agent>

## Notes
<one caveat per spec>
```

## Step 7 — Confirm & surface

Print the plan path, the task count, the full plan content, and suggest
`/start-ticket <id_prefix>-<first_number>` or re-running `/update-plan <chunk_dir>` after
adding more specs.

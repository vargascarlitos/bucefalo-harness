---
name: start-ticket
description: 'Runs the ticket readiness gate, syncs with main, creates the feature branch, dispatches the consolidated implement agent, then chains to /complete-dev.'
triggers:
  - 'start ticket'
  - 'begin ticket'
  - 'start work item'
  - 'pick up ticket'
  - 'working on ticket'
---

<objective>
Transition a ClickUp work item to IN_PROGRESS and surface everything the implement agent needs, then build the ticket from scratch.

The workflow:

1. Sweep leftover worktrees, then load project config
2. Resolve the work item via `find-work-item.md`
3. Run the ticket readiness gate (`/ticket-review`) — hard-stop if Not Ready
4. Display details, warn if the ticket is already past TODO, set status IN_PROGRESS
5. Sync the repo with `main`, create and check out the feature branch, surface the spec
6. Dispatch the `implement` agent (consolidated — replaces separate brief / plan / per-layer phases)
7. Chain to `/complete-dev`

PM coupling: this skill never calls ClickUp tools directly — it references the named operations in `.claude/skills/_shared/pm-clickup.md` (`op: find-work-item`, `op: get-task-description`, `op: set-status`, `op: create-task`). Logical states (TODO, IN_PROGRESS, IN_REVIEW, DEV_DONE, QA, QA_REJECT, DONE) resolve to ClickUp status names through `clickup.states` in `.claude/workflow.json`.
</objective>

---

## Step 0 — Sweep leftover worktrees

Read `.claude/skills/_shared/sweep-worktrees.md` using the Read tool and follow the instructions. This is the cross-run safety net for worktrees and `worktree-agent-*` branches left behind by interrupted prior runs. The detector is sub-second when the workspace is clean, so it runs unconditionally.

---

## Step 1 — Load config

Read `.claude/skills/_shared/load-config.md` using the Read tool and follow the instructions. Store the extracted values: `project_name`, `id_prefix`, `specs_path`, and the `clickup` object (`workspace_id`, `space_id`, `list_id`, `states`, `use_custom_task_ids`).

Before the first ClickUp call, verify the MCP is reachable as described in `load-config.md` (a cheap read like `clickup_get_list(list_id)`). If it fails, tell the user to connect the ClickUp connector and stop.

---

## Step 2 — Identify the work item

If the user invoked the command with an argument (e.g. `/start-ticket <id_prefix>-42`), use that reference directly. Otherwise ask:

> Which work item are you starting? (e.g. `<id_prefix>-42`)

Read `.claude/skills/_shared/find-work-item.md` using the Read tool and follow the instructions to resolve the work item. This returns `{ task_id, name, status, url, list_id }`, where `status` is the raw ClickUp status string. Map `status` back to a logical state via `clickup.states` (reverse lookup) — call it `logical_state`.

`find-work-item.md` also tells you whether a **local spec file** exists for this reference (via its Glob fast-path). Track `local_spec_path` (the resolved spec file, or `null`).

Branch on what was found:

- **Found in ClickUp and locally** → store `task_id`, `name`, `status`, `logical_state`, `url`, `local_spec_path`. Proceed to Step 2.5.
- **Found in ClickUp, no local spec** → confirm, then create the local spec later (Step 5b). See Step 2b.
- **Local spec exists, not in ClickUp** → confirm, then create the task. See Step 2c.
- **Found in neither** → may be brand-new. See Step 2d.

### Step 2b — Found in ClickUp, not found locally

Confirm before creating the local file:

> I found **<id_prefix>-42 — "<name>"** in ClickUp but there is no matching local spec file. Is this the correct ticket?

Use `AskUserQuestion` with **Yes, create the local file** / **No, I'll re-enter the ID** options.

- If No: ask for the correct ID and restart from Step 2.
- If Yes: proceed to Step 2.5. After the status update (Step 4), create the local spec file as described in Step 5b before surfacing it in Step 6.

### Step 2c — Found locally, not found in ClickUp

Confirm before creating the task:

> I found a local spec file for **<id_prefix>-42** but it does not exist in ClickUp. Is this the correct ticket?

Use `AskUserQuestion` with **Yes, create it in ClickUp** / **No, I'll re-enter the ID** options.

- If No: ask for the correct ID and restart from Step 2.
- If Yes: read the local spec for the title, priority, and description, then apply `op: create-task(title, description_markdown, priority?)` from `pm-clickup.md`. Persist the returned `clickup_id` and `clickup_url` into the local spec frontmatter. Store the new `task_id` and proceed to Step 2.5.

### Step 2d — Found in neither

This may be a brand-new ticket. Verify carefully before creating anything.

**First confirmation:**

> I couldn't find **<id_prefix>-42** in ClickUp or locally. Are you sure this is the right ticket number?

Use `AskUserQuestion` with **Yes, it's new — create it** / **No, let me re-enter** options.

- If No: ask for the correct ID and restart from Step 2.
- If Yes, proceed to second confirmation:

**Second confirmation:**

> Just to confirm — you want to create a brand-new work item **<id_prefix>-42** in both ClickUp and locally. Confirm?

Use `AskUserQuestion` with **Confirmed, create it** / **Cancel** options.

- If Cancel: stop and inform the user no changes were made.
- If Confirmed: collect via `AskUserQuestion` / follow-up messages before creating anything:
  1. **Name** — short title
  2. **User story** — "As a [role], I want [goal]..."
  3. **Priority** — `urgent` / `high` / `normal` / `low`
  4. **Details / acceptance criteria** — free-text (can be brief)

Then apply `op: create-task(title, description_markdown, priority?)` from `pm-clickup.md`. Persist the returned `clickup_id` and `clickup_url`, create the local spec file (Step 5b format), and proceed to Step 2.5.

> Note: richer ticket authoring (full Acceptance Criteria / Edge Cases / Scope per the work-item template) belongs in `/create-ticket`. This inline create is a minimal fallback.

---

## Step 2.5 — Ticket readiness gate

Before any branch is created or work begins, the ticket must pass the readiness gate.

Invoke `/ticket-review "<id_prefix>-42"` as a sub-skill. It loads the ticket body via `op: get-task-description(task_id)` and checks Acceptance Criteria, Edge Cases, and Scope.

- If the gate returns **Ready** → proceed to Step 3.
- If the gate returns **Not Ready** and the dev declines to refine → abort `/start-ticket` with exit code 1.
- If the dev passed `--force` to `/start-ticket`, propagate `--force` to `/ticket-review` and continue regardless of verdict.

> (Confidence-based mode detection and the force-record feedback log are deferred — not in core-loop template.)

---

## Step 3 — Display work item details and pre-check state

Show a summary before making any changes:

```
Work item:  <id_prefix>-42 — <name>
Priority:   <priority>
State:      <logical_state>   (ClickUp: <raw status>)
```

If `logical_state` is anything other than TODO, warn the user with a message tailored to the current state:

- **IN_PROGRESS**: "This ticket is already In Progress. Do you still want to restart it?"
- **IN_REVIEW**: "This ticket is currently In Review — the MR is open awaiting code review. Moving it back to In Progress signals the developer needs to make changes. Continue?"
- **DEV_DONE**: "This ticket is marked Dev Done — code review passed and it's awaiting QA. Moving it back to In Progress will reopen it for more development work. Continue?"
- **QA**: "This ticket is currently in QA testing. Moving it back to In Progress will pull it out of QA. Continue?"
- **QA_REJECT**: "This ticket was rejected by QA. Moving it to In Progress is the normal next step to fix it. Continue?"
- **DONE**: "This ticket is already Done. Moving it to In Progress will reopen it. Continue?"

Use `AskUserQuestion` with Yes / No options and stop if they decline.

---

## Step 3.5 — Spec quality check

**Only run this step if a local spec file was found in Step 2 (`local_spec_path` is not null). Skip entirely if the file doesn't exist yet.**

Read the local spec file and check the following. Run all checks before reporting anything.

| Check                 | Pass condition                                                   |
| --------------------- | --------------------------------------------------------------- |
| User Story            | Section present and contains > 20 characters of meaningful text |
| Details & Assumptions | Section present and contains > 50 characters of meaningful text |
| Priority              | `priority` on the task is not null / "none"                     |

**Classify the result and act accordingly:**

**All pass:** Print `✓ Spec looks complete` and continue to Step 4 with no prompt.

**Minor gaps only** (priority not set, but User Story and Details are present): print a short warning list, then continue to Step 4 automatically — no prompt needed.

**Critical gaps** (User Story missing/too short, OR Details & Assumptions missing/too short):

### Step 3.5a — Try to pull from ClickUp

Before prompting, attempt to retrieve the full description from ClickUp via `op: get-task-description(task_id)`. Check whether it contains the missing sections (`## User Story` and `## Details & Assumptions` with substantial content).

**If the ClickUp description is complete:** extract the sections and use the Edit tool to populate the local spec file. Continue to Step 4 with:

```
✓ Pulled missing sections from ClickUp and updated spec file
```

**If the ClickUp description is also incomplete or empty:** use `AskUserQuestion`:

> The spec is missing critical fields: [list]. AI output will be harder to validate without this context. How would you like to proceed?

Options:

- `Proceed anyway — I'll guide Claude directly`
- `Stop — I'll update the spec first`

If **Stop**: print the following, then halt without changing any state:

```
To improve the spec:
1. Update the work item description in ClickUp (add user story + acceptance criteria)
2. Update the local file at <specs_path>/<filename>.md
3. Run /start-ticket again when ready
```

If **Proceed anyway**: continue to Step 4.

> (Deeper spec hole-poking — state-matrix coverage, per-method authorization, external-integration error mapping, etc. — is product/stack-specific and is deferred; not in core-loop template.)

---

## Step 4 — Set status IN_PROGRESS in ClickUp

Apply `op: set-status(task_id, IN_PROGRESS)` from `pm-clickup.md`. This resolves IN_PROGRESS to the ClickUp status name via `clickup.states.in_progress`.

> If ClickUp rejects the status as invalid, follow the recovery note in `pm-clickup.md`: call `clickup_get_task(task_id, expand_statuses: true)`, reconcile against `clickup.states`, and tell the user which status is missing in ClickUp.

Confirm the update succeeded before continuing.

---

## Step 4.5 — Sync with main, then create the git branch

### Sync first (git hygiene)

Before creating a branch or making changes, sync the repo with `main` so work starts from current state. Run via Bash:

```bash
git fetch origin
git merge origin/main
```

If the merge reports conflicts or fails, surface the output and stop — the user must resolve the repo state before starting work. If the working tree is dirty and the merge is refused, tell the user to commit or stash first.

### Create the branch

Ask the user what type of branch this is:

```
AskUserQuestion:
  Q: "What type of branch is this?"
     header: "Branch type"
     options: [
       "feat — new feature",
       "fix — bug fix",
       "chore — maintenance / dependency / config",
       "docs — documentation only",
       "refactor — code restructure without behaviour change"
     ]
```

Generate the branch name using the format:

```
<type>/<lowercase-id_prefix>-<issue_number>-<slug>
```

- `<type>` is the prefix selected (e.g. `feat`, `fix`)
- `<lowercase-id_prefix>` is `id_prefix` in lowercase (e.g. `task`)
- `<issue_number>` is the unpadded number (e.g. `42`, not `0042`)
- `<slug>` is the work item name slugified: lowercase, spaces to hyphens, strip special characters, max ~40 chars

Example: `feat/task-42-add-user-authentication`

Display the generated name before creating anything:

> Branch: `<branch-name>` — creating and checking out now.

Then:

1. Run `git rev-parse --verify <branch-name>` to check if the branch already exists locally.
2. If it **does not exist**: run `git checkout -b <branch-name>`.
3. If it **already exists**: inform the user and ask via `AskUserQuestion`:

   > Branch `<branch-name>` already exists. What would you like to do?

   Options:
   - `Check out the existing branch` → run `git checkout <branch-name>`.
   - `Create with a different name — I'll type it` → ask for the name, run `git checkout -b <custom-name>`, store that name instead.

Store the final branch name as `branch_name` for use in Step 5.

---

## Step 5 — Update or create the local spec file

### Step 5a — File exists: update it

Use the Edit tool to update only the file resolved in Step 2. The file uses YAML frontmatter:

- `state: <old value>` → `state: In Progress`
- `start_date: <old value>` → `start_date: <today YYYY-MM-DD>`
- If `branch:` already exists, update its value to `<branch_name>`. If not, add `branch: <branch_name>` (after `start_date`).

### Step 5b — File does not exist: create it

Create `<specs_path>/<id_prefix>-<padded_number>-<slugified-name>.md` using the Write tool. Slugify the name: lowercase, spaces to hyphens, strip special characters.

Use this format exactly, populated from the task data (or user-provided data for brand-new tickets):

```markdown
---
state: In Progress
priority: <priority>
start_date: <today YYYY-MM-DD>
branch: <branch_name>
clickup_id: <task_id>
clickup_url: <task_url>
---

# <id_prefix>-<number>: <Name>

## User Story

<user story text>

## Details & Assumptions

<description or acceptance criteria from the task, or user-provided>
```

---

## Step 6 — Surface the spec for context

After the status update:

1. Print the full content of the local spec file.
2. If no local spec file exists, display the task description from ClickUp instead (via `op: get-task-description(task_id)`).

> (This skill surfaces the work-item spec; richer chunk-spec / design-system context is not auto-loaded here.)

---

## Step 7 — Dispatch the implement agent

The implement agent's instructions live at `.claude/agents/implement/system-prompt.md`. In this template the implement agent is **stack-agnostic** — its build/test idioms and gates are filled in per project (Layer 3). The `Agent` tool does not resolve custom project agent names, so use `subagent_type: "general-purpose"` and prepend the system-prompt content to the dispatch prompt.

The orchestrator:

1. Reads `.claude/agents/implement/system-prompt.md` using the Read tool.
2. Reads the ticket spec and any path-scoped coding-rules files under `.claude/rules/` that apply to the files being touched (project-specific; may be absent in a fresh template).
3. Extracts the relevant excerpts to pass as the agent's input (NOT the full file paths — the agent receives excerpts).
4. Dispatches:

   ```
   Agent(
     description: "Implement <id_prefix>-42",
     subagent_type: "general-purpose",
     isolation: "worktree",
     prompt: "<full contents of .claude/agents/implement/system-prompt.md>\n\n---\n\n<excerpts + ticket body + branch name>"
   )
   ```

5. On return, parse the JSON deliverable. If `budget_exceeded: true`, surface to the dev with what's incomplete.
6. If all ACs are marked `status: passed`, proceed to chain `/complete-dev`.
7. If any AC failed, surface to the dev (no auto-retry).

---

## Step 8 — Hand off to /complete-dev

Display:

```
✓ Implement complete for <id_prefix>-42
  Branch: <branch_name>

Next: invoke /complete-dev <id_prefix>-42 to run the gates, create the MR, and route the ticket.
```

Then invoke `/complete-dev <id_prefix>-42`.

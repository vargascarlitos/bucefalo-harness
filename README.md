# Claude Code Harness Template — ClickUp edition

A portable, stack-agnostic Claude Code "harness" (AI-assisted SDLC workflow) wired to
**ClickUp via the ClickUp MCP**.

This template is **stack-agnostic** for the orchestration layer (Layer 1) and the
ClickUp integration (Layer 2). The product/stack-specific layer (Layer 3 — coding
rules, the `implement`/`verify` gate commands, code-review specialists) ships with
placeholders you fill in once your project's stack is known.

## The three layers

| Layer | What | Status in this template |
|-------|------|--------------------------|
| 1. Orchestration brain | The SDLC skills + `_shared` helpers + `specs/` format + hooks | Ported, ready |
| 2. PM-tool integration | ClickUp calls via MCP, centralized in `_shared/pm-clickup.md` | Ported, ready |
| 3. Product/stack | `CLAUDE.md`, `.claude/rules/`, verify gate commands, review specialists | Placeholders — fill per project |

## Key difference vs the Plane original

Plane was wired through a Python CLI (`plane_cli.py`) invoked over Bash, plus a SQLite
cache, plus `PLANE_API_KEY` / `plugin_dir` / `python_bin`. **All of that is gone.**
ClickUp is reached through the **ClickUp MCP** (an account-level claude.ai connector),
so skills call MCP tools directly. The entire PM coupling is centralized in one file:
`.claude/skills/_shared/pm-clickup.md`. Swap that one file to retarget another PM tool.

## Prerequisites

1. **ClickUp MCP connected** in your Claude Code session (claude.ai connector).
   Verify with a read call like `clickup_get_workspace_hierarchy`.
2. A target ClickUp **List** for your project's tickets.

## One-time ClickUp setup (manual — the MCP cannot do these)

The ClickUp MCP can create tasks/comments/docs but **cannot create custom statuses**
or enable custom Task IDs. Do these in the ClickUp UI:

1. **Statuses.** On your target List (or its Space), configure these 7 statuses to mirror
   the workflow state machine (List settings → Statuses):

   ```
   Todo → In Progress → In Review → Dev Done → QA → QA Reject → Done
   ```

   Type mapping: `Todo` = not started; `In Progress`/`In Review`/`Dev Done`/`QA`/`QA Reject`
   = active/custom; `Done` = done/closed.

2. **(Optional) Custom Task IDs.** Enable the *Task IDs* ClickApp and set a per-Space prefix
   (e.g. `TASK`) so tasks get human IDs like `TASK-42`. If you do this, set
   `clickup.use_custom_task_ids: true` in `.claude/workflow.json`. Otherwise the harness uses
   ClickUp's native task IDs.

## Configure the harness

Edit `.claude/workflow.json`:

- `project_name` — your project's name
- `id_prefix` — ticket prefix for local spec filenames (e.g. `TASK` → `TASK-0042-slug.md`)
- `clickup.workspace_id` / `space_id` / `list_id` — your target IDs
  (resolve them with `clickup_get_workspace_hierarchy` or `clickup_get_list`)
- `clickup.states` — only change the right-hand values if your ClickUp statuses differ
  from the canonical names

> The values shipped here point at the **"List"** list (`901114014067`) in the dedicated
> **"harness-clickUp"** Space (`90114195110`), which has the 7 harness statuses configured
> and is used to validate the port. Change them for a real project.

There is **no `workflow.local.json`** in the ClickUp edition — user identity comes from the
MCP (`clickup_get_workspace_members` / `clickup_resolve_assignees`).

## The core loop (what's included)

```
/create-ticket   → create ClickUp task + local work-item spec
/ticket-review   → readiness gate (mechanical + semantic + cross-layer)
/start-ticket    → gate, branch, dispatch implement agent, status → In Progress
/complete-dev    → dispatch verify agent; pass → In Review (+ MR link + comment), fail → In Progress
/pr-review       → code review; approve → Dev Done, changes → In Progress
/review-outcome  → QA outcome; pass → Done, fail → QA Reject
```

Deferred to later phases (not in this template yet): `create-chunk`, `update-plan`,
feedback/`ai-insights`/`improve-agents`, `mutation-tests`, the CI `review-agent`.

## Filling in Layer 3 (when your stack is known)

1. Write `CLAUDE.md` from `CLAUDE.md.template` (project overview, commands, architecture).
2. Add `.claude/rules/*.md` with path-scoped coding conventions for your stack.
3. Fill the gate commands in `.claude/agents/verify/system-prompt.md`
   (`{{TEST_CMD}}`, `{{LINT_CMD}}`, `{{TYPECHECK_CMD}}`, `{{FORMAT_CMD}}`).
4. Fill the build/test idioms in `.claude/agents/implement/system-prompt.md`.

## Directory layout

```
.claude/
├── settings.json              # hooks + permissions (no PM plugin — ClickUp is an MCP)
├── workflow.json              # project + ClickUp config
├── skills/
│   ├── _shared/
│   │   ├── pm-clickup.md       # ★ the entire PM coupling: logical op → MCP tool + status map
│   │   ├── load-config.md
│   │   └── find-work-item.md   # clickup_search/filter (no SQLite)
│   ├── create-ticket/
│   ├── ticket-review/
│   ├── start-ticket/
│   ├── complete-dev/
│   ├── pr-review/
│   └── review-outcome/
├── agents/
│   ├── implement/             # stack-agnostic, gate placeholders
│   └── verify/                # stack-agnostic, gate placeholders
└── hooks/
    ├── audit-docs-hook.sh
    └── audit-docs.sh
specs/
├── work-items/_template.md
├── chunks/
└── plans/
```

# Shared: Load Config

Read `.claude/workflow.json` using the Read tool. Extract and store:
- `project_name` — human-readable name (e.g. `"Harness Test"`)
- `id_prefix` — ticket prefix for local spec filenames (e.g. `"TASK"`)
- `specs_path` — local path where spec files live (e.g. `"specs/work-items"`)
- `pm_tool` — must be `"clickup"` for this harness edition
- `clickup` — object with:
  - `workspace_id`, `space_id`, `list_id` — target ClickUp IDs
  - `states` — logical-state → ClickUp-status-name map (see `pm-clickup.md`)
  - `use_custom_task_ids` — whether tasks use a custom id prefix (e.g. `TASK-42`)

If the file does not exist or cannot be parsed:
```
No project config found at .claude/workflow.json.
```
Stop.

If `pm_tool` is not `"clickup"`:
```
This harness edition expects pm_tool: "clickup" in .claude/workflow.json.
```
Stop.

## No machine-local config

There is **no `.claude/workflow.local.json`**. ClickUp is reached
through the ClickUp MCP (an account-level connector), and user identity is resolved at
runtime via `op: resolve-current-user` in `pm-clickup.md`. Before the first ClickUp call,
verify the MCP is reachable with a cheap read (e.g. `clickup_get_list(list_id)`); if it
fails, tell the user to connect the ClickUp connector in Claude Code, then stop.

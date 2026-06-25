# Shared: Find Work Item (ClickUp)

Resolves a ClickUp work item from a user-supplied reference, using the local spec file as
a fast path to skip a ClickUp round-trip when possible. Resolution is via the local spec
frontmatter and the ClickUp MCP.

## Accepted reference forms

- Native ClickUp task id (e.g. `86abc123`)
- Custom task id (e.g. `TASK-42`) when `use_custom_task_ids` is true
- A task URL (`https://app.clickup.com/.../t/<task_id>`) — extract the id segment
- A local spec filename or ticket identifier (`TASK-42`, `TASK-0042-slug`)

## Parse the identifier

If the reference looks like `<id_prefix>-<n>`, break it into:
- `id_prefix` — prefix before the dash (e.g. `TASK`)
- `issue_number` — numeric part (e.g. `42`)
- `padded_number` — zero-padded to 4 digits (e.g. `0042`)

## Fast path — local spec carries the ClickUp id

Glob for `<specs_path>/<id_prefix>-<padded_number>-*.md`.

If exactly one file is found and its YAML frontmatter has a `clickup_id`, use it directly:

```
clickup_get_task(task_id: <clickup_id>, include: ["description"])
```

If the task resolves, skip to **Resolution**.

## Standard path — resolve via ClickUp

Used when no local spec exists, the spec has no `clickup_id`, or the fast-path lookup
failed.

- If `use_custom_task_ids` is true and the reference is `TASK-42`, try
  `clickup_get_task(task_id: "TASK-42")` directly (custom ids are accepted).
- Otherwise, list candidates from the configured list and match by name/number:
```
clickup_filter_tasks(list_ids: [<clickup.list_id>], include_closed: true)
```
  or, for a keyword reference:
```
clickup_search(keywords: "<reference>", filters: { asset_types: ["task"],
  location: { subcategories: [<clickup.list_id>] } })
```

## Duplicate / ambiguous detection

Enter the disambiguation flow if:
- The lookup returned no task or an error, OR
- The local Glob returned more than one file, OR
- A keyword search returned multiple plausible tasks

1. Read each candidate local spec and extract its `clickup_id`.
2. Resolve each with `clickup_get_task`.
3. Present a candidate list (name, task id, status, local filename) and ask the user to pick.

If no reference resolves at all, stop and ask the user for the task id or URL — never invent one.

## Resolution

Store the resolved work item's `task_id`, `name`, `status` (raw ClickUp status string),
`url`, and `list_id`. Map the raw status back to a logical state via `clickup.states`
(reverse lookup) and return to the calling skill's branching logic.

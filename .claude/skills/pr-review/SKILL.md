---
name: pr-review
description: Conducts a structured code review on a ClickUp work item in In Review state. Uses your git host CLI (glab for GitLab, gh for GitHub). Auto-detects the open MR/PR for the current branch, surfaces the diff summary and CI pipeline status, collects structured code review findings, posts a JSON record as a ClickUp comment AND a summary on the MR/PR, then transitions the ticket to Dev Done (approved) or back to In Progress (changes requested).
triggers:
  - 'pr review'
  - 'code review'
  - 'review pr'
  - 'review merge request'
  - 'review the pr'
  - 'approve pr'
  - 'pr-review'
  - 'review code'
---

<objective>
Conduct a structured code review on a ClickUp work item and record the outcome in both
ClickUp and the git host. This skill follows `/complete-dev` (which left the ticket in
In Review with an MR linked) and precedes `/review-outcome` (QA). The workflow:

1. Load project config and verify the ClickUp MCP is reachable
2. Verify your git host CLI is installed and authenticated
3. Identify the target work item (expected logical state: IN_REVIEW)
4. Find and surface the open MR/PR for the branch (diff summary + CI status)
5. Collect structured code review findings via survey
6. Post a structured `code-review` record as a ClickUp comment (`op: post-workflow-record`)
7. Post a human-readable review summary on the MR/PR via the git host CLI
8. Transition the ticket: approved → DEV_DONE; changes requested → IN_PROGRESS
   </objective>

> All PM operations referenced below (`op: find-work-item`, `op: set-status`, etc.) are
> defined in `.claude/skills/_shared/pm-clickup.md`. Never call ClickUp MCP tools or
> hardcode status names directly — go through the named operations and the logical states
> (TODO / IN_PROGRESS / IN_REVIEW / DEV_DONE / QA / QA_REJECT / DONE).

> This skill is the **human-driven** review. The automated CI **review-agent**
> (`.github/workflows/review-agent.yml`) runs separately on every PR. Fusion-agent
> ingestion and verdict scoring/calibration are not included.

---

## Step 1 — Load config

Read `.claude/skills/_shared/load-config.md` and follow it. Store: `project_name`,
`id_prefix`, `specs_path`, and the `clickup` block (`list_id`, `states`,
`use_custom_task_ids`).

Per `load-config.md`, before the first ClickUp call, verify the MCP is reachable with a
cheap read (e.g. `clickup_get_list(list_id)`). If it fails, tell the user to connect the
ClickUp connector, then stop.

---

## Step 1.5 — Verify the git host CLI is installed and authenticated

This template supports either **GitLab** (`glab`) or **GitHub** (`gh`). Detect which the
project uses from the `origin` remote, then check that the matching CLI is available.

Run via Bash:

```bash
git remote get-url origin
```

- If the host looks like GitLab → use `glab` (commands below default to `glab`).
- If the host looks like GitHub → use `gh` (substitute the equivalent `gh` commands noted
  inline; e.g. `gh pr list --head <branch>`, `gh pr view <num> --json ...`,
  `gh pr comment <num> --body ...`).

Check the CLI (substitute `gh` for `glab` on GitHub). Run each as a separate Bash call:

```bash
which glab
```

```bash
glab auth status 2>&1
```

If the CLI is **not found**:

```
<glab|gh> is required for /pr-review but is not installed.

Install it:
  GitLab (glab): brew install glab   |   https://gitlab.com/gitlab-org/cli#installation
  GitHub (gh):   brew install gh     |   https://cli.github.com

Then authenticate:
  glab auth login --hostname <your-git-host>   (or: gh auth login)

And run /pr-review again.
```

If the CLI is installed but **not authenticated** (output contains "No token" or similar):

```
<glab|gh> is installed but not authenticated.

Run:
  glab auth login --hostname <your-git-host>   (or: gh auth login)

Then run /pr-review again.
```

**STOP here if the git host CLI is not installed or not authenticated.**

---

## Step 2 — Identify the work item

If the user invoked the command with an argument (e.g. `/pr-review <id_prefix>-42`), use
that reference directly. Otherwise ask:

> Which work item are you reviewing? (e.g. `<id_prefix>-42`, a ClickUp task id, or a task URL)

Read `.claude/skills/_shared/find-work-item.md` and follow it to resolve the work item.
It returns `{ task_id, name, status, url, list_id }` and maps the raw ClickUp `status`
back to a **logical state** via the `clickup.states` reverse map.

**Auto-select if unambiguous:** if exactly one candidate resolves to logical state
**IN_REVIEW**, select it automatically — no prompt needed. Otherwise present candidates
via `AskUserQuestion`.

Store the resolved `task_id`, `name`, current logical state, `url`, and any local spec
file path (the Glob from `find-work-item.md`).

### State check

The expected logical state is **IN_REVIEW**. If the item is in a different state (map the
raw status to a logical state first), warn before proceeding:

- **IN_PROGRESS**: "This ticket is still In Progress — the developer hasn't finished and
  marked it ready for review yet. Are you sure you want to review it now?"
- **DEV_DONE**: "This ticket is already Dev Done — the MR was already approved. Are you
  sure you want to re-review it?"
- **QA / DONE**: "This ticket is already past code review (state: <state>). Are you sure
  you want to log a code review now?"
- **Any unexpected state**: "This ticket is in '<state>', not In Review. Are you sure you
  want to continue?"

Use `AskUserQuestion` with **Yes, proceed anyway** / **No, cancel** — stop if they cancel.

- If the state is **IN_REVIEW**: proceed normally — no prompt needed.

---

## Step 3 — Find the MR/PR

### 3a — Resolve the source branch

Determine the source branch in priority order:

1. **Spec file branch** (most reliable): if a local spec file was found in Step 2, read its
   `branch` frontmatter key (set during `/start-ticket`).
2. **Current branch fallback**: run `git rev-parse --abbrev-ref HEAD` via Bash.

Store as `source_branch`.

If the branch resolves to `main`, `master`, or another default branch name, do **not** use
it silently. Display:

> Could not determine the feature branch for this ticket — the spec file has no `branch`
> frontmatter key and you appear to be on `<branch>`. Please provide the branch name or
> MR/PR number:

Collect from the user.

### 3b — Detect the git host project path

Run via Bash:

```bash
git remote get-url origin
```

Parse the project path (`<group>/<project>` or `<owner>/<repo>`) from the remote URL.
Examples:

- `https://gitlab.example.com/acme/my-project.git` → `acme/my-project`
- `git@gitlab.example.com:acme/my-project.git` → `acme/my-project`
- `https://github.com/acme/my-project.git` → `acme/my-project`

Store as `git_project`.

### 3c — Find the open MR/PR

GitLab:

```bash
glab mr list --source-branch "<source_branch>" --repo "<git_project>" -F json 2>/dev/null
```

GitHub:

```bash
gh pr list --head "<source_branch>" --repo "<git_project>" --json number,title,url,state 2>/dev/null
```

Parse the JSON and filter for an open MR/PR.

If multiple open MRs/PRs are found, present them via `AskUserQuestion` so the reviewer can
pick the correct one.

If none is found:

> No open MR/PR found for branch `<branch>`. Please provide the MR/PR number or URL:

Collect from the user and retrieve directly:

```bash
glab mr view <iid> --repo "<git_project>" -F json 2>/dev/null
# GitHub: gh pr view <number> --repo "<git_project>" --json number,title,body,baseRefName,author,createdAt,url,changedFiles 2>/dev/null
```

### 3d — Fetch MR/PR details and pipeline status in parallel

Run both via Bash simultaneously.

**MR/PR details:**

```bash
glab mr view <iid> --repo "<git_project>" -F json 2>/dev/null
# GitHub: gh pr view <number> --repo "<git_project>" --json number,title,body,baseRefName,author,createdAt,url,changedFiles 2>/dev/null
```

Extract: title, description, target branch, author username, created date, web URL, and
the number of changed files.

**Pipeline / CI status:**

Run the first command, and only if it produces no useful output, run the fallback:

```bash
glab mr checks <iid> --repo "<git_project>" 2>/dev/null
```

```bash
glab ci status --branch "<source_branch>" --repo "<git_project>" 2>/dev/null
# GitHub: gh pr checks <number> --repo "<git_project>" 2>/dev/null
```

Normalise status to one of: `passed`, `failed`, `running`, `canceled`, `none`.

**Existing comments count (best-effort):**

```bash
glab api "projects/<url-encoded git_project>/merge_requests/<iid>/notes?per_page=1" 2>/dev/null
# GitHub: gh pr view <number> --repo "<git_project>" --json comments 2>/dev/null
```

Use the response to get a comment count. If awkward to parse, record "N/A" rather than
blocking.

### 3e — Display MR/PR summary

```
MR/PR: !<iid> — <title>
Branch: <source> → <target>
Author: <author>
Pipeline: <status>
Changed files: <N>
Existing comments: <N>
```

**CI gate:** If pipeline is `failed` or `canceled`:

> ⚠ The CI pipeline for this MR/PR is failing. Reviewing a failing build is unusual — the
> developer should fix CI before requesting review. Do you want to continue anyway?

Use `AskUserQuestion` with **Yes, review anyway** / **No, cancel** — stop if they cancel.

If pipeline is `running`, note it but do not block: `ℹ Pipeline is still running — results
may change.`

### 3f — Link the MR/PR to the ClickUp task

Record the MR/PR URL on the ticket via **`op: link-mr`** (see `pm-clickup.md`):

```
op: link-mr(task_id: <task_id>, mr_url: "<MR_WEB_URL>")
```

(`link-mr` posts `MR: <url>` as a ClickUp comment by default, or sets a URL custom field
if one is configured.)

---

## Step 4 — Surface context for the reviewer

If a local spec file was found in Step 2, read it and extract:

- **User Story**
- **Acceptance Criteria**

Display:

```
Spec: <id_prefix>-42 — <name>

User Story:
  <user story text>

Acceptance Criteria:
  <criteria text>
```

If no spec file is found, skip this section silently.

---

## Step 5 — Collect code review findings

Use `AskUserQuestion` in logical batches (1–4 questions per call, 2–4 options each).

### Batch A — Correctness

```
AskUserQuestion:
  Q1: "Does the implementation correctly satisfy the acceptance criteria?"
      header: "Correctness"
      options: [
        "Yes — fully correct",
        "Mostly — minor gaps or edge cases missed",
        "Partially — some criteria missed or misunderstood",
        "No — significant correctness issues"
      ]

  Q2: "Were there any logic errors, bugs, or incorrect behaviour in the code?"
      header: "Logic errors"
      options: [
        "None found",
        "Minor issues (cosmetic, edge cases)",
        "Moderate issues (wrong logic, missed case)",
        "Major issues (broken core behaviour)"
      ]
```

If Q2 is anything other than "None found", follow up:

> Briefly describe the logic issues found:

Collect as `logic_issues_detail`.

### Batch B — Code quality and patterns

```
AskUserQuestion:
  Q3: "Were the right patterns and abstractions used?"
      header: "Patterns"
      options: [
        "Yes — clean, consistent with the codebase",
        "Minor inconsistencies (style, naming)",
        "Pattern violations (wrong abstraction, wrong layer, duplicated logic)",
        "Architectural issues requiring structural changes"
      ]

  Q4: "Was test coverage adequate?"
      header: "Test coverage"
      options: [
        "Good coverage",
        "Acceptable — minor gaps",
        "Insufficient — key paths untested",
        "No tests added / tests missing entirely"
      ]
```

### Batch C — Change request and verdict

```
AskUserQuestion:
  Q5: "How many change request rounds were needed?"
      header: "Change rounds"
      options: [
        "0 — approved on first pass",
        "1",
        "2",
        "3 or more"
      ]

  Q6: "Overall code review verdict"
      header: "Verdict"
      options: [
        "Approved — no changes needed",
        "Approved with minor comments (non-blocking)",
        "Approved after changes were made",
        "Changes requested — needs rework before merge"
      ]
```

### Batch D — Notes (optional)

Ask: "Any additional notes about the code, patterns used, or the review session? (press
Enter to skip)"

---

## Step 6 — Post the structured record to ClickUp

Build the code review JSON from all collected answers:

```json
{
  "kind": "code-review",
  "reviewed_at": "<ISO 8601 date>",
  "work_item": "<id_prefix>-<issue_number>",
  "mr_reference": "!<iid>",
  "correctness": "<fully_correct | mostly_correct | partially_correct | incorrect>",
  "logic_errors": {
    "severity": "<none | minor | moderate | major>",
    "detail": "<free text or null>"
  },
  "patterns": "<clean | minor_inconsistencies | pattern_violations | architectural_issues>",
  "test_coverage": "<good | acceptable | insufficient | missing>",
  "change_rounds": "<0 | 1 | 2 | 3+>",
  "verdict": "<approved | approved_with_comments | approved_after_changes | changes_requested>",
  "notes": "<free text or null>"
}
```

Post it as a structured ClickUp comment via **`op: post-workflow-record`** (see
`pm-clickup.md`):

```
op: post-workflow-record(task_id: <task_id>, kind: "code-review", payload: <the JSON above>)
```

`/review-outcome` and any later analytics parse these records.

> **No feedback branch.** The record lives as a task comment, so there is nothing to commit
> or push. (Standalone observations go through `/feedback`; aggregation through `/ai-insights`.)

---

## Step 7 — Post a summary comment on the MR/PR

Post a human-readable summary to the MR/PR via the git host CLI:

```bash
glab mr note <iid> --repo "<git_project>" --message "**Code Review Summary**

Verdict: <verdict>
Correctness: <correctness>
Patterns: <patterns>
Test coverage: <test_coverage>
Change rounds: <change_rounds>

<notes if present>

_Logged via /pr-review_"
```

GitHub equivalent:

```bash
gh pr comment <number> --repo "<git_project>" --body "**Code Review Summary** ..."
```

---

## Step 8 — Transition ticket state

Map the verdict to a **logical state** and apply it via **`op: set-status`**.

**Approved** (any approved variant — `approved`, `approved_with_comments`,
`approved_after_changes`):

```
op: set-status(task_id: <task_id>, DEV_DONE)
```

Update the local spec file frontmatter: `state: <clickup.states.dev_done>` (the display
name, e.g. `Dev Done`).

**Changes requested** (`changes_requested`):

```
op: set-status(task_id: <task_id>, IN_PROGRESS)
```

Update the local spec file frontmatter: `state: <clickup.states.in_progress>` (e.g.
`In Progress`).

Use the Edit tool for the local spec update (only if a spec file was found in Step 2).

When changes are requested, include in the summary:

> The developer should review the requested changes before reworking — see the MR/PR
> comment and the ClickUp `code-review` record. Use `/respond-to-feedback` (deferred) or
> rework on the same branch and re-run `/complete-dev`.

---

## Completion

Display a summary:

```
✓ MR/PR !<iid> surfaced and linked to the ClickUp task
✓ code-review record posted as a ClickUp comment
✓ Review summary posted on MR/PR !<iid>
✓ Ticket moved to Dev Done                ← if approved
✓ Ticket returned to In Progress          ← if changes requested
✓ Local spec file updated                 ← if a spec file was found

Summary:
  Correctness:    <correctness>
  Patterns:       <patterns>
  Test coverage:  <test_coverage>
  Change rounds:  <N>
  Verdict:        <verdict>
```

If approved, remind the reviewer:

```
Next: QA can now run /review-outcome to log functional testing findings.
```

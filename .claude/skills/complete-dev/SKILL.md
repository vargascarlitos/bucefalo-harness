---
name: complete-dev
description: 'Dispatches the verify agent, then routes deterministically: pass → IN_REVIEW (+ create MR, attach MR link, post a dev-complete record), fail → IN_PROGRESS (+ surface failures to the dev). Chained from /start-ticket; feeds /pr-review.'
triggers:
  - 'complete dev'
  - 'finish dev'
  - 'dev done'
  - 'mark dev complete'
  - 'complete development'
  - 'wrap up dev'
  - 'complete-dev'
---

<objective>
Close out AI development on a work item by deterministically validating the implementation:

1. Load config, identify the work item
2. Dispatch the consolidated verify agent
3. Route based on the verify result:
   - **Pass** → commit, push, create MR, attach the MR link, transition the ticket to IN_REVIEW, post a `dev-complete` workflow record
   - **Fail** → do not push or create an MR; transition the ticket back to IN_PROGRESS; surface the failures to the dev

This skill is **chained from `/start-ticket`** and **feeds `/pr-review`** (the next reviewer runs `/pr-review` on the MR this skill creates).
</objective>

> PM coupling: every status change, comment, and MR-link in this skill goes through a
> named operation in `.claude/skills/_shared/pm-clickup.md`. Never call ClickUp MCP tools
> or write a literal status string directly — use the `op:` names and the logical states
> (TODO, IN_PROGRESS, IN_REVIEW, DEV_DONE, QA, QA_REJECT, DONE).

---

## Step 0 — Sweep leftover worktrees

Read `.claude/skills/_shared/sweep-worktrees.md` using the Read tool and follow the instructions. This is the cross-run safety net for worktrees and `worktree-agent-*` branches left behind by interrupted prior runs. The detector is sub-second when the workspace is clean, so it runs unconditionally.

---

## Step 1 — Load config

Read `.claude/skills/_shared/load-config.md` using the Read tool and follow the instructions. Store the extracted values (`project_name`, `id_prefix`, `specs_path`, and the `clickup` object). Then run `op: load-pm-config` from `.claude/skills/_shared/pm-clickup.md` to hold the ClickUp IDs and the `states` map, and verify the ClickUp MCP is reachable as described in `load-config.md` (a cheap read such as `clickup_get_list(list_id)`).

---

## Step 2 — Identify the work item

If the user invoked with a ticket argument (e.g. `/complete-dev <id_prefix>-42`), use it. Otherwise ask:

> Which work item are you completing? (e.g. `<id_prefix>-42`)

Resolve it via `op: find-work-item(reference)` (delegates to `.claude/skills/_shared/find-work-item.md`).

**Auto-select if unambiguous:** if exactly one candidate maps to the **IN_PROGRESS** logical state (reverse-lookup the raw ClickUp status through `clickup.states`), select it automatically. Otherwise present all candidates via `AskUserQuestion`.

Store `task_id`, `name`, `status` (raw + logical state), `url`, and the local spec file path. Build the human identifier `<id_prefix>-<issue_number>` and store it as `WORK_ITEM_IDENTIFIER`.

---

## Step 3 — Resolve branch

Determine the source branch:

```bash
git rev-parse --abbrev-ref HEAD
```

Store as `BRANCH_NAME`. If the branch is `main` or `master`, do not proceed:

```
❌ You are on <branch> — switch to the feature branch before completing.
```

**STOP.**

---

## Step 4 — Verify

The verify agent's instructions live at `.claude/agents/verify/system-prompt.md`. The `Agent` tool does not resolve custom project agent names — use `subagent_type: "general-purpose"` and prepend the system-prompt content to the dispatch prompt.

Read `.claude/agents/verify/system-prompt.md` using the Read tool, then dispatch:

```
Agent(
  description: "Verify <WORK_ITEM_IDENTIFIER>",
  subagent_type: "general-purpose",
  prompt: "<full contents of .claude/agents/verify/system-prompt.md>\n\n---\n\nbranch: <BRANCH_NAME>, ticket: <WORK_ITEM_IDENTIFIER>"
)
```

The verify agent runs **the project's verification gates** (the stack-specific test / lint / typecheck / format gates plus any acceptance-criteria coverage check defined in `.claude/agents/verify/system-prompt.md`). It does **not** fix failures — it reports them with `file:line` precision and returns a structured JSON result.

Parse the JSON output. Store the parsed object as `$VERIFY_RESULT`, and keep the compact JSON form as `$VERIFY_RESULT_JSON` for the workflow record. The result has at least:

```json
{ "ticket": "...", "branch": "...", "status": "pass | fail", "gates": [ ... ] }
```

with each failing gate carrying a `failures` array of `{ category|name, file, line, message }`.

---

## Step 5 — Route based on verify result

### If `$VERIFY_RESULT.status == "pass"`:

1. If uncommitted changes exist, surface them to the dev and stage only the safe files. **Never** use `git add -A` — it can sweep in secrets (`.env`, credentials, key files):

   ```bash
   if ! git diff --cached --quiet || ! git diff --quiet; then
     # Show the dev what's pending so they can confirm
     git status --short

     # Stage files by category. Refuse to stage anything matching the suspicious-name
     # patterns even if listed below.
     SUSPICIOUS='^(\\.env|.*credentials.*|.*secret.*|.*\\.pem$|.*\\.key$)'
     MODIFIED_PATHS=$(git status --short | awk '{print $2}' | grep -Ev "$SUSPICIOUS" || true)
     if [ -z "$MODIFIED_PATHS" ]; then
       echo "No safe files to stage (suspicious files filtered). Aborting auto-commit; dev must resolve."
       exit 1
     fi

     echo "$MODIFIED_PATHS" | xargs git add --
     git commit -m "chore(<WORK_ITEM_IDENTIFIER>): finalize work for review"
   fi
   ```

   If the dev has changes they intentionally want excluded (e.g. local dev settings), they should commit or stash before running `/complete-dev`.

2. Push the branch:

   ```bash
   git push -u origin <BRANCH_NAME>
   ```

3. Create the MR using your git host's CLI (e.g. `glab` for GitLab, `gh` for GitHub):

   ```bash
   # GitLab:
   glab mr create --fill --target-branch main
   # — or GitHub:
   # gh pr create --fill --base main
   ```

   Parse the MR/PR number and URL from the output (or `glab mr view --output json` / `gh pr view --json url,number` if needed). Store as `MR_REF` (e.g. `!42` or `#42`) and `MR_URL`.

4. Attach the MR to the ticket via `op: link-mr(task_id, MR_URL)`. (ClickUp links are task↔task, so `link-mr` posts the URL as a comment by default — see `pm-clickup.md`.)

5. Transition the ticket to **IN_REVIEW** via `op: set-status(task_id, IN_REVIEW)`.

6. Post the machine-readable completion record via `op: post-workflow-record(task_id, "dev-complete", payload)` where `payload` is:

   ```json
   {
     "kind": "dev-complete",
     "completed_at": "<ISO 8601 UTC>",
     "work_item": "<WORK_ITEM_IDENTIFIER>",
     "mr_reference": "<MR_REF>",
     "mr_url": "<MR_URL>",
     "branch": "<BRANCH_NAME>",
     "final_commit_sha": "<sha>",
     "verify": <$VERIFY_RESULT_JSON>
   }
   ```

7. Display:

   ```
   ✓ Verify passed
   ✓ MR <MR_REF> created: <MR_URL>
   ✓ <WORK_ITEM_IDENTIFIER> moved to IN_REVIEW

   Next: a code reviewer can run /pr-review on MR <MR_REF>.
         QA follows after code review passes.
   ```

   Done.

### If `$VERIFY_RESULT.status == "fail"`:

1. Do **NOT** commit. Do **NOT** push. Do **NOT** create an MR.

2. Transition the ticket back to **IN_PROGRESS** via `op: set-status(task_id, IN_PROGRESS)`.

3. Print the failures to the dev. Iterate over each failing gate's `failures` (each item has `category`/`name`, `file`, `line`, `message`):

   ```
   VERIFY FAILED — fix and re-run /complete-dev:
     [<gate>] <file>:<line>: <message>
     ...
   ```

4. Stop here — the dev fixes the failures locally and re-runs `/complete-dev`.

---

## Out of scope (deferred)

The following were part of the original Plane workflow and are **intentionally dropped** from this template's core loop:

- **Passive completion feedback record** (local `specs/feedback/.../complete-dev.json` consumed by `/improve-agents`) — deferred; the `op: post-workflow-record` comment on the ticket carries the same metadata for now.
- **Surveys, confidence scoring, token-usage tracking** — removed; not part of the core loop.

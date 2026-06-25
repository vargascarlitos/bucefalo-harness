<!-- .claude/skills/_shared/sweep-worktrees.md -->

# Sweep leftover worktrees

Reusable safety-net check for entry-point skills (`/start-ticket`, `/complete-dev`). Detects worktrees and auto-generated branches left behind by interrupted prior runs and offers to clean them up before the new run begins.

The Agent tool's `isolation: "worktree"` creates `.claude/worktrees/<name>/` directories backed by `worktree-agent-<id>` branches. If a dispatch is interrupted (cherry-pick conflict, user halts the orchestrator, network failure), neither artifact is removed — the next run inherits the leak.

## Why a sweep, not just per-skill cleanup

Per-skill cleanup blocks handle the happy path and halt paths within a single run. The sweep is the cross-run safety net: it catches any leak from a prior session — including from a future skill that forgets to add cleanup.

## Steps

### 1 — Detect

Run both detectors in a single Bash call:

```bash
leftover_dirs=$(ls -1 .claude/worktrees/ 2>/dev/null || true)
leftover_branches=$(git branch --list 'worktree-agent-*' --format='%(refname:short)')

if [ -z "$leftover_dirs" ] && [ -z "$leftover_branches" ]; then
  echo "clean"
else
  echo "--- worktree dirs ---"
  echo "${leftover_dirs:-<none>}"
  echo "--- agent branches ---"
  echo "${leftover_branches:-<none>}"
fi
```

If output is exactly `clean`, skip the rest of this file and continue with the parent skill.

### 2 — Surface and ask

Display the findings to the user:

```
⚠ Leftover artifacts from a prior run detected:

  Worktree directories (.claude/worktrees/):
    <one per line, or "<none>">

  Auto-generated branches (worktree-agent-*):
    <one per line, or "<none>">

These typically come from a skill run that was interrupted before its cleanup step
(e.g. the user halted, a cherry-pick conflicted, or the parent process was killed).
```

Then ask via `AskUserQuestion`:

```
Q: "Clean up the leftover artifacts before continuing?"
   header: "Sweep worktrees"
   options:
     - "Yes, clean them up (recommended)"
     - "No, leave them — I'm investigating"
     - "Show me what's in the worktrees first"
```

Map the answers:

- **Yes** → proceed to Step 3.
- **No** → continue with the parent skill, leaving artifacts in place.
- **Show me** → for each directory, run `git -C .claude/worktrees/<name> status --short && git -C .claude/worktrees/<name> log --oneline -5` and display the output. Then re-ask the question (drop the "Show me" option).

### 3 — Clean up

For each leftover directory:

```bash
git worktree remove -f -f ".claude/worktrees/<name>"
```

For each leftover branch:

```bash
git branch -D <branch_name>
```

If `git branch -D` reports "not fully merged," the branch has commits not on any other ref — these are usually orphaned subagent commits. Surface the branch name and its tip SHA to the user before deciding:

```
⚠ Branch <name> contains unmerged commits — last commit:
  <sha> <subject>

Delete anyway? (the commits will be unreachable but recoverable from reflog for ~30 days)
```

Use `AskUserQuestion` with **Delete anyway** / **Keep — I want to inspect it**. On "Delete anyway," run `git branch -D` again. On "Keep," leave the branch and continue.

### 4 — Confirm

After cleanup, re-run the detector from Step 1 and confirm output is `clean`. Display:

```
✓ Sweep complete — no leftover worktrees or agent branches.
```

If anything remains (e.g. user kept a branch with unmerged commits), display:

```
✓ Sweep complete — kept <N> branch(es) at user request: <list>
```

Then continue with the parent skill.

## Cost

The detector is one `ls` and one `git branch --list` — sub-second. Skip it if the parent skill already ran a sweep earlier in the same invocation.

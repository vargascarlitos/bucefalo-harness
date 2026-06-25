---
name: ticket-review
description: 'Readiness gate skill: checks a work item against the readiness rubric (mechanical + semantic + cross-layer). Returns Ready / Needs refinement / Not ready. On non-Ready, runs an interactive expansion loop with the dev and writes the expanded body back to both the local spec and the ClickUp task description.'
triggers:
  - 'ticket review'
  - 'review ticket'
  - 'check ticket'
  - 'is ticket ready'
  - 'gate ticket'
---

<objective>
Determine whether a work item is ready for AI-assisted development. If not, work
interactively with the dev to fill the gaps, then write the changes back to BOTH
the local spec file (canonical body) and the ClickUp task description (synced copy).

This gate is invoked by `/start-ticket`, which proceeds only on a Ready verdict.
Outcomes:
- **Ready** → caller proceeds.
- **Not ready** (after the user declines to refine) → caller hard-stops.
</objective>

The local `specs/work-items/*.md` markdown is the **canonical** ticket body
(Acceptance Criteria / Edge Cases / Scope per `specs/work-items/_template.md`).
ClickUp holds a synced copy of that body. The gate reads from the local spec and,
where useful, cross-checks the ClickUp copy; after expansion it writes back to both.

---

## Step 1 — Load config

Read `.claude/skills/_shared/load-config.md` and follow it. Hold `id_prefix`,
`specs_path`, and the `clickup.*` config (via `op: load-pm-config` in
`.claude/skills/_shared/pm-clickup.md`).

## Step 2 — Identify the work item

If invoked with an argument (e.g. `/ticket-review <id_prefix>-42`), use it. Otherwise
ask: "Which work item to review? (e.g. `<id_prefix>-42`)"

Resolve the ticket via `.claude/skills/_shared/find-work-item.md` (`op: find-work-item`).
Store:
- `TASK_REF` — the human reference (e.g. `<id_prefix>-42`)
- `CLICKUP_ID` — the resolved `task_id`
- `LOCAL_SPEC_PATH` — the absolute path to the local spec (from the Glob in find-work-item)
- The ClickUp description, fetched with `op: get-task-description(CLICKUP_ID)`

If no local spec file exists for a resolved task, stop and tell the user to run
`/create-ticket` (or create the spec) first — the gate operates on the canonical body.

## Step 3 — Phase A: Mechanical checks

Fast, deterministic checks against the local spec. On any failure, the script prints
the reasons; collect them and proceed directly to Step 7 (skip Phase B/C).

Run the bundled check script (absolute path resolved from this skill's folder):

```bash
python3 "$REPO/.claude/skills/ticket-review/check_mechanical.py" "$LOCAL_SPEC_PATH" "$CLICKUP_ID"
```

Exit 0 = pass (`PHASE A PASS`); non-zero = fail (one `FAIL: <reason>` line each).

**Checks performed by `check_mechanical.py`:**

1. **Required sections present & non-empty:** `## User Story`, `## Acceptance Criteria`,
   `## Edge Cases & Error States`, `## Scope`, `## Design Reference`. Each must have at
   least one non-blank line after the header.
2. **Design links usable:** No empty markdown links (`[label]()`). Unless the Design
   Reference section is explicitly declared N/A (e.g. "N/A — no UI" / api-only /
   backend-only), it must contain at least one non-empty link. (stack-specific notation —
   tune the script for your design tool if needed.)
3. **Parent chunk path resolves:** If frontmatter has `chunk_spec:`, the resolved path
   must exist on disk.
4. **clickup_id matches:** Frontmatter `clickup_id` must equal the resolved `CLICKUP_ID`
   (catches a local spec pointing at the wrong task).
5. **estimate and priority set:** Frontmatter `estimate` and `priority` are non-empty.

If all pass, proceed to Step 4.

## Step 4 — Phase B: Semantic check

A single LLM pass over the ticket body + chunk spec. There is no script — you reason
over the content directly. Gather inputs:

1. Read the local spec file (`LOCAL_SPEC_PATH`) — the canonical body.
2. Fetch the ClickUp description via `op: get-task-description(CLICKUP_ID)`.
3. Read the parent chunk spec at the `chunk_spec:` frontmatter path (if present).

Apply this readiness rubric to the ticket (carried over from the readiness-and-expansion
rubric — keep it intact):

- **Behavior clear?** Is the desired behavior unambiguous?
- **Inputs/outputs defined?**
- **Success conditions testable?** Each AC must have specific, observable success criteria.
  Vague phrases ("should work", "looks correct", "is fine") fail.
- **Failure conditions described?** (validation, bad input, integration failure)
- **Permissions/security expectations clear?** (or explicitly N/A)
- **Integrations/dependencies identified?**
- **Edge cases addressed?**
- **Scope bounded?** (explicit in/out)
- **Anything vague, implied, or assumed?**

**Additional Phase B checks (beyond the base rubric):**

- **Title / User Story alignment** — compare the title's noun phrase with the User Story's
  action. Flag if they describe different scopes (catches title-vs-story drift).
- **Local-spec vs ClickUp drift** — diff the local spec body against the ClickUp
  description. Flag any meaningful divergence (ignore whitespace). The local spec wins;
  the writeback in Step 8 reconciles them.
- **AC testability** — every Acceptance Criterion must have specific, observable success
  criteria.

**Output structure (printed to the user):**

```
PHASE B: <Ready | Needs refinement | Not ready>

Gaps by category:
  [alignment]   <details>
  [drift]       <details>
  [ac-quality]  <details>
  [edge-cases]  <details>
  [scope]       <details>
```

If `Ready`, proceed to Step 5. Otherwise collect the gap list and proceed to Step 7.

## Step 5 — Phase C: Cross-layer audit

```bash
python3 "$REPO/.claude/skills/ticket-review/check_crosslayer.py" "$LOCAL_SPEC_PATH"
```

Exit 0 = pass; non-zero = fail. The script audits the Scope `Consumes:` lines of a
consumer ticket and flags any consumed contract that no sibling ticket in the same chunk
`Provides:`. On fail it lists the unprovided contracts and recommends `/create-ticket`.

This audits each affected layer/component's contracts within a chunk (stack-specific:
the default matches inline-code contracts and `METHOD /path` tokens — tune
`extract_contracts` in the script for your stack's contract notation). Tickets without a
`chunk_spec` or with no consumed contracts pass automatically.

## Step 6 — Decision

- All three phases `Ready` → print "READY: <TASK_REF> passed all gates." and return Ready.
- Any phase flagged issues → print the categorized gap list and proceed to Step 7.

## Step 7 — Interactive expansion loop

For each gap from Phases A/B/C, walk the dev through filling it, **one gap at a time**:

1. **Show the gap and a proposed fix.** Draft the proposal by reading the chunk spec and
   sibling tickets (and any design reference present, via your design tool of choice —
   stack-specific).

2. **Ask the dev to accept, edit, or skip** using `AskUserQuestion`:

   ```
   Question: "Gap: <category> — <specifics>"
   Options:
     - "Accept proposal"
     - "Edit"
     - "Skip (will fail gate)"
   ```

3. **On Edit:** open a free-text prompt for the dev's revised content.

4. **On Skip:** mark the gap unresolved; the gate fails on re-run.

5. **For AC gaps:** draft Given/When/Then candidates from the User Story and chunk spec.
   Iterate one AC at a time until the dev says "done".

6. **For cross-layer gaps:** offer to invoke `/create-ticket` to add the missing provider
   sibling ticket. If accepted, branch into `/create-ticket` interactively, then return.

After all gaps are walked, proceed to Step 8.

## Step 8 — Write back

1. **Write the updated local spec file** with the Write tool. Preserve YAML frontmatter;
   replace the body sections with the expanded content. The local spec is canonical.

2. **Update the ClickUp task description** with `op: set-description`:

   ```
   op: set-description(CLICKUP_ID, <local spec body with YAML frontmatter stripped>)
   ```

   Strip the leading `---`-fenced frontmatter block before sending — ClickUp stores the
   body, not the local frontmatter.

3. **Confirm the diff** by showing the user the before/after of the local file and the
   ClickUp description preview.

## Step 9 — Re-run gate

Re-run Step 3 through Step 6 on the updated spec. Loop until `Ready` or the user aborts.
On abort, return Not ready so the caller hard-stops.

## `--force` override

If invoked with `--force`, skip Steps 3-9 and return Ready immediately. Post a
human-readable note on the task so the override is auditable:

```
op: add-comment(CLICKUP_ID, "ticket-review forced past readiness gate. Reason: <reason if provided>")
```

> Structured `--force` override records are **not** part of this template's core loop.

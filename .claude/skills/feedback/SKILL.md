---
name: feedback
description: Records an AI-workflow observation not tied to a specific ticket (a recurring pattern, a session-level note, a strength). Writes a small standalone JSON record under specs/feedback/standalone/ and commits it. No PM-tool coupling.
triggers:
  - 'log feedback'
  - 'record feedback'
  - 'add feedback'
  - 'feedback'
  - 'note feedback'
---

<objective>
Capture a free-standing observation about how the AI workflow is going — something not
attached to a ticket's dev/review/QA cycle. The record feeds `/ai-insights` (reporting) and
`/improve-agents` (clustering). This skill writes a local JSON file and commits it; it makes
**no** ClickUp calls.
</objective>

---

## Step 1 — Load config

Read `.claude/skills/_shared/load-config.md` and follow it. Store `id_prefix`, `specs_path`.

## Step 2 — Collect the observation

**Batch A** (`AskUserQuestion`):
- Q1 "What kind of observation is this?" header "Category" — options:
  `["A recurring pattern", "A one-off session note", "Both"]` → `category` ∈ `pattern|session|both`
- Q2 "What does it relate to?" header "Pattern type" — options:
  `["Hallucination / wrong fact", "Missed a convention", "Domain misunderstanding", "A strength worth keeping", "Workflow / process", "Other"]`
  → `pattern_type` ∈ `hallucination|missed_convention|domain_misunderstanding|strength|workflow|other`

**Batch B**:
- Q3 "Describe it" header "Detail" — options `["Enter via Other ↓"]` (**required** free text) → `detail`
- Q4 "Related ticket? (optional)" header "Ticket" — options `["None", "Enter <id_prefix>-NN via Other ↓"]` → `ticket_ref` or null
- Q5 "Any extra notes? (optional)" header "Notes" — options `["None", "Enter via Other ↓"]` → `notes` or null

## Step 3 — Pick the filename

Get today's date (`date -u +%F`). Glob `specs/feedback/standalone/<YYYY-MM-DD>-*.json` and
take the next increment, zero-padded to 3 digits. Filename:
`specs/feedback/standalone/<YYYY-MM-DD>-<NNN>.json`.

## Step 4 — Write + commit the record

Write the JSON (timestamp via `date -u +%FT%TZ`):

```json
{
  "type": "feedback",
  "recorded_at": "<ISO 8601 UTC>",
  "ticket_ref": "<id_prefix>-NN or null",
  "category": "<pattern|session|both>",
  "pattern_type": "<hallucination|missed_convention|domain_misunderstanding|strength|workflow|other>",
  "detail": "<free text>",
  "notes": "<free text or null>"
}
```

Commit it **off the feature branch** so it doesn't re-trigger CI on unrelated work:

```bash
CUR=$(git rev-parse --abbrev-ref HEAD)
WK=$(date -u +%G-W%V)                       # ISO week, e.g. 2026-W26
git stash --include-untracked || true
git checkout -B "feedback/$WK" 2>/dev/null || git checkout "feedback/$WK"
git stash pop || true
git add specs/feedback/standalone/<file>.json
git commit -m "chore(feedback): record observation $(date -u +%F)"
git push -u origin "feedback/$WK" 2>&1 || echo "(push skipped — no remote / offline)"
git checkout "$CUR"
```

> If the working tree is dirty in a way that blocks the stash dance, fall back to writing the
> file on the current branch and tell the user to move it onto a `feedback/*` branch later.

## Step 5 — Confirm

```
✓ Feedback recorded: specs/feedback/standalone/<file>.json  (on feedback/<week>)
  category=<category> · pattern_type=<pattern_type>
```

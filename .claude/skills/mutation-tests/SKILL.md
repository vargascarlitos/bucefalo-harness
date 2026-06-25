---
name: mutation-tests
description: Mutation-testing orchestrator. Runs the project's mutation tool, dispatches parallel file-agent test-writers for up to 3 rounds to kill survivors, commits the new tests as a GitHub PR, and surfaces any remaining survivors as a ClickUp summary task. The orchestration is generic; the mutation tool and build/test commands are project placeholders.
triggers:
  - 'mutation tests'
  - 'run mutation testing'
  - 'kill mutants'
  - 'mutation-tests'
---

<objective>
Improve test strength by finding **surviving mutants** (code mutations your tests fail to
catch) and writing tests that kill them. Flow: run the mutation tool → for up to 3 rounds,
dispatch one test-writer agent per surviving file in parallel, write + compile-check their
tests, re-run the tool to confirm kills → commit the kills as a GitHub PR → file a ClickUp
task for anything still surviving.

**Stack-agnostic:** the mutation tool, report path/schema, compile command, and test-file
naming are `{{PLACEHOLDERS}}` supplied by the project (e.g. a `mutation` block in
`.claude/workflow.json`, or filled into this skill per project). The orchestration around
them is portable.
</objective>

> PM ops in `pm-clickup.md`. Git host is GitHub via `gh`.

---

## Step 1 — Load config

Read `.claude/skills/_shared/load-config.md`. Store `id_prefix`, the `clickup` block, and the
project's mutation settings:
- `{{MUTATION_RUN_CMD}}` — command to run the mutation tool, e.g. `--output <dir>`
- `{{MUTATION_REPORT_PATH}}` — where the JSON report lands (per run dir)
- `{{COMPILE_TEST_CMD}}` — compile/build just the tests (to reject broken generated tests)
- `{{TEST_FILE_PATTERN}}` — how a source file maps to its test file, e.g. `<dir>/<Name>Tests.<ext>`
- `{{TEST_STAGE_GLOB}}` — the path/glob to `git add` for generated tests

## Step 2 — Initial run

Run `{{MUTATION_RUN_CMD}}` with output dir `initial`. Read `{{MUTATION_REPORT_PATH}}`.

## Step 3 — Parse survivors

From the report, collect every mutant with `status == "Survived"`. Group by source file. For
each survivor keep `id`, `mutator`, `replacement`, `location` (line/col), and the
`original_snippet` (read from the source). Compute the mutation score
`killed / (killed + survived)`. Hold `remaining` = the survivor set.

> The report shape is tool-specific (`{{MUTATION_REPORT_SCHEMA}}`). The fields above are the
> common denominator across mutation tools — adapt the parse per tool.

## Step 4 — Rounds (up to 3)

Repeat until `remaining` is empty or 3 rounds elapse:

**4a — Dispatch test-writers (parallel).** Read `.claude/agents/mutation-file-agent/index.md`.
For each source file with survivors, dispatch **one** `Agent` (all in a single batch so they
run concurrently), `subagent_type: "general-purpose"`, prompt = the agent file + a
`FIXER_INPUT` block:

```
FIXER_INPUT_START
{ "source_file": "<path>", "test_file": "<path per {{TEST_FILE_PATTERN}}>",
  "round": <n>, "survivors": [ <mutant descriptors> ] }
FIXER_INPUT_END
```

**4b — Collect tests.** Each agent returns JSON between `MUTATION_RESULT_JSON_START` /
`_END` with `{ test_file, test_code }`. Write `test_code` to `test_file`. Skip (with a
warning) any response that doesn't parse.

**4c — Compile-check.** Run `{{COMPILE_TEST_CMD}}`. If it fails, `git checkout --` the
test files written this round (revert) so a broken test never lands.

**4d — Verify kills.** Run the mutation tool again (output `round-<n>`). Compare statuses:
move newly-killed mutants out of `remaining`, accumulate `killed_ids`. Recompute the score.

## Step 5 — Decide output

| killed | remaining | Action |
| ------ | --------- | ------ |
| 0 | 0 | Nothing — exit cleanly |
| ≥1 | 0 | **PR only** |
| ≥1 | ≥1 | **PR + ClickUp task** |
| 0 | ≥1 | **ClickUp task only** |

## Step 6 — Commit + GitHub PR (if killed ≥ 1)

```bash
BR="chore/mutation-test-fixes-$(date -u +%F)"
git checkout -b "$BR" 2>/dev/null || git checkout "$BR"
git add {{TEST_STAGE_GLOB}}
git commit -m "test: kill surviving mutants $(date -u +%F)"
git push -u origin "$BR"
gh pr create --base main --no-editor \
  --title "test: kill surviving mutants $(date -u +%F)" \
  --body "## Mutation auto-fix
**Killed:** <killed_count> · **Remaining:** <remaining_count>
**Score:** <initial>% → <final>%

### New/modified test files
<list>"
```

## Step 7 — ClickUp survivor task (if remaining ≥ 1)

Apply **`op: create-task`** with priority `low`:

```
op: create-task(
  title: "Mutation survivors <YYYY-MM-DD>",
  description_markdown: "<N> mutant(s) survived after 3 rounds.\n\n| File | Line | Mutator | Original | Mutant |\n|---|---|---|---|---|\n<one row per survivor>",
  priority: "low"
)
```

## Step 8 — Summary

```
✓ Killed <X> / <X+remaining> survivors · score <initial>% → <final>%
✓ PR: <pr_url>                (if created)
✓ ClickUp survivor task: <url> (if created)
```

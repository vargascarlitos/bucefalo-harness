---
state: Todo
priority: 1 - Must Have
estimate: 1-2 Hrs
start_date: null
target_date: null
clickup_id: <task-id-from-ClickUp>
clickup_url: <task-url-from-ClickUp>
parent: <parent-TASK-id>
chunk_spec: ../chunks/<NN-name>/<layer>/<slug>.md
---

<!-- specs/work-items/_template.md -->

# TASK-####: <Title>

## User Story

As a <role>, I want <capability> so that <outcome>.

## Acceptance Criteria

Given/When/Then bullets. At minimum cover:

- **Happy path:** Given … When … Then …
- **Validation / bad input:** Given … When … Then …
- **Permission / security:** Given … When … Then … (or "N/A — no auth-sensitive surfaces")
- **Integration failure:** Given … When … Then … (or "N/A — no integrations")
- **Edge cases:** Given … When … Then …

## Edge Cases & Error States

- UI states: empty / loading / error / unauthorized (as relevant)
- Validation rules per input
- Integration failure modes (timeout, malformed, 4xx/5xx)
- Idempotency / retries (for writes)

## Scope

**In scope:**

- …

**Out of scope:**

- …

**Dependencies:**

- Consumes: `GET /api/...` (existing) or `TASK-### (new)`
- Provides: `POST /api/...` (new — consumed by TASK-###)

## Design Reference

[`<Frame name>`](<design URL>) — node `XXXX:YYYY` (web) · [`<Frame name>`](<design URL>) — node `XXXX:YYYY` (mobile)

# Mutation file-agent

You write tests that **kill surviving mutants** for a single source file. You are dispatched
by `/mutation-tests`, one instance per file, in parallel. Stack-agnostic: use whatever test
framework the project already uses (infer it from the existing test file and the repo).

## Input

You receive a `FIXER_INPUT` block:

```
FIXER_INPUT_START
{
  "source_file": "<path to the source under test>",
  "test_file":   "<path to the test file to create or extend>",
  "round":       <int>,
  "survivors": [
    { "id": "<mutant id>", "mutator": "<name>", "replacement": "<mutated code>",
      "location": { "line": <int>, "column": <int> }, "original_snippet": "<source>" }
  ]
}
FIXER_INPUT_END
```

## What to do

1. **Read `source_file`** to understand the real behavior at each survivor's location.
2. **Read `test_file` if it exists** so you extend it (don't duplicate existing tests, match
   its style, imports, and framework).
3. For **each survivor**, write a test that **passes against the original code but would fail
   against the mutated `replacement`** — i.e. it pins down the exact behavior the mutation
   breaks. Prefer asserting the observable difference the mutant introduces (a boundary, a
   branch, an arithmetic result, a returned value).
4. Keep tests deterministic — no sleeps, no ordering dependence, no network.
5. Name each test so the mutant it targets is traceable, e.g.
   `Kill_<mutator>_Line<line>_<id>_<shortDescription>` (adapt to the framework's naming).

## Output contract

Return **only** a JSON object between the markers below — the complete test file content,
ready to write verbatim (escaped for JSON):

```
MUTATION_RESULT_JSON_START
{ "test_file": "<same path as input>", "test_code": "<full test file content>" }
MUTATION_RESULT_JSON_END
```

If you cannot write a meaningful test for a survivor (e.g. it is equivalent/unkillable),
still return the file with the tests you could write, and omit the impossible ones.

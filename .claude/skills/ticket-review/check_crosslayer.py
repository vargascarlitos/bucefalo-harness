#!/usr/bin/env python3
"""Phase C cross-layer audit for /ticket-review (ClickUp, stack-agnostic edition).

A ticket in one layer/component may *consume* a contract (API endpoint, event,
shared type, etc.) that a *sibling* ticket in the same chunk is supposed to
*provide*. This check flags consumed contracts that no sibling ticket provides —
so the dev can add the missing provider ticket before AI work starts.

It is intentionally generic: an earlier version hard-coded `web` →
`api` HTTP endpoints. Here it matches `Consumes:` and `Provides:` lines from the
Scope section across every sibling spec in the chunk directory, by their literal
contract text. Tune `extract_contracts` for your stack's contract notation
(stack-specific).

Layout assumption (matches _template.md frontmatter):
    chunk_spec: ../chunks/<NN-name>/<layer>/<slug>.md
so a chunk directory contains one subdirectory per layer/component, each holding
that layer's chunk specs. Sibling work-item specs live under specs/work-items/
and point back to their chunk spec via `chunk_spec:`.

Usage:
    python3 check_crosslayer.py <local_spec_path>

Exit 0 + "PHASE C PASS" on success (or when nothing to audit);
exit 1 + one "FAIL: ..." line per unprovided contract.
"""

import re
import sys
from pathlib import Path


def find_chunk_dir(spec_path):
    """From the spec's chunk_spec frontmatter, return (chunk_dir, layer).

    chunk_spec like ../chunks/13-feature/web/add-thing.md →
      layer = "web" (the chunk_spec's parent dir name)
      chunk_dir = the chunk root (chunk_spec.parent.parent)
    Returns (None, None) when no chunk_spec is declared.
    """
    text = spec_path.read_text()
    m = re.search(r"^chunk_spec:\s*(\S+)", text, re.MULTILINE)
    if not m:
        return None, None
    raw = m.group(1).strip().strip("\"'")
    # YAML null (chunk_spec: null / ~ / none) means "no chunk" — not a real path.
    # Without this, a standalone ticket's literal "null" resolves to specs/ and the
    # whole specs tree gets audited (false positives). Standalone tickets with no
    # chunk_spec are common, so this matters.
    if raw.lower() in ("null", "none", "nil", "~", ""):
        return None, None
    chunk_path = (spec_path.parent / raw).resolve()
    return chunk_path.parent.parent, chunk_path.parent.name


def scope_section(text):
    m = re.search(r"## Scope(.*?)(?=\n## |\Z)", text, re.DOTALL)
    return m.group(1) if m else ""


def extract_lines(text, label):
    """Return the trimmed text after each 'Consumes:' / 'Provides:' bullet."""
    out = []
    for line in scope_section(text).splitlines():
        m = re.match(rf"\s*[-*]\s+{label}:\s*(.+)", line)
        if m:
            out.append(m.group(1).strip())
    return out


def extract_contracts(text_lines):
    """Normalize a list of Consumes/Provides bullet bodies into comparable contract tokens.

    Stack-specific: this default pulls inline-code spans (`like this`) and bare
    METHOD /path tokens, which covers the common cases (HTTP endpoints, typed
    contracts written in backticks). Replace with your stack's notation if needed.
    A trailing parenthetical such as "(new — consumed by TASK-12)" is ignored.
    """
    contracts = set()
    for line in text_lines:
        line = re.sub(r"\(.*?\)", "", line)  # drop parentheticals/annotations
        contracts |= set(re.findall(r"`([^`]+)`", line))
        contracts |= set(
            re.findall(r"\b(?:GET|POST|PUT|PATCH|DELETE)\s+\S+", line, re.IGNORECASE)
        )
    # Normalize: strip surrounding backticks/whitespace so a `METHOD /path` span and
    # the bare METHOD /path token (which can sweep up a trailing backtick) dedupe.
    normalized = (c.strip().strip("`").strip() for c in contracts)
    return {c for c in normalized if c}


def sibling_provided(chunk_dir, self_spec):
    """All contracts 'Provides:' by sibling work-item specs in the same chunk.

    Siblings are discovered by scanning the chunk's per-layer subdirectories for
    chunk specs and following any sibling work-item specs that reference them.
    For robustness we also scan the chunk dir's specs directly: a chunk spec may
    itself list Provides lines.
    """
    provided = set()
    for md in chunk_dir.rglob("*.md"):
        if md.resolve() == self_spec.resolve():
            continue
        provided |= extract_contracts(extract_lines(md.read_text(), "Provides"))
    return provided


def main():
    if len(sys.argv) != 2:
        print("Usage: check_crosslayer.py <local_spec_path>", file=sys.stderr)
        sys.exit(2)

    spec_path = Path(sys.argv[1]).resolve()
    if not spec_path.exists():
        print(f"FAIL: spec not found: {spec_path}")
        sys.exit(1)

    chunk_dir, layer = find_chunk_dir(spec_path)
    if chunk_dir is None or not chunk_dir.exists():
        print("PHASE C PASS (no chunk_spec to audit)")
        sys.exit(0)

    # A Consumes line annotated "(existing)" already ships — exclude it before
    # extraction (the FIX message advertises this escape hatch; honor it here).
    consumed_lines = [
        ln
        for ln in extract_lines(spec_path.read_text(), "Consumes")
        if not re.search(r"\(\s*existing\b", ln, re.IGNORECASE)
    ]
    consumed = extract_contracts(consumed_lines)
    if not consumed:
        print("PHASE C PASS (ticket consumes no sibling-provided contracts)")
        sys.exit(0)

    provided = sibling_provided(chunk_dir, spec_path)
    # Only flag contracts marked as needing a sibling provider, i.e. not already
    # satisfied. Contracts annotated "(existing)" should be excluded by the dev's
    # notation; this check is conservative and reports any consumed-but-unprovided.
    missing = consumed - provided

    if missing:
        for m in sorted(missing):
            print(
                f"FAIL: consumed contract '{m}' has no sibling 'Provides:' ticket "
                f"in {chunk_dir} (layer: {layer})"
            )
        print("FIX: invoke `/create-ticket` to add the missing provider ticket(s), "
              "or annotate the Consumes line as '(existing)' if it already ships.")
        sys.exit(1)

    print("PHASE C PASS")
    sys.exit(0)


if __name__ == "__main__":
    main()

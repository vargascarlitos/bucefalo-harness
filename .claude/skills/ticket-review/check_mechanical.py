#!/usr/bin/env python3
"""Phase A mechanical checks for /ticket-review (ClickUp edition).

Stack-agnostic. Validates the LOCAL work-item spec (the canonical body) against
the structural rules in specs/work-items/_template.md. No PM-tool coupling here —
the orchestrator handles ClickUp via _shared/pm-clickup.md.

Usage:
    python3 check_mechanical.py <local_spec_path> <clickup_id>

Exit 0 + "PHASE A PASS" on success; exit 1 + one "FAIL: ..." line per failure.
"""

import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    msg = "FAIL: pyyaml not installed; cannot parse frontmatter"
    print(msg)
    print(msg, file=sys.stderr)
    sys.exit(2)


REQUIRED_SECTIONS = [
    "## User Story",
    "## Acceptance Criteria",
    "## Edge Cases & Error States",
    "## Scope",
    "## Design Reference",
]


def parse_frontmatter(text):
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text
    try:
        fm = yaml.safe_load(text[4:end])
    except yaml.YAMLError as e:
        return {"_yaml_error": str(e)}, text[end + 5 :]
    return fm or {}, text[end + 5 :]


def check_sections(body, failures):
    for section in REQUIRED_SECTIONS:
        header_pattern = rf"^{re.escape(section)}\s*$"
        match = re.search(header_pattern, body, re.MULTILINE)
        if not match:
            failures.append(f"Missing required section: {section}")
            continue
        idx = match.end()
        rest = body[idx:]
        next_header_match = re.search(r"^## ", rest, re.MULTILINE)
        block = rest if not next_header_match else rest[: next_header_match.start()]
        if not block.strip():
            failures.append(f"Section {section} is empty")


def check_design_links(body, failures):
    """Design Reference is optional content but, when present, links must be real.

    - No empty markdown links: `[label]()`.
    - Unless the Design Reference section explicitly declares N/A (api-only / no UI /
      backend-only / no design), require at least one non-empty link in the section.
    """
    for match in re.finditer(r"\[([^\]]+)\]\(([^)]*)\)", body):
        if not match.group(2).strip():
            failures.append(f"Design link has empty URL: [{match.group(1)}]()")

    section_match = re.search(
        r"^## Design Reference\s*$(.*?)(?=^## |\Z)", body, re.MULTILINE | re.DOTALL
    )
    section_body = section_match.group(1).strip() if section_match else ""
    is_na = bool(
        re.search(
            r"\bN/A\b|api.only|no ui|backend.only|no design|no figma",
            section_body,
            re.IGNORECASE,
        )
    )
    has_link = bool(re.search(r"\[[^\]]+\]\(\s*\S+\s*\)", section_body))
    if section_body and not is_na and not has_link:
        failures.append(
            "Design Reference has no usable link and is not declared N/A "
            "(add a design URL, or write 'N/A — no UI')"
        )


def check_frontmatter(fm, clickup_id, failures, spec_path):
    if str(fm.get("clickup_id")) != str(clickup_id):
        failures.append(
            f"clickup_id mismatch: spec='{fm.get('clickup_id')}' vs expected='{clickup_id}'"
        )
    if not fm.get("estimate"):
        failures.append("Frontmatter `estimate` is missing or empty")
    if not fm.get("priority"):
        failures.append("Frontmatter `priority` is missing or empty")
    chunk = fm.get("chunk_spec")
    if chunk:
        resolved = (spec_path.parent / chunk).resolve()
        if not resolved.exists():
            failures.append(f"Parent chunk_spec path does not exist: {resolved}")


def main():
    if len(sys.argv) != 3:
        print("Usage: check_mechanical.py <local_spec_path> <clickup_id>", file=sys.stderr)
        sys.exit(2)

    spec_path = Path(sys.argv[1]).resolve()
    clickup_id = sys.argv[2]

    if not spec_path.exists():
        print(f"FAIL: spec file not found: {spec_path}")
        sys.exit(1)

    text = spec_path.read_text()
    fm, body = parse_frontmatter(text)
    if "_yaml_error" in fm:
        print(f"FAIL: frontmatter YAML is malformed: {fm['_yaml_error']}")
        sys.exit(1)
    failures = []

    check_sections(body, failures)
    check_design_links(body, failures)
    check_frontmatter(fm, clickup_id, failures, spec_path)

    if failures:
        for f in failures:
            print(f"FAIL: {f}")
        sys.exit(1)

    print("PHASE A PASS")
    sys.exit(0)


if __name__ == "__main__":
    main()

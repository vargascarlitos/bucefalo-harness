#!/usr/bin/env bash
set -euo pipefail

# Read hook input from stdin (size-limited for safety)
input="$(head -c 65536)"
command="$(echo "$input" | jq -r '.tool_input.command // ""' 2>/dev/null)" || {
  echo '{}'; exit 0
}

# Only run on git commit
[[ "$command" == *"git commit"* ]] || { echo '{}'; exit 0; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(git rev-parse --show-toplevel 2>/dev/null || { cd "$SCRIPT_DIR/../.." && pwd; })"
DOCS_DIR="$PROJECT_DIR/docs"

[[ -d "$DOCS_DIR" ]] || { echo '{}'; exit 0; }

# Filename patterns indicating temporary docs
TEMP_PATTERN='_(SUMMARY|ANALYSIS|RESULTS?|CHECKLIST|MEETING|NOTES?|v[0-9]+|[0-9]{4}-[0-9]{2}-[0-9]{2}).*\.md$'

flagged=()
while IFS= read -r f; do
  name="$(basename "$f")"
  if echo "$name" | grep -qEi "$TEMP_PATTERN"; then
    # Compute path relative to project root
    flagged+=("${f#"$PROJECT_DIR/"}")
  fi
done < <(find "$DOCS_DIR" -name "*.md" -type f 2>/dev/null)

if (( ${#flagged[@]} > 0 )); then
  file_list="$(printf '  - %s\n' "${flagged[@]}")"
  jq -n --arg reason "$(printf '\xe2\x9a\xa0 Temporary docs detected in docs/:\n%s\nConsider running /audit-docs to clean these up.' "$file_list")" \
    '{reason: $reason}'
else
  echo '{}'
fi

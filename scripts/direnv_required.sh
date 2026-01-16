#!/usr/bin/env bash
set -euo pipefail

# Parse arguments
strict=false
file=""

for arg in "$@"; do
    if [[ "$arg" == "--strict" ]]; then
        strict=true
    else
        file="$arg"
    fi
done

# Check if filename was provided
if [[ -z "$file" ]]; then
    echo "Error: No filename provided" >&2
    echo "Usage: $0 [--strict] <filename>" >&2
    exit 1
fi

# Check if file exists
if [[ ! -f "$file" ]]; then
    if [[ "$strict" == true ]]; then
        echo "Error: File '$file' not found" >&2
        exit 1
    fi
    exit 0
fi

# Read file and extract required keys
keys=()
prev_line=""

while IFS= read -r line || [[ -n "$line" ]]; do
    # Check if current line is a KEY=value line with uppercase key only
    # Keys with lowercase letters are ignored
    if [[ "$line" =~ ^([A-Z_][A-Z0-9_]*)= ]]; then
        key="${BASH_REMATCH[1]}"
        is_optional=false

        # Check for inline comment: \s+#.*(direnv:\s?optional)(?=\s|$)
        # Requires whitespace before #, then anything, then "direnv: optional" or "direnv:optional"
        # followed by whitespace or end of line
        if [[ "$line" =~ [[:space:]]+#.*(direnv:[[:space:]]?optional)([[:space:]]|$) ]]; then
            is_optional=true
        fi

        # Check if previous line is a comment containing direnv: optional
        # Previous line must start with optional whitespace then #
        if [[ "$prev_line" =~ ^[[:space:]]*#.*(direnv:[[:space:]]?optional)([[:space:]]|$) ]]; then
            is_optional=true
        fi

        if [[ "$is_optional" == false ]]; then
            keys+=("$key")
        fi
    fi

    prev_line="$line"
done < "$file"

# Output space-separated keys
echo "${keys[*]}"

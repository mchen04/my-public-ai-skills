#!/usr/bin/env bash
set -u
[ "$#" -gt 0 ] || { echo "sweep-markers: name the files that were conflicted" >&2; exit 2; }
pattern='^(<<<<<<<|>>>>>>>|\|\|\|\|\|\|\|)( |$)'
found=0
for file in "$@"; do
  hits=""
  [ -f "$file" ] && hits=$(grep -nE "$pattern" -- "$file" | sed "s|^|$file (worktree):|")
  if git cat-file -e "HEAD:$file" 2>/dev/null; then
    hits="$hits$(git show "HEAD:$file" | grep -nE "$pattern" | sed "s|^|$file (HEAD):|")"
  fi
  if [ -n "$hits" ]; then printf '%s\n' "$hits"; found=1; fi
done
[ "$found" -eq 0 ] && echo "sweep-markers: clean ($# file(s))"
exit "$found"

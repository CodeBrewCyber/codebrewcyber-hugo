#!/usr/bin/env bash
# Sort every published lab by body words and words-per-screenshot.
#
# Run it before editing (to see the band you're aiming for) and after (to see
# where the new lab landed). The point is not the absolute number, it is where
# the new lab sorts. If it lands at the bottom of the list it is not finished.
#
# Usage: length-check.sh [content/cloud/labs]

set -euo pipefail

dir="${1:-content/cloud/labs}"
[ -d "$dir" ] || { echo "no such directory: $dir" >&2; exit 1; }
cd "$dir"

for d in */; do
  d="${d%/}"
  [ -f "$d/index.md" ] || continue
  # Strip the TOML front matter so only body prose is counted.
  w=$(sed '/^+++$/,/^+++$/d' "$d/index.md" | wc -w | tr -d ' ')
  i=$(ls "$d"/*.png 2>/dev/null | wc -l | tr -d ' ')
  if [ "$i" -gt 0 ]; then
    printf "%-45s %5s words %3s imgs %4s w/img\n" "$d" "$w" "$i" "$((w / i))"
  else
    printf "%-45s %5s words %3s imgs    - w/img\n" "$d" "$w" "$i"
  fi
done | sort -k2 -n

cat <<'EOF'

Targets: 600-1300 body words (hard ceiling ~1300), 40-120 words per screenshot.
Words-per-screenshot is the better signal; it catches bloat in a lab that looks
short. A new lab should interleave with the existing ones, not sort to the end.
EOF

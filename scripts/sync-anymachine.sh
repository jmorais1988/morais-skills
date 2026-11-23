#!/usr/bin/env bash
# Refresh .agents/skills/anymachine/PIPELINE.md from the upstream anymachine repo.
# PIPELINE.md is copied verbatim; SKILL.md is ours and is never touched.
# UPSTREAM records the commit PIPELINE.md was taken from, and only changes when
# PIPELINE.md itself changes, so unrelated upstream commits produce no diff.
# Run by .github/workflows/sync-anymachine.yml; also safe to run by hand.
set -euo pipefail

UPSTREAM_REPO="apekshik/anymachine"
BRANCH="main"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILL="$REPO_ROOT/.agents/skills/anymachine"

sha="$(git ls-remote "https://github.com/$UPSTREAM_REPO.git" "refs/heads/$BRANCH" | cut -f1)"
[[ -n "$sha" ]] || { echo "Could not resolve $UPSTREAM_REPO@$BRANCH" >&2; exit 1; }

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
curl -fsSL "https://raw.githubusercontent.com/$UPSTREAM_REPO/$sha/PIPELINE.md" -o "$tmp"
[[ -s "$tmp" ]] || { echo "Downloaded PIPELINE.md is empty" >&2; exit 1; }

if cmp -s "$tmp" "$SKILL/PIPELINE.md"; then
  echo "PIPELINE.md unchanged at ${sha:0:7}"
  exit 0
fi

cp "$tmp" "$SKILL/PIPELINE.md"
printf 'repo=%s\ncommit=%s\n' "$UPSTREAM_REPO" "$sha" > "$SKILL/UPSTREAM"
echo "PIPELINE.md updated to ${sha:0:7}"

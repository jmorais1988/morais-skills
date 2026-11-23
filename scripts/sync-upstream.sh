#!/usr/bin/env bash
# Refresh vendored upstream files in .agents/skills/<skill>/ from their source repos.
#
# Each vendored skill has an UPSTREAM manifest:
#   repo=owner/name                  GitHub repo to pull from
#   branch=main                      branch to follow
#   commit=<sha>                     written by this script: the upstream commit the files match
#   path=<upstream path>:<dest>      one line per file or folder; <dest> is relative to the skill
#                                    (use vendor/..., never upstream/: it collides with UPSTREAM on
#                                    case-insensitive filesystems)
#
# Folders are mirrored exactly (files deleted upstream are deleted here). Any SKILL.md inside a
# mirrored folder is stored as UPSTREAM-SKILL.md, so agents that scan skill folders recursively
# don't register the vendored copy as a second skill; its relative links still resolve.
# Our own SKILL.md at the top of each skill folder is never touched.
#
# `commit=` only changes when the synced files change, so unrelated upstream commits produce
# no diff. A missing or empty upstream path is an error (a moved folder must not wipe ours).
#
# Usage: scripts/sync-upstream.sh [skill ...]   (default: every skill with an UPSTREAM manifest)
# Run daily by .github/workflows/sync-upstream.yml; also safe to run by hand.
# Exits non-zero if any skill failed; the skills that synced keep their changes.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILLS="$REPO_ROOT/.agents/skills"

if [[ $# -gt 0 ]]; then
  names=("$@")
else
  names=()
  for f in "$SKILLS"/*/UPSTREAM; do
    grep -q '^path=' "$f" && names+=("$(basename "$(dirname "$f")")")
  done
fi

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

sync_skill() {
  local name="$1"
  local skill="$SKILLS/$name"
  local manifest="$skill/UPSTREAM"
  [[ -f "$manifest" ]] || { echo "$name: no UPSTREAM manifest" >&2; return 1; }

  local repo branch
  repo="$(sed -n 's/^repo=//p' "$manifest")"
  branch="$(sed -n 's/^branch=//p' "$manifest")"
  branch="${branch:-main}"
  local -a maps=()
  mapfile -t maps < <(sed -n 's/^path=//p' "$manifest" | tr -d '\r')
  [[ -n "$repo" && ${#maps[@]} -gt 0 ]] || { echo "$name: UPSTREAM needs repo= and path= lines" >&2; return 1; }

  local src="$work/$name/src" out="$work/$name/out"
  mkdir -p "$out"

  # Shallow, blobless, sparse: only the listed paths' blobs are downloaded.
  local -a patterns=()
  local m
  for m in "${maps[@]}"; do patterns+=("/${m%%:*}"); done
  git -c core.autocrlf=false clone --quiet --depth 1 --filter=blob:none --no-checkout \
      --branch "$branch" "https://github.com/$repo.git" "$src" || { echo "$name: clone of $repo@$branch failed" >&2; return 1; }
  # Patterns go in on stdin: Git Bash would rewrite a "/path" argument into a Windows path.
  printf '%s
' "${patterns[@]}" | git -C "$src" sparse-checkout set --no-cone --stdin || return 1
  git -C "$src" -c core.autocrlf=false checkout --quiet || { echo "$name: checkout failed" >&2; return 1; }
  local sha
  sha="$(git -C "$src" rev-parse HEAD)"

  # Stage every mapped path into $out/<dest>.
  local from dest
  for m in "${maps[@]}"; do
    from="${m%%:*}"; dest="${m#*:}"
    if [[ -d "$src/$from" ]]; then
      [[ -n "$(find "$src/$from" -type f -print -quit)" ]] || { echo "$name: $repo:$from is empty" >&2; return 1; }
      mkdir -p "$out/$(dirname "$dest")" && cp -R "$src/$from" "$out/$dest" || return 1
      find "$out/$dest" -type f -name SKILL.md -execdir mv SKILL.md UPSTREAM-SKILL.md \;
    elif [[ -s "$src/$from" ]]; then
      mkdir -p "$out/$(dirname "$dest")" && cp "$src/$from" "$out/$dest" || return 1
    else
      echo "$name: $repo:$from is missing or empty at ${sha:0:7}" >&2; return 1
    fi
  done

  # Compare, then replace only what differs.
  local changed=0
  for m in "${maps[@]}"; do
    dest="${m#*:}"
    if ! diff -rq "$out/$dest" "$skill/$dest" >/dev/null 2>&1; then
      changed=1
      rm -rf "${skill:?}/$dest"
      mkdir -p "$skill/$(dirname "$dest")" && cp -R "$out/$dest" "$skill/$dest"         || { echo "$name: could not write $dest" >&2; return 1; }
    fi
  done

  if [[ $changed -eq 0 ]]; then
    echo "$name: unchanged at ${sha:0:7}"
    return 0
  fi
  {
    grep -v '^commit=' "$manifest" | sed -n '/^repo=/p;/^branch=/p'
    echo "commit=$sha"
    grep -v -e '^repo=' -e '^branch=' -e '^commit=' "$manifest"
  } > "$work/$name/UPSTREAM"
  cp "$work/$name/UPSTREAM" "$manifest"
  echo "$name: updated to $repo@${sha:0:7}"
}

failed=()
for n in "${names[@]}"; do
  sync_skill "$n" || failed+=("$n")
done

if [[ ${#failed[@]} -gt 0 ]]; then
  echo "Failed: ${failed[*]}" >&2
  exit 1
fi

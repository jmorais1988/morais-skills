#!/usr/bin/env python3
"""Lint this skill after any self-improvement edit: registration, paths, script syntax, frontmatter, leak scan.

    python skill_lint.py [--skill-dir DIR] [--deny "term1,term2"] [--deny-file FILE] [--json]
    (--json prints one line: SKILL_LINT <json>)

Checks (errors fail with exit 1; warnings don't):
  frontmatter   SKILL.md has name + description; frontmatter <= 1024 chars; name == folder name
  size          SKILL.md body > 500 lines or > 20 000 bytes (~5k tokens: what survives auto-compaction) is warned
  registration  every scripts/*.py is named in SKILL.md; every references/*.md is named in SKILL.md
                (references must be linked one level deep from SKILL.md, never only from another reference)
  paths         every `scripts/x.py` / `references/x.md` mentioned in any skill .md exists
  sections      `x.md §N` / `references/x.md §N` pointers name a heading `## N.` that exists in x.md (error);
                a bare `§N` inside a file with numbered headings must exist in that file (warning)
  contents      a reference longer than 100 lines without a `## Contents` list is warned
  scripts       every script parses (ast) and has a module docstring
  cli-tag       a script with an `if __name__ == "__main__"` guard but no tagged print (`print("NAME " + json...)`,
                `print(TAG, ...)`) is warned: house style CLIs print exactly one `<SCRIPTNAME_UPPER> <json>` line
  caches        __pycache__ directories and .pyc/.pyo files inside the skill (error: delete them)
  changelog     CHANGELOG.md exists (warning)
  leaks         absolute user-home paths (C:\\Users\\<name>, /Users/<name>, /home/<name>), Windows 8.3 short
                user dirs (tilde + digit), e-mail addresses, and every --deny / --deny-file term (case-insensitive,
                whole word) in any text file of the skill.
Project-side files the skill tells agents to create (references/NOTES.md, manifest.json, ...) are not skill files
and are ignored by the path checks (PROJECT_FILES).
Pass the current job's distinctive terms (project/folder/asset/object/client/character names) as --deny;
they are only used for matching and are never written anywhere. Pure stdlib.
"""
import argparse, ast, json, re, sys
from pathlib import Path

TEXT_EXT = {".md", ".py", ".txt", ".json", ".yaml", ".yml", ".toml", ".cfg"}
GENERIC_HOMES = {"public", "default", "all users", "<name>", "name", "user", "username", "you", "me"}
LEAK_PATTERNS = [
    ("user-home path", re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+([^\\/\s`'\"<>]+)", re.I)),
    ("user-home path", re.compile(r"(?<![\w.])/(?:Users|home)/([^/\s`'\"<>]+)")),
    ("short user dir", re.compile(r"\b([A-Z0-9]{1,6}~\d)\b")),
    ("e-mail address", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
]
PROJECT_FILES = {"NOTES.md", "manifest.json", "README.md"}  # created in the user's asset folder, not in the skill
NO_TAG_OK = {"addon_template.py"}  # its __main__ only registers the add-on; not a CLI
SKILL_MAX_LINES = 500      # Anthropic/Claude Code guidance: keep SKILL.md under 500 lines
SKILL_MAX_BYTES = 20_000   # ~5k tokens: Claude Code keeps only the first 5k tokens of a skill after compaction
CONTENTS_MIN_LINES = 100   # reference files longer than this need a "## Contents" list at the top
MAIN_GUARD = re.compile(r"""__name__\s*==\s*["']__main__["']""")
HEADING_NUM = re.compile(r"^##\s+§?\s*(\d+)(?:[.:)]|\s)")
FILE_SECTION = re.compile(r"(?:references/)?([\w-]+\.md)`?[\s(]*(?:§|section\s)\s*(\d+)")
BARE_SECTION = re.compile(r"(?<![\w`/.-])§\s*(\d+)")
TAG_PRINT = re.compile(r"""print\(\s*(?:f?["'][A-Z][A-Z0-9_]{2,}\s|_?[A-Z][A-Z0-9_]*\s*[,+])""")
EMAIL_ALLOW = re.compile(r"@(example\.(com|org)|users\.noreply\.github\.com)$", re.I)


def frontmatter(text):
    if not text.startswith("---"):
        return None, None
    end = text.find("\n---", 3)
    if end < 0:
        return None, None
    block = text[: end + 4]
    fields = {}
    for line in block.splitlines()[1:-1]:
        m = re.match(r"^(\w[\w-]*):\s*(.*)$", line)
        if m:
            fields[m.group(1)] = m.group(2).strip()
    return block, fields


def lint(skill_dir, deny_terms):
    root = Path(skill_dir).resolve()
    errors, warnings = [], []
    skill_md = root / "SKILL.md"
    if not skill_md.exists():
        return {"errors": [f"missing {skill_md.name}"], "warnings": [], "checked_files": 0}
    skill_text = skill_md.read_text(encoding="utf-8-sig")

    block, fields = frontmatter(skill_text)
    if block is None:
        errors.append("SKILL.md: no YAML frontmatter")
    else:
        for key in ("name", "description"):
            if not fields.get(key):
                errors.append(f"SKILL.md frontmatter: missing '{key}'")
        if len(block) > 1024:
            errors.append(f"SKILL.md frontmatter is {len(block)} chars (> 1024)")
        if fields.get("name") and fields["name"] != root.name:
            warnings.append(f"frontmatter name '{fields['name']}' != folder '{root.name}'")
    body_lines = skill_text.count("\n") + 1
    body_bytes = len(skill_text.encode("utf-8"))
    if body_lines > SKILL_MAX_LINES:
        warnings.append(f"SKILL.md is {body_lines} lines (> {SKILL_MAX_LINES}); move detail to references/")
    if body_bytes > SKILL_MAX_BYTES:
        warnings.append(f"SKILL.md is {body_bytes} bytes (~{body_bytes // 4} tokens > ~5k kept after compaction); "
                        "move detail to references/")

    scripts = sorted((root / "scripts").glob("*.py")) if (root / "scripts").exists() else []
    refs = sorted((root / "references").glob("*.md")) if (root / "references").exists() else []
    for p in scripts:
        if f"scripts/{p.name}" not in skill_text:
            errors.append(f"unregistered script: scripts/{p.name} is not named in SKILL.md")
        src = p.read_text(encoding="utf-8-sig")
        try:
            tree = ast.parse(src)
            if not ast.get_docstring(tree):
                errors.append(f"scripts/{p.name}: missing module docstring (usage)")
        except SyntaxError as e:
            errors.append(f"scripts/{p.name}: syntax error line {e.lineno}: {e.msg}")
        if MAIN_GUARD.search(src) and not TAG_PRINT.search(src) and p.name not in NO_TAG_OK:
            warnings.append(f"scripts/{p.name}: has a __main__ CLI but no tagged one-line JSON print "
                            f"('{p.stem.upper()} <json>')")
    for f in sorted(root.rglob("*")):
        if f.is_dir() and f.name == "__pycache__":
            errors.append(f"bytecode cache inside the skill: {f.relative_to(root)} (delete it)")
        elif f.is_file() and f.suffix.lower() in (".pyc", ".pyo") and "__pycache__" not in f.parts:
            errors.append(f"bytecode file inside the skill: {f.relative_to(root)} (delete it)")
    for p in refs:
        if f"references/{p.name}" not in skill_text:
            errors.append(f"unregistered reference: references/{p.name} is not named in SKILL.md")

    md_files = [skill_md] + refs + [p for p in root.glob("*.md") if p.name != "SKILL.md"]
    mention = re.compile(r"\b(scripts/[\w.-]+\.py|references/[\w.-]+\.md)\b")
    bare_ref = re.compile(r"`([\w-]+\.md)`")
    ref_names = {p.name for p in refs} | {p.name for p in root.glob("*.md")}
    # numbered "## N." headings per markdown file, for section-pointer validation
    headings = {}
    for f in md_files:
        nums = set()
        for line in f.read_text(encoding="utf-8-sig").splitlines():
            m = HEADING_NUM.match(line)
            if m:
                nums.add(int(m.group(1)))
        headings[f.name] = nums
    for f in md_files:
        text = f.read_text(encoding="utf-8-sig")
        rel = f.relative_to(root)
        for m in mention.finditer(text):
            if Path(m.group(1)).name in PROJECT_FILES:
                continue
            if not (root / m.group(1)).exists():
                errors.append(f"{rel}: mentions missing {m.group(1)}")
        for m in bare_ref.finditer(text):
            name = m.group(1)
            if name not in ref_names and name not in PROJECT_FILES and "<" not in name:
                warnings.append(f"{rel}: `{name}` is not a file in this skill")
        if f in refs and text.count("\n") + 1 > CONTENTS_MIN_LINES and not re.search(r"^## Contents", text, re.M):
            warnings.append(f"{rel}: {text.count(chr(10)) + 1} lines without a '## Contents' list")
        if f.name == "CHANGELOG.md":
            continue  # history: old section numbers stay as they were
        for i, line in enumerate(text.splitlines(), 1):
            covered = set()
            for m in FILE_SECTION.finditer(line):
                name, num = m.group(1), int(m.group(2))
                covered.add(m.start(2))
                if name not in headings or name in PROJECT_FILES:
                    continue  # missing files are reported by the path check
                if headings[name] and num not in headings[name]:
                    errors.append(f"{rel}:{i}: points at {name} §{num} but that file has no '## {num}.' heading")
            own = headings.get(f.name, set())
            if own:
                for m in BARE_SECTION.finditer(line):
                    if m.start(1) in covered:
                        continue
                    num = int(m.group(1))
                    if num not in own and not FILE_SECTION.search(line):
                        warnings.append(f"{rel}:{i}: bare §{num} but this file has no '## {num}.' heading")

    if not (root / "CHANGELOG.md").exists():
        warnings.append("CHANGELOG.md missing")

    deny = [t.strip() for t in deny_terms if t and t.strip()]
    deny_res = [(t, re.compile(r"(?<!\w)" + re.escape(t) + r"(?!\w)", re.I)) for t in deny]
    checked = 0
    for f in sorted(root.rglob("*")):
        if not f.is_file() or f.suffix.lower() not in TEXT_EXT or "__pycache__" in f.parts:
            continue
        checked += 1
        try:
            lines = f.read_text(encoding="utf-8-sig").splitlines()
        except UnicodeDecodeError:
            continue
        rel = f.relative_to(root)
        for i, line in enumerate(lines, 1):
            for label, rx in LEAK_PATTERNS:
                for m in rx.finditer(line):
                    hit = m.group(0)
                    if label == "user-home path" and m.group(1).lower() in GENERIC_HOMES:
                        continue
                    if label == "e-mail address" and EMAIL_ALLOW.search(hit):
                        continue
                    errors.append(f"leak ({label}) {rel}:{i}: {hit}")
            for term, rx in deny_res:
                if rx.search(line):
                    errors.append(f"leak (deny term) {rel}:{i}: matches a --deny term")
    return {"errors": errors, "warnings": warnings, "checked_files": checked,
            "scripts": len(scripts), "references": len(refs), "deny_terms": len(deny)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill-dir", default=str(Path(__file__).resolve().parent.parent))
    ap.add_argument("--deny", default="", help="comma-separated terms from the current job that must not appear")
    ap.add_argument("--deny-file", help="file with one deny term per line (keep it outside the skill)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    terms = a.deny.split(",") if a.deny else []
    if a.deny_file:
        terms += Path(a.deny_file).read_text(encoding="utf-8").splitlines()
    r = lint(a.skill_dir, terms)
    if a.json:
        print("SKILL_LINT " + json.dumps(r))
    else:
        print(f"skill_lint: {r['checked_files']} files, {r.get('scripts', 0)} scripts, "
              f"{r.get('references', 0)} references, {r.get('deny_terms', 0)} deny terms")
        for e in r["errors"]:
            print("ERROR  " + e)
        for w in r["warnings"]:
            print("WARN   " + w)
        print("PASS" if not r["errors"] else f"FAIL ({len(r['errors'])} errors)")
    sys.exit(1 if r["errors"] else 0)


if __name__ == "__main__":
    main()

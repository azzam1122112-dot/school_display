from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent

EXCLUDE_DIRS = {
    ".venv", "venv", ".git", "staticfiles", "media", "node_modules", "__pycache__", "migrations"
}

# ملفات نستهدفها (باختصار: py + html)
INCLUDE_SUFFIXES = {".py", ".html"}

REPLACEMENTS: list[tuple[re.Pattern, str]] = [
    # Python
    (re.compile(r"\brequest\.user\.profile\.school\b"), "request.user.profile.active_school"),
    (re.compile(r"\buser\.profile\.school\b"), "user.profile.active_school"),
    (re.compile(r"\bprofile\.school\b"), "profile.active_school"),
    (re.compile(r"\bprofile\.school_id\b"), "profile.active_school_id"),

    # update_or_create defaults={"active_school": ...} أو {'school': ...}
    (re.compile(r"defaults=\{\s*\"school\"\s*:"), 'defaults={"active_school":'),
    (re.compile(r"defaults=\{\s*'school'\s*:"), "defaults={'active_school':"),

    # Templates
    (re.compile(r"\bu\.profile\.school\b"), "u.profile.active_school"),
]

def is_excluded(p: Path) -> bool:
    parts = set(p.parts)
    return any(d in parts for d in EXCLUDE_DIRS)

def patch_file(path: Path) -> int:
    txt = path.read_text(encoding="utf-8", errors="ignore")
    new = txt
    total = 0
    for pattern, repl in REPLACEMENTS:
        new2, n = pattern.subn(repl, new)
        if n:
            total += n
            new = new2

    if total and new != txt:
        backup = path.with_suffix(path.suffix + ".bak")
        if not backup.exists():
            backup.write_text(txt, encoding="utf-8")
        path.write_text(new, encoding="utf-8")
    return total

def main():
    changed = []
    for p in ROOT.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in INCLUDE_SUFFIXES:
            continue
        if is_excluded(p):
            continue

        n = patch_file(p)
        if n:
            changed.append((p, n))

    print("\n=== Patch Summary ===")
    if not changed:
        print("No changes were needed.")
        return
    for p, n in changed:
        print(f"{p}  ->  {n} replacements")
    print("\nBackups were saved as *.bak next to each modified file.")

if __name__ == "__main__":
    main()

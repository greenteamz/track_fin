"""Guardrail: scan tracked files for personal / corporate identifiers.

Run as:
    python guardrail_check.py          # exits 0 if clean, 1 if leaks found
    python guardrail_check.py --fix    # (future) auto-redact

Used by the CI pipeline (GitHub Actions) to block commits that leak PII.
"""
import os
import re
import sys

# ── Patterns that must NEVER appear in committed files ──────────────────────
# Add names, PAN numbers, company names, emails, etc.
BLOCKED_PATTERNS = [
    # Personal identifiers (case-insensitive)
    r"(?i)\bajaya\s*prakash?\b",
    r"(?i)\bajaya\s*prakas[ae]m\b",
    r"(?i)\bajayapr\b",
    r"(?i)\bAZLPL\d+[A-Z]\b",           # PAN pattern
    r"(?i)\bmerced[ea]s[\s\-]*benz\b",   # Company name
    r"(?i)\bdaimler\b",                  # Parent company
    # DP / Client IDs
    r"\b12081801\b",
    r"\b69278308\b",
    # Email patterns with real name
    r"(?i)jayaprakasam",
]

# Files / dirs to skip
SKIP_DIRS = {".git", "__pycache__", "venv", ".venv", "node_modules", ".eggs"}
SKIP_FILES = {".env", "portfolio.db", "guardrail_check.py"}
ALLOWED_EXTENSIONS = {
    ".py", ".md", ".txt", ".yml", ".yaml", ".json", ".toml", ".cfg",
    ".ini", ".sh", ".bat", ".ps1", ".html", ".css", ".js",
}


def scan_file(filepath: str) -> list[dict]:
    """Return list of {line_no, pattern, snippet} for any matches."""
    findings = []
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            for line_no, line in enumerate(f, 1):
                for pat in BLOCKED_PATTERNS:
                    if re.search(pat, line):
                        findings.append({
                            "file": filepath,
                            "line": line_no,
                            "pattern": pat,
                            "snippet": line.strip()[:120],
                        })
    except (PermissionError, OSError):
        pass
    return findings


def main():
    root = os.path.dirname(os.path.abspath(__file__))
    all_findings = []

    for dirpath, dirnames, filenames in os.walk(root):
        # Prune skipped dirs
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]

        for fname in filenames:
            if fname in SKIP_FILES:
                continue
            ext = os.path.splitext(fname)[1].lower()
            if ext not in ALLOWED_EXTENSIONS:
                continue

            full_path = os.path.join(dirpath, fname)
            rel_path = os.path.relpath(full_path, root)
            findings = scan_file(full_path)
            for f in findings:
                f["file"] = rel_path
            all_findings.extend(findings)

    if all_findings:
        print(f"\n{'!'*60}")
        print(f"  GUARDRAIL FAILED — {len(all_findings)} personal data leak(s)")
        print(f"{'!'*60}\n")
        for f in all_findings:
            print(f"  {f['file']}:{f['line']}")
            print(f"    Pattern : {f['pattern']}")
            print(f"    Content : {f['snippet']}")
            print()
        sys.exit(1)
    else:
        print("Guardrail check passed — no personal data found.")
        sys.exit(0)


if __name__ == "__main__":
    main()

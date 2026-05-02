"""Run all documentation audits and produce a single summary.

Wraps the seven individual audit scripts under dev/ and presents
their results as a unified report.  Exits non-zero if any
contract-style audit (1A, 1D, 2, 3, 4) is dirty.  Step 1B
(symbol existence) and 1E (phase markers) are report-only and
do not gate the exit code — both have a mix of legitimate and
borderline findings that need human judgment.

Run:

    /Users/cr/.local/share/virtualenvs/cse-rXGMsE9U/bin/python \\
        dev/audit_doc.py            # full run, default output
    /Users/cr/.local/share/virtualenvs/cse-rXGMsE9U/bin/python \\
        dev/audit_doc.py --quiet    # condensed summary only

Designed to be the single entry point a maintainer runs before
tagging a release.  Each individual audit script remains usable
on its own for focused investigation.
"""

import argparse
import subprocess
import sys
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
PYTHON = "/Users/cr/.local/share/virtualenvs/cse-rXGMsE9U/bin/python"

# (id, label, script, gates_exit)
AUDITS = [
    ("1A", "doc cross-references",
     "audit_doc_links.py", True),
    ("1B", "backticked symbol existence",
     "audit_doc_symbols.py", False),
    ("1D", "numerical drift (ZP / PRG / tests)",
     "audit_doc_numbers.py", True),
    ("1E", "stale historical markers (report)",
     "audit_phase_markers.py", False),
    ("2",  "per-module BSS byte counts",
     "audit_doc_module_bss.py", True),
    ("3",  "module Owned-files coverage",
     "audit_doc_owned_files.py", True),
    ("4",  "module Depends-on accuracy",
     "audit_doc_depends_on.py", True),
    ("6",  "tone/structure (heading skips, tables, etc.)",
     "audit_doc_structure.py", True),
]


def run_audit(script):
    """Run a single audit; return (returncode, stdout)."""
    path = ROOT / "dev" / script
    if not path.exists():
        return None, f"(missing: {script})"
    try:
        result = subprocess.run(
            [PYTHON, str(path)],
            cwd=ROOT, capture_output=True, text=True,
            timeout=120, check=False)
        return result.returncode, result.stdout
    except subprocess.TimeoutExpired:
        return None, "(timeout)"


def summarize(stdout):
    """Pull the headline summary line(s) from a script's stdout."""
    last_check = None
    last_count = None
    for line in stdout.splitlines():
        s = line.strip()
        if s.startswith(("✓", "✗")):
            last_check = s
        # Step 1E uses "After filter:" instead.
        if s.startswith("After filter:"):
            last_count = s
    return last_check or last_count or "(no summary)"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--quiet", "-q", action="store_true",
                    help="Print one line per audit, no per-script details")
    ap.add_argument("--verbose", "-v", action="store_true",
                    help="Print full stdout for every audit")
    args = ap.parse_args()

    print(f"CSE doc audit — running {len(AUDITS)} audits ...\n")

    overall_ok = True
    rows = []
    for aid, label, script, gates in AUDITS:
        rc, out = run_audit(script)
        if rc is None:
            status = "ERR"
            summary = out
        elif rc == 0:
            status = "✓"
            summary = summarize(out)
        else:
            status = "✗"
            summary = summarize(out)
            if gates:
                overall_ok = False
        rows.append((aid, label, status, summary, out, gates))

    if args.verbose:
        for aid, label, status, summary, out, gates in rows:
            gate_marker = "" if gates else " (report-only)"
            print(f"═══ {aid}  {label}{gate_marker}  [{status}] ═══")
            print(out)
            print()
    else:
        for aid, label, status, summary, out, gates in rows:
            gate_marker = "" if gates else "  (report-only)"
            print(f"  [{status}]  {aid:3s}  {label}{gate_marker}")
            if not args.quiet:
                print(f"        {summary}")

    print()
    if overall_ok:
        print("✓ All gating audits clean.")
    else:
        print("✗ At least one gating audit reported drift.  "
              "Investigate per-script with `dev/audit_<name>.py`.")

    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())

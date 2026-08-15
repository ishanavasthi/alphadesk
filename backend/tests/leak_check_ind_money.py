#!/usr/bin/env python3
"""Adversarial leak check: does anything staged for commit echo a real capture?

Card C2 captured live IND Money payloads into a scratch directory outside the
repo. Everything committed (fixtures + docs) is supposed to be invented. This
script proves it, by brute force rather than by eyeballing.

    python3 backend/tests/leak_check_ind_money.py --captures /path/to/c2-captures

It compares every distinctive string and number found in the raw captures
against every file staged for commit, and fails on any overlap.

IMPORTANT: this script never prints a capture value. A hit is reported as
"<staged file> :: <json path or line> :: <kind> :: sha1=<8 hex>" so the author
can find the offending field in their own (synthetic) file without the tool
itself leaking the secret it just found.

Exit code 0 = clean, 1 = leak found, 2 = usage error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys

# ---------------------------------------------------------------------------
# What is NOT a secret. Structural tokens are published on purpose (the payload
# doc documents shapes); only *values* from the operator's account are secret.
# ---------------------------------------------------------------------------

ASSET_TYPES = {
    "IND_STOCK", "MF", "US_STOCK", "BOND", "EPF", "NPS", "SA", "FD",
    "CRYPTO", "INSURANCE", "VEHICLE", "RE", "RD", "AIF", "PMS", "PPF",
    "US_STOCK_WALLET",
}
BREAKDOWNS = {"assets", "sector", "market_cap"}
CAPTURE_HARNESS_TOKENS = {"structuredContent", "textContent", "ExceptionGroup"}

# These captures contain NO account data by construction, only public server
# metadata, so they seed the allowlist instead of the secret corpus:
#   tool_inventory.json          — tool names, descriptions, input enums (vendor
#                                  schema; its English prose would false-positive
#                                  against ordinary English in the docs).
#   probe_dcr.json               — the OAuth discovery document plus per-attempt
#                                  status codes. The probe harness recorded
#                                  client_id/client_secret as booleans only, so
#                                  no credential and no holding is in this file;
#                                  what is in it is RFC 8414 vocabulary
#                                  (authorization_code, refresh_token, S256,
#                                  client_secret_post, …) that Q5 quotes on
#                                  purpose.
#   probe_unauth_list_tools.json — an exception type and message from a call that
#                                  was rejected before returning any data.
SCHEMA_ONLY_FILES = {
    "tool_inventory.json",
    "probe_dcr.json",
    "probe_unauth_list_tools.json",
}

MIN_STRING_LEN = 4
# Small integers (counts, flags, row indices) are not account data.
INT_SECRET_FLOOR = 1000


def sha8(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]


# ---------------------------------------------------------------------------
# Harvest
# ---------------------------------------------------------------------------

def walk(node, on_key=None, on_str=None, on_num=None, path=""):
    if isinstance(node, dict):
        for key, value in node.items():
            if on_key:
                on_key(key)
            walk(value, on_key, on_str, on_num, f"{path}.{key}" if path else key)
    elif isinstance(node, list):
        for i, value in enumerate(node):
            walk(value, on_key, on_str, on_num, f"{path}[{i}]")
    elif isinstance(node, str):
        if on_str:
            on_str(node, path)
    elif isinstance(node, bool):
        pass
    elif isinstance(node, (int, float)):
        if on_num:
            on_num(node, path)


def harvest_captures(capture_dir: str):
    """Return (secret_strings, secret_numbers, allowlist, provenance)."""
    secret_strings: set[str] = set()
    secret_numbers: set[float] = set()
    allowlist: set[str] = set(ASSET_TYPES | BREAKDOWNS | CAPTURE_HARNESS_TOKENS)
    provenance: dict[str, set[str]] = {}

    files = [f for f in sorted(os.listdir(capture_dir)) if f.endswith(".json")]
    if not files:
        print(f"ERROR: no .json captures in {capture_dir}", file=sys.stderr)
        sys.exit(2)

    for name in files:
        with open(os.path.join(capture_dir, name), encoding="utf-8") as fh:
            doc = json.load(fh)

        if name in SCHEMA_ONLY_FILES:
            # Everything in here is publishable schema: seed the allowlist with
            # its keys, tool names and enum members.
            walk(doc, on_key=allowlist.add)
            for tool in doc.get("tools", []):
                allowlist.add(tool.get("name", ""))
                props = (tool.get("inputSchema") or {}).get("properties", {})
                for spec in props.values():
                    for member in spec.get("enum", []) or []:
                        allowlist.add(str(member))
            continue

        # Field names are structural and published on purpose.
        walk(doc, on_key=allowlist.add)

        def note(token: str, src: str = name) -> None:
            provenance.setdefault(token, set()).add(src)

        def take_str(s, _p, src=name):
            secret_strings.add(s)
            note(sha8(s), src)

        def take_num(n, _p, src=name):
            secret_numbers.add(float(n))
            note(sha8(repr(float(n))), src)
            note(sha8("%g" % float(n)), src)

        walk(doc, on_str=take_str, on_num=take_num)

    allowlist_lower = {a.lower() for a in allowlist if a}
    secret_strings = {
        s for s in secret_strings
        if len(s.strip()) >= MIN_STRING_LEN and s.strip().lower() not in allowlist_lower
    }
    secret_numbers = {
        n for n in secret_numbers
        if not (float(n).is_integer() and abs(n) < INT_SECRET_FLOOR)
    }
    return secret_strings, secret_numbers, allowlist, provenance


# ---------------------------------------------------------------------------
# Scan
# ---------------------------------------------------------------------------

def staged_files(repo_root: str, explicit: list[str]) -> list[str]:
    if explicit:
        return explicit
    out = subprocess.run(
        ["git", "-C", repo_root, "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        capture_output=True, text=True, check=True,
    ).stdout.split()
    tracked = subprocess.run(
        ["git", "-C", repo_root, "ls-files"],
        capture_output=True, text=True, check=True,
    ).stdout.split()
    paths = []
    for rel in sorted(set(out) | set(tracked)):
        if rel.startswith("docs/") or rel.startswith("backend/tests/fixtures/ind_money/"):
            full = os.path.join(repo_root, rel)
            if os.path.isfile(full):
                paths.append(full)
    return paths


def scan(paths, secret_strings, secret_numbers, repo_root):
    hits = []
    lowered = sorted(((s.strip().lower(), s) for s in secret_strings), key=lambda p: -len(p[0]))
    numstrings = sorted(
        {(("%g" % n), n) for n in secret_numbers} | {(repr(n), n) for n in secret_numbers},
        key=lambda p: -len(p[0]),
    )

    for path in paths:
        rel = os.path.relpath(path, repo_root)
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        text_lower = text.lower()

        # Every occurrence, not just the first — fixing one must not mask others.
        for needle, original in lowered:
            start = 0
            while (idx := text_lower.find(needle, start)) != -1:
                line = text[:idx].count("\n") + 1
                hits.append((rel, f"line {line}", "string", sha8(original), len(original)))
                start = idx + 1

        # Numbers match on TOKEN boundaries, not as bare substrings: a short
        # real value like 4242 also occurs inside an invented 142420, and
        # treating that as a leak would drown the real signal in noise.
        for needle, value in numstrings:
            if len(needle) < 4:
                continue
            start = 0
            while (idx := text.find(needle, start)) != -1:
                start = idx + 1
                before = text[idx - 1] if idx else " "
                after = text[idx + len(needle)] if idx + len(needle) < len(text) else " "
                if before.isdigit() or before == "." or after.isdigit() or after == ".":
                    continue
                line = text[:idx].count("\n") + 1
                hits.append((rel, f"line {line}", "number-token", sha8(needle), len(needle)))

        # Exact numeric equality inside JSON fixtures (catches a leaked value
        # that got reformatted, e.g. 1234.50 vs 1234.5).
        if path.endswith(".json"):
            try:
                doc = json.loads(text)
            except json.JSONDecodeError:
                continue
            found = []
            walk(doc, on_num=lambda n, p: found.append((float(n), p)))
            for value, jpath in found:
                if value in secret_numbers:
                    hits.append((rel, jpath, "number-exact", sha8(repr(value)), 0))
    return hits


def self_test(capture_dir, secret_strings, secret_numbers, repo_root) -> int:
    """Prove the scanner can fail.

    Plants one real capture string and one real capture number into a temp file
    OUTSIDE the repo, scans it, and requires both to be caught. Nothing is
    printed but pass/fail — the canary file is deleted either way.
    """
    import tempfile

    if not secret_strings or not secret_numbers:
        print("SELF-TEST: INCONCLUSIVE — capture corpus yielded no secrets to plant.")
        return 1

    canary_string = max(secret_strings, key=len)
    canary_number = max(secret_numbers, key=abs)

    fd, canary = tempfile.mkstemp(suffix=".md", prefix="leakcheck_canary_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(f"planted string: {canary_string}\nplanted number: {canary_number}\n")
        hits = scan([canary], secret_strings, secret_numbers, repo_root)
        kinds = {h[2] for h in hits}
        ok_string = "string" in kinds
        ok_number = bool({"number-token", "number-exact"} & kinds)
        print(f"SELF-TEST planted string caught: {ok_string}")
        print(f"SELF-TEST planted number caught: {ok_number}")
        if ok_string and ok_number:
            print("SELF-TEST: PASS — the scanner detects planted capture values, "
                  "so a PASS on the real files is meaningful.")
            return 0
        print("SELF-TEST: FAIL — the scanner missed a planted value. Do not trust a PASS.")
        return 1
    finally:
        os.unlink(canary)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--captures", required=True,
                        help="scratch dir holding the raw capture JSON (outside the repo)")
    parser.add_argument("--repo-root", default=None)
    parser.add_argument("--self-test", action="store_true",
                        help="plant a real capture value in a temp file and prove the "
                             "check flags it, so a PASS cannot be vacuous")
    parser.add_argument("files", nargs="*",
                        help="explicit files to scan (default: docs/ + the ind_money fixtures)")
    args = parser.parse_args()

    repo_root = args.repo_root or subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()

    if not os.path.isdir(args.captures):
        print(f"ERROR: captures dir not found: {args.captures}", file=sys.stderr)
        return 2
    if os.path.abspath(args.captures).startswith(os.path.abspath(repo_root) + os.sep):
        print("ERROR: captures dir is INSIDE the repo. That is the leak. Move it out.",
              file=sys.stderr)
        return 2

    secret_strings, secret_numbers, allowlist, provenance = harvest_captures(args.captures)

    if args.self_test:
        return self_test(args.captures, secret_strings, secret_numbers, repo_root)

    paths = staged_files(repo_root, [os.path.abspath(p) for p in args.files])

    print(f"captures dir      : {args.captures}")
    print(f"secret strings    : {len(secret_strings)}")
    print(f"secret numbers    : {len(secret_numbers)}")
    print(f"allowlisted tokens: {len(allowlist)} (field names, tool names, schema enums)")
    print(f"files scanned     : {len(paths)}")

    hits = scan(paths, secret_strings, secret_numbers, repo_root)
    if not hits:
        print("\nLEAK CHECK: PASS — no capture value appears in any scanned file.")
        return 0

    print(f"\nLEAK CHECK: FAIL — {len(hits)} overlap(s). Values withheld by design:")
    for rel, where, kind, digest, length in hits:
        src = ",".join(sorted(provenance.get(digest, {"?"})))
        print(f"  {rel} :: {where} :: {kind} :: sha1={digest} len={length} :: from {src}")
    return 1


if __name__ == "__main__":
    sys.exit(main())

"""Check the static TVT parity ledger against the 77-case APK audit."""

from __future__ import annotations

import argparse
import re
from collections import Counter
from pathlib import Path

CASE_PATTERN = re.compile(r"^P\d{2}\.\d+(?:\.[a-z][a-z0-9_]*)?$")
AUDIT_ROW = re.compile(r"^\| (P\d{2}\.\d+) [CDL] ", re.MULTILINE)
SOURCE_LINK = re.compile(
    r"\[12:(P\d{2}\.\d+)\]\(apk-audit/12-functional-parity-contracts\.md\)"
)
START = "<!-- PARITY_CASES_START -->"
END = "<!-- PARITY_CASES_END -->"


def audit_ids(text: str) -> set[str]:
    """Extract the frozen seed IDs from the atomic APK audit."""
    return set(AUDIT_ROW.findall(text))


def validate_ledger(text: str, expected_ids: set[str]) -> list[str]:
    """Return all structural/evidence defects, without promoting static data."""
    errors: list[str] = []
    if START not in text or END not in text:
        return ["parity case table markers are missing"]
    table = text.split(START, 1)[1].split(END, 1)[0]
    rows: list[list[str]] = []
    for line in table.splitlines():
        if not line.startswith("| P"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 10:
            errors.append(f"case row has {len(cells)} columns: {line[:60]}")
            continue
        rows.append(cells)

    ids = [row[0] for row in rows]
    duplicates = sorted(case_id for case_id, n in Counter(ids).items() if n > 1)
    for case_id in duplicates:
        errors.append(f"duplicate case_id: {case_id}")
    for case_id in sorted(expected_ids - set(ids)):
        errors.append(f"missing audit case: {case_id}")
    discovered_ids = set(ids) - expected_ids
    for case_id in sorted(discovered_ids):
        seed_id = re.match(r"^P\d{2}\.\d+", case_id)
        if (
            not seed_id
            or seed_id.group() not in expected_ids
            or case_id == seed_id.group()
        ):
            errors.append(f"unreviewed case outside audit baseline: {case_id}")

    for row in rows:
        (
            case_id,
            feature,
            owner,
            gate,
            static_path,
            reachability,
            build,
            parity,
            source,
            runtime,
        ) = row
        if not CASE_PATTERN.fullmatch(case_id):
            errors.append(f"invalid case_id: {case_id}")
        if not re.fullmatch(r"F\d{2}", feature):
            errors.append(f"{case_id}: missing feature owner")
        if not re.fullmatch(r"W\d{2}(?:/W\d{2})*", owner):
            errors.append(f"{case_id}: missing implementation owner")
        if not gate or gate == "—":
            errors.append(f"{case_id}: missing gate")
        if static_path not in {"C", "D", "L"}:
            errors.append(f"{case_id}: invalid static path classification")
        if reachability not in {"DECLARED", "REACHABLE", "BLOCKED", "NOT_APPLICABLE"}:
            errors.append(f"{case_id}: invalid reachability status")
        if build not in {"NOT_STARTED", "IMPLEMENTED"}:
            errors.append(f"{case_id}: invalid implementation status")
        if parity not in {"UNTESTED", "MATCHED", "DIFFERENT"}:
            errors.append(f"{case_id}: invalid parity status")
        seed_id = re.match(r"^P\d{2}\.\d+", case_id)
        source_match = SOURCE_LINK.search(source)
        if not source_match or not seed_id or source_match.group(1) != seed_id.group():
            errors.append(f"{case_id}: missing case-specific APK source link")
        if case_id in discovered_ids and not (
            "discovery-digest:" in runtime and "reviewer:" in runtime
        ):
            errors.append(
                f"{case_id}: runtime discovery lacks artifact digest and reviewer"
            )
        if reachability == "REACHABLE" and not (
            "entry-proof:" in runtime and "reviewer:" in runtime
        ):
            errors.append(
                f"{case_id}: REACHABLE lacks runtime entry proof and reviewer"
            )
        if reachability == "BLOCKED" and runtime == "—":
            errors.append(f"{case_id}: BLOCKED lacks a concrete reason")
        if reachability == "NOT_APPLICABLE":
            errors.append(
                f"{case_id}: NOT_APPLICABLE needs a reviewed case × matrix "
                "gate registry; a case-level marker cannot exclude every model"
            )
        if parity == "MATCHED":
            errors.append(
                f"{case_id}: MATCHED requires a W24-validated run registry; "
                "the static checker cannot verify a self-labeled verdict"
            )
        if parity == "DIFFERENT" and runtime == "—":
            errors.append(f"{case_id}: DIFFERENT lacks comparison evidence")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ledger", type=Path)
    args = parser.parse_args()
    audit = (
        Path(__file__).resolve().parents[1]
        / "docs/integrations/apk-audit/12-functional-parity-contracts.md"
    )
    expected = audit_ids(audit.read_text(encoding="utf-8"))
    text = args.ledger.read_text(encoding="utf-8")
    errors = validate_ledger(text, expected)
    source_target = args.ledger.parent / "apk-audit/12-functional-parity-contracts.md"
    if not source_target.is_file():
        errors.append(f"missing source document: {source_target}")
    row_count = len(re.findall(r"^\| P\d{2}\.", text, re.MULTILINE))
    print(f"audit cases={len(expected)}; ledger rows={row_count}")
    print(f"duplicate/missing/source/status errors={len(errors)}")
    for error in errors:
        print(f"ERROR: {error}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())

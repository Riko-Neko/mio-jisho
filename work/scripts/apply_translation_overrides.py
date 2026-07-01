#!/usr/bin/env python3
"""Apply reviewed/LLM translation overrides to built CSV outputs."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


TARGET_FILES = [
    "master_lexicon.csv",
    "verbs_by_transitivity.csv",
    "adjective_clusters.csv",
]


def read_overrides(path: Path) -> dict[str, dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = csv.DictReader(handle, delimiter="\t")
        return {
            row["词条ID"].strip(): {
                "中文翻译": row["中文翻译"].strip(),
                "翻译来源": row["翻译来源"].strip(),
            }
            for row in rows
            if row.get("词条ID") and row.get("中文翻译")
        }


def update_csv(path: Path, overrides: dict[str, dict[str, str]]) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    if "词条ID" not in fieldnames:
        return 0
    for field in ["中文翻译", "翻译来源"]:
        if field not in fieldnames:
            fieldnames.append(field)

    count = 0
    for row in rows:
        override = overrides.get((row.get("词条ID") or "").strip())
        if not override:
            continue
        row.update(override)
        count += 1

    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-dir", type=Path, default=Path("work/build"))
    parser.add_argument("--overrides", type=Path, required=True)
    args = parser.parse_args()

    overrides = read_overrides(args.overrides)
    total = 0
    for filename in TARGET_FILES:
        count = update_csv(args.build_dir / filename, overrides)
        total += count
        print(f"{filename}: {count}")
    print(f"overrides_loaded: {len(overrides)}")
    print(f"rows_updated: {total}")


if __name__ == "__main__":
    main()

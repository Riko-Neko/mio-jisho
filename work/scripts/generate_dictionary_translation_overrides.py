#!/usr/bin/env python3
"""Generate local dictionary-style Chinese translation overrides.

The script is intentionally batch-friendly:
- rows translated with sufficient confidence are written to an override TSV;
- low-confidence rows are still given a draft, but are also exported to a JSONL
  repair queue for a later LLM pass.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

from gloss_translation import (
    DICTIONARY_TRANSLATION_SOURCE,
    LLM_REPAIR_QUEUE_SOURCE,
    load_cedict_index,
    translate_glosses_detailed,
)


def split_glosses(value: str | None) -> list[str]:
    return [part.strip() for part in re.split(r"\s*[;；]\s*", value or "") if part.strip()]


def should_preserve(row: dict[str, str], prefixes: tuple[str, ...]) -> bool:
    source = (row.get("翻译来源") or "").strip()
    return bool(source and prefixes and source.startswith(prefixes))


def source_for(confidence: float, needs_llm: bool, threshold: float) -> str:
    if needs_llm or confidence < threshold:
        return LLM_REPAIR_QUEUE_SOURCE
    return DICTIONARY_TRANSLATION_SOURCE


def generate(args: argparse.Namespace) -> None:
    levels = {item.strip() for item in args.levels.split(",") if item.strip()}
    preserve_prefixes = tuple(item.strip() for item in args.preserve_source_prefix.split(",") if item.strip())
    cedict = load_cedict_index(args.cedict)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.repair_queue.parent.mkdir(parents=True, exist_ok=True)

    translated = 0
    preserved = 0
    queued = 0
    skipped = 0

    with args.input.open("r", encoding="utf-8-sig", newline="") as src, args.output.open(
        "w", encoding="utf-8-sig", newline=""
    ) as out, args.repair_queue.open("w", encoding="utf-8") as repair:
        reader = csv.DictReader(src)
        writer = csv.DictWriter(out, fieldnames=["词条ID", "中文翻译", "翻译来源"], delimiter="\t")
        writer.writeheader()

        for row in reader:
            if levels and row.get("等级") not in levels:
                skipped += 1
                continue
            if args.max_rows and translated >= args.max_rows:
                skipped += 1
                continue
            if should_preserve(row, preserve_prefixes):
                preserved += 1
                continue

            glosses = split_glosses(row.get("英文释义摘录"))
            if not glosses:
                skipped += 1
                continue

            results = translate_glosses_detailed(
                glosses,
                limit=args.limit,
                major_pos=row.get("大类", ""),
                subpos=row.get("细品词", ""),
                cedict=cedict,
            )
            if not results:
                skipped += 1
                continue

            confidence = min(item.confidence for item in results)
            needs_llm = any(item.needs_llm for item in results)
            translation = "；".join(item.text for item in results)
            source = source_for(confidence, needs_llm, args.threshold)
            writer.writerow({"词条ID": row["词条ID"], "中文翻译": translation, "翻译来源": source})
            translated += 1

            if source == LLM_REPAIR_QUEUE_SOURCE:
                queued += 1
                repair.write(
                    json.dumps(
                        {
                            "id": row.get("词条ID", ""),
                            "level": row.get("等级", ""),
                            "word": row.get("表记", ""),
                            "reading": row.get("读音", ""),
                            "major": row.get("大类", ""),
                            "subpos": row.get("细品词", ""),
                            "glosses": glosses,
                            "draft_translation": translation,
                            "min_confidence": round(confidence, 2),
                            "methods": [item.method for item in results],
                            "instruction": "请基于日语表记、读音、词性和英文释义，生成简短中文词典释义；不要扩展英文释义之外的意思。",
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )

    print(f"input: {args.input}")
    print(f"output: {args.output}")
    print(f"repair_queue: {args.repair_queue}")
    print(f"cedict_loaded: {bool(cedict)}")
    print(f"levels: {','.join(sorted(levels)) or 'ALL'}")
    print(f"translated_overrides: {translated}")
    print(f"preserved_existing: {preserved}")
    print(f"queued_for_llm: {queued}")
    print(f"skipped: {skipped}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("work/build/master_lexicon.csv"))
    parser.add_argument("--output", type=Path, default=Path("work/data/a_dictionary_translation_overrides.tsv"))
    parser.add_argument("--repair-queue", type=Path, default=Path("work/data/a_llm_repair_queue.jsonl"))
    parser.add_argument("--cedict", type=Path, default=Path("work/data/cedict_1_0_ts_utf-8_mdbg.txt.gz"))
    parser.add_argument("--levels", default="A")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--threshold", type=float, default=0.60)
    parser.add_argument("--max-rows", type=int, default=0)
    parser.add_argument("--preserve-source-prefix", default="LLM")
    args = parser.parse_args()
    generate(args)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Translate repair-queue glosses with DeepL API and emit override TSV.

This script is designed for the DeepL Free API. It translates complete English
gloss lists for rows in the repair queue, up to a configurable character budget,
then writes a normal override TSV consumable by apply_translation_overrides.py.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


DEEPL_FREE_ENDPOINT = "https://api-free.deepl.com/v2/translate"
DEEPL_SOURCE = "DeepL初译（待复核）"
LOW_METHODS = {"untranslated", "phrase-word-low", "phrase-word-partial", "proper-original"}


def read_queue(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def sort_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    level_rank = {"A": 0, "B": 1, "C": 2}
    return sorted(
        rows,
        key=lambda row: (
            level_rank.get(str(row.get("level", "")), 9),
            sum(len(item) for item in row.get("glosses", [])),
            str(row.get("word", "")),
        ),
    )


def split_draft(value: str) -> list[str]:
    return [part.strip() for part in value.split("；") if part.strip()]


def compact_translation(value: str) -> str:
    value = " ".join(value.replace("\n", " ").split())
    value = value.strip("。.;； ")
    value = value.replace("；", "、")
    return value or "待译"


def translate_batch(
    texts: list[str],
    auth_key: str,
    endpoint: str,
    source_lang: str,
    target_lang: str,
    timeout: int,
    retries: int,
) -> list[str]:
    payload: list[tuple[str, str]] = [
        ("auth_key", auth_key),
        ("source_lang", source_lang),
        ("target_lang", target_lang),
    ]
    payload.extend(("text", text) for text in texts)
    data = urllib.parse.urlencode(payload).encode("utf-8")
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    for attempt in range(retries + 1):
        request = urllib.request.Request(endpoint, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8")
            parsed = json.loads(body)
            return [item["text"] for item in parsed["translations"]]
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            if exc.code == 400 and target_lang.upper() == "ZH-HANS":
                return translate_batch(texts, auth_key, endpoint, source_lang, "ZH", timeout, retries)
            if exc.code in {429, 500, 502, 503, 504} and attempt < retries:
                time.sleep(2**attempt)
                continue
            raise RuntimeError(f"DeepL HTTP {exc.code}: {body[:500]}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt < retries:
                time.sleep(2**attempt)
                continue
            raise RuntimeError(f"DeepL request failed: {exc}") from exc

    raise RuntimeError("DeepL request failed after retries")


def select_rows(rows: list[dict[str, Any]], max_chars: int, max_rows: int) -> list[dict[str, Any]]:
    selected = []
    used = 0
    for row in sort_rows(rows):
        glosses = [item for item in row.get("glosses", []) if item]
        if not glosses:
            continue
        row_chars = sum(len(item) for item in glosses)
        if max_rows and len(selected) >= max_rows:
            break
        if selected and used + row_chars > max_chars:
            break
        if row_chars > max_chars:
            continue
        selected.append(row)
        used += row_chars
    return selected


def build_override(row: dict[str, Any], translations: list[str]) -> dict[str, str]:
    translated_parts = [compact_translation(item) for item in translations]
    return {
        "词条ID": str(row.get("id", "")),
        "中文翻译": "；".join(dict.fromkeys(translated_parts)),
        "翻译来源": DEEPL_SOURCE,
    }


def run(args: argparse.Namespace) -> None:
    key = os.environ.get(args.auth_env) or os.environ.get("DEEPL_AUTH_KEY") or os.environ.get("DEEPL_API_KEY")
    rows = read_queue(args.input)
    selected = select_rows(rows, args.max_chars, args.max_rows)
    selected_chars = sum(sum(len(item) for item in row.get("glosses", [])) for row in selected)

    print(f"queue_rows: {len(rows)}")
    print(f"selected_rows: {len(selected)}")
    print(f"selected_source_chars: {selected_chars}")
    print(f"max_chars: {args.max_chars}")
    print(f"output: {args.output}")

    if args.dry_run:
        for row in selected[: args.preview]:
            print(f"{row.get('level')} {row.get('word')} {row.get('glosses')}")
        return

    if not key:
        raise SystemExit(
            f"Missing DeepL key. Set {args.auth_env}=... or DEEPL_AUTH_KEY=... before running without --dry-run."
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    translated_texts = 0
    translated_rows = 0

    with args.output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["词条ID", "中文翻译", "翻译来源"], delimiter="\t")
        writer.writeheader()

        batch_rows: list[dict[str, Any]] = []
        batch_texts: list[str] = []
        for row in selected:
            glosses = [item for item in row.get("glosses", []) if item]
            if not glosses:
                continue
            if batch_texts and (len(batch_texts) + len(glosses) > args.batch_size or sum(map(len, batch_texts + glosses)) > args.batch_chars):
                translated = translate_batch(
                    batch_texts,
                    key,
                    args.endpoint,
                    args.source_lang,
                    args.target_lang,
                    args.timeout,
                    args.retries,
                )
                offset = 0
                for batch_row in batch_rows:
                    count = len(batch_row.get("glosses", []))
                    writer.writerow(build_override(batch_row, translated[offset : offset + count]))
                    offset += count
                    translated_rows += 1
                translated_texts += len(translated)
                print(f"translated_rows: {translated_rows}", flush=True)
                time.sleep(args.sleep)
                batch_rows = []
                batch_texts = []

            batch_rows.append(row)
            batch_texts.extend(glosses)

        if batch_texts:
            translated = translate_batch(
                batch_texts,
                key,
                args.endpoint,
                args.source_lang,
                args.target_lang,
                args.timeout,
                args.retries,
            )
            offset = 0
            for batch_row in batch_rows:
                count = len(batch_row.get("glosses", []))
                writer.writerow(build_override(batch_row, translated[offset : offset + count]))
                offset += count
                translated_rows += 1
            translated_texts += len(translated)

    print(f"translated_rows: {translated_rows}")
    print(f"translated_texts: {translated_texts}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("work/data/llm_repair_queue.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("work/data/deepl_translation_overrides.tsv"))
    parser.add_argument("--endpoint", default=DEEPL_FREE_ENDPOINT)
    parser.add_argument("--auth-env", default="DEEPL_AUTH_KEY")
    parser.add_argument("--source-lang", default="EN")
    parser.add_argument("--target-lang", default="ZH-HANS")
    parser.add_argument("--max-chars", type=int, default=480_000)
    parser.add_argument("--max-rows", type=int, default=0)
    parser.add_argument("--batch-size", type=int, default=45)
    parser.add_argument("--batch-chars", type=int, default=10_000)
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--sleep", type=float, default=0.2)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--preview", type=int, default=10)
    args = parser.parse_args()
    try:
        run(args)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Build static Tatoeba example data for the lexicon app.

This first pass is deliberately conservative: it uses only Japanese sentences
that have direct Chinese translations in Tatoeba, then matches them to selected
lexicon entries by visible Japanese surface forms and a few common stem forms.
"""

from __future__ import annotations

import argparse
import bz2
import csv
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


JP_TEXT_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]")
KANJI_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
KANA_ONLY_RE = re.compile(r"^[\u3040-\u30ffー・]+$")
LATIN_RE = re.compile(r"[A-Za-z]")

FIELDS = {
    "id": "词条ID",
    "level": "等级",
    "word": "表记",
    "reading": "读音",
    "major": "大类",
    "subpos": "细品词",
    "writings": "全部表记",
    "rank": "BCCWJ_rank",
}

SOURCE_LABEL = "Tatoeba / CC BY"
LICENSE_URL = "https://creativecommons.org/licenses/by/2.0/fr/"

DENY_TERMS = {
    "する",
    "ある",
    "いる",
    "なる",
    "こと",
    "もの",
    "それ",
    "これ",
    "そこ",
    "ここ",
    "ため",
    "よう",
    "さん",
    "ない",
    "いい",
}

GODAN_RENYOU = {
    "う": "い",
    "く": "き",
    "ぐ": "ぎ",
    "す": "し",
    "つ": "ち",
    "ぬ": "に",
    "ぶ": "び",
    "む": "み",
    "る": "り",
}

GODAN_TE_TA = {
    "う": "っ",
    "つ": "っ",
    "る": "っ",
    "く": "い",
    "ぐ": "い",
    "す": "し",
    "ぬ": "ん",
    "ぶ": "ん",
    "む": "ん",
}


def clean(value: str | None) -> str:
    return (value or "").strip()


def split_semicolon(value: str | None) -> list[str]:
    return [part.strip() for part in clean(value).split("；") if part.strip()]


def maybe_int(value: str | None) -> int | None:
    value = clean(value)
    if not value:
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def read_master(path: Path, levels: set[str]) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            level = clean(row.get(FIELDS["level"]))
            if levels and level not in levels:
                continue
            entries.append(
                {
                    "id": clean(row.get(FIELDS["id"])),
                    "level": level,
                    "word": clean(row.get(FIELDS["word"])),
                    "reading": clean(row.get(FIELDS["reading"])),
                    "major": clean(row.get(FIELDS["major"])),
                    "subpos": clean(row.get(FIELDS["subpos"])),
                    "writings": split_semicolon(row.get(FIELDS["writings"])),
                    "rank": maybe_int(row.get(FIELDS["rank"])),
                }
            )
    return entries


def iter_bz2_tsv(path: Path) -> list[list[str]]:
    rows: list[list[str]] = []
    with bz2.open(path, "rt", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle, delimiter="\t")
        rows.extend(reader)
    return rows


def load_sentences(path: Path) -> dict[str, str]:
    sentences: dict[str, str] = {}
    for row in iter_bz2_tsv(path):
        if len(row) >= 3:
            sentence_id, _lang, text = row[0], row[1], row[2]
            sentences[sentence_id] = text.strip()
    return sentences


def load_links(path: Path) -> dict[str, list[str]]:
    links: dict[str, list[str]] = defaultdict(list)
    for row in iter_bz2_tsv(path):
        if len(row) >= 2:
            links[row[0]].append(row[1])
    return links


def is_candidate_term(term: str) -> bool:
    term = term.strip()
    if term in DENY_TERMS:
        return False
    if not term or not JP_TEXT_RE.search(term):
        return False
    if LATIN_RE.search(term):
        return False
    if KANA_ONLY_RE.match(term):
        return len(term.replace("ー", "")) >= 3
    return len(term) >= 2


def variant_terms(entry: dict[str, object]) -> set[str]:
    terms: set[str] = set()
    word = str(entry["word"])
    major = str(entry["major"])
    subpos = str(entry["subpos"]).lower()

    for term in [word, *list(entry.get("writings") or [])]:
        if is_candidate_term(term):
            terms.add(term)

    if major == "动词" and len(word) >= 3:
        last = word[-1]
        stem = word[:-1]
        if word.endswith("る") and ("ichidan" in subpos or "一段" in subpos):
            for suffix in ("", "た", "て", "ます", "ない", "よう", "られる", "させる"):
                term = stem + suffix
                if is_candidate_term(term):
                    terms.add(term)
        elif last in GODAN_RENYOU:
            for suffix in ("ます", "たい", "ながら"):
                term = stem + GODAN_RENYOU[last] + suffix
                if is_candidate_term(term):
                    terms.add(term)
            for suffix in ("た", "て"):
                term = stem + GODAN_TE_TA[last] + suffix
                if is_candidate_term(term):
                    terms.add(term)

    if major == "一类形容词" and word.endswith("い") and len(word) >= 3:
        stem = word[:-1]
        for suffix in ("い", "く", "かった", "ければ", "さ"):
            term = stem + suffix
            if is_candidate_term(term):
                terms.add(term)

    return terms


def build_term_index(entries: list[dict[str, object]]) -> dict[str, list[tuple[str, str]]]:
    by_first: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for entry in entries:
        entry_id = str(entry["id"])
        for term in variant_terms(entry):
            by_first[term[0]].append((term, entry_id))
    for key, items in by_first.items():
        by_first[key] = sorted(set(items), key=lambda item: (-len(item[0]), item[0], item[1]))
    return by_first


def score_example(sentence: str, translation: str, term: str, rank: int | None) -> tuple[int, int, int, int]:
    sentence_len = len(sentence)
    translation_len = len(translation)
    kanji_bonus = 0 if KANJI_RE.search(term) else 1
    rank_value = rank if rank is not None else 999999
    return (kanji_bonus, abs(sentence_len - 24), abs(translation_len - 24), rank_value)


def eligible_sentence(text: str) -> bool:
    text = text.strip()
    if len(text) < 6 or len(text) > 62:
        return False
    return bool(JP_TEXT_RE.search(text))


def eligible_translation(text: str) -> bool:
    text = text.strip()
    if len(text) < 4 or len(text) > 90:
        return False
    return bool(KANJI_RE.search(text))


def build_examples(
    entries: list[dict[str, object]],
    jpn_sentences: dict[str, str],
    cmn_sentences: dict[str, str],
    jpn_cmn_links: dict[str, list[str]],
    max_per_entry: int,
) -> dict[str, list[dict[str, object]]]:
    entry_by_id = {str(entry["id"]): entry for entry in entries}
    term_index = build_term_index(entries)
    candidates: dict[str, list[tuple[tuple[int, int, int, int], dict[str, object]]]] = defaultdict(list)

    linked_ids = set(jpn_cmn_links)
    for sentence_id in linked_ids:
        sentence = jpn_sentences.get(sentence_id, "").strip()
        if not eligible_sentence(sentence):
            continue
        translation_ids = [
            translation_id
            for translation_id in jpn_cmn_links.get(sentence_id, [])
            if eligible_translation(cmn_sentences.get(translation_id, ""))
        ]
        if not translation_ids:
            continue
        translation_id = min(translation_ids, key=lambda item: len(cmn_sentences[item]))
        translation = cmn_sentences[translation_id].strip()

        matched: set[tuple[str, str]] = set()
        for char in set(sentence):
            for term, entry_id in term_index.get(char, []):
                if (term, entry_id) in matched or term not in sentence:
                    continue
                matched.add((term, entry_id))
                entry = entry_by_id[entry_id]
                example = {
                    "ja": sentence,
                    "zh": translation,
                    "source": SOURCE_LABEL,
                    "sentenceId": sentence_id,
                    "translationId": translation_id,
                    "url": f"https://tatoeba.org/en/sentences/show/{sentence_id}",
                    "matched": term,
                }
                candidates[entry_id].append(
                    (score_example(sentence, translation, term, entry.get("rank")), example)
                )

    examples: dict[str, list[dict[str, object]]] = {}
    for entry_id, items in candidates.items():
        unique_by_sentence: dict[str, tuple[tuple[int, int, int, int], dict[str, object]]] = {}
        for score, example in items:
            sentence_id = str(example["sentenceId"])
            current = unique_by_sentence.get(sentence_id)
            if current is None or score < current[0]:
                unique_by_sentence[sentence_id] = (score, example)
        chosen = [example for _score, example in sorted(unique_by_sentence.values(), key=lambda item: item[0])[:max_per_entry]]
        if chosen:
            examples[entry_id] = chosen
    return examples


def write_csv(output_path: Path, examples: dict[str, list[dict[str, object]]]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "词条ID",
                "日文例句",
                "中文译文",
                "来源",
                "日文句子ID",
                "中文句子ID",
                "匹配词形",
                "URL",
            ],
        )
        writer.writeheader()
        for entry_id, items in sorted(examples.items(), key=lambda item: int(item[0])):
            for item in items:
                writer.writerow(
                    {
                        "词条ID": entry_id,
                        "日文例句": item["ja"],
                        "中文译文": item["zh"],
                        "来源": item["source"],
                        "日文句子ID": item["sentenceId"],
                        "中文句子ID": item["translationId"],
                        "匹配词形": item["matched"],
                        "URL": item["url"],
                    }
                )


def write_js(output_path: Path, examples: dict[str, list[dict[str, object]]], target_count: int) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    public_examples: dict[str, list[dict[str, object]]] = {}
    total_examples = 0
    for entry_id, items in examples.items():
        public_items = []
        for item in items:
            public_items.append(
                {
                    "ja": item["ja"],
                    "zh": item["zh"],
                    "source": item["source"],
                    "sentenceId": item["sentenceId"],
                    "translationId": item["translationId"],
                    "url": item["url"],
                }
            )
        public_examples[entry_id] = public_items
        total_examples += len(public_items)

    payload = {
        "meta": {
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "source": "Tatoeba direct Japanese-Chinese links",
            "license": "CC BY 2.0 FR",
            "licenseUrl": LICENSE_URL,
            "targetEntries": target_count,
            "coveredEntries": len(public_examples),
            "examples": total_examples,
        },
        "entries": public_examples,
    }
    output_path.write_text(
        "window.LEXICON_EXAMPLES = "
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        + ";\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lexicon", type=Path, default=Path("work/build/master_lexicon.csv"))
    parser.add_argument("--tatoeba-dir", type=Path, default=Path("work/data/tatoeba"))
    parser.add_argument("--csv-output", type=Path, default=Path("work/build/tatoeba_examples.csv"))
    parser.add_argument("--js-output", type=Path, default=Path("outputs/lexicon_app/examples-data.js"))
    parser.add_argument("--levels", default="A", help="Comma-separated lexicon levels to build, e.g. A or A,B,C")
    parser.add_argument("--max-per-entry", type=int, default=2)
    args = parser.parse_args()

    levels = {item.strip() for item in args.levels.split(",") if item.strip()}
    entries = read_master(args.lexicon, levels)
    jpn_sentences = load_sentences(args.tatoeba_dir / "jpn_sentences.tsv.bz2")
    cmn_sentences = load_sentences(args.tatoeba_dir / "cmn_sentences.tsv.bz2")
    jpn_cmn_links = load_links(args.tatoeba_dir / "jpn-cmn_links.tsv.bz2")

    examples = build_examples(
        entries=entries,
        jpn_sentences=jpn_sentences,
        cmn_sentences=cmn_sentences,
        jpn_cmn_links=jpn_cmn_links,
        max_per_entry=args.max_per_entry,
    )
    write_csv(args.csv_output, examples)
    write_js(args.js_output, examples, len(entries))

    total_examples = sum(len(items) for items in examples.values())
    print(f"target_entries={len(entries)}")
    print(f"covered_entries={len(examples)}")
    print(f"examples={total_examples}")
    print(f"csv_output={args.csv_output}")
    print(f"js_output={args.js_output}")


if __name__ == "__main__":
    main()

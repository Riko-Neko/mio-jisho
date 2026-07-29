#!/usr/bin/env python3
"""Export the built lexicon CSVs as a browser-friendly static data file."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


FIELDS = {
    "id": "词条ID",
    "level": "等级",
    "jlpt": "JLPT参考等级",
    "jlpt_source": "JLPT来源",
    "jlpt_confidence": "JLPT置信度",
    "jlpt_note": "JLPT备注",
    "word": "表记",
    "reading": "读音",
    "major": "大类",
    "subpos": "细品词",
    "transitivity": "自他",
    "conjugation": "活用",
    "cluster": "词群",
    "pair": "自他对应候补",
    "kanji": "核心汉字",
    "writings": "全部表记",
    "readings": "全部读音",
    "tags": "常用度标签",
    "gloss": "英文释义摘录",
    "translation": "中文翻译",
    "translation_source": "翻译来源",
    "rank": "BCCWJ_rank",
    "frequency": "BCCWJ_frequency",
    "pmw": "BCCWJ_pmw",
    "bccwj_pos": "BCCWJ_pos",
    "review": "复核状态",
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


def maybe_float(value: str | None) -> float | None:
    value = clean(value)
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def build_kanji_metadata(noun_tree_rows: list[dict[str, str]]) -> dict[str, dict[str, object]]:
    metadata: dict[str, dict[str, object]] = {}
    for row in noun_tree_rows:
        kanji = clean(row.get("核心汉字"))
        if not kanji:
            continue
        item = metadata.setdefault(
            kanji,
            {
                "kanji": kanji,
                "status": "",
                "on": "",
                "kun": "",
                "nounCount": 0,
                "sampleWords": [],
            },
        )
        item["status"] = item["status"] or clean(row.get("汉字状态"))
        item["on"] = item["on"] or clean(row.get("音读"))
        item["kun"] = item["kun"] or clean(row.get("训读"))
        if clean(row.get("关系")) == "主节点":
            item["nounCount"] = int(item["nounCount"]) + 1
        sample_words = item["sampleWords"]
        if isinstance(sample_words, list) and len(sample_words) < 6:
            word = clean(row.get("关联词"))
            reading = clean(row.get("单词读音"))
            if word and all(existing.get("word") != word for existing in sample_words):
                sample_words.append({"word": word, "reading": reading})
    return metadata


def export_data(input_dir: Path, output_dir: Path) -> Path:
    master_rows = read_csv(input_dir / "master_lexicon.csv")
    cluster_rows = read_csv(input_dir / "cluster_summary.csv")
    noun_tree_rows = read_csv(input_dir / "noun_kanji_tree.csv")
    kanji_metadata = build_kanji_metadata(noun_tree_rows)

    entries: list[dict[str, object]] = []
    major_counts: Counter[str] = Counter()
    level_counts: Counter[str] = Counter()
    transitivity_counts: Counter[str] = Counter()
    jlpt_counts: Counter[str] = Counter()
    cluster_counts: Counter[tuple[str, str]] = Counter()
    kanji_counts: Counter[str] = Counter()

    for row in master_rows:
        entry = {
            "id": clean(row.get(FIELDS["id"])),
            "level": clean(row.get(FIELDS["level"])),
            "jlpt": clean(row.get(FIELDS["jlpt"])),
            "jlptSource": clean(row.get(FIELDS["jlpt_source"])),
            "jlptConfidence": clean(row.get(FIELDS["jlpt_confidence"])),
            "jlptNote": clean(row.get(FIELDS["jlpt_note"])),
            "word": clean(row.get(FIELDS["word"])),
            "reading": clean(row.get(FIELDS["reading"])),
            "major": clean(row.get(FIELDS["major"])),
            "subpos": clean(row.get(FIELDS["subpos"])),
            "transitivity": clean(row.get(FIELDS["transitivity"])),
            "conjugation": clean(row.get(FIELDS["conjugation"])),
            "cluster": clean(row.get(FIELDS["cluster"])),
            "pair": clean(row.get(FIELDS["pair"])),
            "kanji": split_semicolon(row.get(FIELDS["kanji"])),
            "writings": split_semicolon(row.get(FIELDS["writings"])),
            "readings": split_semicolon(row.get(FIELDS["readings"])),
            "tags": split_semicolon(row.get(FIELDS["tags"])),
            "gloss": split_semicolon(row.get(FIELDS["gloss"])),
            "translation": split_semicolon(row.get(FIELDS["translation"])),
            "translationSource": clean(row.get(FIELDS["translation_source"])),
            "rank": maybe_int(row.get(FIELDS["rank"])),
            "frequency": maybe_int(row.get(FIELDS["frequency"])),
            "pmw": maybe_float(row.get(FIELDS["pmw"])),
            "bccwjPos": clean(row.get(FIELDS["bccwj_pos"])),
            "review": clean(row.get(FIELDS["review"])),
        }
        entries.append(entry)

        major = str(entry["major"])
        level = str(entry["level"])
        transitivity = str(entry["transitivity"])
        jlpt = str(entry["jlpt"])
        cluster = str(entry["cluster"])
        major_counts[major] += 1
        level_counts[level] += 1
        if jlpt:
            jlpt_counts[jlpt] += 1
        if transitivity:
            transitivity_counts[transitivity] += 1
        if cluster:
            cluster_counts[(major, cluster)] += 1
        for kanji in entry["kanji"]:
            kanji_counts[str(kanji)] += 1

    clusters = []
    for row in cluster_rows:
        clusters.append(
            {
                "major": clean(row.get("大类")),
                "cluster": clean(row.get("词群")),
                "count": maybe_int(row.get("词条数")) or 0,
            }
        )
    if not clusters:
        clusters = [
            {"major": major, "cluster": cluster, "count": count}
            for (major, cluster), count in cluster_counts.items()
        ]
    clusters.sort(key=lambda item: (item["major"], -int(item["count"]), item["cluster"]))

    kanji_index = []
    for kanji, count in kanji_counts.items():
        metadata = kanji_metadata.get(kanji, {"kanji": kanji})
        kanji_index.append({**metadata, "count": count})
    kanji_index.sort(key=lambda item: (-int(item["count"]), str(item["kanji"])))

    payload = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "source": {
            "master": "work/build/master_lexicon.csv",
            "clusters": "work/build/cluster_summary.csv",
            "nounKanjiTree": "work/build/noun_kanji_tree.csv",
        },
        "stats": {
            "entries": len(entries),
            "majors": dict(sorted(major_counts.items())),
            "levels": dict(sorted(level_counts.items())),
            "jlpt": dict(sorted(jlpt_counts.items())),
            "transitivity": dict(transitivity_counts.most_common()),
            "kanji": len(kanji_index),
        },
        "clusters": clusters,
        "kanjiIndex": kanji_index,
        "entries": entries,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "lexicon-data.js"
    json_text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    output_path.write_text(f"window.LEXICON_DATA = {json_text};\n", encoding="utf-8")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    output_path = export_data(args.input_dir, args.output_dir)
    print(output_path)


if __name__ == "__main__":
    main()

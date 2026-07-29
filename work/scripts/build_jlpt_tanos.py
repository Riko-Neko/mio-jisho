#!/usr/bin/env python3
"""Build JLPT reference-level match reports from Tanos Mnemosyne files."""

from __future__ import annotations

import argparse
import csv
import json
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path


LEVEL_ORDER = {"N5": 0, "N4": 1, "N3": 2, "N2": 3, "N1": 4}
TANOS_SOURCE = "Tanos JLPT / CC BY"
TANOS_PAGE = "https://www.tanos.co.uk/jlpt/skills/vocab/"
ITEM_RE = re.compile(r"\(imnemosyne\.core\.mnemosyne_core\s+Item\s+p\d+\s+\(dp\d+(.*?)(?=\nsba|\nssba)", re.S)
FIELD_RE = re.compile(r"(?:^|\n)s?S'([aq])'\s*\nV(.*?)\np\d+", re.S)
CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
KANA_RE = re.compile(r"^[\u3040-\u30ffー・]+$")


@dataclass(frozen=True)
class Candidate:
    level: str
    writing: str
    reading: str
    meaning: str
    source_file: str
    source_url: str


def clean(value: str | None) -> str:
    return (value or "").strip()


def split_semicolon(value: str | None) -> list[str]:
    return [part.strip() for part in clean(value).split("；") if part.strip()]


def unique(seq):
    seen = set()
    out = []
    for item in seq:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def katakana_to_hiragana(text: str) -> str:
    out = []
    for ch in text:
        code = ord(ch)
        if 0x30A1 <= code <= 0x30F6:
            out.append(chr(code - 0x60))
        else:
            out.append(ch)
    return "".join(out)


def normalize_japanese(text: str) -> str:
    text = unicodedata.normalize("NFKC", clean(text))
    text = re.sub(r"\s+", "", text)
    return katakana_to_hiragana(text)


def is_kana(text: str) -> bool:
    return bool(text) and bool(KANA_RE.match(normalize_japanese(text)))


def reading_like(text: str) -> bool:
    value = normalize_japanese(text)
    return bool(value) and bool(KANA_RE.match(value))


def has_kanji(text: str) -> bool:
    return bool(CJK_RE.search(text))


def decode_pickle_string(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith('"') and raw.endswith('"'):
        raw = raw[1:-1]
    return bytes(raw, "utf-8").decode("unicode_escape")


def parse_mem(path: Path) -> list[dict[str, str]]:
    text = path.read_text(encoding="ascii", errors="replace")
    rows = []
    for item_match in ITEM_RE.finditer(text):
        fields = {}
        for key, raw_value in FIELD_RE.findall(item_match.group(1)):
            fields[key] = decode_pickle_string(raw_value)
        if fields.get("q") and fields.get("a"):
            rows.append({"q": fields["q"], "a": fields["a"]})
    return rows


def expand_writing_variants(raw: str) -> list[str]:
    variants = []
    for part in re.split(r"[\/／]|\s{2,}", clean(raw)):
        part = part.strip()
        if not part:
            continue
        variants.append(part.replace("・", ""))
        if part.startswith(("お・", "ご・")):
            variants.append(part[2:].replace("・", ""))
    return unique(variants)


def expand_reading_variants(raw: str, writing: str) -> list[str]:
    value = clean(raw)
    value = re.sub(r"[（(][^）)]*[）)]", "", value).strip()
    if not value and reading_like(writing):
        value = writing
    variants = []
    for part in re.split(r"[\/／,，、]|\s+", value):
        part = part.strip()
        if reading_like(part):
            variants.append(part)
    if not variants and reading_like(writing):
        variants.append(writing)
    return unique(variants)


def read_tanos_candidates(data_dir: Path) -> list[Candidate]:
    candidates: list[Candidate] = []
    for level in ["N5", "N4", "N3", "N2", "N1"]:
        prefix = level.lower()
        kana_path = data_dir / f"{prefix}-vocab-kanji-hiragana.mem"
        eng_path = data_dir / f"{prefix}-vocab-kanji-eng.mem"
        kana_rows = parse_mem(kana_path)
        eng_by_q: dict[str, str] = {}
        if eng_path.exists():
            for row in parse_mem(eng_path):
                eng_by_q.setdefault(normalize_japanese(row["q"]), row["a"])
        source_url = f"https://www.tanos.co.uk/jlpt/jlpt{level[-1]}/vocab/{prefix}-vocab-kanji-hiragana.mem"
        for row in kana_rows:
            raw_writing = clean(row["q"])
            if not raw_writing:
                continue
            meaning = eng_by_q.get(normalize_japanese(raw_writing), "")
            for writing in expand_writing_variants(raw_writing):
                readings = expand_reading_variants(row["a"], writing)
                for reading in readings:
                    candidates.append(
                        Candidate(
                            level=level,
                            writing=writing,
                            reading=reading,
                            meaning=meaning,
                            source_file=kana_path.name,
                            source_url=source_url,
                        )
                )

    by_key: dict[tuple[str, str], Candidate] = {}
    duplicate_sources: defaultdict[tuple[str, str], list[Candidate]] = defaultdict(list)
    for cand in candidates:
        key = (normalize_japanese(cand.writing), normalize_japanese(cand.reading))
        duplicate_sources[key].append(cand)
        old = by_key.get(key)
        if old is None or LEVEL_ORDER[cand.level] < LEVEL_ORDER[old.level]:
            by_key[key] = cand

    merged = []
    for key, cand in by_key.items():
        levels = unique([item.level for item in duplicate_sources[key]])
        if len(levels) > 1:
            meaning = cand.meaning
            merged.append(
                Candidate(
                    level=cand.level,
                    writing=cand.writing,
                    reading=cand.reading,
                    meaning=meaning,
                    source_file=";".join(unique([item.source_file for item in duplicate_sources[key]])),
                    source_url=TANOS_PAGE,
                )
            )
        else:
            merged.append(cand)
    merged.sort(key=lambda c: (LEVEL_ORDER[c.level], normalize_japanese(c.reading), normalize_japanese(c.writing)))
    return merged


def read_master(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def build_indexes(rows: list[dict[str, str]]):
    pair_index = defaultdict(list)
    word_index = defaultdict(list)
    reading_index = defaultdict(list)
    for row in rows:
        writings = unique([row.get("表记", "")] + split_semicolon(row.get("全部表记")))
        readings = unique([row.get("读音", "")] + split_semicolon(row.get("全部读音")))
        norm_writings = unique([normalize_japanese(item) for item in writings])
        norm_readings = unique([normalize_japanese(item) for item in readings])
        for writing in norm_writings:
            word_index[writing].append(row)
            for reading in norm_readings:
                pair_index[(writing, reading)].append(row)
        for reading in norm_readings:
            reading_index[reading].append(row)
    return pair_index, word_index, reading_index


def classify_match(candidate: Candidate, pair_index, word_index, reading_index):
    writing_key = normalize_japanese(candidate.writing)
    reading_key = normalize_japanese(candidate.reading)
    pair_hits = pair_index.get((writing_key, reading_key), [])
    if pair_hits:
        rule = "exact_writing_reading"
        confidence = "high" if len(pair_hits) == 1 else "ambiguous"
        return rule, confidence, pair_hits

    if is_kana(candidate.writing):
        reading_hits = reading_index.get(reading_key, [])
        same_surface_hits = [
            row
            for row in reading_hits
            if normalize_japanese(row.get("表记", "")) == writing_key
            or writing_key in [normalize_japanese(item) for item in split_semicolon(row.get("全部表记"))]
        ]
        if same_surface_hits:
            rule = "exact_kana_surface_reading"
            confidence = "high" if len(same_surface_hits) == 1 else "ambiguous"
            return rule, confidence, same_surface_hits
        if len(reading_hits) == 1:
            return "reading_only_unique", "medium", reading_hits
        if reading_hits:
            return "reading_only_multiple", "ambiguous", reading_hits

    word_hits = word_index.get(writing_key, [])
    if len(word_hits) == 1:
        return "writing_only_unique", "low", word_hits
    if word_hits:
        return "writing_only_multiple", "ambiguous", word_hits
    return "unmatched", "none", []


def write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def emit_reports(candidates: list[Candidate], master_rows: list[dict[str, str]], out_dir: Path) -> dict[str, object]:
    pair_index, word_index, reading_index = build_indexes(master_rows)
    candidate_rows = []
    match_rows = []
    ambiguous_rows = []
    unmatched_rows = []
    per_level = Counter()
    match_level = Counter()
    auto_match_level = Counter()
    confidence_counts = Counter()
    rule_counts = Counter()
    matched_entry_levels: defaultdict[str, list[tuple[str, str]]] = defaultdict(list)

    for cand in candidates:
        per_level[cand.level] += 1
        base = {
            "JLPT等级": cand.level,
            "表记": cand.writing,
            "读音": cand.reading,
            "英文义": cand.meaning,
            "来源": TANOS_SOURCE,
            "来源文件": cand.source_file,
            "来源URL": cand.source_url,
            "备注": "非官方参考等级；如同词多等级重复，保留较低等级",
        }
        candidate_rows.append(base)
        rule, confidence, hits = classify_match(cand, pair_index, word_index, reading_index)
        confidence_counts[confidence] += 1
        rule_counts[rule] += 1
        if confidence == "none":
            unmatched_rows.append({**base, "匹配规则": rule})
            continue
        target = ambiguous_rows if confidence == "ambiguous" else match_rows
        if confidence != "ambiguous":
            match_level[cand.level] += 1
        if confidence in {"high", "medium"}:
            auto_match_level[cand.level] += 1
        for row in hits:
            out = {
                **base,
                "匹配规则": rule,
                "置信度": confidence,
                "词条ID": row.get("词条ID", ""),
                "词典表记": row.get("表记", ""),
                "词典读音": row.get("读音", ""),
                "ABC等级": row.get("等级", ""),
                "大类": row.get("大类", ""),
                "英文释义摘录": row.get("英文释义摘录", ""),
            }
            target.append(out)
            if confidence in {"high", "medium"}:
                matched_entry_levels[row.get("词条ID", "")].append((cand.level, confidence))

    preview_rows = []
    for row in master_rows:
        levels = matched_entry_levels.get(row.get("词条ID", ""), [])
        if not levels:
            continue
        levels.sort(key=lambda item: (LEVEL_ORDER[item[0]], item[1]))
        best_level, best_confidence = levels[0]
        preview_rows.append(
            {
                "词条ID": row.get("词条ID", ""),
                "表记": row.get("表记", ""),
                "读音": row.get("读音", ""),
                "ABC等级": row.get("等级", ""),
                "JLPT参考等级": best_level,
                "JLPT置信度": best_confidence,
                "JLPT来源": TANOS_SOURCE,
                "JLPT备注": "非官方参考等级",
            }
        )

    write_csv(
        out_dir / "jlpt_tanos_candidates.csv",
        candidate_rows,
        ["JLPT等级", "表记", "读音", "英文义", "来源", "来源文件", "来源URL", "备注"],
    )
    report_fields = [
        "JLPT等级",
        "表记",
        "读音",
        "英文义",
        "来源",
        "来源文件",
        "来源URL",
        "备注",
        "匹配规则",
        "置信度",
        "词条ID",
        "词典表记",
        "词典读音",
        "ABC等级",
        "大类",
        "英文释义摘录",
    ]
    write_csv(out_dir / "jlpt_tanos_matches.csv", match_rows, report_fields)
    write_csv(out_dir / "jlpt_tanos_ambiguous.csv", ambiguous_rows, report_fields)
    write_csv(out_dir / "jlpt_tanos_unmatched.csv", unmatched_rows, ["JLPT等级", "表记", "读音", "英文义", "来源", "来源文件", "来源URL", "备注", "匹配规则"])
    write_csv(
        out_dir / "jlpt_tanos_entry_preview.csv",
        preview_rows,
        ["词条ID", "表记", "读音", "ABC等级", "JLPT参考等级", "JLPT置信度", "JLPT来源", "JLPT备注"],
    )

    summary = {
        "source": TANOS_SOURCE,
        "source_page": TANOS_PAGE,
        "notes": [
            "JLPT 官方当前不发布词汇表，本结果只作为非官方参考等级。",
            "主匹配以 Tanos 表记+读音 对 master_lexicon 的 全部表记+全部读音 精确匹配为 high。",
            "kana-only reading-only unique 为 medium；writing-only 为 low，仅入报告不建议自动写回。",
        ],
        "candidates_total": len(candidate_rows),
        "candidates_by_level": dict(sorted(per_level.items(), key=lambda item: LEVEL_ORDER[item[0]])),
        "matches_rows_non_ambiguous": len(match_rows),
        "matches_high_medium_rows": sum(confidence_counts[level] for level in ("high", "medium")),
        "matched_entries_high_medium": len(matched_entry_levels),
        "ambiguous_rows": len(ambiguous_rows),
        "unmatched_candidates": len(unmatched_rows),
        "matches_by_level_non_ambiguous": dict(sorted(match_level.items(), key=lambda item: LEVEL_ORDER[item[0]])),
        "matches_by_level_high_medium": dict(sorted(auto_match_level.items(), key=lambda item: LEVEL_ORDER[item[0]])),
        "confidence_counts": dict(confidence_counts.most_common()),
        "rule_counts": dict(rule_counts.most_common()),
        "outputs": [
            "jlpt_tanos_candidates.csv",
            "jlpt_tanos_matches.csv",
            "jlpt_tanos_ambiguous.csv",
            "jlpt_tanos_unmatched.csv",
            "jlpt_tanos_entry_preview.csv",
            "jlpt_tanos_summary.json",
        ],
    }
    (out_dir / "jlpt_tanos_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("work/data/jlpt_tanos"))
    parser.add_argument("--master", type=Path, default=Path("work/build/master_lexicon.csv"))
    parser.add_argument("--out-dir", type=Path, default=Path("work/build"))
    args = parser.parse_args()

    candidates = read_tanos_candidates(args.data_dir)
    master_rows = read_master(args.master)
    summary = emit_reports(candidates, master_rows, args.out_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

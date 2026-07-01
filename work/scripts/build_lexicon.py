#!/usr/bin/env python3
"""Build an auditable A+B+C modern Japanese lexicon from public dictionary data.

Primary input is JMdict because it provides machine-readable headwords,
readings, parts of speech, commonness priority tags, transitivity labels, and
archaic/dialect/rare flags. KANJIDIC2 is optional and adds kanji reading data for
the noun kanji tree.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import re
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree as etree

JMDICT_SOURCE_URL = "http://ftp.edrdg.org/pub/Nihongo/JMdict_e.gz"
KANJIDIC2_SOURCE_URL = "http://ftp.edrdg.org/pub/Nihongo/kanjidic2.xml.gz"
BCCWJ_SOURCE_URL = "https://repository.ninjal.ac.jp/record/3234/files/BCCWJ_frequencylist_suw_ver1_0.zip"
TRANSLATION_POLICY = "DeepSeek V4 Flash 翻译（基于 JMdict/EDRDG 英文释义；待抽样复核）"

CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
KANA_RE = re.compile(r"^[\u3040-\u30ffー・]+$")
XML_LANG_ATTR = "{http://www.w3.org/XML/1998/namespace}lang"


POS_LABELS = {
    "adj-i": "adjective (keiyoushi)",
    "adj-ix": "adjective (keiyoushi) - yoi/ii class",
    "adj-na": "adjectival nouns or quasi-adjectives (keiyodoshi)",
    "adj-no": "nouns which may take the genitive case particle 'no'",
    "adj-pn": "pre-noun adjectival (rentaishi)",
    "adj-t": "'taru' adjective",
    "adv": "adverb",
    "aux": "auxiliary",
    "aux-v": "auxiliary verb",
    "cop": "copula",
    "ctr": "counter",
    "exp": "expressions (phrases, clauses, etc.)",
    "int": "interjection",
    "n": "noun",
    "n-adv": "adverbial noun",
    "n-pr": "proper noun",
    "n-pref": "noun, used as a prefix",
    "n-suf": "noun, used as a suffix",
    "n-t": "noun (temporal)",
    "num": "numeric",
    "pn": "pronoun",
    "pref": "prefix",
    "prt": "particle",
    "suf": "suffix",
    "unc": "unclassified",
    "v1": "Ichidan verb",
    "v5": "Godan verb",
    "vs": "suru verb",
    "vi": "intransitive verb",
    "vt": "transitive verb",
    "vk": "Kuru verb",
    "vz": "Ichidan verb - zuru verb",
}

EXCLUDE_MISC_FRAGMENTS = {
    "archaism",
    "archaic",
    "obsolete",
    "obscure",
    "rare",
    "dated term",
    "historical term",
}

EXCLUDE_POS_FRAGMENTS = {
    "proper noun",
    "unclassified name",
    "company name",
    "place name",
    "product name",
    "person",
    "given name",
    "surname",
}

EXCLUDE_FIELDS = {
    "Buddhist term",
    "Christian term",
}

POS_PREFIXES = {
    "noun": ["noun", "pronoun", "numeric"],
    "verb": ["verb", "suru verb", "Kuru verb"],
    "i_adjective": ["adjective (keiyoushi)", "yoi/ii class"],
    "na_adjective": ["adjectival nouns", "'taru' adjective"],
}


@dataclass
class Entry:
    ent_seq: str
    headword: str
    reading: str
    all_writings: list[str]
    all_readings: list[str]
    priority_tags: list[str]
    pos: list[str]
    misc: list[str]
    fields: list[str]
    glosses: list[str]
    level: str
    major_pos: str
    transitivity: str
    conjugation: str
    cluster: str
    related_candidate: str = ""
    kanji_chars: list[str] = field(default_factory=list)
    bccwj_rank: str = ""
    bccwj_frequency: str = ""
    bccwj_pmw: str = ""
    bccwj_pos: str = ""


def text_list(parent, path: str) -> list[str]:
    return [str(x.text).strip() for x in parent.findall(path) if x.text and str(x.text).strip()]


def xml_lang(elem) -> str | None:
    return elem.get(XML_LANG_ATTR) or elem.get("xml:lang")


def normalize_label(value: str) -> str:
    value = value.strip()
    return POS_LABELS.get(value, value)


def unique(seq: Iterable[str]) -> list[str]:
    seen = set()
    out = []
    for item in seq:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def priority_level(tags: Iterable[str]) -> str:
    tags = set(tags)
    if not tags:
        return ""
    if tags & {"ichi1", "news1", "spec1", "gai1"}:
        return "A"
    nf_ranks = []
    for tag in tags:
        if tag.startswith("nf") and tag[2:].isdigit():
            nf_ranks.append(int(tag[2:]))
    if nf_ranks and min(nf_ranks) <= 10:
        return "A"
    if tags & {"ichi2", "news2", "spec2", "gai2"}:
        return "B"
    if nf_ranks and min(nf_ranks) <= 32:
        return "B"
    return "C"


def katakana_to_hiragana(text: str) -> str:
    chars = []
    for ch in text:
        code = ord(ch)
        if 0x30A1 <= code <= 0x30F6:
            chars.append(chr(code - 0x60))
        else:
            chars.append(ch)
    return "".join(chars)


def bccwj_level(rank: str) -> str:
    if not rank:
        return ""
    try:
        value = int(rank)
    except ValueError:
        return ""
    if value <= 5000:
        return "A"
    if value <= 30000:
        return "B"
    return "C"


def parse_bccwj(path: Path | None) -> dict[str, dict[str, str]]:
    if not path or not path.exists():
        return {}
    best: dict[str, dict[str, str]] = {}
    with zipfile.ZipFile(path) as zf:
        names = [name for name in zf.namelist() if name.endswith(".tsv")]
        if not names:
            return {}
        with zf.open(names[0]) as raw:
            header = raw.readline().decode("utf-8").rstrip("\n").split("\t")
            idx = {name: i for i, name in enumerate(header)}
            for raw_line in raw:
                row = raw_line.decode("utf-8").rstrip("\n").split("\t")
                try:
                    rank = int(row[idx["rank"]])
                except (ValueError, KeyError, IndexError):
                    continue
                if rank > 50000:
                    break
                record = {
                    "rank": str(rank),
                    "lemma": row[idx["lemma"]],
                    "lForm": row[idx["lForm"]],
                    "pos": row[idx["pos"]],
                    "frequency": row[idx["frequency"]],
                    "pmw": row[idx["pmw"]],
                }
                keys = {record["lemma"], record["lForm"], katakana_to_hiragana(record["lForm"])}
                for key in {k for k in keys if k}:
                    old = best.get(key)
                    if old is None or rank < int(old["rank"]):
                        best[key] = record
    return best


def lookup_bccwj(index: dict[str, dict[str, str]], headword: str, writings: list[str], readings: list[str]) -> dict[str, str]:
    if not index:
        return {}
    has_written_kanji = CJK_RE.search(headword) or any(CJK_RE.search(w) for w in writings)
    if has_written_kanji:
        keys = unique([headword] + writings)
    else:
        keys = unique([headword] + writings + readings + [katakana_to_hiragana(r) for r in readings])
    hits = [index[key] for key in keys if key in index]
    if has_written_kanji and readings:
        hits = [record for record in hits if katakana_to_hiragana(record.get("lForm", "")) in readings]
    if not hits:
        return {}
    return sorted(hits, key=lambda record: int(record["rank"]))[0]


def bccwj_pos_compatible(major_pos: str, bccwj_pos: str) -> bool:
    if not bccwj_pos:
        return False
    if major_pos == "动词":
        return "動詞" in bccwj_pos
    if major_pos == "一类形容词":
        return "形容詞" in bccwj_pos
    if major_pos == "二类形容词":
        return "形状詞" in bccwj_pos or "名詞" in bccwj_pos
    if major_pos == "名词":
        return "名詞" in bccwj_pos or "接頭辞" in bccwj_pos or "接尾辞" in bccwj_pos
    return False


def has_excluded_label(labels: Iterable[str], fragments: set[str]) -> bool:
    joined = " | ".join(labels).lower()
    return any(fragment.lower() in joined for fragment in fragments)


def classify_major_pos(pos: list[str]) -> str:
    joined = " | ".join(pos)
    if any(label in joined for label in POS_PREFIXES["i_adjective"]):
        return "一类形容词"
    if any(label in joined for label in POS_PREFIXES["na_adjective"]):
        return "二类形容词"
    if "verb" in joined or "Kuru verb" in joined:
        return "动词"
    if "noun" in joined or "pronoun" in joined or "numeric" in joined:
        return "名词"
    return ""


def classify_transitivity(pos: list[str]) -> str:
    joined = " | ".join(pos)
    is_vi = "intransitive verb" in joined
    is_vt = "transitive verb" in joined
    if is_vi and is_vt:
        return "自他両用"
    if is_vi:
        return "自动词"
    if is_vt:
        return "他动词"
    return ""


def classify_conjugation(pos: list[str], major_pos: str) -> str:
    joined = " | ".join(pos)
    if major_pos != "动词":
        return ""
    if "Ichidan" in joined:
        return "一段"
    if "Godan" in joined:
        return "五段"
    if "suru verb" in joined:
        return "サ変"
    if "Kuru verb" in joined:
        return "カ変"
    if "zuru verb" in joined:
        return "ザ変"
    return "动词"


def kana_tail(text: str, tail: str) -> bool:
    return text.endswith(tail)


def classify_cluster(headword: str, reading: str, major_pos: str, conjugation: str) -> str:
    basis = reading or headword
    surface = headword or reading
    if major_pos == "动词":
        if basis.endswith("する") or surface.endswith("する"):
            return "サ変：名词/汉语 + する"
        compound_tails = [
            "込む",
            "こむ",
            "出す",
            "だす",
            "上げる",
            "あげる",
            "上がる",
            "あがる",
            "下げる",
            "さげる",
            "下がる",
            "さがる",
            "切る",
            "きる",
            "直す",
            "なおす",
            "合う",
            "あう",
            "始める",
            "はじめる",
            "続ける",
            "つづける",
            "終える",
            "おえる",
            "終わる",
            "おわる",
            "返す",
            "かえす",
            "返る",
            "かえる",
            "付ける",
            "つける",
            "付く",
            "つく",
        ]
        for tail in compound_tails:
            if surface.endswith(tail) or basis.endswith(tail):
                return f"复合动词后项：-{tail}"
        pair_tails = [
            ("まる", "自他形态：-まる / -める"),
            ("める", "自他形态：-まる / -める"),
            ("がる", "自他形态：-がる / -げる"),
            ("げる", "自他形态：-がる / -げる"),
            ("れる", "自他形态：-れる / -す"),
            ("す", "自他形态：-れる/-る / -す"),
            ("える", "自他形态：-える / -やす等"),
            ("やす", "自他形态：-える / -やす"),
            ("つ", "自他形态：-つ / -てる"),
            ("てる", "自他形态：-つ / -てる"),
            ("ぶ", "自他形态：-ぶ / -べる"),
            ("べる", "自他形态：-ぶ / -べる"),
            ("む", "自他形态：-む / -める"),
            ("く", "自他形态：-く / -ける"),
            ("ける", "自他形态：-く / -ける"),
        ]
        for tail, label in pair_tails:
            if basis.endswith(tail):
                return label
        return f"活用类：{conjugation or '动词'}"
    if major_pos == "一类形容词":
        tails = ["らしい", "っぽい", "しい", "ない", "たい", "づらい", "にくい", "やすい"]
        for tail in tails:
            if basis.endswith(tail):
                return f"い形容词后缀：-{tail}"
        return "い形容词基本类"
    if major_pos == "二类形容词":
        if surface.endswith("的"):
            return "ナ形容词：汉语/名词 + 的"
        for tail in ["やか", "らか", "げ", "そう", "か"]:
            if basis.endswith(tail) or surface.endswith(tail):
                return f"ナ形容词后缀：-{tail}"
        return "ナ形容词基本类"
    if major_pos == "名词":
        if KANA_RE.match(surface):
            return "假名名词"
        if CJK_RE.search(surface):
            return "汉字名词"
        return "外来语/其他名词"
    return ""


def extract_kanji(text: str) -> list[str]:
    return unique(CJK_RE.findall(text))


def choose_headword(k_ele, r_ele) -> tuple[str, list[str], list[str], list[str]]:
    writings = [k.findtext("keb").strip() for k in k_ele if k.findtext("keb")]
    readings = [r.findtext("reb").strip() for r in r_ele if r.findtext("reb")]
    pri = []
    for k in k_ele:
        pri.extend(text_list(k, "ke_pri"))
    for r in r_ele:
        pri.extend(text_list(r, "re_pri"))
    if writings:
        tagged = []
        for keb in writings:
            score = 0
            for k in k_ele:
                if k.findtext("keb") == keb:
                    score += sum(10 for p in text_list(k, "ke_pri") if p.endswith("1"))
                    score += sum(5 for p in text_list(k, "ke_pri") if p.endswith("2"))
                    score += sum(1 for p in text_list(k, "ke_pri") if p.startswith("nf"))
            tagged.append((score, keb))
        headword = sorted(tagged, key=lambda x: (-x[0], len(x[1]), x[1]))[0][1]
    elif readings:
        headword = readings[0]
    else:
        headword = ""
    return headword, writings, readings, unique(pri)


def parse_jmdict(path: Path, bccwj_index: dict[str, dict[str, str]]) -> tuple[list[Entry], dict[str, int], list[dict[str, str]]]:
    entries: list[Entry] = []
    stats = Counter()
    rejected_samples: list[dict[str, str]] = []

    with gzip.open(path, "rb") as fh:
        context = etree.iterparse(fh, events=("end",))
        for _, elem in context:
            if elem.tag != "entry":
                continue
            stats["jmdict_entries_seen"] += 1
            ent_seq = elem.findtext("ent_seq") or ""
            k_ele = elem.findall("k_ele")
            r_ele = elem.findall("r_ele")
            headword, writings, readings, priority_tags = choose_headword(k_ele, r_ele)
            bccwj_hit = lookup_bccwj(bccwj_index, headword, writings, readings)
            priority_based_level = priority_level(priority_tags)
            bccwj_based_level = bccwj_level(bccwj_hit.get("rank", ""))
            level = priority_based_level if priority_based_level in {"A", "B", "C"} else bccwj_based_level
            if level not in {"A", "B", "C"}:
                stats["rejected_no_abc_evidence"] += 1
                if len(rejected_samples) < 100:
                    rejected_samples.append(
                        {
                            "ent_seq": ent_seq,
                            "headword": headword,
                            "reason": "no_A_B_C_priority_or_bccwj_evidence",
                            "priority_tags": ";".join(priority_tags),
                            "bccwj_rank": bccwj_hit.get("rank", ""),
                        }
                    )
                elem.clear()
                continue

            senses = elem.findall("sense")
            sense_pos = []
            sense_misc = []
            sense_dial = []
            sense_fields = []
            glosses = []
            for sense in senses:
                pos = [normalize_label(x) for x in text_list(sense, "pos")]
                misc = [normalize_label(x) for x in text_list(sense, "misc")]
                dial = [normalize_label(x) for x in text_list(sense, "dial")]
                fields = [normalize_label(x) for x in text_list(sense, "field")]
                # Keep English glosses compact; they are audit hints, not the target output.
                gl = [x.text.strip() for x in sense.findall("gloss") if x.text and xml_lang(x) in (None, "eng")]
                if has_excluded_label(misc, EXCLUDE_MISC_FRAGMENTS) or dial:
                    continue
                sense_pos.extend(pos)
                sense_misc.extend(misc)
                sense_dial.extend(dial)
                sense_fields.extend(fields)
                glosses.extend(gl[:3])

            pos = unique(sense_pos)
            misc = unique(sense_misc)
            fields = unique(sense_fields)
            if not pos:
                stats["rejected_all_senses_excluded"] += 1
                elem.clear()
                continue
            if has_excluded_label(fields, EXCLUDE_FIELDS):
                stats["rejected_specialized_field"] += 1
                elem.clear()
                continue

            major_pos = classify_major_pos(pos)
            if not major_pos and has_excluded_label(pos, EXCLUDE_POS_FRAGMENTS):
                major_pos = "名词"
            if major_pos not in {"动词", "一类形容词", "二类形容词", "名词"}:
                stats["rejected_out_of_requested_pos"] += 1
                elem.clear()
                continue
            if (
                priority_based_level not in {"A", "B", "C"}
                and bccwj_based_level in {"A", "B", "C"}
                and not bccwj_pos_compatible(major_pos, bccwj_hit.get("pos", ""))
            ):
                stats["rejected_bccwj_pos_mismatch"] += 1
                elem.clear()
                continue
            if "counter" in " | ".join(pos).lower() and major_pos == "名词":
                stats["rejected_counter"] += 1
                elem.clear()
                continue

            reading = readings[0] if readings else ""
            transitivity = classify_transitivity(pos) if major_pos == "动词" else ""
            conjugation = classify_conjugation(pos, major_pos)
            cluster = classify_cluster(headword, reading, major_pos, conjugation)

            entries.append(
                Entry(
                    ent_seq=ent_seq,
                    headword=headword,
                    reading=reading,
                    all_writings=writings,
                    all_readings=readings,
                    priority_tags=priority_tags,
                    pos=pos,
                    misc=misc,
                    fields=fields,
                    glosses=unique(glosses)[:5],
                    level=level,
                    major_pos=major_pos,
                    transitivity=transitivity,
                    conjugation=conjugation,
                    cluster=cluster,
                    kanji_chars=extract_kanji(headword),
                    bccwj_rank=bccwj_hit.get("rank", ""),
                    bccwj_frequency=bccwj_hit.get("frequency", ""),
                    bccwj_pmw=bccwj_hit.get("pmw", ""),
                    bccwj_pos=bccwj_hit.get("pos", ""),
                )
            )
            stats[f"accepted_{major_pos}"] += 1
            stats[f"accepted_level_{level}"] += 1
            if bccwj_hit:
                stats["accepted_with_bccwj_match"] += 1
            if priority_based_level not in {"A", "B", "C"} and bccwj_based_level in {"A", "B", "C"}:
                stats["accepted_by_bccwj_rank_only"] += 1
            elem.clear()
    stats["accepted_total"] = len(entries)
    return entries, dict(stats), rejected_samples


def parse_kanjidic2(path: Path | None) -> dict[str, dict[str, str]]:
    if not path or not path.exists():
        return {}
    out: dict[str, dict[str, str]] = {}
    with gzip.open(path, "rb") as fh:
        context = etree.iterparse(fh, events=("end",))
        for _, elem in context:
            if elem.tag != "character":
                continue
            literal = elem.findtext("literal") or ""
            if not literal:
                elem.clear()
                continue
            grade = elem.findtext("misc/grade") or ""
            is_joyo = grade in {"1", "2", "3", "4", "5", "6", "8"}
            readings_on = []
            readings_kun = []
            for reading in elem.findall("reading_meaning/rmgroup/reading"):
                r_type = reading.get("r_type")
                if r_type == "ja_on" and reading.text:
                    readings_on.append(reading.text)
                elif r_type == "ja_kun" and reading.text:
                    readings_kun.append(reading.text)
            out[literal] = {
                "grade": grade,
                "joyo": "常用漢字" if is_joyo else "",
                "on": "、".join(unique(readings_on)),
                "kun": "、".join(unique(readings_kun)),
            }
            elem.clear()
    return out


def build_transitive_candidates(entries: list[Entry]) -> None:
    by_reading = defaultdict(list)
    for e in entries:
        if e.major_pos == "动词" and e.reading:
            by_reading[e.reading].append(e)

    transforms = [
        ("まる", "める"),
        ("める", "まる"),
        ("がる", "げる"),
        ("げる", "がる"),
        ("れる", "す"),
        ("る", "す"),
        ("える", "やす"),
        ("やす", "える"),
        ("つ", "てる"),
        ("てる", "つ"),
        ("ぶ", "べる"),
        ("べる", "ぶ"),
        ("む", "める"),
        ("く", "ける"),
        ("ける", "く"),
    ]
    for e in entries:
        if e.major_pos != "动词" or not e.reading:
            continue
        candidates = []
        for src, dst in transforms:
            if e.reading.endswith(src):
                cand_reading = e.reading[: -len(src)] + dst
                for other in by_reading.get(cand_reading, []):
                    if other.ent_seq != e.ent_seq and other.transitivity and other.transitivity != e.transitivity:
                        candidates.append(f"{other.headword}（{other.reading}）")
        e.related_candidate = "；".join(unique(candidates)[:5])


def write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def read_translation_overrides(path: Path | None) -> dict[str, dict[str, str]]:
    if not path:
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = csv.DictReader(handle, delimiter="\t")
        return {
            row["词条ID"].strip(): {
                "中文翻译": row.get("中文翻译", "").strip(),
                "翻译来源": row.get("翻译来源", "").strip(),
            }
            for row in rows
            if row.get("词条ID") and row.get("中文翻译")
        }


def entry_to_row(e: Entry, translation_overrides: dict[str, dict[str, str]]) -> dict[str, object]:
    translation = translation_overrides.get(e.ent_seq, {})
    return {
        "词条ID": e.ent_seq,
        "等级": e.level,
        "表记": e.headword,
        "读音": e.reading,
        "大类": e.major_pos,
        "细品词": "；".join(e.pos),
        "自他": e.transitivity,
        "活用": e.conjugation,
        "词群": e.cluster,
        "自他对应候补": e.related_candidate,
        "核心汉字": "；".join(e.kanji_chars),
        "全部表记": "；".join(e.all_writings),
        "全部读音": "；".join(e.all_readings),
        "常用度标签": "；".join(e.priority_tags),
        "英文释义摘录": "；".join(e.glosses),
        "中文翻译": translation.get("中文翻译", ""),
        "翻译来源": translation.get("翻译来源", ""),
        "BCCWJ_rank": e.bccwj_rank,
        "BCCWJ_frequency": e.bccwj_frequency,
        "BCCWJ_pmw": e.bccwj_pmw,
        "BCCWJ_pos": e.bccwj_pos,
        "来源": "JMdict/EDRDG",
        "来源URL": JMDICT_SOURCE_URL,
        "复核状态": "机器抽取-待抽样复核",
    }


def emit_outputs(
    entries: list[Entry],
    kanji_info: dict[str, dict[str, str]],
    out_dir: Path,
    stats: dict[str, int],
    rejected_samples: list[dict[str, str]],
    translation_overrides: dict[str, dict[str, str]],
) -> None:
    build_transitive_candidates(entries)
    entries.sort(key=lambda e: (e.major_pos, e.level, e.reading or e.headword, e.headword))

    master_fields = [
        "词条ID",
        "等级",
        "表记",
        "读音",
        "大类",
        "细品词",
        "自他",
        "活用",
        "词群",
        "自他对应候补",
        "核心汉字",
        "全部表记",
        "全部读音",
        "常用度标签",
        "英文释义摘录",
        "中文翻译",
        "翻译来源",
        "BCCWJ_rank",
        "BCCWJ_frequency",
        "BCCWJ_pmw",
        "BCCWJ_pos",
        "来源",
        "来源URL",
        "复核状态",
    ]
    master_rows = [entry_to_row(e, translation_overrides) for e in entries]
    write_csv(out_dir / "master_lexicon.csv", master_rows, master_fields)

    verbs = [entry_to_row(e, translation_overrides) for e in entries if e.major_pos == "动词"]
    write_csv(out_dir / "verbs_by_transitivity.csv", verbs, master_fields)

    adjectives = [
        entry_to_row(e, translation_overrides)
        for e in entries
        if e.major_pos in {"一类形容词", "二类形容词"}
    ]
    write_csv(out_dir / "adjective_clusters.csv", adjectives, master_fields)

    noun_tree_rows = []
    for e in entries:
        if e.major_pos != "名词" or not e.kanji_chars:
            continue
        for idx, ch in enumerate(e.kanji_chars):
            info = kanji_info.get(ch, {})
            noun_tree_rows.append(
                {
                    "核心汉字": ch,
                    "汉字状态": info.get("joyo", ""),
                    "音读": info.get("on", ""),
                    "训读": info.get("kun", ""),
                    "树路径": f"{ch} > {info.get('on') or info.get('kun') or '读音待核'} > {e.headword}",
                    "关联词": e.headword,
                    "单词读音": e.reading,
                    "等级": e.level,
                    "关系": "主节点" if idx == 0 else "包含",
                    "词条ID": e.ent_seq,
                    "来源": "JMdict/EDRDG；KANJIDIC2/EDRDG" if kanji_info else "JMdict/EDRDG",
                }
            )
    noun_tree_fields = ["核心汉字", "汉字状态", "音读", "训读", "树路径", "关联词", "单词读音", "等级", "关系", "词条ID", "来源"]
    write_csv(out_dir / "noun_kanji_tree.csv", noun_tree_rows, noun_tree_fields)

    cluster_counter = Counter((e.major_pos, e.cluster) for e in entries)
    cluster_rows = [
        {"大类": major, "词群": cluster, "词条数": count}
        for (major, cluster), count in sorted(cluster_counter.items(), key=lambda x: (x[0][0], -x[1], x[0][1]))
    ]
    write_csv(out_dir / "cluster_summary.csv", cluster_rows, ["大类", "词群", "词条数"])

    audit_rows = [
        {"项目": key, "数量": value, "说明": ""}
        for key, value in sorted(stats.items())
    ]
    audit_rows.extend(
        {
            "项目": "rejected_sample",
            "数量": "",
            "说明": json.dumps(sample, ensure_ascii=False),
        }
        for sample in rejected_samples
    )
    audit_rows.extend(
        [
            {
                "项目": "source_policy",
                "数量": "",
                "说明": "A+B+C 使用 JMdict priority tags 与 BCCWJ rank 证据；C 类限于 JMdict 低频 priority 或 BCCWJ rank 30001-50000 且品词匹配的现代标准语候补；专有名词按 JMdict 词性原样收录，不另设特殊标记字段；继续排除古语、废语、方言、生僻和请求范围外品词。",
            },
            {
                "项目": "jmdict_source_url",
                "数量": "",
                "说明": JMDICT_SOURCE_URL,
            },
            {
                "项目": "kanjidic2_source_url",
                "数量": "",
                "说明": KANJIDIC2_SOURCE_URL,
            },
            {
                "项目": "bccwj_source_url",
                "数量": "",
                "说明": BCCWJ_SOURCE_URL,
            },
            {
                "项目": "translation_policy",
                "数量": "",
                "说明": TRANSLATION_POLICY,
            },
            {
                "项目": "translation_overrides_loaded",
                "数量": len(translation_overrides),
                "说明": "仅从 --translation-overrides 写入中文翻译；基础构建不再进行本地词典混合转译。",
            },
        ]
    )
    write_csv(out_dir / "source_audit.csv", audit_rows, ["项目", "数量", "说明"])

    summary = {
        "stats": stats,
        "output_files": [
            "master_lexicon.csv",
            "verbs_by_transitivity.csv",
            "adjective_clusters.csv",
            "noun_kanji_tree.csv",
            "cluster_summary.csv",
            "source_audit.csv",
        ],
        "source_urls": {
            "jmdict": JMDICT_SOURCE_URL,
            "kanjidic2": KANJIDIC2_SOURCE_URL,
            "bccwj": BCCWJ_SOURCE_URL,
        },
        "translation_source": TRANSLATION_POLICY,
        "translation_overrides_loaded": len(translation_overrides),
    }
    (out_dir / "build_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--jmdict", type=Path, required=True)
    parser.add_argument("--kanjidic2", type=Path)
    parser.add_argument("--bccwj", type=Path)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--translation-overrides", type=Path)
    args = parser.parse_args()

    bccwj_index = parse_bccwj(args.bccwj)
    entries, stats, rejected_samples = parse_jmdict(args.jmdict, bccwj_index)
    kanji_info = parse_kanjidic2(args.kanjidic2)
    translation_overrides = read_translation_overrides(args.translation_overrides)
    if kanji_info:
        stats["kanjidic2_characters_loaded"] = len(kanji_info)
    if bccwj_index:
        stats["bccwj_keys_loaded"] = len(bccwj_index)
    emit_outputs(entries, kanji_info, args.out_dir, stats, rejected_samples, translation_overrides)


if __name__ == "__main__":
    main()

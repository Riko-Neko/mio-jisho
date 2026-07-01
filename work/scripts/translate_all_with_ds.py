#!/usr/bin/env python3
"""Translate all lexicon glosses with an OpenAI-compatible DS API.

Input is the generated master CSV. Output is an override TSV that can be used by
build_lexicon.py --translation-overrides or apply_translation_overrides.py.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_API_BASE = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_SOURCE_LABEL = "DeepSeek V4 Flash"
TRANSLATION_POLICY = "DeepSeek V4 Flash 翻译（基于 JMdict/EDRDG 英文释义；待抽样复核）"
TRANSIENT_STATUS = {408, 409, 429, 500, 502, 503, 504}


class ApiError(RuntimeError):
    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"API HTTP {status}: {body[:500]}")
        self.status = status
        self.body = body


def clean(value: str | None) -> str:
    return " ".join((value or "").strip().split())


def split_semicolon(value: str | None) -> list[str]:
    return [part.strip() for part in re.split(r"\s*[;；]\s*", value or "") if part.strip()]


def read_rows(path: Path, levels: set[str]) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if levels:
        rows = [row for row in rows if clean(row.get("等级")) in levels]
    return [row for row in rows if clean(row.get("词条ID")) and split_semicolon(row.get("英文释义摘录"))]


def chat_endpoint(api_base: str) -> str:
    base = api_base.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def row_payload(row: dict[str, str], max_glosses: int) -> dict[str, Any]:
    return {
        "id": clean(row.get("词条ID")),
        "word": clean(row.get("表记")),
        "reading": clean(row.get("读音")),
        "level": clean(row.get("等级")),
        "major_pos": clean(row.get("大类")),
        "subpos": clean(row.get("细品词")),
        "glosses": split_semicolon(row.get("英文释义摘录"))[:max_glosses],
    }


def approx_prompt_chars(rows: list[dict[str, str]], max_glosses: int) -> int:
    payload = [row_payload(row, max_glosses) for row in rows]
    return len(json.dumps(payload, ensure_ascii=False))


def source_chars(rows: list[dict[str, str]]) -> int:
    return sum(len(gloss) for row in rows for gloss in split_semicolon(row.get("英文释义摘录")))


def load_cache(path: Path) -> dict[str, dict[str, Any]]:
    cache: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return cache
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            entry_id = clean(str(record.get("id", "")))
            translations = normalize_translation(record.get("translation"))
            if entry_id and translations:
                record["translation"] = translations
                cache[entry_id] = record
    return cache


def append_cache(path: Path, records: list[dict[str, Any]]) -> None:
    if not records:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


def normalize_translation(value: Any, limit: int = 5) -> list[str]:
    raw_parts: list[str] = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str):
                raw_parts.extend(re.split(r"\s*[;；]\s*|\n+", item))
    elif isinstance(value, str):
        raw_parts.extend(re.split(r"\s*[;；]\s*|\n+", value))

    parts: list[str] = []
    seen = set()
    for raw in raw_parts:
        part = clean(raw)
        part = re.sub(r"^\d+[\.\)、]\s*", "", part)
        part = part.strip(" 。.;；")
        if not part or part in seen:
            continue
        if part.lower() in {"n/a", "none", "null"}:
            continue
        seen.add(part)
        parts.append(part)
        if len(parts) >= limit:
            break
    return parts


def write_overrides(
    rows: list[dict[str, str]],
    cache: dict[str, dict[str, Any]],
    output: Path,
    source_label: str,
) -> int:
    output.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["词条ID", "中文翻译", "翻译来源"], delimiter="\t")
        writer.writeheader()
        for row in rows:
            entry_id = clean(row.get("词条ID"))
            cached = cache.get(entry_id)
            if not cached:
                continue
            translations = normalize_translation(cached.get("translation"))
            if not translations:
                continue
            writer.writerow(
                {
                    "词条ID": entry_id,
                    "中文翻译": "；".join(translations),
                    "翻译来源": clean(str(cached.get("source") or source_label)),
                }
            )
            count += 1
    return count


def update_source_audit(build_dir: Path, override_count: int) -> None:
    path = build_dir / "source_audit.csv"
    if not path.exists():
        return
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or ["项目", "数量", "说明"])
        rows = list(reader)

    if not {"项目", "数量", "说明"}.issubset(fieldnames):
        return

    by_key = {row.get("项目", ""): row for row in rows}
    if "translation_policy" in by_key:
        by_key["translation_policy"]["说明"] = TRANSLATION_POLICY
    else:
        rows.append({"项目": "translation_policy", "数量": "", "说明": TRANSLATION_POLICY})

    detail = "中文翻译由 DeepSeek V4 Flash override 写入；不使用本地词典混合转译或待LLM修补队列。"
    if "translation_overrides_loaded" in by_key:
        by_key["translation_overrides_loaded"].update({"数量": str(override_count), "说明": detail})
    else:
        rows.append({"项目": "translation_overrides_loaded", "数量": str(override_count), "说明": detail})

    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def update_build_summary(build_dir: Path, override_count: int) -> None:
    path = build_dir / "build_summary.json"
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return
    data["translation_source"] = TRANSLATION_POLICY
    data["translation_overrides_loaded"] = override_count
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def make_batches(rows: list[dict[str, str]], batch_size: int, batch_chars: int, max_glosses: int):
    batch: list[dict[str, str]] = []
    used = 0
    for row in rows:
        row_chars = approx_prompt_chars([row], max_glosses)
        if batch and (len(batch) >= batch_size or used + row_chars > batch_chars):
            yield batch
            batch = []
            used = 0
        batch.append(row)
        used += row_chars
    if batch:
        yield batch


def build_messages(items: list[dict[str, Any]]) -> list[dict[str, str]]:
    system = (
        "你是日语-中文词典编辑。请根据日语表记、读音、词性和 JMdict 英文释义，"
        "生成简短、自然、词典风格的中文释义。不要逐词硬翻，不要扩展英文释义之外的含义，"
        "专名、外来语和术语可保留必要原文。只输出 JSON。"
    )
    user = {
        "task": "translate_japanese_lexicon_glosses_to_chinese",
        "output_schema": {
            "items": [
                {
                    "id": "词条ID",
                    "translation": ["中文义项1", "中文义项2"],
                }
            ]
        },
        "rules": [
            "每个词条返回 1 到 5 个中文义项。",
            "中文义项用短语，不写解释性长句。",
            "根据 major_pos/subpos 消歧，例如助词、助动词、动词、名词、形容词要符合词典口径。",
            "不要返回英文原文，除非它是必要的专名、缩写、符号或外来语标记。",
            "必须保留所有输入 id，且不要增加额外 id。",
        ],
        "items": items,
    }
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ]


def extract_json_text(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    starts = [pos for pos in (text.find("{"), text.find("[")) if pos >= 0]
    ends = [pos for pos in (text.rfind("}"), text.rfind("]")) if pos >= 0]
    if starts and ends:
        return text[min(starts) : max(ends) + 1]
    return text


def parse_model_items(content: str) -> dict[str, list[str]]:
    data = json.loads(extract_json_text(content))
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict) and isinstance(data.get("items"), list):
        items = data["items"]
    elif isinstance(data, dict) and isinstance(data.get("translations"), list):
        items = data["translations"]
    elif isinstance(data, dict):
        items = [{"id": key, "translation": value} for key, value in data.items()]
    else:
        raise ValueError("model output is not a JSON object or array")

    out: dict[str, list[str]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        entry_id = clean(str(item.get("id", "")))
        translations = normalize_translation(item.get("translation") or item.get("translations"))
        if entry_id and translations:
            out[entry_id] = translations
    return out


def post_chat(
    endpoint: str,
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
    timeout: int,
    max_tokens: int,
    temperature: float,
    use_response_format: bool,
) -> str:
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "thinking": {"type": "disabled"},
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if use_response_format:
        payload["response_format"] = {"type": "json_object"}

    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise ApiError(exc.code, body) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"API request failed: {exc}") from exc

    parsed = json.loads(body)
    try:
        return parsed["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Unexpected API response: {body[:500]}") from exc


def translate_batch(
    rows: list[dict[str, str]],
    args: argparse.Namespace,
    endpoint: str,
    api_key: str,
    model: str,
) -> dict[str, list[str]]:
    items = [row_payload(row, args.max_glosses) for row in rows]
    messages = build_messages(items)
    use_response_format = not args.no_response_format
    expected_ids = [item["id"] for item in items]

    for attempt in range(args.retries + 1):
        try:
            content = post_chat(
                endpoint,
                api_key,
                model,
                messages,
                args.timeout,
                args.max_tokens,
                args.temperature,
                use_response_format,
            )
            parsed = parse_model_items(content)
            missing = [entry_id for entry_id in expected_ids if entry_id not in parsed]
            if missing:
                raise RuntimeError(f"Model response missing ids: {', '.join(missing[:5])}")
            return parsed
        except ApiError as exc:
            if exc.status == 400 and use_response_format:
                use_response_format = False
                continue
            if exc.status in TRANSIENT_STATUS and attempt < args.retries:
                time.sleep(args.retry_sleep * (2**attempt))
                continue
            raise
        except (RuntimeError, json.JSONDecodeError, ValueError) as exc:
            if attempt < args.retries:
                time.sleep(args.retry_sleep * (2**attempt))
                continue
            raise RuntimeError(f"Failed to translate batch: {exc}") from exc

    raise RuntimeError("Failed to translate batch after retries")


def env_first(names: list[str]) -> str:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return ""


def file_first(paths: list[Path]) -> str:
    for path in paths:
        if not path or not path.exists():
            continue
        value = path.read_text(encoding="utf-8").strip()
        if value:
            return value
    return ""


def run(args: argparse.Namespace) -> None:
    levels = {item.strip() for item in args.levels.split(",") if item.strip()}
    rows = read_rows(args.input, levels)
    cache = load_cache(args.cache)
    api_key_file = Path(env_first(["DS_V4_API_FILE", "DS_API_KEY_FILE", "DEEPSEEK_API_KEY_FILE"]) or args.api_key_file)
    api_key = env_first([args.api_key_env, "DS_V4_API", "DS_API_KEY", "DEEPSEEK_API_KEY"])
    api_key = api_key or file_first([api_key_file])
    model = args.model or env_first(["DS_MODEL", "DEEPSEEK_MODEL"]) or DEFAULT_MODEL
    api_base = args.api_base or env_first(["DS_API_BASE", "DEEPSEEK_API_BASE"]) or DEFAULT_API_BASE
    endpoint = args.endpoint or chat_endpoint(api_base)

    pending = [row for row in rows if args.force or clean(row.get("词条ID")) not in cache]
    if args.max_rows:
        pending = pending[: args.max_rows]

    print(f"input_rows: {len(rows)}")
    print(f"cached_rows: {len(cache)}")
    print(f"pending_rows: {len(pending)}")
    print(f"source_chars: {source_chars(rows)}")
    print(f"approx_prompt_chars_total: {approx_prompt_chars(rows, args.max_glosses)}")
    print(f"model: {model}")
    print(f"endpoint: {endpoint}")
    print(f"output: {args.output}")
    print(f"cache: {args.cache}")

    if args.estimate_only:
        for row in pending[: args.preview]:
            print(json.dumps(row_payload(row, args.max_glosses), ensure_ascii=False))
        return

    if args.dry_run:
        for row in pending[: args.preview]:
            print(json.dumps(row_payload(row, args.max_glosses), ensure_ascii=False))
        write_count = write_overrides(rows, cache, args.output, args.source_label)
        print(f"override_rows_written_from_cache: {write_count}")
        return

    if not api_key:
        raise SystemExit(
            f"Missing API key. Set {args.api_key_env}=..., DS_V4_API=..., DS_API_KEY=..., "
            f"DEEPSEEK_API_KEY=..., or write the key to {api_key_file}."
        )

    translated_total = 0
    for batch_index, batch in enumerate(
        make_batches(pending, args.batch_size, args.batch_chars, args.max_glosses),
        start=1,
    ):
        translated = translate_batch(batch, args, endpoint, api_key, model)
        now = datetime.now(timezone.utc).isoformat()
        records = []
        for row in batch:
            entry_id = clean(row.get("词条ID"))
            record = {
                "id": entry_id,
                "word": clean(row.get("表记")),
                "reading": clean(row.get("读音")),
                "translation": translated[entry_id],
                "source": args.source_label,
                "model": model,
                "createdAt": now,
            }
            cache[entry_id] = record
            records.append(record)

        append_cache(args.cache, records)
        translated_total += len(records)
        written = write_overrides(rows, cache, args.output, args.source_label)
        print(f"batch: {batch_index} translated_total: {translated_total} override_rows: {written}", flush=True)
        time.sleep(args.sleep)

    written = write_overrides(rows, cache, args.output, args.source_label)
    print(f"translated_rows: {translated_total}")
    print(f"override_rows_written: {written}")

    if args.apply_build_dir:
        from apply_translation_overrides import read_overrides, update_csv

        overrides = read_overrides(args.output)
        applied = 0
        for filename in ["master_lexicon.csv", "verbs_by_transitivity.csv", "adjective_clusters.csv"]:
            count = update_csv(args.apply_build_dir / filename, overrides)
            applied += count
            print(f"applied_{filename}: {count}")
        update_source_audit(args.apply_build_dir, len(overrides))
        update_build_summary(args.apply_build_dir, len(overrides))
        print(f"applied_rows: {applied}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("work/build/master_lexicon.csv"))
    parser.add_argument("--output", type=Path, default=Path("work/data/ds_translation_overrides.tsv"))
    parser.add_argument("--cache", type=Path, default=Path("work/data/ds_translation_cache.jsonl"))
    parser.add_argument("--api-key-env", default="DS_V4_API")
    parser.add_argument("--api-key-file", type=Path, default=Path("work/private/ds_v4_api.key"))
    parser.add_argument("--api-base", default="")
    parser.add_argument("--endpoint", default="")
    parser.add_argument("--model", default="")
    parser.add_argument("--source-label", default=DEFAULT_SOURCE_LABEL)
    parser.add_argument("--levels", default="")
    parser.add_argument("--max-rows", type=int, default=0)
    parser.add_argument("--max-glosses", type=int, default=5)
    parser.add_argument("--batch-size", type=int, default=12)
    parser.add_argument("--batch-chars", type=int, default=6500)
    parser.add_argument("--max-tokens", type=int, default=1800)
    parser.add_argument("--temperature", type=float, default=0.1)
    parser.add_argument("--timeout", type=int, default=90)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--retry-sleep", type=float, default=2.0)
    parser.add_argument("--sleep", type=float, default=0.2)
    parser.add_argument("--preview", type=int, default=5)
    parser.add_argument("--apply-build-dir", type=Path)
    parser.add_argument("--estimate-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--no-response-format", action="store_true")
    args = parser.parse_args()
    try:
        run(args)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()

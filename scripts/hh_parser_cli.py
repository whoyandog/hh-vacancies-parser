#!/usr/bin/env python3
import argparse
import json
import os
import sys
from typing import Any, Dict, List

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from parser.client import fetch_vacancies


def load_config() -> dict:
    config_path = os.path.join(PROJECT_ROOT, "config", "parser_config.json")
    if not os.path.exists(config_path):
        return {}
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def print_summary(data: dict) -> None:
    print(
        f"source={data.get('_source')}, found={data.get('found')}, "
        f"pages={data.get('pages')}, page={data.get('page')}, "
        f"per_page={data.get('per_page')}, items_on_page={len(data.get('items', []))}"
    )
    print("-" * 80)

    for idx, item in enumerate(data.get("items", [])[:10], start=1):
        print(f"{idx}. {item.get('name')}")
        print(f"   URL: {item.get('alternate_url')}")
        print(f"   Текст: {item.get('vacancy_text')}")
        print()


def build_n8n_items(data: Dict[str, Any], limit: int = 0, include_meta: bool = False) -> List[Dict[str, Any]]:
    raw_items = data.get("items", []) or []
    if limit and limit > 0:
        raw_items = raw_items[:limit]

    meta = {
        "_source": data.get("_source"),
        "found": data.get("found"),
        "pages": data.get("pages"),
        "page": data.get("page"),
        "per_page": data.get("per_page"),
    }

    n8n_items: List[Dict[str, Any]] = []
    for idx, item in enumerate(raw_items, start=1):
        payload = dict(item)
        payload["rank"] = idx
        if include_meta:
            payload.update(meta)
        n8n_items.append({"json": payload})
    return n8n_items


if __name__ == "__main__":
    config = load_config()
    search_cfg = config.get("search", {})

    parser = argparse.ArgumentParser(description="Простой HH парсер для n8n/LLM.")
    parser.add_argument("--text", default=None, help="Поисковая строка. Если не указана, берётся из config.search.text.")
    parser.add_argument("--area", type=int, default=None, help="Регион. Если не указан, берётся из config.search.area.")
    parser.add_argument("--per-page", type=int, default=None, help="Размер страницы. Если не указан, берётся из config.search.per_page.")
    parser.add_argument("--page", type=int, default=None, help="Номер страницы. Если не указан, берётся из config.search.page.")
    parser.add_argument("--json", action="store_true", help="Вывести JSON результата fetch_vacancies.")
    parser.add_argument("--n8n-items", action="store_true", help="Вывести массив item-ов в формате n8n: [{\"json\": {...}}, ...].")
    parser.add_argument("--n8n-split", action="store_true", help="Вывести по одному n8n item в строке (JSONL).")
    parser.add_argument("--limit", type=int, default=0, help="Ограничить число вакансий на выходе (0 = без ограничений).")
    parser.add_argument("--include-meta", action="store_true", help="Добавить мета-информацию поиска в каждый item для n8n.")
    args = parser.parse_args()

    text = args.text if args.text is not None else search_cfg.get("text", "python developer")
    area = args.area if args.area is not None else int(search_cfg.get("area", 1))
    per_page = args.per_page if args.per_page is not None else int(search_cfg.get("per_page", 20))
    page = args.page if args.page is not None else int(search_cfg.get("page", 0))

    result = fetch_vacancies(
        text=text,
        area=area,
        per_page=per_page,
        page=page,
    )

    if args.n8n_items or args.n8n_split:
        items = build_n8n_items(
            result,
            limit=args.limit,
            include_meta=args.include_meta,
        )
        if args.n8n_split:
            for item in items:
                print(json.dumps(item, ensure_ascii=False))
        else:
            print(json.dumps(items, ensure_ascii=False))
    elif args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print_summary(result)

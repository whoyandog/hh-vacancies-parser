import os
import re
import time
import uuid
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from html import unescape
from typing import List

import requests

RSS_URL = "https://hh.ru/search/vacancy/rss"
HH_UA_PATTERN = re.compile(r"^[\w.\-]+ \([^\s@]+@[^\s@]+\.[^\s@]+\)$")


def get_hh_user_agent() -> str:
    value = os.getenv("HH_USER_AGENT", "").strip()
    if not value:
        raise RuntimeError(
            "Не задан HH_USER_AGENT.\n"
            "Установите переменную окружения, например:\n"
            "export HH_USER_AGENT='my-hh-app (your_email@example.com)'"
        )
    if not HH_UA_PATTERN.match(value):
        raise RuntimeError(
            "Некорректный формат HH_USER_AGENT.\n"
            "Ожидается формат: app-name (email), например:\n"
            "export HH_USER_AGENT='my-hh-app (your_email@example.com)'"
        )
    return value


def build_headers() -> dict:
    hh_user_agent = get_hh_user_agent()
    return {
        "User-Agent": hh_user_agent,
        "HH-User-Agent": hh_user_agent,
        "Accept": "application/xml",
        "X-Request-Id": str(uuid.uuid4()),
    }


def create_session(trust_env: bool = True) -> requests.Session:
    session = requests.Session()
    session.headers.update(build_headers())
    session.trust_env = trust_env
    return session


def strip_html(text: str) -> str:
    cleaned = re.sub(r"<[^>]+>", " ", text or "")
    cleaned = unescape(cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def parse_description(html: str) -> dict:
    """Извлекает структурированные поля из HTML-описания RSS-элемента."""
    text = strip_html(html)

    employer = None
    region = None
    salary = None

    m = re.search(r"Вакансия компании:\s*(.+?)(?:\s+Создана:|$)", text)
    if m:
        employer = m.group(1).strip()

    m = re.search(r"Регион:\s*(.+?)(?:\s+Предполагаемый|$)", text)
    if m:
        region = m.group(1).strip()

    m = re.search(r"Предполагаемый уровень месячного дохода:\s*(.+?)$", text)
    if m:
        salary = m.group(1).strip()

    return {"employer": employer, "region": region, "salary": salary}


def request_with_retries(
    session: requests.Session,
    url: str,
    params: dict,
    max_attempts: int = 4,
    backoff_seconds: float = 1.5,
) -> requests.Response:
    retriable_statuses = {429, 500, 502, 503, 504}
    last_response = None

    for attempt in range(1, max_attempts + 1):
        try:
            response = session.get(url, params=params, timeout=15)
            last_response = response

            if response.status_code in retriable_statuses and attempt < max_attempts:
                retry_after_header = response.headers.get("Retry-After")
                if retry_after_header and retry_after_header.isdigit():
                    sleep_for = max(int(retry_after_header), 1)
                else:
                    sleep_for = backoff_seconds * attempt
                time.sleep(sleep_for)
                continue

            return response
        except requests.RequestException:
            if attempt == max_attempts:
                raise
            time.sleep(backoff_seconds * attempt)

    if last_response is not None:
        return last_response
    raise RuntimeError("Не удалось получить ответ от HH.")


def parse_rss_items(xml_text: str, per_page: int) -> List[dict]:
    root = ET.fromstring(xml_text)
    channel = root.find("channel")
    if channel is None:
        return []

    items = []
    for item in channel.findall("item")[:per_page]:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub_date_raw = (item.findtext("pubDate") or "").strip()
        description_raw = (item.findtext("description") or "").strip()

        published_at = None
        if pub_date_raw:
            try:
                published_at = parsedate_to_datetime(pub_date_raw).isoformat()
            except (TypeError, ValueError):
                published_at = pub_date_raw

        parsed = parse_description(description_raw)

        items.append(
            {
                "id": link or title,
                "name": title,
                "alternate_url": link,
                "published_at": published_at,
                "employer": parsed["employer"],
                "region": parsed["region"],
                "salary": parsed["salary"],
            }
        )

    return items


def fetch_vacancies(
    text: str = "python developer",
    area: int = 1,
    per_page: int = 20,
    page: int = 0,
) -> dict:
    params = {"text": text, "area": area, "page": page}

    use_no_proxy = os.getenv("HH_NO_PROXY", "").strip() == "1"
    session = create_session(trust_env=not use_no_proxy)

    response = request_with_retries(session, RSS_URL, params, max_attempts=3, backoff_seconds=1.0)
    response.raise_for_status()

    items = parse_rss_items(response.text, per_page=per_page)
    return {
        "found": len(items),
        "page": page,
        "per_page": per_page,
        "items": items,
    }

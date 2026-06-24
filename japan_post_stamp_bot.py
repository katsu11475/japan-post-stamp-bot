import json
import os
import re
import time
from datetime import date
from pathlib import Path

import requests
from bs4 import BeautifulSoup

NOTION_TOKEN = os.environ["NOTION_TOKEN"]
NOTION_DATABASE_ID = os.environ["NOTION_DATABASE_ID"]
STATE_FILE = Path("seen_stamps.json")
BASE_URL = "https://www.post.japanpost.jp"
DETAIL_URL = BASE_URL + "/enjoy/culture/stamp/fuke/detail.php?id={}"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.7,en;q=0.3",
    "Referer": BASE_URL + "/enjoy/culture/stamp/fuke/",
}
REQUEST_INTERVAL = float(os.environ.get("REQUEST_INTERVAL", "2"))  # seconds


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"last_id": 12498}


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def scrape_detail(stamp_id: int, max_retries: int = 3) -> dict | None:
    for attempt in range(max_retries):
        try:
            res = requests.get(DETAIL_URL.format(stamp_id), headers=HEADERS, timeout=15)
            if res.status_code == 404:
                return None
            if res.status_code >= 500:
                wait = 2 ** attempt
                print(f"  scrape {stamp_id}: HTTP {res.status_code}, retry in {wait}s... (attempt {attempt + 1}/{max_retries})")
                time.sleep(wait)
                continue
            res.raise_for_status()
            break
        except requests.exceptions.RequestException as e:
            wait = 2 ** attempt
            print(f"  scrape {stamp_id}: {e}, retry in {wait}s... (attempt {attempt + 1}/{max_retries})")
            time.sleep(wait)
    else:
        print(f"  scrape {stamp_id}: 全リトライ失敗、スキップします")
        return None
    res.encoding = res.apparent_encoding
    soup = BeautifulSoup(res.text, "html.parser")

    h1 = soup.select_one("h1")
    if not h1:
        return None

    fields: dict[str, str] = {}
    for dl in soup.select("div.stampdata dl"):
        dt = dl.select_one("dt")
        dd = dl.select_one("dd")
        if dt and dd:
            fields[dt.get_text(strip=True)] = dd.get_text(" ", strip=True)

    if not fields.get("使用開始日") or not fields.get("意匠図案説明"):
        return None

    img = soup.select_one("img.layout_tate")
    img_src = img["src"] if img else None
    if img_src and not img_src.startswith("http"):
        img_src = BASE_URL + img_src

    iso_date = parse_jp_date(fields["使用開始日"])
    if not iso_date:
        return None

    return {
        "id": stamp_id,
        "郵便局名": h1.get_text(strip=True),
        "使用開始日": iso_date,
        "意匠図案説明": fields["意匠図案説明"],
        "備考": fields.get("備考", ""),
        "印面": img_src,
        "url": DETAIL_URL.format(stamp_id),
    }


def parse_jp_date(text: str) -> str | None:
    m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", text)
    if not m:
        return None
    return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()


def save_to_notion(stamp: dict, max_retries: int = 5):
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28",
    }
    properties: dict = {
        "郵便局": {"title": [{"text": {"content": stamp["郵便局名"]}}]},
        "使用開始日": {"date": {"start": stamp["使用開始日"]}},
        "意匠図案説明": {"rich_text": [{"text": {"content": stamp["意匠図案説明"][:2000]}}]},
        "備考": {"rich_text": [{"text": {"content": stamp["備考"][:2000]}}]},
    }
    if stamp["印面"]:
        properties["印面"] = {"url": stamp["印面"]}
    body = {
        "parent": {"database_id": NOTION_DATABASE_ID},
        "properties": properties,
    }
    if stamp["印面"]:
        body["cover"] = {"type": "external", "external": {"url": stamp["印面"]}}

    for attempt in range(max_retries):
        try:
            res = requests.post(
                "https://api.notion.com/v1/pages",
                headers=headers,
                json=body,
                timeout=30,
            )
            if res.status_code == 429:
                retry_after = int(res.headers.get("Retry-After", "10"))
                print(f"  Notion rate limit, waiting {retry_after}s...")
                time.sleep(retry_after)
                continue
            res.raise_for_status()
            return
        except requests.exceptions.Timeout:
            wait = 2 ** attempt
            print(f"  Notion timeout (attempt {attempt + 1}/{max_retries}), retry in {wait}s...")
            time.sleep(wait)
        except requests.exceptions.RequestException as e:
            wait = 2 ** attempt
            print(f"  Notion error (attempt {attempt + 1}/{max_retries}): {e}, retry in {wait}s...")
            time.sleep(wait)

    raise RuntimeError(f"Notion API failed after {max_retries} attempts for {stamp['郵便局名']}")


def main():
    start_id = int(os.environ.get("START_ID", "0"))
    end_id = int(os.environ.get("END_ID", "0"))
    range_mode = start_id > 0 and end_id > 0

    if range_mode:
        # 範囲指定モード：start_id から end_id を処理し、seen_stamps.json は更新しない
        print(f"範囲モード: ID {start_id} 〜 {end_id}")
        new_count = 0
        for stamp_id in range(start_id, end_id + 1):
            stamp = scrape_detail(stamp_id)
            time.sleep(REQUEST_INTERVAL)
            if stamp is None:
                print(f"  skip: {stamp_id}")
                continue
            save_to_notion(stamp)
            print(f"  登録: {stamp['郵便局名']} (ID: {stamp_id})")
            new_count += 1
        print(f"完了: {new_count}件 登録しました")
    else:
        # 通常モード：last_id の続きから新着をチェック
        state = load_state()
        current_id = state["last_id"] + 1
        new_count = 0
        consecutive_missing = 0
        while consecutive_missing < 5:
            stamp = scrape_detail(current_id)
            time.sleep(REQUEST_INTERVAL)
            if stamp is None:
                consecutive_missing += 1
                current_id += 1
                continue
            consecutive_missing = 0
            save_to_notion(stamp)
            print(f"Notion登録: {stamp['郵便局名']} (ID: {current_id})")
            new_count += 1
            state["last_id"] = current_id
            current_id += 1
        save_state(state)
        print(f"完了: {new_count}件 登録しました")


if __name__ == "__main__":
    main()

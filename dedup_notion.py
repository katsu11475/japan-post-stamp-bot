import os
import time

import requests

NOTION_TOKEN = os.environ["NOTION_TOKEN"]
NOTION_DATABASE_ID = os.environ["NOTION_DATABASE_ID"]
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}


def get_all_pages() -> list:
    pages = []
    has_more = True
    start_cursor = None
    while has_more:
        body: dict = {"page_size": 100}
        if start_cursor:
            body["start_cursor"] = start_cursor
        for attempt in range(5):
            res = requests.post(
                f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query",
                headers=HEADERS,
                json=body,
                timeout=30,
            )
            if res.status_code == 429:
                wait = int(res.headers.get("Retry-After", "10"))
                print(f"  rate limit, waiting {wait}s...")
                time.sleep(wait)
                continue
            res.raise_for_status()
            break
        data = res.json()
        pages.extend(data["results"])
        has_more = data["has_more"]
        start_cursor = data.get("next_cursor")
        time.sleep(0.3)
    return pages


def archive_page(page_id: str):
    for attempt in range(5):
        res = requests.patch(
            f"https://api.notion.com/v1/pages/{page_id}",
            headers=HEADERS,
            json={"archived": True},
            timeout=30,
        )
        if res.status_code == 429:
            wait = int(res.headers.get("Retry-After", "10"))
            print(f"  rate limit, waiting {wait}s...")
            time.sleep(wait)
            continue
        res.raise_for_status()
        return
    raise RuntimeError(f"archive failed for {page_id}")


def main():
    print("全ページ取得中...")
    pages = get_all_pages()
    print(f"取得: {len(pages)}件")

    groups: dict[str, list] = {}
    for page in pages:
        props = page["properties"]
        title_items = props.get("郵便局", {}).get("title", [])
        name = title_items[0]["text"]["content"] if title_items else ""
        date_val = props.get("使用開始日", {}).get("date") or {}
        start_date = date_val.get("start", "")
        groups.setdefault(name, []).append({"id": page["id"], "date": start_date})

    delete_count = 0
    for name, entries in groups.items():
        if len(entries) <= 1:
            continue
        entries.sort(key=lambda x: x["date"], reverse=True)
        for entry in entries[1:]:
            print(f"  削除: {name} (使用開始日: {entry['date']})")
            archive_page(entry["id"])
            delete_count += 1
            time.sleep(0.4)

    print(f"完了: {delete_count}件 削除しました")


if __name__ == "__main__":
    main()

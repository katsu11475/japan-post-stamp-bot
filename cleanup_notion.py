"""Notionデータベースから全エントリを削除するスクリプト"""
import os
import requests

NOTION_TOKEN = os.environ["NOTION_TOKEN"]
NOTION_DATABASE_ID = os.environ["NOTION_DATABASE_ID"]

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}


def fetch_all_pages() -> list[dict]:
    pages = []
    url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
    payload = {"page_size": 100}
    while True:
        res = requests.post(url, headers=HEADERS, json=payload, timeout=15)
        res.raise_for_status()
        data = res.json()
        pages.extend(data["results"])
        if not data.get("has_more"):
            break
        payload["start_cursor"] = data["next_cursor"]
    return pages


def archive_page(page_id: str):
    res = requests.patch(
        f"https://api.notion.com/v1/pages/{page_id}",
        headers=HEADERS,
        json={"archived": True},
        timeout=15,
    )
    res.raise_for_status()


def main():
    pages = fetch_all_pages()
    print(f"全{len(pages)}件削除します")
    for p in pages:
        archive_page(p["id"])
        props = p["properties"]
        title = props.get("郵便局", {}).get("title", [])
        name = title[0]["plain_text"] if title else "(empty)"
        print(f"削除: {name}")
    print("完了")


if __name__ == "__main__":
    main()

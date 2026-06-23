import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

DISCORD_WEBHOOK = os.environ["DISCORD_WEBHOOK"]
STATE_FILE = Path("seen_stamps.json")
STAMP_URL = "https://www.post.japanpost.jp/kitte/new/"
BASE_URL = "https://www.post.japanpost.jp"

JST = timezone(timedelta(hours=9))


def load_seen() -> set:
    try:
        return set(json.loads(STATE_FILE.read_text(encoding="utf-8")))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def save_seen(seen: set):
    STATE_FILE.write_text(
        json.dumps(sorted(seen), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def fetch_stamps() -> list[dict]:
    headers = {"User-Agent": "Mozilla/5.0 (compatible; StampBot/1.0)"}
    res = requests.get(STAMP_URL, headers=headers, timeout=10)
    res.raise_for_status()
    res.encoding = res.apparent_encoding
    soup = BeautifulSoup(res.text, "html.parser")

    stamps = []
    seen_urls: set[str] = set()

    for a in soup.select("a[href]"):
        href: str = a["href"]
        title = a.get_text(" ", strip=True)
        if not title or len(title) < 4:
            continue
        full_url = href if href.startswith("http") else BASE_URL + href
        if full_url in seen_urls:
            continue
        seen_urls.add(full_url)
        stamp_id = hashlib.md5(full_url.encode()).hexdigest()
        stamps.append({"id": stamp_id, "title": title[:100], "url": full_url})

    return stamps


def send_to_discord(stamps: list[dict]):
    today = datetime.now(JST).strftime("%Y年%m月%d日")
    lines = [f"**📮 日本郵便 新着切手情報 — {today}**", "━" * 20, ""]

    for s in stamps[:10]:
        lines.append(f"🔖 **{s['title']}**")
        lines.append(f"🔗 {s['url']}")
        lines.append("")

    lines.append("━" * 20)

    res = requests.post(DISCORD_WEBHOOK, json={"content": "\n".join(lines)})
    res.raise_for_status()
    print(f"Discord送信完了: {len(stamps)}件")


def main():
    seen = load_seen()
    all_stamps = fetch_stamps()
    new_stamps = [s for s in all_stamps if s["id"] not in seen]

    if new_stamps:
        send_to_discord(new_stamps)
        seen.update(s["id"] for s in new_stamps)
        save_seen(seen)
        print(f"新着切手 {len(new_stamps)}件 を通知しました")
    else:
        print("新着切手情報はありません")


if __name__ == "__main__":
    main()

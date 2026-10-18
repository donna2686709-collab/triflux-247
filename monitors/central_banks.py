
import html
import re
import urllib.parse

from core.feed import (
    fetch_latest_feed,
    item_id,
    item_link,
    item_title,
)
from core.network import download
from core.telegram import send_one


def fetch_federal_reserve():
    source = "Federal Reserve"

    try:
        from datetime import datetime, timezone

        year = datetime.now(timezone.utc).year

        url = (
            "https://www.federalreserve.gov/"
            "newsevents/pressreleases/"
            f"{year}-press.htm"
        )

        page = download(url).decode(
            "utf-8",
            errors="ignore",
        )

        matches = re.findall(
            r"""href=["']([^"']*/newsevents/pressreleases/[^"']+\.htm)["'][^>]*>(.*?)</a>""",
            page,
            re.I | re.S,
        )

        if not matches:
            raise RuntimeError(
                "No Federal Reserve press releases found"
            )

        link, raw_title = matches[0]

        title = " ".join(
            html.unescape(
                re.sub(r"<[^>]+>", " ", raw_title)
            ).split()
        )

        if not title:
            raise RuntimeError(
                "Federal Reserve press release has no title"
            )

        send_one(
            source,
            "🇺🇸",
            title,
            urllib.parse.urljoin(url, link),
            ".last_fed_news",
        )

    except Exception as error:
        print(
            f"{source} failed, skipping: {error}"
        )


def fetch_ecb():
    source = "European Central Bank (ECB)"

    try:
        url = (
            "https://www.ecb.europa.eu/"
            "rss/press.html"
        )

        items = fetch_latest_feed(url)

        if not items:
            raise RuntimeError(
                "No ECB feed entries found"
            )

        item = items[0]

        title = item_title(item)
        link = item_link(item)
        stable_id = item_id(item)

        if link:
            link = urllib.parse.urljoin(url, link)

        if not title or not link:
            raise RuntimeError(
                "Newest ECB entry has no title/link"
            )

        send_one(
            source,
            "🇪🇺",
            title,
            link,
            ".last_ecb_news",
            item_id=stable_id,
        )

    except Exception as error:
        print(
            f"{source} failed, skipping: {error}"
        )


def fetch_boj():
    source = "Bank of Japan (BOJ)"

    try:
        url = (
            "https://www.boj.or.jp/"
            "en/rss/whatsnew.xml"
        )

        items = fetch_latest_feed(url)

        if not items:
            raise RuntimeError(
                "No BOJ feed entries found"
            )

        item = items[0]

        title = item_title(item)
        link = item_link(item)
        stable_id = item_id(item)

        if link:
            link = urllib.parse.urljoin(url, link)

        if not title or not link:
            raise RuntimeError(
                "Newest BOJ entry has no title/link"
            )

        send_one(
            source,
            "🇯🇵",
            title,
            link,
            ".last_boj_news",
            item_id=stable_id,
        )

    except Exception as error:
        print(
            f"{source} failed, skipping: {error}"
        )


def fetch_boe():
    source = "Bank of England (BoE)"

    try:
        url = (
            "https://www.bankofengland.co.uk/"
            "news?Direction=Latest"
            "&InfiniteScrolling=False"
        )

        page = download(url).decode(
            "utf-8",
            errors="ignore",
        )

        candidates = []

        matches = re.findall(
            r"""href=["']([^"']+)["'][^>]*>(.*?)</a>""",
            page,
            re.I | re.S,
        )

        for link, raw_title in matches:
            if "/news/" not in link.lower():
                continue

            title = " ".join(
                html.unescape(
                    re.sub(
                        r"<[^>]+>",
                        " ",
                        raw_title,
                    )
                ).split()
            )

            if not title:
                continue

            candidates.append((link, title))

        if not candidates:
            raise RuntimeError(
                "No Bank of England news items found"
            )

        link, title = candidates[0]

        send_one(
            source,
            "🇬🇧",
            title,
            urllib.parse.urljoin(url, link),
            ".last_boe_news",
        )

    except Exception as error:
        print(
            f"{source} failed, skipping: {error}"
        )


def fetch_central_banks():
    """Fetch the latest news from four central banks."""
    fetch_federal_reserve()
    fetch_ecb()
    fetch_boj()
    fetch_boe()

import os
import re
import html
import time
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone


BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

USER_AGENT = "Mozilla/5.0 (compatible; TriFlux247/1.0)"


# ============================================================
# Common functions
# ============================================================

def download(url, retries=3):
    last_error = None

    for attempt in range(1, retries + 1):
        try:
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": (
                        "text/html,application/xhtml+xml,"
                        "application/xml;q=0.9,*/*;q=0.8"
                    ),
                    "Accept-Language": "en-US,en;q=0.9",
                }
            )

            with urllib.request.urlopen(
                request,
                timeout=30
            ) as response:
                return response.read()

        except Exception as error:
            last_error = error

            print(
                f"Download attempt {attempt}/{retries} failed "
                f"for {url}: {error}"
            )

            if attempt < retries:
                time.sleep(5)

    raise last_error


def send_telegram(message):
    url = (
        "https://api.telegram.org/bot"
        + BOT_TOKEN
        + "/sendMessage"
    )

    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": message,
        "disable_web_page_preview": "true"
    }).encode()

    request = urllib.request.Request(
        url,
        data=data,
        method="POST"
    )

    with urllib.request.urlopen(
        request,
        timeout=30
    ) as response:
        response.read()


def normalize_url(url):
    parsed = urllib.parse.urlsplit(url)

    return urllib.parse.urlunsplit((
        parsed.scheme,
        parsed.netloc,
        parsed.path.rstrip("/"),
        "",
        ""
    ))


def process_news(
    source_name,
    flag,
    title,
    link,
    state_file
):
    title = " ".join(title.split())
    link = normalize_url(link)

    if not title or not link:
        raise RuntimeError(
            f"{source_name}: missing title or link"
        )

    previous_link = ""

    if os.path.exists(state_file):
        with open(
            state_file,
            "r",
            encoding="utf-8"
        ) as file:
            previous_link = normalize_url(
                file.read().strip()
            )

    if previous_link == link:
        print(f"No new {source_name} news.")
        return

    message = (
        f"{flag} {source_name}\n\n"
        f"📌 {title}\n\n"
        f"🔗 {link}\n\n"
        "📡 TriFlux 24/7 Financial Radar"
    )

    send_telegram(message)

    with open(
        state_file,
        "w",
        encoding="utf-8"
    ) as file:
        file.write(link)

    print(f"New {source_name} news sent.")


# ============================================================
# Federal Reserve
# ============================================================

def fetch_federal_reserve():
    try:
        year = datetime.now(timezone.utc).year

        page_url = (
            "https://www.federalreserve.gov/"
            f"newsevents/pressreleases/{year}-press.htm"
        )

        page = download(page_url).decode(
            "utf-8",
            errors="ignore"
        )

        pattern = re.compile(
            r'href="([^"]*/newsevents/'
            r'pressreleases/[^"]+\.htm)"'
            r'[^>]*>(.*?)</a>',
            re.IGNORECASE | re.DOTALL
        )

        matches = pattern.findall(page)

        if not matches:
            raise RuntimeError(
                "No Federal Reserve press releases found"
            )

        link, raw_title = matches[0]

        title = re.sub(r"<[^>]+>", "", raw_title)
        title = html.unescape(title)

        if link.startswith("/"):
            link = (
                "https://www.federalreserve.gov"
                + link
            )

        elif not link.startswith("http"):
            link = urllib.parse.urljoin(
                page_url,
                link
            )

        process_news(
            "Federal Reserve",
            "🇺🇸",
            title,
            link,
            ".last_fed_news"
        )

    except Exception as error:
        print(
            f"Federal Reserve failed, skipping: {error}"
        )


# ============================================================
# European Central Bank
# ============================================================

def fetch_ecb():
    try:
        feed_url = (
            "https://www.ecb.europa.eu/rss/press.html"
        )

        feed_data = download(feed_url)

        root = ET.fromstring(feed_data)
        items = root.findall(".//item")

        if not items:
            raise RuntimeError(
                "No ECB news items found"
            )

        item = items[0]

        title = (
            item.findtext("title") or ""
        ).strip()

        link = (
            item.findtext("link") or ""
        ).strip()

        process_news(
            "European Central Bank (ECB)",
            "🇪🇺",
            title,
            link,
            ".last_ecb_news"
        )

    except Exception as error:
        print(f"ECB failed, skipping: {error}")


# ============================================================
# Bank of Japan
# ============================================================

def fetch_boj():
    try:
        feed_url = (
            "https://www.boj.or.jp/en/rss/whatsnew.xml"
        )

        feed_data = download(feed_url)

        root = ET.fromstring(feed_data)

        items = root.findall(".//item")

        if not items:
            items = root.findall(".//{*}entry")

        if not items:
            raise RuntimeError(
                "No BOJ news items found"
            )

        item = items[0]

        title_node = item.find("{*}title")

        if title_node is None:
            title_node = item.find("title")

        title = (
            "".join(title_node.itertext()).strip()
            if title_node is not None
            else ""
        )

        link = (
            item.findtext("link") or ""
        ).strip()

        if not link:
            for node in item.findall("{*}link"):
                link = node.attrib.get("href", "")

                if link:
                    break

        process_news(
            "Bank of Japan (BOJ)",
            "🇯🇵",
            title,
            link,
            ".last_boj_news"
        )

    except Exception as error:
        print(f"BOJ failed, skipping: {error}")


# ============================================================
# Bank of England
# ============================================================

def fetch_boe():
    try:
        page_url = (
            "https://www.bankofengland.co.uk/news"
            "?Direction=Latest"
            "&InfiniteScrolling=False"
        )

        page = download(page_url).decode(
            "utf-8",
            errors="ignore"
        )

        matches = re.findall(
            r'href=["\']([^"\']+)["\']'
            r'[^>]*>(.*?)</a>',
            page,
            flags=re.IGNORECASE | re.DOTALL
        )

        selected_link = ""
        selected_title = ""

        for link, raw_title in matches:

            if "/news/" not in link.lower():
                continue

            title = re.sub(
                r"<[^>]+>",
                " ",
                raw_title
            )

            title = html.unescape(title)

            title = re.sub(
                r"\s+",
                " ",
                title
            ).strip()

            if len(title) < 15:
                continue

            if link.startswith("/"):
                link = (
                    "https://www.bankofengland.co.uk"
                    + link
                )

            elif not link.startswith("http"):
                link = urllib.parse.urljoin(
                    page_url,
                    link
                )

            selected_link = link
            selected_title = title
            break

        if (
            not selected_link
            or not selected_title
        ):
            raise RuntimeError(
                "No Bank of England news item found"
            )

        process_news(
            "Bank of England (BoE)",
            "🇬🇧",
            selected_title,
            selected_link,
            ".last_boe_news"
        )

    except Exception as error:
        print(f"BoE failed, skipping: {error}")


# ============================================================
# U.S. Department of the Treasury
# ============================================================

def fetch_treasury():
    try:
        page_url = (
            "https://home.treasury.gov/"
            "news/press-releases"
        )

        raw_data = download(page_url)

        page = raw_data.decode(
            "utf-8",
            errors="ignore"
        )

        patterns = [
            r'/news/press-releases/[A-Za-z]{1,10}[0-9]{2,10}',
            r'\\/news\\/press-releases\\/'
            r'[A-Za-z]{1,10}[0-9]{2,10}',
        ]

        article_paths = []

        for pattern in patterns:
            matches = re.findall(
                pattern,
                page,
                flags=re.IGNORECASE
            )

            for path in matches:
                path = path.replace("\\/", "/")
                path = html.unescape(path)
                path = path.rstrip("/")

                if path not in article_paths:
                    article_paths.append(path)

        if not article_paths:
            raise RuntimeError(
                "No Treasury article paths found"
            )

        selected_path = article_paths[0]

        selected_link = (
            "https://home.treasury.gov"
            + selected_path
        )

        article_page = download(
            selected_link
        ).decode(
            "utf-8",
            errors="ignore"
        )

        title = ""

        title_patterns = [
            (
                r'<meta[^>]+property=["\']'
                r'og:title["\'][^>]+content=["\']'
                r'([^"\']+)'
            ),
            (
                r'<meta[^>]+content=["\']'
                r'([^"\']+)["\'][^>]+property=["\']'
                r'og:title["\']'
            ),
            (
                r'<h1[^>]*>(.*?)</h1>'
            ),
            (
                r'<title[^>]*>(.*?)</title>'
            ),
        ]

        for pattern in title_patterns:
            match = re.search(
                pattern,
                article_page,
                flags=re.IGNORECASE | re.DOTALL
            )

            if not match:
                continue

            title = re.sub(
                r"<[^>]+>",
                " ",
                match.group(1)
            )

            title = html.unescape(title)

            title = re.sub(
                r"\s+",
                " ",
                title
            ).strip()

            if title:
                break

        if not title:
            raise RuntimeError(
                "Treasury article found, "
                "but title could not be extracted"
            )

        process_news(
            "U.S. Department of the Treasury",
            "🇺🇸",
            title,
            selected_link,
            ".last_treasury_news"
        )

    except Exception as error:
        print(
            f"Treasury failed, skipping: {error}"
        )


# ============================================================
# U.S. Securities and Exchange Commission
# ============================================================

def fetch_sec():
    try:
        feed_url = (
            "https://www.sec.gov/news/pressreleases.rss"
        )

        feed_data = download(feed_url)

        root = ET.fromstring(feed_data)

        items = root.findall(".//item")

        if not items:
            raise RuntimeError(
                "No SEC press release items found"
            )

        item = items[0]

        title = (
            item.findtext("title") or ""
        ).strip()

        link = (
            item.findtext("link") or ""
        ).strip()

        if not link:
            guid = (
                item.findtext("guid") or ""
            ).strip()

            if guid.startswith("http"):
                link = guid

        process_news(
            "U.S. Securities and Exchange Commission (SEC)",
            "🇺🇸",
            title,
            link,
            ".last_sec_news"
        )

    except Exception as error:
        print(
            f"SEC failed, skipping: {error}"
        )


# ============================================================
# Main
# ============================================================

def main():
    print("====================================")
    print("TriFlux 24/7 Financial Radar")
    print("====================================")

    fetch_federal_reserve()
    fetch_ecb()
    fetch_boj()
    fetch_boe()
    fetch_treasury()
    fetch_sec()

    print("====================================")
    print("Radar scan complete.")
    print("====================================")


if __name__ == "__main__":
    main()

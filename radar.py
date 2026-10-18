
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
                        "application/rss+xml, application/xml, "
                        "text/xml, text/html, */*"
                    ),
                    "Accept-Language": "en-US,en;q=0.9",
                },
            )

            with urllib.request.urlopen(
                request, timeout=30
            ) as response:
                return response.read()

        except Exception as error:
            last_error = error
            print(
                f"Download attempt {attempt}/{retries} "
                f"failed for {url}: {error}"
            )

            if attempt < retries:
                time.sleep(3)

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
        "disable_web_page_preview": "true",
    }).encode()

    request = urllib.request.Request(
        url, data=data, method="POST"
    )

    with urllib.request.urlopen(
        request, timeout=30
    ) as response:
        result = response.read().decode(
            "utf-8", errors="replace"
        )

    if '"ok": false' in result or '"ok":false' in result:
        raise RuntimeError(
            f"Telegram rejected the message: {result}"
        )


def normalize_url(url):
    url = url.strip()

    if not url:
        return ""

    parsed = urllib.parse.urlsplit(url)

    return urllib.parse.urlunsplit((
        parsed.scheme,
        parsed.netloc,
        parsed.path.rstrip("/"),
        parsed.query,
        "",
    ))


def process_news(
    source_name,
    flag,
    title,
    link,
    state_file,
):
    title = " ".join(html.unescape(title).split())
    link = normalize_url(link)

    if not title or not link:
        raise RuntimeError(
            f"{source_name}: missing title or link"
        )

    previous_link = ""

    if os.path.exists(state_file):
        with open(
            state_file, "r", encoding="utf-8"
        ) as file:
            previous_link = normalize_url(
                file.read().strip()
            )

    if previous_link == link:
        print(f"No new {source_name} news.")
        return

    message = (
        f"🇺🇸 {source_name}\n\n"
        f"📌 {title}\n\n"
        f"🔗 {link}\n\n"
        "📡 TriFlux 24/7 Financial Radar"
    )

    send_telegram(message)

    with open(
        state_file, "w", encoding="utf-8"
    ) as file:
        file.write(link)

    print(f"New {source_name} news sent.")


def extract_item_link(item, base_url):
    link = (
        item.findtext("link") or ""
    ).strip()

    if not link:
        for node in item.findall("{*}link"):
            link = (
                node.attrib.get("href", "")
                or node.attrib.get("url", "")
            ).strip()

            if link:
                break

    if not link:
        guid = (
            item.findtext("guid") or ""
        ).strip()

        if guid.startswith("http"):
            link = guid

    if link:
        link = urllib.parse.urljoin(base_url, link)

    return link


def fetch_rss_source(
    source_name,
    flag,
    feed_url,
    state_file,
):
    try:
        feed_data = download(feed_url)
        root = ET.fromstring(feed_data)

        items = root.findall(".//item")

        if not items:
            items = root.findall(".//{*}entry")

        if not items:
            raise RuntimeError(
                f"No RSS items found at {feed_url}"
            )

        item = items[0]

        title_node = item.find("{*}title")

        if title_node is not None:
            title = "".join(
                title_node.itertext()
            ).strip()
        else:
            title = (
                item.findtext("title") or ""
            ).strip()

        link = extract_item_link(item, feed_url)

        process_news(
            source_name,
            flag,
            title,
            link,
            state_file,
        )

    except Exception as error:
        print(f"{source_name} failed, skipping: {error}")


# ============================================================
# 1. Federal Reserve
# ============================================================

def fetch_federal_reserve():
    try:
        year = datetime.now(timezone.utc).year

        page_url = (
            "https://www.federalreserve.gov/"
            f"newsevents/pressreleases/{year}-press.htm"
        )

        page = download(page_url).decode(
            "utf-8", errors="ignore"
        )

        pattern = re.compile(
            r'href=["\']([^"\']*/newsevents/'
            r'pressreleases/[^"\']+\.htm)["\']'
            r'[^>]*>(.*?)</a>',
            re.IGNORECASE | re.DOTALL,
        )

        matches = pattern.findall(page)

        if not matches:
            raise RuntimeError(
                "No Federal Reserve press releases found"
            )

        for link, raw_title in matches:
            title = html.unescape(
                re.sub(r"<[^>]+>", "", raw_title)
            ).strip()

            if not title:
                continue

            link = urllib.parse.urljoin(page_url, link)

            process_news(
                "Federal Reserve",
                "🇺🇸",
                title,
                link,
                ".last_fed_news",
            )
            return

        raise RuntimeError(
            "Federal Reserve titles could not be extracted"
        )

    except Exception as error:
        print(f"Federal Reserve failed, skipping: {error}")


# ============================================================
# 2. European Central Bank
# ============================================================

def fetch_ecb():
    fetch_rss_source(
        "European Central Bank (ECB)",
        "🇪🇺",
        "https://www.ecb.europa.eu/rss/press.html",
        ".last_ecb_news",
    )


# ============================================================
# 3. Bank of Japan
# ============================================================

def fetch_boj():
    fetch_rss_source(
        "Bank of Japan (BOJ)",
        "🇯🇵",
        "https://www.boj.or.jp/en/rss/whatsnew.xml",
        ".last_boj_news",
    )


# ============================================================
# 4. Bank of England
# ============================================================

def fetch_boe():
    try:
        page_url = (
            "https://www.bankofengland.co.uk/news"
            "?Direction=Latest&InfiniteScrolling=False"
        )

        page = download(page_url).decode(
            "utf-8", errors="ignore"
        )

        matches = re.findall(
            r'href=["\']([^"\']+)["\']'
            r'[^>]*>(.*?)</a>',
            page,
            flags=re.IGNORECASE | re.DOTALL,
        )

        for link, raw_title in matches:
            if "/news/" not in link.lower():
                continue

            title = re.sub(
                r"<[^>]+>", " ", raw_title
            )
            title = html.unescape(title)
            title = " ".join(title.split())

            if len(title) < 15:
                continue

            link = urllib.parse.urljoin(page_url, link)

            process_news(
                "Bank of England (BoE)",
                "🇬🇧",
                title,
                link,
                ".last_boe_news",
            )
            return

        raise RuntimeError(
            "No Bank of England news item found"
        )

    except Exception as error:
        print(f"BoE failed, skipping: {error}")


# ============================================================
# 5. U.S. Department of the Treasury
# ============================================================

def fetch_treasury():
    try:
        page_url = (
            "https://home.treasury.gov/"
            "news/press-releases"
        )

        page = download(page_url).decode(
            "utf-8", errors="ignore"
        )

        patterns = [
            r'/news/press-releases/[A-Za-z]{1,10}[0-9]{2,10}',
            r'\\/news\\/press-releases\\/'
            r'[A-Za-z]{1,10}[0-9]{2,10}',
        ]

        article_paths = []

        for pattern in patterns:
            for path in re.findall(
                pattern, page, flags=re.IGNORECASE
            ):
                path = path.replace("\\/", "/").rstrip("/")

                if path not in article_paths:
                    article_paths.append(path)

        if not article_paths:
            raise RuntimeError(
                "No Treasury article paths found"
            )

        article_link = urllib.parse.urljoin(
            "https://home.treasury.gov",
            article_paths[0],
        )

        article_page = download(
            article_link
        ).decode("utf-8", errors="ignore")

        title = ""

        title_patterns = [
            r'<meta[^>]+property=["\']og:title["\']'
            r'[^>]+content=["\']([^"\']+)',

            r'<meta[^>]+content=["\']([^"\']+)'
            r'["\'][^>]+property=["\']og:title["\']',

            r'<h1[^>]*>(.*?)</h1>',
            r'<title[^>]*>(.*?)</title>',
        ]

        for pattern in title_patterns:
            match = re.search(
                pattern,
                article_page,
                flags=re.IGNORECASE | re.DOTALL,
            )

            if match:
                title = html.unescape(
                    re.sub(
                        r"<[^>]+>", " ", match.group(1)
                    )
                )
                title = " ".join(title.split())

                if title:
                    break

        if not title:
            raise RuntimeError(
                "Treasury article title not found"
            )

        process_news(
            "U.S. Department of the Treasury",
            "🇺🇸",
            title,
            article_link,
            ".last_treasury_news",
        )

    except Exception as error:
        print(f"Treasury failed, skipping: {error}")


# ============================================================
# 6. U.S. Securities and Exchange Commission
# ============================================================

def fetch_sec():
    fetch_rss_source(
        "U.S. Securities and Exchange Commission (SEC)",
        "🇺🇸",
        "https://www.sec.gov/news/pressreleases.rss",
        ".last_sec_news",
    )


# ============================================================
# 7. BLS: Employment Situation
# ============================================================

def fetch_bls_employment():
    fetch_rss_source(
        "BLS Employment Situation",
        "🇺🇸",
        "https://www.bls.gov/feed/empsit.rss",
        ".last_bls_employment",
    )


# ============================================================
# 8. BLS: CPI
# ============================================================

def fetch_bls_cpi():
    fetch_rss_source(
        "BLS Consumer Price Index (CPI)",
        "🇺🇸",
        "https://www.bls.gov/feed/cpi.rss",
        ".last_bls_cpi",
    )


# ============================================================
# 9. BLS: PPI
# ============================================================

def fetch_bls_ppi():
    fetch_rss_source(
        "BLS Producer Price Index (PPI)",
        "🇺🇸",
        "https://www.bls.gov/feed/ppi.rss",
        ".last_bls_ppi",
    )


# ============================================================
# 10. BLS: JOLTS
# ============================================================

def fetch_bls_jolts():
    fetch_rss_source(
        "BLS Job Openings and Labor Turnover (JOLTS)",
        "🇺🇸",
        "https://www.bls.gov/feed/jolts.rss",
        ".last_bls_jolts",
    )


# ============================================================
# 11. BEA: GDP and PCE
# ============================================================

def fetch_bea():
    feed_url = "https://apps.bea.gov/rss/rss.xml"

    try:
        feed_data = download(feed_url)
        root = ET.fromstring(feed_data)

        items = root.findall(".//item")

        if not items:
            items = root.findall(".//{*}entry")

        if not items:
            raise RuntimeError("No BEA RSS items found")

        categories = {
            "gdp": (
                "gross domestic product",
                "gdp",
            ),
            "pce": (
                "personal income and outlays",
                "personal consumption expenditures",
                "pce price index",
                "personal income",
                "personal consumption",
            ),
        }

        # One shared state file prevents one BEA article
        # from being sent once as GDP and again as PCE.
        state_file = ".last_bea_news"

        previous_links = set()

        for filename in (
            state_file,
            ".last_bea_gdp",
            ".last_bea_pce",
        ):
            if os.path.exists(filename):
                with open(
                    filename, "r", encoding="utf-8"
                ) as file:
                    saved_link = normalize_url(
                        file.read().strip()
                    )

                    if saved_link:
                        previous_links.add(saved_link)

        for item in items:
            title_node = item.find("{*}title")

            if title_node is not None:
                title = "".join(
                    title_node.itertext()
                ).strip()
            else:
                title = (
                    item.findtext("title") or ""
                ).strip()

            if not title:
                continue

            link = normalize_url(
                extract_item_link(item, feed_url)
            )

            if not link:
                continue

            title_lower = title.lower()

            matched_categories = [
                category
                for category, keywords in categories.items()
                if any(
                    keyword in title_lower
                    for keyword in keywords
                )
            ]

            if not matched_categories:
                continue

            # Already seen under either old category,
            # or already processed by the shared state.
            if link in previous_links:
                with open(
                    state_file, "w", encoding="utf-8"
                ) as file:
                    file.write(link)

                print(
                    "No new BEA news; duplicate article "
                    "already recorded."
                )
                return

            if len(matched_categories) > 1:
                source_name = "BEA GDP / PCE"
            elif matched_categories[0] == "gdp":
                source_name = (
                    "BEA Gross Domestic Product (GDP)"
                )
            else:
                source_name = (
                    "BEA Personal Income, Outlays and PCE"
                )

            process_news(
                source_name,
                "🇺🇸",
                title,
                link,
                state_file,
            )

            return

        print("No matching new BEA GDP/PCE release found.")

    except Exception as error:
        print(f"BEA failed, skipping: {error}")


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

    fetch_bls_employment()
    fetch_bls_cpi()
    fetch_bls_ppi()
    fetch_bls_jolts()

    fetch_bea()

    print("====================================")
    print("Radar scan complete.")
    print("====================================")


if __name__ == "__main__":
    main()

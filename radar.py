
import html
import json
import os
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone


BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

USER_AGENT = os.environ.get(
    "SEC_USER_AGENT",
    "TriFlux247/1.0 (contact: configure-SEC_USER_AGENT-in-GitHub)"
).strip()

REQUEST_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/rss+xml, application/atom+xml, application/json, application/xml, text/xml, text/html, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

MAX_STATE_ITEMS = 500


# ============================================================
# Common functions
# ============================================================

def download(url, retries=3):
    last_error = None

    for attempt in range(1, retries + 1):
        try:
            request = urllib.request.Request(
                url,
                headers=REQUEST_HEADERS
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
                time.sleep(3 * attempt)

    raise last_error


def send_telegram(message):
    url = (
        f"https://api.telegram.org/bot"
        f"{BOT_TOKEN}/sendMessage"
    )

    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": message,
        "disable_web_page_preview": "true",
    }).encode("utf-8")

    request = urllib.request.Request(
        url, data=data, method="POST"
    )

    with urllib.request.urlopen(
        request, timeout=30
    ) as response:
        result = json.loads(
            response.read().decode(
                "utf-8", errors="replace"
            )
        )

    if not result.get("ok"):
        raise RuntimeError(
            f"Telegram rejected the message: {result}"
        )


def normalize_url(url):
    url = (url or "").strip()

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


def read_state(state_file):
    """Read JSON state; support old single-link state files."""

    if not os.path.exists(state_file):
        return {"initialized": False, "ids": []}

    try:
        with open(
            state_file, "r", encoding="utf-8"
        ) as file:
            raw = file.read().strip()

        if not raw:
            return {"initialized": False, "ids": []}

        try:
            data = json.loads(raw)

            if (
                isinstance(data, dict)
                and isinstance(data.get("ids"), list)
            ):
                return {
                    "initialized": bool(
                        data.get("initialized", True)
                    ),
                    "ids": [
                        str(item)
                        for item in data["ids"]
                        if item
                    ],
                }

        except json.JSONDecodeError:
            pass

        # Legacy state stored one URL as plain text.
        return {
            "initialized": True,
            "ids": [normalize_url(raw)],
        }

    except OSError as error:
        print(
            f"Could not read state file "
            f"{state_file}: {error}"
        )

        return {"initialized": False, "ids": []}


def write_state(state_file, ids, initialized=True):
    unique_ids = list(dict.fromkeys(
        str(item) for item in ids if item
    ))[-MAX_STATE_ITEMS:]

    temp_file = state_file + ".tmp"

    with open(
        temp_file, "w", encoding="utf-8"
    ) as file:
        json.dump(
            {
                "initialized": initialized,
                "ids": unique_ids,
            },
            file,
            ensure_ascii=False,
        )

    os.replace(temp_file, state_file)


def make_message(
    source_name, flag, title, link, details=None
):
    lines = [
        f"{flag} {source_name}",
        "",
        f"📌 {title}",
    ]

    if details:
        lines.extend(["", details])

    lines.extend([
        "",
        f"🔗 {link}",
        "",
        "📡 TriFlux 24/7 Financial Radar",
    ])

    return "\n".join(lines)


def process_news(
    source_name,
    flag,
    title,
    link,
    state_file,
    details=None,
    item_id=None,
):
    title = " ".join(
        html.unescape(str(title or "")).split()
    )

    link = normalize_url(link)
    stable_id = str(item_id or link)

    if not title or not link or not stable_id:
        raise RuntimeError(
            f"{source_name}: missing title, link, or ID"
        )

    state = read_state(state_file)
    known = state["ids"]

    if stable_id in known or link in known:
        print(
            f"No new {source_name}; duplicate already "
            f"recorded: {stable_id}"
        )
        return False

    message = make_message(
        source_name,
        flag,
        title,
        link,
        details,
    )

    # Send before recording the state.
    send_telegram(message)

    write_state(
        state_file,
        known + [stable_id, link],
    )

    print(f"New {source_name} message sent: {title}")

    return True


def extract_item_link(item, base_url):
    link = (
        item.findtext("link") or ""
    ).strip()

    if not link:
        for node in item.findall("{*}link"):
            rel = node.attrib.get("rel", "alternate")

            if rel in ("alternate", ""):
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

    return (
        urllib.parse.urljoin(base_url, link)
        if link else ""
    )


def item_title(item):
    node = item.find("{*}title")

    if node is not None:
        return " ".join(
            "".join(node.itertext()).split()
        )

    return " ".join(
        (item.findtext("title") or "").split()
    )


def item_identity(item, link):
    for tag in ("id", "guid"):
        value = (
            item.findtext(tag) or ""
        ).strip()

        if value:
            return value

    return normalize_url(link)


def fetch_rss_source(
    source_name,
    flag,
    feed_url,
    state_file,
    max_items=30,
):
    try:
        root = ET.fromstring(download(feed_url))

        items = (
            root.findall(".//item")
            or root.findall(".//{*}entry")
        )

        if not items:
            raise RuntimeError(
                f"No RSS/Atom entries found at {feed_url}"
            )

        entries = []

        for item in items[:max_items]:
            title = item_title(item)
            link = normalize_url(
                extract_item_link(item, feed_url)
            )

            if title and link:
                entries.append((
                    item_identity(item, link),
                    title,
                    link,
                ))

        if not entries:
            raise RuntimeError(
                f"No usable entries found at {feed_url}"
            )

        state = read_state(state_file)

        if not state["initialized"]:
            seed = []

            for identity, _title, link in entries:
                seed.extend([identity, link])

            write_state(state_file, seed)

            print(
                f"{source_name}: initialized baseline "
                f"with {len(entries)} existing entries; "
                "no historical messages sent."
            )

            return

        known = set(state["ids"])

        new_entries = [
            (identity, title, link)
            for identity, title, link in entries
            if identity not in known and link not in known
        ]

        if not new_entries:
            print(f"No new {source_name} news.")
            return

        # Feeds are normally newest first.
        # Send older unseen items before newer ones.
        for identity, title, link in reversed(new_entries):
            process_news(
                source_name,
                flag,
                title,
                link,
                state_file,
                item_id=identity,
            )

    except Exception as error:
        print(
            f"{source_name} failed, skipping: {error}"
        )


# ============================================================
# Existing sources: central banks, Treasury, SEC, BLS, BEA
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
            re.I | re.S,
        )

        matches = pattern.findall(page)

        if not matches:
            raise RuntimeError(
                "No Federal Reserve press releases found"
            )

        entries = []

        for link, raw_title in matches:
            title = " ".join(
                html.unescape(
                    re.sub(r"<[^>]+>", " ", raw_title)
                ).split()
            )

            full_link = urllib.parse.urljoin(
                page_url, link
            )

            if title and full_link:
                entries.append((title, full_link))

        fetch_html_latest_list(
            "Federal Reserve",
            "🇺🇸",
            entries,
            ".last_fed_news",
        )

    except Exception as error:
        print(
            f"Federal Reserve failed, skipping: {error}"
        )


def fetch_html_latest_list(
    source_name, flag, entries, state_file
):
    if not entries:
        raise RuntimeError(
            f"{source_name}: no usable entries"
        )

    state = read_state(state_file)

    if not state["initialized"]:
        title, link = entries[0]

        write_state(
            state_file,
            [normalize_url(link)],
        )

        print(
            f"{source_name}: initialized baseline; "
            "no historical message sent."
        )

        return

    known = set(state["ids"])

    new_entries = [
        (title, normalize_url(link))
        for title, link in entries[:30]
        if normalize_url(link) not in known
    ]

    if not new_entries:
        print(f"No new {source_name} news.")
        return

    for title, link in reversed(new_entries):
        process_news(
            source_name,
            flag,
            title,
            link,
            state_file,
        )


def fetch_ecb():
    fetch_rss_source(
        "European Central Bank (ECB)",
        "🇪🇺",
        "https://www.ecb.europa.eu/rss/press.html",
        ".last_ecb_news",
    )


def fetch_boj():
    fetch_rss_source(
        "Bank of Japan (BOJ)",
        "🇯🇵",
        "https://www.boj.or.jp/en/rss/whatsnew.xml",
        ".last_boj_news",
    )


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
            re.I | re.S,
        )

        entries = []

        for link, raw_title in matches:
            if "/news/" not in link.lower():
                continue

            title = " ".join(
                html.unescape(
                    re.sub(r"<[^>]+>", " ", raw_title)
                ).split()
            )

            if len(title) >= 15:
                entries.append((
                    title,
                    urllib.parse.urljoin(page_url, link),
                ))

        fetch_html_latest_list(
            "Bank of England (BoE)",
            "🇬🇧",
            entries,
            ".last_boe_news",
        )

    except Exception as error:
        print(f"BoE failed, skipping: {error}")


def fetch_treasury():
    try:
        page_url = (
            "https://home.treasury.gov/"
            "news/press-releases"
        )

        page = download(page_url).decode(
            "utf-8", errors="ignore"
        )

        paths = []

        for path in re.findall(
            r'/news/press-releases/[A-Za-z]{1,10}[0-9]{2,10}',
            page,
            re.I,
        ):
            if path not in paths:
                paths.append(path)

        if not paths:
            raise RuntimeError(
                "No Treasury article paths found"
            )

        entries = []

        for path in paths[:30]:
            link = urllib.parse.urljoin(
                "https://home.treasury.gov", path
            )

            article = download(link).decode(
                "utf-8", errors="ignore"
            )

            title = ""

            patterns = [
                r'<meta[^>]+property=["\']og:title["\']'
                r'[^>]+content=["\']([^"\']+)',

                r'<meta[^>]+content=["\']([^"\']+)'
                r'["\'][^>]+property=["\']og:title["\']',

                r'<h1[^>]*>(.*?)</h1>',
                r'<title[^>]*>(.*?)</title>',
            ]

            for pattern in patterns:
                match = re.search(
                    pattern, article, re.I | re.S
                )

                if match:
                    title = " ".join(
                        html.unescape(
                            re.sub(
                                r"<[^>]+>",
                                " ",
                                match.group(1),
                            )
                        ).split()
                    )

                    if title:
                        break

            if title:
                entries.append((title, link))

        fetch_html_latest_list(
            "U.S. Department of the Treasury",
            "🇺🇸",
            entries,
            ".last_treasury_news",
        )

    except Exception as error:
        print(f"Treasury failed, skipping: {error}")


def fetch_sec_news():
    fetch_rss_source(
        "U.S. Securities and Exchange Commission (SEC) News",
        "🇺🇸",
        "https://www.sec.gov/news/pressreleases.rss",
        ".last_sec_news",
    )


def fetch_bls_employment():
    fetch_rss_source(
        "BLS Employment Situation",
        "🇺🇸",
        "https://www.bls.gov/feed/empsit.rss",
        ".last_bls_employment",
    )


def fetch_bls_cpi():
    fetch_rss_source(
        "BLS Consumer Price Index (CPI)",
        "🇺🇸",
        "https://www.bls.gov/feed/cpi.rss",
        ".last_bls_cpi",
    )


def fetch_bls_ppi():
    fetch_rss_source(
        "BLS Producer Price Index (PPI)",
        "🇺🇸",
        "https://www.bls.gov/feed/ppi.rss",
        ".last_bls_ppi",
    )


def fetch_bls_jolts():
    fetch_rss_source(
        "BLS Job Openings and Labor Turnover (JOLTS)",
        "🇺🇸",
        "https://www.bls.gov/feed/jolts.rss",
        ".last_bls_jolts",
    )


def fetch_bea():
    feed_url = "https://apps.bea.gov/rss/rss.xml"

    try:
        root = ET.fromstring(download(feed_url))

        items = (
            root.findall(".//item")
            or root.findall(".//{*}entry")
        )

        if not items:
            raise RuntimeError("No BEA RSS items found")

        keywords = {
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

        state_file = ".last_bea_news"
        state = read_state(state_file)

        # Migrate the previous BEA state files.
        for legacy in (
            ".last_bea_gdp",
            ".last_bea_pce",
        ):
            if os.path.exists(legacy):
                try:
                    with open(
                        legacy, "r", encoding="utf-8"
                    ) as file:
                        old = normalize_url(
                            file.read().strip()
                        )

                        if old and old not in state["ids"]:
                            state["ids"].append(old)

                except OSError:
                    pass

        entries = []

        for item in items:
            title = item_title(item)

            link = normalize_url(
                extract_item_link(item, feed_url)
            )

            if not title or not link:
                continue

            lower = title.lower()

            categories = [
                name
                for name, terms in keywords.items()
                if any(term in lower for term in terms)
            ]

            if not categories:
                continue

            name = (
                "BEA GDP / PCE"
                if len(categories) > 1
                else (
                    "BEA Gross Domestic Product (GDP)"
                    if categories[0] == "gdp"
                    else "BEA Personal Income, Outlays and PCE"
                )
            )

            entries.append((
                item_identity(item, link),
                name,
                title,
                link,
            ))

        if not entries:
            print(
                "No matching BEA GDP/PCE release found."
            )
            return

        if not state["initialized"]:
            seed = []

            for identity, _name, _title, link in entries:
                seed.extend([identity, link])

            write_state(state_file, seed)

            print(
                f"BEA: initialized baseline with "
                f"{len(entries)} matching entries; "
                "no historical messages sent."
            )

            return

        known = set(state["ids"])

        new_entries = [
            entry for entry in entries
            if entry[0] not in known
            and entry[3] not in known
        ]

        if not new_entries:
            print("No new BEA GDP/PCE news.")
            return

        for identity, name, title, link in reversed(new_entries):
            process_news(
                name,
                "🇺🇸",
                title,
                link,
                state_file,
                item_id=identity,
            )

    except Exception as error:
        print(f"BEA failed, skipping: {error}")


# ============================================================
# New: SEC corporate filings (EDGAR Atom feeds)
# ============================================================

SEC_FORM_FEEDS = [
    ("Form 4", "4", ".last_sec_form4", "内部人交易申报"),
    ("Schedule 13D", "SC 13D", ".last_sec_13d", "重要股东持股披露"),
    ("Schedule 13D/A", "SC 13D/A", ".last_sec_13da", "重要股东持股修订"),
    ("Schedule 13G", "SC 13G", ".last_sec_13g", "重要股东持股披露"),
    ("Schedule 13G/A", "SC 13G/A", ".last_sec_13ga", "重要股东持股修订"),
    ("Form 8-K", "8-K", ".last_sec_8k", "企业重大事件申报"),
    ("Form 13F-HR", "13F-HR", ".last_sec_13f", "机构季度持仓申报"),
    ("Form 13F-HR/A", "13F-HR/A", ".last_sec_13fa", "机构季度持仓修订申报"),
]


def fetch_sec_form_feed(
    form_name, form_type, state_file, description
):
    try:
        query = urllib.parse.urlencode({
            "action": "getcurrent",
            "type": form_type,
            "company": "",
            "dateb": "",
            "owner": "include",
            "start": "0",
            "count": "40",
            "output": "atom",
        })

        feed_url = (
            "https://www.sec.gov/cgi-bin/browse-edgar?"
            + query
        )

        root = ET.fromstring(download(feed_url))

        entries = (
            root.findall(".//{*}entry")
            or root.findall(".//entry")
        )

        if not entries:
            raise RuntimeError(
                f"No EDGAR Atom entries returned for {form_type}"
            )

        rows = []

        for entry in entries[:40]:
            title = item_title(entry)

            link = normalize_url(
                extract_item_link(entry, feed_url)
            )

            identity = item_identity(entry, link)

            if title and link and identity:
                rows.append((identity, title, link))

        if not rows:
            raise RuntimeError(
                f"No usable EDGAR filings for {form_type}"
            )

        state = read_state(state_file)

        if not state["initialized"]:
            seed = []

            for identity, _title, link in rows:
                seed.extend([identity, link])

            write_state(state_file, seed)

            print(
                f"SEC {form_name}: initialized baseline "
                f"with {len(rows)} current filings; "
                "no historical flood."
            )

            return

        known = set(state["ids"])

        new_rows = [
            (identity, title, link)
            for identity, title, link in rows
            if identity not in known and link not in known
        ]

        if not new_rows:
            print(f"No new SEC {form_name} filings.")
            return

        for identity, title, link in reversed(new_rows):
            details = (
                f"类型：{form_name}（{description}）\n"
                "说明：以 SEC 原始申报为准；"
                "申报本身不一定代表买入或卖出结论。"
            )

            process_news(
                f"SEC {form_name}",
                "🇺🇸",
                title,
                link,
                state_file,
                details=details,
                item_id=identity,
            )

    except Exception as error:
        print(
            f"SEC {form_name} failed, skipping: {error}"
        )


def fetch_sec_corporate_filings():
    for (
        form_name,
        form_type,
        state_file,
        description,
    ) in SEC_FORM_FEEDS:
        fetch_sec_form_feed(
            form_name,
            form_type,
            state_file,
            description,
        )

        # Avoid rapid request bursts to SEC.
        time.sleep(0.25)


# ============================================================
# New: New York Fed SOFR official market rate
# ============================================================

def fetch_sofr():
    try:
        today = datetime.now(timezone.utc).date()
        start = today - timedelta(days=14)

        query = urllib.parse.urlencode({
            "startDate": start.isoformat(),
            "endDate": today.isoformat(),
        })

        api_url = (
            "https://markets.newyorkfed.org/api/rates/"
            "secured/sofr/search.json?"
            + query
        )

        payload = json.loads(
            download(api_url).decode(
                "utf-8", errors="replace"
            )
        )

        rates = payload.get("refRates", [])

        if not rates:
            raise RuntimeError(
                "New York Fed SOFR API returned no rates "
                "in the last 14 days"
            )

        rates.sort(
            key=lambda row: str(
                row.get("effectiveDate", "")
            ),
            reverse=True,
        )

        row = rates[0]

        effective_date = str(
            row.get("effectiveDate", "unknown date")
        )

        rate = row.get(
            "percentRate",
            row.get("percent_rate", "unknown"),
        )

        stable_id = f"SOFR:{effective_date}:{rate}"

        link = (
            "https://www.newyorkfed.org/"
            "markets/reference-rates/sofr"
        )

        state_file = ".last_nyfed_sofr"
        state = read_state(state_file)

        if stable_id in state["ids"]:
            print(
                "No new SOFR observation; latest effective "
                f"date is {effective_date}."
            )
            return

        details = (
            f"生效日期：{effective_date}\n"
            f"SOFR：{rate}%\n"
            "来源：纽约联储官方参考利率。"
            "SOFR 是隔夜担保融资参考利率，"
            "不等同于股票资金流。"
        )

        send_telegram(
            make_message(
                "New York Fed SOFR",
                "🇺🇸",
                f"最新 SOFR：{rate}%（{effective_date}）",
                link,
                details,
            )
        )

        write_state(
            state_file,
            state["ids"] + [stable_id],
        )

        print(
            f"New York Fed SOFR sent: "
            f"{effective_date} {rate}%"
        )

    except Exception as error:
        print(
            f"New York Fed SOFR failed, skipping: {error}"
        )


# ============================================================
# Main
# ============================================================

def main():
    print("====================================")
    print("TriFlux 24/7 Financial Radar")
    print(
        "UTC scan time: "
        f"{datetime.now(timezone.utc).isoformat(timespec='seconds')}"
    )
    print("====================================")

    # Existing sources are preserved.
    fetch_federal_reserve()
    fetch_ecb()
    fetch_boj()
    fetch_boe()
    fetch_treasury()
    fetch_sec_news()
    fetch_bls_employment()
    fetch_bls_cpi()
    fetch_bls_ppi()
    fetch_bls_jolts()
    fetch_bea()

    # New corporate filing and liquidity modules.
    fetch_sec_corporate_filings()
    fetch_sofr()

    print("====================================")
    print("Radar scan complete.")
    print("====================================")


if __name__ == "__main__":
    main()

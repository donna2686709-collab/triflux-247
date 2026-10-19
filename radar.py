import html
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

from monitors.central_banks import (
    fetch_federal_reserve,
    fetch_ecb,
    fetch_boj,
    fetch_boe,
)

from monitors.liquidity import (
    fetch_on_rrp,
)

from monitors.market_events import (
    fetch_nasdaq_trading_halts,
)
from monitors.sec import (
    fetch_sec_filings as fetch_sec_filings_modular,
)
from monitors.nasdaq_alerts import (
    fetch_nasdaq_equity_alerts,
)

from monitors.treasury import (
    fetch_treasury_tic,
)


BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

SEC_USER_AGENT = os.environ.get(
    "SEC_USER_AGENT", ""
).strip()

GENERAL_USER_AGENT = (
    "Mozilla/5.0 (compatible; TriFlux247/2.0)"
)

MAX_STATE_ITEMS = 500


def download(url, retries=4, sec=False):
    headers = {
        "User-Agent": (
            SEC_USER_AGENT
            if sec and SEC_USER_AGENT
            else GENERAL_USER_AGENT
        ),
        "Accept": (
            "application/atom+xml, "
            "application/rss+xml, "
            "application/json, "
            "application/xml, "
            "text/xml, "
            "text/html, */*"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }

    last_error = None

    for attempt in range(retries):
        try:
            request = urllib.request.Request(
                url,
                headers=headers,
            )

            with urllib.request.urlopen(
                request,
                timeout=30,
            ) as response:
                return response.read()

        except urllib.error.HTTPError as error:
            last_error = error

            if (
                error.code == 429
                and attempt < retries - 1
            ):
                wait = 15 * (attempt + 1)

                print(
                    f"HTTP 429 for {url}; "
                    f"waiting {wait}s..."
                )

                time.sleep(wait)
                continue

            raise

        except Exception as error:
            last_error = error

            if attempt < retries - 1:
                time.sleep(5 * (attempt + 1))
                continue

            raise

    raise last_error


def send_telegram(message):
    url = (
        "https://api.telegram.org/bot"
        f"{BOT_TOKEN}/sendMessage"
    )

    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": message[:4000],
        "disable_web_page_preview": "true",
    }).encode("utf-8")

    for attempt in range(4):
        try:
            request = urllib.request.Request(
                url,
                data=data,
                method="POST",
            )

            with urllib.request.urlopen(
                request,
                timeout=30,
            ) as response:
                result = json.loads(
                    response.read().decode(
                        "utf-8",
                        errors="replace",
                    )
                )

            if not result.get("ok"):
                raise RuntimeError(str(result))

            time.sleep(1.2)
            return

        except urllib.error.HTTPError as error:
            if (
                error.code == 429
                and attempt < 3
            ):
                wait = 20 * (attempt + 1)

                print(
                    "Telegram rate limit; "
                    f"waiting {wait}s..."
                )

                time.sleep(wait)
                continue

            raise


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


def read_state(path):
    if not os.path.exists(path):
        return {
            "initialized": False,
            "ids": [],
        }

    try:
        with open(
            path,
            "r",
            encoding="utf-8",
        ) as file:
            raw = file.read().strip()

        if not raw:
            return {
                "initialized": False,
                "ids": [],
            }

        try:
            data = json.loads(raw)

            if (
                isinstance(data, dict)
                and isinstance(
                    data.get("ids"),
                    list,
                )
            ):
                return {
                    "initialized": bool(
                        data.get(
                            "initialized",
                            True,
                        )
                    ),
                    "ids": [
                        str(item)
                        for item in data["ids"]
                        if item
                    ],
                }

        except json.JSONDecodeError:
            pass

        return {
            "initialized": True,
            "ids": [
                normalize_url(raw)
            ],
        }

    except Exception:
        return {
            "initialized": False,
            "ids": [],
        }


def write_state(path, ids):
    unique = list(
        dict.fromkeys(
            str(item)
            for item in ids
            if item
        )
    )[-MAX_STATE_ITEMS:]

    temp_path = path + ".tmp"

    with open(
        temp_path,
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            {
                "initialized": True,
                "ids": unique,
            },
            file,
            ensure_ascii=False,
        )

    os.replace(
        temp_path,
        path,
    )


def make_message(
    source,
    flag,
    title,
    link,
    details="",
):
    parts = [
        f"{flag} {source}",
        "",
        f"📌 {title}",
    ]

    if details:
        parts.extend([
            "",
            details,
        ])

    parts.extend([
        "",
        f"🔗 {link}",
        "",
        "📡 TriFlux 24/7 Financial Radar",
    ])

    return "\n".join(parts)


def send_one(
    source,
    flag,
    title,
    link,
    state_file,
    item_id=None,
    details="",
):
    link = normalize_url(link)

    title = " ".join(
        html.unescape(
            str(title or "")
        ).split()
    )

    stable_id = str(
        item_id or link
    )

    if (
        not title
        or not link
        or not stable_id
    ):
        return False

    state = read_state(
        state_file
    )

    if (
        stable_id in state["ids"]
        or link in state["ids"]
    ):
        print(
            f"No new {source}; "
            "duplicate already recorded."
        )
        return False

    send_telegram(
        make_message(
            source,
            flag,
            title,
            link,
            details,
        )
    )

    write_state(
        state_file,
        state["ids"]
        + [
            stable_id,
            link,
        ],
    )

    print(
        f"New {source} message sent: "
        f"{title}"
    )

    return True


def item_title(item):
    node = item.find(
        "{*}title"
    )

    if node is None:
        node = item.find(
            "title"
        )

    if node is None:
        return ""

    return " ".join(
        "".join(
            node.itertext()
        ).split()
    )


def item_link(item, base):
    nodes = (
        item.findall("{*}link")
        + item.findall("link")
    )

    for node in nodes:
        href = node.attrib.get(
            "href",
            "",
        ).strip()

        if href:
            return normalize_url(
                urllib.parse.urljoin(
                    base,
                    href,
                )
            )

        if (
            node.text
            and node.text.strip().startswith(
                "http"
            )
        ):
            return normalize_url(
                node.text.strip()
            )

    text = (
        item.findtext("link")
        or ""
    ).strip()

    if text:
        return normalize_url(
            urllib.parse.urljoin(
                base,
                text,
            )
        )

    guid = (
        item.findtext("guid")
        or ""
    ).strip()

    if guid.startswith("http"):
        return normalize_url(
            guid
        )

    return ""


def item_id(item, link):
    for tag in (
        "{*}id",
        "id",
        "guid",
    ):
        value = (
            item.findtext(tag)
            or ""
        ).strip()

        if value:
            return value

    return link


def fetch_latest_feed(
    source,
    flag,
    url,
    state_file,
):
    try:
        root = ET.fromstring(
            download(url)
        )

        items = (
            root.findall(".//item")
            or root.findall(
                ".//{*}entry"
            )
        )

        if not items:
            raise RuntimeError(
                "No feed entries found"
            )

        item = items[0]

        title = item_title(
            item
        )

        link = item_link(
            item,
            url,
        )

        if not title or not link:
            raise RuntimeError(
                "Newest feed entry "
                "has no title/link"
            )

        send_one(
            source,
            flag,
            title,
            link,
            state_file,
            item_id=item_id(
                item,
                link,
            ),
        )

    except Exception as error:
        print(
            f"{source} failed, "
            f"skipping: {error}"
        )


def fetch_cftc_cot_tff():
    source = "CFTC COT TFF"
    state_file = ".last_cftc_cot_tff"

    try:
        query = urllib.parse.urlencode({
            "$select": (
                "report_date_as_yyyy_mm_dd,"
                "market_and_exchange_names,"
                "commodity_name,"
                "open_interest_all,"
                "dealer_positions_long_all,"
                "dealer_positions_short_all,"
                "asset_mgr_positions_long,"
                "asset_mgr_positions_short,"
                "lev_money_positions_long,"
                "lev_money_positions_short"
            ),
            "$order": "report_date_as_yyyy_mm_dd DESC",
            "$limit": "500",
        })

        api_url = (
            "https://publicreporting.cftc.gov/resource/"
            "yw9f-hn96.json?"
            + query
        )

        rows = json.loads(
            download(api_url).decode(
                "utf-8",
                errors="replace",
            )
        )

        if not isinstance(rows, list) or not rows:
            raise RuntimeError(
                "CFTC TFF API returned no rows"
            )

        report_dates = [
            str(
                row.get(
                    "report_date_as_yyyy_mm_dd",
                    "",
                )
            )[:10]
            for row in rows
            if row.get(
                "report_date_as_yyyy_mm_dd"
            )
        ]

        if not report_dates:
            raise RuntimeError(
                "CFTC TFF API returned no report date"
            )

        latest_date = max(
            report_dates
        )

        latest_rows = [
            row
            for row in rows
            if str(
                row.get(
                    "report_date_as_yyyy_mm_dd",
                    "",
                )
            )[:10] == latest_date
        ]

        if not latest_rows:
            raise RuntimeError(
                "CFTC TFF latest report has no rows"
            )

        stable_id = (
            f"CFTC-TFF:{latest_date}"
        )

        state = read_state(
            state_file
        )

        if not state["initialized"]:
            write_state(
                state_file,
                [stable_id],
            )

            print(
                "CFTC COT TFF: initialized baseline "
                f"with report date {latest_date} "
                f"and {len(latest_rows)} market rows; "
                "no historical messages sent."
            )

            return

        if stable_id in state["ids"]:
            print(
                "No new CFTC COT TFF report; "
                f"latest report date is {latest_date}."
            )

            return

        link = (
            "https://publicreporting.cftc.gov/"
            "Commitments-of-Traders/"
            "TFF-Combined/yw9f-hn96"
        )

        details = (
            f"Report date: {latest_date}\n"
            f"Financial market rows: "
            f"{len(latest_rows)}\n"
            "Categories: Dealer, Asset Manager, "
            "Leveraged Money, Other Reportables, "
            "and Non-Reportables.\n"
            "Frequency: Weekly COT report; "
            "positions are reported as of the "
            "prior Tuesday close.\n"
            "Source: U.S. Commodity Futures "
            "Trading Commission official "
            "Public Reporting Environment."
        )

        send_one(
            source,
            "🇺🇸",
            (
                "New TFF positioning report "
                f"({latest_date})"
            ),
            link,
            state_file,
            item_id=stable_id,
            details=details,
        )

    except Exception as error:
        print(
            f"{source} failed, "
            f"skipping: {error}"
        )


def extract_page_title(page):
    patterns = [
        (
            r'<meta[^>]+'
            r'property=["\']og:title["\']'
            r'[^>]+content=["\']'
            r'([^"\']+)'
        ),
        (
            r'<meta[^>]+'
            r'content=["\']([^"\']+)'
            r'["\'][^>]+'
            r'property=["\']og:title["\']'
        ),
        r'<h1[^>]*>(.*?)</h1>',
        r'<title[^>]*>(.*?)</title>',
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            page,
            re.I | re.S,
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
                return title

    return ""


def fetch_treasury():
    source = (
        "U.S. Department "
        "of the Treasury"
    )

    try:
        url = (
            "https://home.treasury.gov/"
            "news/press-releases"
        )

        page = download(
            url
        ).decode(
            "utf-8",
            errors="ignore",
        )

        paths = []

        matches = re.findall(
            r'/news/press-releases/'
            r'[A-Za-z]{1,10}[0-9]{2,10}',
            page,
            re.I,
        )

        for path in matches:
            if path not in paths:
                paths.append(path)

        if not paths:
            raise RuntimeError(
                "No Treasury release found"
            )

        link = urllib.parse.urljoin(
            "https://home.treasury.gov",
            paths[0],
        )

        article = download(
            link
        ).decode(
            "utf-8",
            errors="ignore",
        )

        title = extract_page_title(
            article
        )

        if not title:
            raise RuntimeError(
                "Treasury title not found"
            )

        send_one(
            source,
            "🇺🇸",
            title,
            link,
            ".last_treasury_news",
        )

    except Exception as error:
        print(
            f"{source} failed, "
            f"skipping: {error}"
        )


def fetch_sec_news():
    fetch_latest_feed(
        (
            "U.S. Securities and "
            "Exchange Commission "
            "(SEC) News"
        ),
        "🇺🇸",
        "https://www.sec.gov/news/pressreleases.rss",
        ".last_sec_news",
    )


def fetch_bls_employment():
    fetch_latest_feed(
        "BLS Employment Situation",
        "🇺🇸",
        "https://www.bls.gov/feed/empsit.rss",
        ".last_bls_employment",
    )


def fetch_bls_cpi():
    fetch_latest_feed(
        (
            "BLS Consumer Price "
            "Index (CPI)"
        ),
        "🇺🇸",
        "https://www.bls.gov/feed/cpi.rss",
        ".last_bls_cpi",
    )


def fetch_bls_ppi():
    fetch_latest_feed(
        (
            "BLS Producer Price "
            "Index (PPI)"
        ),
        "🇺🇸",
        "https://www.bls.gov/feed/ppi.rss",
        ".last_bls_ppi",
    )


def fetch_bls_jolts():
    fetch_latest_feed(
        (
            "BLS Job Openings and "
            "Labor Turnover (JOLTS)"
        ),
        "🇺🇸",
        "https://www.bls.gov/feed/jolts.rss",
        ".last_bls_jolts",
    )


def fetch_bea():
    source = "BEA GDP / PCE"

    try:
        url = (
            "https://apps.bea.gov/"
            "rss/rss.xml"
        )

        root = ET.fromstring(
            download(url)
        )

        items = (
            root.findall(".//item")
            or root.findall(
                ".//{*}entry"
            )
        )

        keywords = (
            "gross domestic product",
            "gdp",
            "personal income and outlays",
            "personal consumption expenditures",
            "pce price index",
            "personal income",
            "personal consumption",
        )

        match = None

        for item in items:
            title = item_title(
                item
            )

            lower = title.lower()

            if any(
                keyword in lower
                for keyword in keywords
            ):
                link = item_link(
                    item,
                    url,
                )

                if link:
                    match = (
                        item,
                        title,
                        link,
                    )
                    break

        if not match:
            print(
                "No matching BEA "
                "GDP/PCE release found."
            )
            return

        item, title, link = match

        send_one(
            source,
            "🇺🇸",
            title,
            link,
            ".last_bea_news",
            item_id=item_id(
                item,
                link,
            ),
        )

    except Exception as error:
        print(
            f"{source} failed, "
            f"skipping: {error}"
        )


SEC_FORMS = [
    (
        "Form 4",
        "4",
        ".last_sec_form4",
        (
            "Insider ownership change filing; "
            "Form 4 alone does not necessarily indicate "
            "an open-market purchase or sale"
        ),
    ),
    (
        "Schedule 13D",
        "SCHEDULE 13D",
        ".last_sec_13d",
        (
            "Beneficial ownership disclosure "
            "for certain holders above 5%"
        ),
    ),
    (
        "Schedule 13D/A",
        "SCHEDULE 13D/A",
        ".last_sec_13da",
        "Amendment to Schedule 13D",
    ),
    (
        "Schedule 13G",
        "SCHEDULE 13G",
        ".last_sec_13g",
        (
            "Beneficial ownership disclosure "
            "for certain holders above 5%"
        ),
    ),
    (
        "Schedule 13G/A",
        "SCHEDULE 13G/A",
        ".last_sec_13ga",
        "Amendment to Schedule 13G",
    ),
    (
        "Form 8-K",
        "8-K",
        ".last_sec_8k",
        (
            "Current report covering material "
            "corporate events"
        ),
    ),
    (
        "Form 13F-HR",
        "13F-HR",
        ".last_sec_13f",
        (
            "Quarterly institutional holdings report; "
            "this is delayed disclosure, "
            "not real-time trading activity"
        ),
    ),
    (
        "Form 13F-HR/A",
        "13F-HR/A",
        ".last_sec_13fa",
        (
            "Amendment to quarterly institutional "
            "holdings report; this is delayed disclosure"
        ),
    ),
    (
        "Form 10-Q",
        "10-Q",
        ".last_sec_10q",
        (
            "Quarterly financial report used to monitor "
            "revenue, earnings, cash flow, balance sheet, "
            "and changes in business conditions"
        ),
    ),
    (
        "Form 10-K",
        "10-K",
        ".last_sec_10k",
        (
            "Annual financial report used to monitor "
            "revenue, earnings, cash flow, balance sheet, "
            "risk factors, and changes in business conditions"
        ),
    ),
]


def fetch_sec_form(
    name,
    form_type,
    state_file,
    description,
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

        url = (
            "https://www.sec.gov/"
            "cgi-bin/browse-edgar?"
            + query
        )

        root = ET.fromstring(
            download(
                url,
                sec=True,
            )
        )

        entries = root.findall(
            ".//{*}entry"
        )

        rows = []

        for entry in entries:
            title = item_title(
                entry
            )

            link = item_link(
                entry,
                url,
            )

            stable_id = item_id(
                entry,
                link,
            )

            if (
                title
                and link
                and stable_id
            ):
                rows.append(
                    (
                        stable_id,
                        title,
                        link,
                    )
                )

        if not rows:
            print(
                f"SEC {name}: "
                "no current filings returned; "
                "nothing sent."
            )
            return

        state = read_state(
            state_file
        )

        if not state["initialized"]:
            seed = []

            for (
                stable_id,
                _title,
                link,
            ) in rows:
                seed.extend([
                    stable_id,
                    link,
                ])

            write_state(
                state_file,
                seed,
            )

            print(
                f"SEC {name}: "
                "initialized baseline with "
                f"{len(rows)} current filings; "
                "no historical messages sent."
            )

            return

        known = set(
            state["ids"]
        )

        unseen = [
            row
            for row in rows
            if (
                row[0] not in known
                and row[2] not in known
            )
        ]

        if not unseen:
            print(
                f"No new SEC "
                f"{name} filings."
            )
            return

        for (
            stable_id,
            title,
            link,
        ) in reversed(unseen):

            details = (
                f"Type: {name}\n"
                f"Description: {description}\n"
                "Source: Official SEC EDGAR filing"
            )

            send_one(
                f"SEC {name}",
                "🇺🇸",
                title,
                link,
                state_file,
                item_id=stable_id,
                details=details,
            )

    except Exception as error:
        print(
            f"SEC {name} failed, "
            f"skipping: {error}"
        )


def fetch_sec_filings():
    if not SEC_USER_AGENT:
        print(
            "SEC filings skipped: "
            "SEC_USER_AGENT "
            "is not configured."
        )
        return

    for row in SEC_FORMS:
        fetch_sec_form(
            *row
        )

        time.sleep(1.0)


def fetch_sofr():
    fetch_cftc_cot_tff()

    source = (
        "New York Fed SOFR"
    )

    try:
        end = datetime.now(
            timezone.utc
        ).date()

        start = (
            end
            - timedelta(days=14)
        )

        query = urllib.parse.urlencode({
            "startDate": (
                start.isoformat()
            ),
            "endDate": (
                end.isoformat()
            ),
        })

        url = (
            "https://markets.newyorkfed.org/"
            "api/rates/secured/sofr/"
            "search.json?"
            + query
        )

        data = json.loads(
            download(
                url
            ).decode(
                "utf-8",
                errors="replace",
            )
        )

        rates = (
            data.get("refRates")
            or []
        )

        if not rates:
            raise RuntimeError(
                "SOFR API returned "
                "no observations"
            )

        rates.sort(
            key=lambda row: str(
                row.get(
                    "effectiveDate",
                    "",
                )
            ),
            reverse=True,
        )

        row = rates[0]

        effective_date = str(
            row.get(
                "effectiveDate",
                "",
            )
        )

        rate = row.get(
            "percentRate"
        )

        if rate is None:
            raise RuntimeError(
                "SOFR response has "
                "no percentRate"
            )

        stable_id = (
            f"SOFR:"
            f"{effective_date}:"
            f"{rate}"
        )

        state_file = (
            ".last_nyfed_sofr"
        )

        state = read_state(
            state_file
        )

        if not state["initialized"]:
            write_state(
                state_file,
                [stable_id],
            )

            print(
                "New York Fed SOFR: "
                "initialized baseline "
                f"{effective_date} "
                f"{rate}%; "
                "no historical message sent."
            )

            return

        if stable_id in state["ids"]:
            print(
                "No new SOFR observation; "
                f"latest is "
                f"{effective_date} "
                f"{rate}%."
            )
            return

        link = (
            "https://www.newyorkfed.org/"
            "markets/reference-rates/sofr"
        )

        details = (
            f"Effective date: {effective_date}\n"
            f"SOFR: {rate}%\n"
            "Source: Federal Reserve Bank "
            "of New York official reference rate"
        )

        send_one(
            source,
            "🇺🇸",
            (
                f"SOFR {rate}%"
                f" ({effective_date})"
            ),
            link,
            state_file,
            item_id=stable_id,
            details=details,
        )

    except Exception as error:
        print(
            f"{source} failed, "
            f"skipping: {error}"
        )


def main():
    print(
        "===================================="
    )

    print(
        "TriFlux 24/7 Financial Radar"
    )

    print(
        "UTC scan time:",
        datetime.now(
            timezone.utc
        ).isoformat(
            timespec="seconds"
        ),
    )

    print(
        "===================================="
    )

    # Global central bank monitoring
    fetch_federal_reserve()
    fetch_ecb()
    fetch_boj()
    fetch_boe()

    # U.S. government and regulatory news
    fetch_treasury()
    fetch_treasury_tic()
    fetch_sec_news()

    # U.S. macroeconomic indicators
    fetch_bls_employment()
    fetch_bls_cpi()
    fetch_bls_ppi()
    fetch_bls_jolts()
    fetch_bea()

    # SEC filing monitoring
    fetch_sec_filings_modular()

            # CFTC positioning and New York Fed liquidity
    fetch_sofr()
    fetch_on_rrp()

        # U.S. stock market events
    fetch_nasdaq_trading_halts()
    fetch_nasdaq_equity_alerts()

    print(
        "===================================="
    )

    print(
        "Radar scan complete."
    )

    print(
        "===================================="
    )


if __name__ == "__main__":
    main()

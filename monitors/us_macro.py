import html
import re
import urllib.parse
import xml.etree.ElementTree as ET

from core.network import download
from core.feed import item_title, item_link, item_id
from core.telegram import send_one


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
    source = "U.S. Department of the Treasury"

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
            source=source,
            title=title,
            link=link,
            state_file=".last_treasury_news",
            category="U.S. Macro",
        )

    except Exception as error:
        print(
            f"{source} failed, "
            f"skipping: {error}"
        )


def _fetch_bls(
    source,
    url,
    state_file,
):
    try:
        root = ET.fromstring(
            download(url)
        )

        items = (
            root.findall(".//item")
            or root.findall(".//{*}entry")
        )

        if not items:
            raise RuntimeError(
                "No feed entries found"
            )

        item = items[0]

        title = item_title(item)
        link = item_link(item)

        if link:
            link = urllib.parse.urljoin(
                url,
                link,
            )

        if not title or not link:
            raise RuntimeError(
                "Newest feed entry has no title/link"
            )

        send_one(
            source=source,
            title=title,
            link=link,
            state_file=state_file,
            item_id=item_id(item),
            category="U.S. Macro",
        )

    except Exception as error:
        print(
            f"{source} failed, "
            f"skipping: {error}"
        )


def fetch_bls_employment():
    _fetch_bls(
        source="BLS Employment Situation",
        url="https://www.bls.gov/feed/empsit.rss",
        state_file=".last_bls_employment",
    )


def fetch_bls_cpi():
    _fetch_bls(
        source="BLS Consumer Price Index (CPI)",
        url="https://www.bls.gov/feed/cpi.rss",
        state_file=".last_bls_cpi",
    )


def fetch_bls_ppi():
    _fetch_bls(
        source="BLS Producer Price Index (PPI)",
        url="https://www.bls.gov/feed/ppi.rss",
        state_file=".last_bls_ppi",
    )


def fetch_bls_jolts():
    _fetch_bls(
        source=(
            "BLS Job Openings and "
            "Labor Turnover (JOLTS)"
        ),
        url="https://www.bls.gov/feed/jolts.rss",
        state_file=".last_bls_jolts",
    )


def fetch_bea():
    source = "BEA GDP / PCE"

    try:
        url = "https://apps.bea.gov/rss/rss.xml"

        root = ET.fromstring(
            download(url)
        )

        items = (
            root.findall(".//item")
            or root.findall(".//{*}entry")
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
            title = item_title(item)
            lower = title.lower()

            if any(
                keyword in lower
                for keyword in keywords
            ):
                link = item_link(item)

                if link:
                    link = urllib.parse.urljoin(
                        url,
                        link,
                    )

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
            source=source,
            title=title,
            link=link,
            state_file=".last_bea_news",
            item_id=item_id(item),
            category="U.S. Macro",
        )

    except Exception as error:
        print(
            f"{source} failed, "
            f"skipping: {error}"
        )

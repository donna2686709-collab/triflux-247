import html
import re
import urllib.parse

from core.feed import fetch_latest_feed, item_id, item_link, item_title
from core.telegram import send_one


FED_FEED = "https://www.federalreserve.gov/feeds/press_all.xml"
ECB_FEED = "https://www.ecb.europa.eu/rss/press.html"
BOJ_FEED = "https://www.boj.or.jp/en/rss/whatsnew.xml"
BOE_FEED = "https://www.bankofengland.co.uk/rss/news"

FED_STATE = ".last_fed_news"
ECB_STATE = ".last_ecb_news"
BOJ_STATE = ".last_boj_news"
BOE_STATE = ".last_boe_news"


def _clean_text(value):
    if not value:
        return ""

    value = html.unescape(value)
    value = re.sub(r"\s+", " ", value)

    return value.strip()


def _absolute_url(base_url, link):
    if not link:
        return ""

    return urllib.parse.urljoin(base_url, link)


def _fetch_latest(
    source,
    feed_url,
    state_file,
):
    try:
        items = fetch_latest_feed(feed_url)

        if not items:
            print(f"{source}: feed returned no items.")
            return

        latest = items[0]

        title = _clean_text(item_title(latest))
        link = _absolute_url(
            feed_url,
            item_link(latest),
        )
        identifier = _clean_text(item_id(latest))

        if not title:
            print(f"{source}: latest feed item has no title.")
            return

        send_one(
            source=source,
            title=title,
            link=link,
            state_file=state_file,
            item_id=identifier,
            category="Central Banks",
        )

    except Exception as exc:
        print(f"{source} error: {exc}")


def fetch_fed():
    _fetch_latest(
        source="Federal Reserve",
        feed_url=FED_FEED,
        state_file=FED_STATE,
    )


def fetch_ecb():
    _fetch_latest(
        source="European Central Bank (ECB)",
        feed_url=ECB_FEED,
        state_file=ECB_STATE,
    )


def fetch_boj():
    _fetch_latest(
        source="Bank of Japan (BOJ)",
        feed_url=BOJ_FEED,
        state_file=BOJ_STATE,
    )


def fetch_boe():
    _fetch_latest(
        source="Bank of England (BoE)",
        feed_url=BOE_FEED,
        state_file=BOE_STATE,
    )

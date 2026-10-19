import html
import re
import urllib.parse

from core.network import download
from core.state import read_state, write_state
from core.telegram import send_one


NASDAQ_ALERT_FEEDS = [
    (
        "Nasdaq Equity Trader Alerts",
        "https://www.nasdaqtrader.com/rss.aspx?feed=tradealerts",
    ),
    (
        "Nasdaq Regulatory Alerts",
        "https://www.nasdaqtrader.com/rss.aspx?feed=regulatoryalerts",
    ),
    (
        "Nasdaq Technical Updates",
        "https://www.nasdaqtrader.com/rss.aspx?feed=technicalupdates",
    ),
]


def _to_text(raw):
    if isinstance(raw, bytes):
        return raw.decode(
            "utf-8",
            errors="replace",
        )

    return str(raw or "")


def _clean_text(value):
    value = re.sub(
        r"<!\[CDATA\[(.*?)\]\]>",
        r"\1",
        str(value or ""),
        flags=re.DOTALL,
    )

    value = re.sub(
        r"<[^>]+>",
        " ",
        value,
    )

    value = html.unescape(
        value
    )

    return " ".join(
        value.split()
    )


def _extract_tag(block, tag):
    patterns = [
        rf"<{tag}\b[^>]*>(.*?)</{tag}>",
        rf"<[A-Za-z0-9_-]+:{tag}\b[^>]*>"
        rf"(.*?)"
        rf"</[A-Za-z0-9_-]+:{tag}>",
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            block,
            flags=(
                re.IGNORECASE
                | re.DOTALL
            ),
        )

        if match:
            return _clean_text(
                match.group(1)
            )

    return ""


def _extract_items(raw):
    text = _to_text(raw)

    text = text.replace(
        "\x00",
        "",
    )

    matches = re.findall(
        r"<item\b[^>]*>(.*?)</item>",
        text,
        flags=(
            re.IGNORECASE
            | re.DOTALL
        ),
    )

    return matches


def fetch_nasdaq_equity_alerts():
    source = "Nasdaq Equity Alerts"
    state_file = ".last_nasdaq_equity_alerts"

    try:
        all_rows = []

        for feed_name, url in NASDAQ_ALERT_FEEDS:
            try:
                raw = download(
                    url
                )

                items = _extract_items(
                    raw
                )

                print(
                    f"{feed_name}: "
                    f"found {len(items)} alert(s)."
                )

                for item in items:
                    title = _extract_tag(
                        item,
                        "title",
                    )

                    link = _extract_tag(
                        item,
                        "link",
                    )

                    guid = _extract_tag(
                        item,
                        "guid",
                    )

                    pub_date = _extract_tag(
                        item,
                        "pubDate",
                    )

                    description = _extract_tag(
                        item,
                        "description",
                    )

                    if not title:
                        continue

                    if link:
                        link = urllib.parse.urljoin(
                            url,
                            link,
                        )

                    stable_id = (
                        guid
                        or link
                        or (
                            f"{feed_name}:"
                            f"{pub_date}:"
                            f"{title}"
                        )
                    )

                    all_rows.append({
                        "id": stable_id,
                        "feed": feed_name,
                        "title": title,
                        "link": link,
                        "pub_date": pub_date,
                        "description": description,
                    })

            except Exception as feed_error:
                print(
                    f"{feed_name} failed, "
                    f"skipping: {feed_error}"
                )

        if not all_rows:
            raise RuntimeError(
                "Nasdaq alert feeds returned "
                "no usable alerts"
            )

        unique_rows = []
        seen_ids = set()

        for row in all_rows:
            if row["id"] in seen_ids:
                continue

            seen_ids.add(
                row["id"]
            )

            unique_rows.append(
                row
            )

        state = read_state(
            state_file
        )

        current_ids = [
            row["id"]
            for row in unique_rows
        ]

        if not state["initialized"]:
            write_state(
                state_file,
                current_ids,
            )

            print(
                "Nasdaq Equity Alerts: "
                "initialized baseline with "
                f"{len(unique_rows)} alert(s); "
                "no historical messages sent."
            )

            return

        known = set(
            state["ids"]
        )

        unseen = [
            row
            for row in unique_rows
            if row["id"] not in known
        ]

        if not unseen:
            print(
                "No new Nasdaq Equity Alerts."
            )
            return

        for row in reversed(unseen):
            details = [
                f"Category: {row['feed']}",
            ]

            if row["pub_date"]:
                details.append(
                    f"Published: {row['pub_date']}"
                )

            if row["description"]:
                details.append(
                    "Summary: "
                    f"{row['description'][:800]}"
                )

            details.append(
                "Source: Nasdaq Trader official alert feed"
            )

            send_one(
                source,
                "🚨",
                row["title"],
                (
                    row["link"]
                    or "https://www.nasdaqtrader.com/"
                ),
                state_file,
                item_id=row["id"],
                details="\n".join(
                    details
                ),
            )

        updated_ids = (
            state["ids"]
            + current_ids
        )

        write_state(
            state_file,
            updated_ids,
        )

    except Exception as error:
        print(
            f"{source} failed, "
            f"skipping: {error}"
        )

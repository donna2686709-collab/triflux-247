import html
import re
import urllib.parse
import xml.etree.ElementTree as ET

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


def _clean(value):
    return " ".join(
        html.unescape(
            str(value or "")
        ).split()
    )


def _clean_xml(raw):
    if isinstance(raw, bytes):
        raw = raw.decode(
            "utf-8",
            errors="replace",
        )

    raw = str(raw)

    # Remove control characters that are illegal in XML 1.0.
    raw = re.sub(
        r"[\x00-\x08\x0B\x0C\x0E-\x1F]",
        "",
        raw,
    )

    # Nasdaq feeds can contain bare ampersands.
    raw = re.sub(
        r"&(?!amp;|lt;|gt;|quot;|apos;|#\d+;|#x[0-9A-Fa-f]+;)",
        "&amp;",
        raw,
    )

    return raw


def _text(node, name):
    value = node.findtext(name)

    if value is None:
        value = node.findtext(
            f"{{*}}{name}"
        )

    return _clean(value)


def fetch_nasdaq_equity_alerts():
    source = "Nasdaq Equity Alerts"
    state_file = ".last_nasdaq_equity_alerts"

    try:
        all_rows = []

        for feed_name, url in NASDAQ_ALERT_FEEDS:
            try:
                raw = download(url)

                root = ET.fromstring(
                    _clean_xml(raw)
                )

                items = root.findall(
                    ".//item"
                )

                if not items:
                    items = root.findall(
                        ".//{*}item"
                    )

                print(
                    f"{feed_name}: "
                    f"found {len(items)} alert(s)."
                )

                for item in items:
                    title = _text(
                        item,
                        "title",
                    )

                    link = _text(
                        item,
                        "link",
                    )

                    guid = _text(
                        item,
                        "guid",
                    )

                    pub_date = _text(
                        item,
                        "pubDate",
                    )

                    description = _text(
                        item,
                        "description",
                    )

                    if link:
                        link = urllib.parse.urljoin(
                            url,
                            link,
                        )

                    if not title:
                        continue

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

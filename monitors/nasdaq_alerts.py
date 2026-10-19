import html
import re
import urllib.parse

from core.network import download
from core.state import read_state, write_state
from core.telegram import send_one


NASDAQ_ARCHIVE_URL = (
    "https://www.nasdaqtrader.com/"
    "Trader.aspx?cat_id=2&id=archiveheadlines"
)


def _clean_text(value):
    value = re.sub(
        r"<script\b[^>]*>.*?</script>",
        " ",
        str(value or ""),
        flags=re.IGNORECASE | re.DOTALL,
    )

    value = re.sub(
        r"<style\b[^>]*>.*?</style>",
        " ",
        value,
        flags=re.IGNORECASE | re.DOTALL,
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


def _extract_alerts(raw):
    if isinstance(raw, bytes):
        text = raw.decode(
            "utf-8",
            errors="replace",
        )
    else:
        text = str(raw or "")

    rows = []

    link_pattern = re.compile(
        r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>'
        r"(.*?)"
        r"</a>",
        flags=re.IGNORECASE | re.DOTALL,
    )

    for match in link_pattern.finditer(text):
        href = html.unescape(
            match.group(1)
        ).strip()

        title = _clean_text(
            match.group(2)
        )

        if not title:
            continue

        title_lower = title.lower()

        is_equity_alert = (
            "equity trader alert" in title_lower
            or "equity regulatory alert" in title_lower
            or "equity technical update" in title_lower
        )

        if not is_equity_alert:
            continue

        link = urllib.parse.urljoin(
            NASDAQ_ARCHIVE_URL,
            href,
        )

        rows.append({
            "id": link,
            "title": title,
            "link": link,
        })

    unique_rows = []
    seen_ids = set()

    for row in rows:
        if row["id"] in seen_ids:
            continue

        seen_ids.add(
            row["id"]
        )

        unique_rows.append(
            row
        )

    return unique_rows


def fetch_nasdaq_equity_alerts():
    source = "Nasdaq Equity Alerts"
    state_file = ".last_nasdaq_equity_alerts"

    try:
        raw = download(
            NASDAQ_ARCHIVE_URL
        )

        if isinstance(raw, bytes):
            debug_text = raw.decode(
                "utf-8",
                errors="replace",
            )
        else:
            debug_text = str(raw or "")

                debug_lower = debug_text.lower()

        debug_position = debug_lower.find(
            "equity trader alert"
        )

        if debug_position == -1:
            debug_position = debug_lower.find(
                "tradernews.aspx"
            )

        if debug_position == -1:
            print(
                "Nasdaq Equity Alerts DEBUG: "
                "no Equity Trader Alert text found."
            )
        else:
            debug_start = max(
                0,
                debug_position - 1000,
            )

            debug_end = min(
                len(debug_text),
                debug_position + 3000,
            )

            print(
                "Nasdaq Equity Alerts DEBUG MATCH: "
                f"{repr(debug_text[debug_start:debug_end])}"
            )

        rows = _extract_alerts(
            raw
        )

        print(
            "Nasdaq Equity Alerts: "
            f"found {len(rows)} official alert(s)."
        )

        if not rows:
            raise RuntimeError(
                "Nasdaq official archive returned "
                "no usable Equity Alerts"
            )

        state = read_state(
            state_file
        )

        current_ids = [
            row["id"]
            for row in rows
        ]

        if not state["initialized"]:
            write_state(
                state_file,
                current_ids,
            )

            print(
                "Nasdaq Equity Alerts: "
                "initialized baseline with "
                f"{len(rows)} alert(s); "
                "no historical messages sent."
            )

            return

        known = set(
            state["ids"]
        )

        unseen = [
            row
            for row in rows
            if row["id"] not in known
        ]

        if not unseen:
            print(
                "No new Nasdaq Equity Alerts."
            )
            return

        for row in reversed(unseen):
            title_lower = row[
                "title"
            ].lower()

            if "regulatory" in title_lower:
                category = (
                    "Equity Regulatory Alert"
                )
                emoji = "🚨"

            elif "technical" in title_lower:
                category = (
                    "Equity Technical Update"
                )
                emoji = "🟠"

            else:
                category = (
                    "Equity Trader Alert"
                )
                emoji = "🔴"

            details = "\n".join([
                f"Category: {category}",
                (
                    "Source: Nasdaq Trader "
                    "official alert archive"
                ),
            ])

            send_one(
                source,
                emoji,
                row["title"],
                row["link"],
                state_file,
                item_id=row["id"],
                details=details,
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

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
    value = str(value or "")

    value = re.sub(
        r"<script\b[^>]*>.*?</script>",
        " ",
        value,
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


def _to_text(raw):
    if isinstance(raw, bytes):
        return raw.decode(
            "utf-8",
            errors="replace",
        )

    return str(raw or "")


def _extract_alerts(raw):
    text = _to_text(
        raw
    )

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

        if not href or not title:
            continue

        href_lower = href.lower()
        title_lower = title.lower()

        is_alert = (
            "tradernews.aspx" in href_lower
            or "equity trader alert" in title_lower
            or "equity regulatory alert" in title_lower
            or "equity technical update" in title_lower
        )

        if not is_alert:
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


def _print_debug_match(text):
    text_lower = text.lower()

    search_terms = [
        "equity trader alert",
        "tradernews.aspx",
        "equity regulatory alert",
        "equity technical update",
    ]

    position = -1
    matched_term = ""

    for term in search_terms:
        position = text_lower.find(
            term
        )

        if position != -1:
            matched_term = term
            break

    if position == -1:
        print(
            "Nasdaq Equity Alerts DEBUG: "
            "no alert text or TraderNews link found."
        )
        return

    start = max(
        0,
        position - 1000,
    )

    end = min(
        len(text),
        position + 3000,
    )

    snippet = text[
        start:end
    ]

    print(
        "Nasdaq Equity Alerts DEBUG MATCH: "
        f"term={matched_term!r}, "
        f"position={position}, "
        f"html={snippet!r}"
    )


def fetch_nasdaq_equity_alerts():
    source = "Nasdaq Equity Alerts"
    state_file = ".last_nasdaq_equity_alerts"

    try:
        raw = download(
            NASDAQ_ARCHIVE_URL
        )

        debug_text = _to_text(
            raw
        )

        print(
            "Nasdaq Equity Alerts: "
            f"archive response length="
            f"{len(debug_text)}."
        )

        _print_debug_match(
            debug_text
        )

        rows = _extract_alerts(
            raw
        )

        print(
            "Nasdaq Equity Alerts: "
            f"found {len(rows)} "
            "candidate official alert(s)."
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

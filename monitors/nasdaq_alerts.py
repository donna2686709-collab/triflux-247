import html
import re
import urllib.parse

from core.network import download
from core.state import read_state, write_state
from core.telegram import send_one


NASDAQ_EQUITY_ALERTS_URL = (
    "https://www.nasdaqtrader.com/"
    "Trader.aspx?id=EquityTraderAlerts"
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
        r'(.*?)'
        r'</a>',
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

        if (
            "equity trader alert" not in title_lower
            and "equity regulatory alert" not in title_lower
            and "equity technical update" not in title_lower
        ):
            continue

        link = urllib.parse.urljoin(
            NASDAQ_EQUITY_ALERTS_URL,
            href,
        )

        stable_id = link

        rows.append({
            "id": stable_id,
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
            NASDAQ_EQUITY_ALERTS_URL
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
                "Nasdaq Equity Alerts page "
                "returned no usable alerts"
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
                    "official Equity Alerts"
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

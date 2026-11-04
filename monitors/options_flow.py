"""TriFlux #30 — Cboe U.S. options activity monitor.

Cboe intraday tables are cumulative and may be delayed.
Only consecutive observations from the same market date are compared.
This module is deliberately conservative: no historical alerts on initialization.
"""
import html
import json
import os
import re
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

SOURCE_URL = "https://www.cboe.com/us/options/market_statistics/market/"
STATE_FILE = ".last_cboe_options_flow"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; TriFlux247/2.0)", "Accept-Language": "en-US,en;q=0.9"}


def _read_page():
    request = urllib.request.Request(SOURCE_URL, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=25) as response:
        return response.read().decode("utf-8", errors="replace")


def _section(page, start, end=None):
    match = re.search(re.escape(start) + r"(.*?)" + (re.escape(end) if end else r"$"), page, re.I | re.S)
    return match.group(1) if match else ""


def _rows(section):
    section = re.sub(r"<(?:script|style)\b[^>]*>.*?</(?:script|style)>", " ", section, flags=re.I | re.S)
    section = html.unescape(re.sub(r"<[^>]+>", " ", section))
    section = " ".join(section.split())
    pattern = re.compile(r"(\d{1,2}:\d{2}\s*(?:AM|PM))\s+([\d,]+)\s+([\d,]+)\s+([\d,]+)\s+(\d+(?:\.\d+)?)", re.I)
    result = []
    for match in pattern.finditer(section):
        calls, puts, total = (int(match.group(i).replace(",", "")) for i in (2, 3, 4))
        if abs(calls + puts - total) > max(2, total * 0.01):
            continue
        result.append({"time": " ".join(match.group(1).upper().split()), "calls": calls, "puts": puts, "total": total})
    return result


def _parse(page):
    # Refuse to invent data if Cboe changes the structure of its public page.
    sections = {
        "total": _section(page, "Total", "Index Options"),
        "index": _section(page, "Index Options", "Equity Options"),
        "equity": _section(page, "Equity Options"),
    }
    result = {name: _rows(value) for name, value in sections.items()}
    if not all(result.values()):
        raise ValueError("Cboe tables not found in downloaded HTML; source/parser requires review")
    latest = {name: rows[-1] for name, rows in result.items()}
    if len({row["time"] for row in latest.values()}) != 1:
        raise ValueError("Cboe tables have inconsistent latest timestamps")
    return latest


def _save(state):
    temp = STATE_FILE + ".tmp"
    with open(temp, "w", encoding="utf-8") as stream:
        json.dump(state, stream, ensure_ascii=False, indent=2)
    os.replace(temp, STATE_FILE)


def _interval(before, after):
    delta = {key: after[key] - before[key] for key in ("calls", "puts", "total")}
    if any(value < 0 for value in delta.values()):
        raise ValueError("Cboe cumulative volume decreased; resetting baseline")
    delta["pc_ratio"] = delta["puts"] / delta["calls"] if delta["calls"] else None
    return delta


def fetch_options_flow():
    """Check Cboe options tables without disrupting other TriFlux monitors."""
    try:
        page = _read_page()
        latest = _parse(page)
        # Cboe table clock labels alone are not unique across trading days.
        # Date is used for reset protection, not asserted as the source timestamp.
        market_date = datetime.now(ZoneInfo("America/Chicago")).date().isoformat()
        state = {}
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, "r", encoding="utf-8") as stream:
                    state = json.load(stream)
            except (OSError, ValueError, TypeError):
                state = {}

        current_time = latest["total"]["time"]
        if state.get("market_date") != market_date or not isinstance(state.get("latest"), dict):
            _save({"market_date": market_date, "latest": latest, "updated_utc": datetime.now(timezone.utc).isoformat()})
            print(f"Cboe Options Flow: baseline initialized at {current_time} CT; no historical alerts.")
            return

        previous = state["latest"]
        if previous.get("total", {}).get("time") == current_time:
            print(f"Cboe Options Flow: no new observation ({current_time} CT).")
            return

        index = _interval(previous["index"], latest["index"])
        equity = _interval(previous["equity"], latest["equity"])
        print(
            f"Cboe Options Flow: {previous['total']['time']} -> {current_time} CT | "
            f"Index calls={index['calls']:,} puts={index['puts']:,} P/C={index['pc_ratio']} | "
            f"Equity calls={equity['calls']:,} puts={equity['puts']:,} P/C={equity['pc_ratio']}"
        )
        # Alert delivery remains disabled until the public source's format,
        # data delay and interval calculations have been validated in logs.
        print("Cboe Options Flow: observation recorded; directional alerts pending validation.")
        _save({"market_date": market_date, "latest": latest, "updated_utc": datetime.now(timezone.utc).isoformat()})
    except Exception as error:
        print(f"Cboe Options Flow: source check failed; skipped safely: {error}")


if __name__ == "__main__":
    fetch_options_flow()

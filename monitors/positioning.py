import json
import os
import urllib.parse
import urllib.request


CFTC_COT_TFF_URL = "https://publicreporting.cftc.gov/resource/yw9f-hn96.json"
CFTC_COT_TFF_STATE = ".last_cftc_cot_tff"

GENERAL_USER_AGENT = "Mozilla/5.0 (compatible; TriFlux247/2.0)"


def _download_json(url):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": GENERAL_USER_AGENT,
            "Accept": "application/json",
        },
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _read_last_report_date():
    if not os.path.exists(CFTC_COT_TFF_STATE):
        return ""

    try:
        with open(CFTC_COT_TFF_STATE, "r", encoding="utf-8") as file:
            return file.read().strip()
    except Exception:
        return ""


def _write_last_report_date(report_date):
    with open(CFTC_COT_TFF_STATE, "w", encoding="utf-8") as file:
        file.write(report_date)


def _number(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def fetch_cftc_cot_tff():
    """
    Fetch the latest CFTC Traders in Financial Futures (TFF) Combined report.

    During the modularization stage this function intentionally does not send
    Telegram messages. The existing radar.py remains the production source
    until the new module has been verified.
    """

    try:
        params = {
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
        }

        url = CFTC_COT_TFF_URL + "?" + urllib.parse.urlencode(params)
        rows = _download_json(url)

        if not rows:
            print("CFTC COT TFF: no data returned.")
            return

        latest_report_date = rows[0].get("report_date_as_yyyy_mm_dd", "").strip()

        if not latest_report_date:
            print("CFTC COT TFF: latest report date missing.")
            return

        latest_rows = [
            row
            for row in rows
            if row.get("report_date_as_yyyy_mm_dd", "").strip()
            == latest_report_date
        ]

        if not latest_rows:
            print("CFTC COT TFF: no rows found for latest report date.")
            return

        previous_report_date = _read_last_report_date()

        if not previous_report_date:
            print(
                "CFTC COT TFF module test: "
                f"latest report date {latest_report_date}; "
                f"{len(latest_rows)} market rows available."
            )
            print(
                "CFTC COT TFF module test: production state was not changed."
            )
            return

        if previous_report_date == latest_report_date:
            print(
                "CFTC COT TFF module test: "
                f"latest report remains {latest_report_date}; "
                f"{len(latest_rows)} market rows available."
            )
            return

        total_open_interest = sum(
            _number(row.get("open_interest_all"))
            for row in latest_rows
        )

        print(
            "CFTC COT TFF module test: "
            f"new report {latest_report_date}; "
            f"{len(latest_rows)} market rows; "
            f"combined open interest {total_open_interest:,}."
        )

        print(
            "CFTC COT TFF module test: "
            "production state was not changed."
        )

    except Exception as exc:
        print(f"CFTC COT TFF module error: {exc}")

import json
import urllib.parse
from datetime import datetime, timezone, timedelta

from core.network import download
from core.state import read_state, write_state
from core.telegram import send_one


def fetch_sofr():
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

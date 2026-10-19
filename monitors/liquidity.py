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


def fetch_on_rrp():
    source = (
        "New York Fed ON RRP"
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
            "api/rp/reverserepo/propositions/"
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

        operations = (
            data.get("repo")
            or data.get("repos")
            or data.get("operations")
            or []
        )

        if not operations:
            raise RuntimeError(
                "ON RRP API returned "
                "no operations"
            )

        operations.sort(
            key=lambda row: str(
                row.get(
                    "operationDate",
                    row.get(
                        "operation_date",
                        "",
                    ),
                )
            ),
            reverse=True,
        )

        row = operations[0]

        operation_date = str(
            row.get(
                "operationDate",
                row.get(
                    "operation_date",
                    "",
                ),
            )
        )

        accepted = (
            row.get("totalAmtAccepted")
            or row.get("totalAmountAccepted")
            or row.get("amountAccepted")
        )

        submitted = (
            row.get("totalAmtSubmitted")
            or row.get("totalAmountSubmitted")
            or row.get("amountSubmitted")
        )

        rate = (
            row.get("awardRate")
            or row.get("rate")
        )

        counterparties = (
            row.get("participatingCpty")
            or row.get("participatingCounterparties")
            or row.get("counterparties")
        )

        if not operation_date:
            raise RuntimeError(
                "ON RRP response has "
                "no operation date"
            )

        if accepted is None:
            raise RuntimeError(
                "ON RRP response has "
                "no accepted amount"
            )

        stable_id = (
            f"ONRRP:"
            f"{operation_date}:"
            f"{accepted}"
        )

        state_file = (
            ".last_nyfed_on_rrp"
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
                "New York Fed ON RRP: "
                "initialized baseline "
                f"{operation_date}, "
                f"accepted={accepted}; "
                "no historical message sent."
            )

            return

        if stable_id in state["ids"]:
            print(
                "No new ON RRP operation; "
                f"latest is "
                f"{operation_date}, "
                f"accepted={accepted}."
            )
            return

        link = (
            "https://www.newyorkfed.org/"
            "markets/desk-operations/"
            "reverse-repo"
        )

        detail_lines = [
            f"Operation date: {operation_date}",
            f"Accepted amount: {accepted}",
        ]

        if submitted is not None:
            detail_lines.append(
                f"Submitted amount: {submitted}"
            )

        if rate is not None:
            detail_lines.append(
                f"Award rate: {rate}"
            )

        if counterparties is not None:
            detail_lines.append(
                "Participating counterparties: "
                f"{counterparties}"
            )

        detail_lines.append(
            "Source: Federal Reserve Bank "
            "of New York official market operations data"
        )

        details = "\n".join(
            detail_lines
        )

        send_one(
            source,
            "🇺🇸",
            (
                "ON RRP "
                f"{operation_date} "
                f"— accepted {accepted}"
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

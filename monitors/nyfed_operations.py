import json
from datetime import datetime, timedelta, timezone

from core.network import download
from core.state import read_state, write_state
from core.telegram import send_one


TREASURY_RESULTS_URL = (
    "https://markets.newyorkfed.org/"
    "api/tsy/all/results/details/search.json"
)

MBS_RESULTS_URL = (
    "https://markets.newyorkfed.org/"
    "api/ambs/all/results/details/search.json"
)

TREASURY_PUBLIC_URL = (
    "https://www.newyorkfed.org/markets/"
    "domestic-market-operations/"
    "monetary-policy-implementation/"
    "treasury-securities/"
    "treasury-securities-operational-details"
)

MBS_PUBLIC_URL = (
    "https://www.newyorkfed.org/markets/"
    "domestic-market-operations/"
    "monetary-policy-implementation/"
    "agency-mortgage-backed-securities/"
    "agency-mortgage-backed-securities-operations"
)


def _text(value):
    if value is None:
        return ""

    return str(value).strip()


def _first(row, *keys):
    for key in keys:
        value = row.get(key)

        if value not in (
            None,
            "",
        ):
            return value

    return ""


def _money(value):
    if value in (
        None,
        "",
    ):
        return "N/A"

    try:
        number = float(
            str(value).replace(
                ",",
                "",
            )
        )
    except (
        TypeError,
        ValueError,
    ):
        return str(value)

    absolute = abs(number)

    if absolute >= 1_000_000_000:
        return (
            f"${number / 1_000_000_000:,.2f}B"
        )

    if absolute >= 1_000_000:
        return (
            f"${number / 1_000_000:,.2f}M"
        )

    if absolute >= 1_000:
        return (
            f"${number / 1_000:,.2f}K"
        )

    return f"${number:,.2f}"


def _direction(value):
    value = _text(
        value
    )

    upper = value.upper()

    if upper in (
        "P",
        "PURCHASE",
        "PURCHASES",
        "BUY",
    ):
        return "Purchase"

    if upper in (
        "S",
        "SALE",
        "SALES",
        "SELL",
    ):
        return "Sale"

    return value or "Unknown"


def _operation_id(
    row,
    prefix,
):
    operation_id = _first(
        row,
        "operationId",
        "operationID",
        "auctionId",
        "auctionID",
        "id",
    )

    if operation_id:
        return (
            f"{prefix}:"
            f"{operation_id}"
        )

    parts = [
        prefix,
        _text(
            _first(
                row,
                "operationDate",
                "auctionDate",
                "date",
            )
        ),
        _text(
            _first(
                row,
                "operationType",
                "type",
            )
        ),
        _text(
            _first(
                row,
                "operationDirection",
                "direction",
            )
        ),
        _text(
            _first(
                row,
                "closeTime",
                "releaseTime",
            )
        ),
        _text(
            _first(
                row,
                "totalParAmtAccepted",
                "totalAmtAcceptedPar",
                "totalAmtAccepted",
            )
        ),
    ]

    return ":".join(
        parts
    )


def _extract_rows(
    data,
    group_name,
):
    if not isinstance(
        data,
        dict,
    ):
        return []

    group = data.get(
        group_name
    )

    if isinstance(
        group,
        dict,
    ):
        rows = group.get(
            "auctions"
        )

        if isinstance(
            rows,
            list,
        ):
            return rows

    rows = data.get(
        "auctions"
    )

    if isinstance(
        rows,
        list,
    ):
        return rows

    return []


def _download_json(
    base_url,
):
    today = datetime.now(
        timezone.utc
    ).date()

    start = (
        today
        - timedelta(
            days=45
        )
    )

    separator = (
        "&"
        if "?" in base_url
        else "?"
    )

    url = (
        f"{base_url}"
        f"{separator}"
        f"startDate={start.isoformat()}"
        f"&endDate={today.isoformat()}"
    )

    raw = download(
        url
    )

    return json.loads(
        raw.decode(
            "utf-8",
            errors="replace",
        )
    )


def _sort_key(row):
    return (
        _text(
            _first(
                row,
                "operationDate",
                "auctionDate",
                "date",
            )
        ),
        _text(
            _first(
                row,
                "releaseTime",
                "closeTime",
                "lastUpdated",
            )
        ),
        _text(
            _first(
                row,
                "operationId",
                "auctionId",
                "id",
            )
        ),
    )


def _treasury_details(
    row,
):
    operation_date = _first(
        row,
        "operationDate",
        "auctionDate",
        "date",
    )

    settlement_date = _first(
        row,
        "settlementDate",
    )

    operation_type = _first(
        row,
        "operationType",
        "type",
    )

    direction = _direction(
        _first(
            row,
            "operationDirection",
            "direction",
        )
    )

    submitted = _first(
        row,
        "totalParAmtSubmitted",
        "totalAmtSubmittedPar",
        "totalAmtSubmitted",
    )

    accepted = _first(
        row,
        "totalParAmtAccepted",
        "totalAmtAcceptedPar",
        "totalAmtAccepted",
    )

    status = _first(
        row,
        "auctionStatus",
        "status",
    )

    lines = [
        (
            "Asset: U.S. Treasury "
            "securities"
        ),
        (
            f"Direction: "
            f"{direction}"
        ),
    ]

    if operation_type:
        lines.append(
            f"Operation type: "
            f"{operation_type}"
        )

    if operation_date:
        lines.append(
            f"Operation date: "
            f"{operation_date}"
        )

    if settlement_date:
        lines.append(
            f"Settlement date: "
            f"{settlement_date}"
        )

    if submitted not in (
        None,
        "",
    ):
        lines.append(
            "Submitted: "
            + _money(
                submitted
            )
        )

    if accepted not in (
        None,
        "",
    ):
        lines.append(
            "Accepted: "
            + _money(
                accepted
            )
        )

    if status:
        lines.append(
            f"Status: {status}"
        )

    lines.extend([
        (
            "Market layer: "
            "Federal Reserve Bank of "
            "New York / SOMA operation"
        ),
        (
            "Source: Federal Reserve Bank "
            "of New York official "
            "Markets Data API"
        ),
    ])

    return "\n".join(
        lines
    )


def _mbs_details(
    row,
):
    operation_date = _first(
        row,
        "operationDate",
        "auctionDate",
        "date",
    )

    settlement_date = _first(
        row,
        "settlementDate",
    )

    operation_type = _first(
        row,
        "operationType",
        "type",
    )

    direction = _direction(
        _first(
            row,
            "operationDirection",
            "direction",
        )
    )

    method = _first(
        row,
        "method",
    )

    class_type = _first(
        row,
        "classType",
    )

    submitted = _first(
        row,
        "totalAmtSubmittedPar",
        "totalParAmtSubmitted",
        "totalAmtSubmitted",
    )

    accepted = _first(
        row,
        "totalAmtAcceptedPar",
        "totalParAmtAccepted",
        "totalAmtAccepted",
    )

    status = _first(
        row,
        "auctionStatus",
        "status",
    )

    lines = [
        "Asset: Agency MBS",
        (
            f"Direction: "
            f"{direction}"
        ),
    ]

    if operation_type:
        lines.append(
            f"Operation type: "
            f"{operation_type}"
        )

    if class_type:
        lines.append(
            f"Class: {class_type}"
        )

    if method:
        lines.append(
            f"Method: {method}"
        )

    if operation_date:
        lines.append(
            f"Operation date: "
            f"{operation_date}"
        )

    if settlement_date:
        lines.append(
            f"Settlement date: "
            f"{settlement_date}"
        )

    if submitted not in (
        None,
        "",
    ):
        lines.append(
            "Submitted: "
            + _money(
                submitted
            )
        )

    if accepted not in (
        None,
        "",
    ):
        lines.append(
            "Accepted: "
            + _money(
                accepted
            )
        )

    if status:
        lines.append(
            f"Status: {status}"
        )

    lines.extend([
        (
            "Market layer: "
            "Federal Reserve Bank of "
            "New York / SOMA operation"
        ),
        (
            "Note: small-value/test "
            "operations should not by "
            "themselves be interpreted "
            "as a monetary-policy change."
        ),
        (
            "Source: Federal Reserve Bank "
            "of New York official "
            "Markets Data API"
        ),
    ])

    return "\n".join(
        lines
    )


def _treasury_title(
    row,
):
    direction = _direction(
        _first(
            row,
            "operationDirection",
            "direction",
        )
    )

    operation_type = _text(
        _first(
            row,
            "operationType",
            "type",
        )
    )

    accepted = _first(
        row,
        "totalParAmtAccepted",
        "totalAmtAcceptedPar",
        "totalAmtAccepted",
    )

    title = (
        "NY Fed Treasury "
        f"{direction}"
    )

    if operation_type:
        title += (
            f" — {operation_type}"
        )

    if accepted not in (
        None,
        "",
    ):
        title += (
            " — Accepted "
            + _money(
                accepted
            )
        )

    return title


def _mbs_title(
    row,
):
    direction = _direction(
        _first(
            row,
            "operationDirection",
            "direction",
        )
    )

    operation_type = _text(
        _first(
            row,
            "operationType",
            "type",
        )
    )

    accepted = _first(
        row,
        "totalAmtAcceptedPar",
        "totalParAmtAccepted",
        "totalAmtAccepted",
    )

    title = (
        "NY Fed Agency MBS "
        f"{direction}"
    )

    if operation_type:
        title += (
            f" — {operation_type}"
        )

    if accepted not in (
        None,
        "",
    ):
        title += (
            " — Accepted "
            + _money(
                accepted
            )
        )

    return title


def _monitor_operations(
    source,
    state_file,
    prefix,
    data,
    group_name,
    public_url,
    title_builder,
    details_builder,
):
    rows = _extract_rows(
        data,
        group_name,
    )

    rows = [
        row
        for row in rows
        if isinstance(
            row,
            dict,
        )
    ]

    if not rows:
        print(
            f"{source}: "
            "official API returned "
            "no operation results "
            "in the lookback window."
        )
        return

    rows.sort(
        key=_sort_key
    )

    ids = [
        _operation_id(
            row,
            prefix,
        )
        for row in rows
    ]

    state = read_state(
        state_file
    )

    if not state[
        "initialized"
    ]:
        write_state(
            state_file,
            ids,
        )

        print(
            f"{source}: initialized "
            f"baseline with "
            f"{len(rows)} operation(s); "
            "no historical messages sent."
        )

        return

    known = set(
        state["ids"]
    )

    unseen = [
        row
        for row in rows
        if _operation_id(
            row,
            prefix,
        ) not in known
    ]

    if not unseen:
        print(
            f"No new {source} "
            "operation results."
        )
        return

    for row in unseen:
        stable_id = _operation_id(
            row,
            prefix,
        )

        direction = _direction(
            _first(
                row,
                "operationDirection",
                "direction",
            )
        )

        if direction == "Purchase":
            emoji = "🔴"
        elif direction == "Sale":
            emoji = "🚨"
        else:
            emoji = "🟠"

        send_one(
            source,
            emoji,
            title_builder(
                row
            ),
            public_url,
            state_file,
            item_id=stable_id,
            details=details_builder(
                row
            ),
        )

    updated_ids = (
        state["ids"]
        + ids
    )

    write_state(
        state_file,
        updated_ids,
    )


def fetch_nyfed_treasury_operations():
    source = (
        "NY Fed Treasury Operations"
    )

    try:
        data = _download_json(
            TREASURY_RESULTS_URL
        )

        _monitor_operations(
            source=source,
            state_file=(
                ".last_nyfed_treasury_operations"
            ),
            prefix="NYFED-TSY",
            data=data,
            group_name="treasury",
            public_url=TREASURY_PUBLIC_URL,
            title_builder=_treasury_title,
            details_builder=_treasury_details,
        )

    except Exception as error:
        print(
            f"{source} failed, "
            f"skipping: {error}"
        )


def fetch_nyfed_mbs_operations():
    source = (
        "NY Fed Agency MBS Operations"
    )

    try:
        data = _download_json(
            MBS_RESULTS_URL
        )

        _monitor_operations(
            source=source,
            state_file=(
                ".last_nyfed_mbs_operations"
            ),
            prefix="NYFED-MBS",
            data=data,
            group_name="ambs",
            public_url=MBS_PUBLIC_URL,
            title_builder=_mbs_title,
            details_builder=_mbs_details,
        )

    except Exception as error:
        print(
            f"{source} failed, "
            f"skipping: {error}"
        )


def fetch_nyfed_market_operations():
    fetch_nyfed_treasury_operations()
    fetch_nyfed_mbs_operations()

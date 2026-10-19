import json
import urllib.parse
from datetime import datetime, timedelta, timezone

from core.network import download
from core.state import read_state, write_state
from core.telegram import send_one


API_URL = (
    "https://api.fiscaldata.treasury.gov/"
    "services/api/fiscal_service/v1/"
    "accounting/od/auctions_query"
)

PUBLIC_URL = (
    "https://fiscaldata.treasury.gov/"
    "datasets/treasury-securities-auctions-data/"
    "treasury-securities-auctions-data"
)

STATE_FILE = ".last_treasury_auction_results"


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


def _number(value):
    if value in (
        None,
        "",
    ):
        return None

    try:
        return float(
            str(value)
            .replace(",", "")
            .replace("$", "")
            .replace("%", "")
        )
    except (
        TypeError,
        ValueError,
    ):
        return None


def _money(value):
    number = _number(
        value
    )

    if number is None:
        return _text(value) or "N/A"

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


def _percent(value):
    if value in (
        None,
        "",
    ):
        return "N/A"

    text = _text(
        value
    )

    if text.endswith("%"):
        return text

    number = _number(
        value
    )

    if number is None:
        return text

    return f"{number:g}%"


def _ratio(
    tendered,
    accepted,
):
    tendered_number = _number(
        tendered
    )

    accepted_number = _number(
        accepted
    )

    if (
        tendered_number is None
        or accepted_number is None
        or accepted_number == 0
    ):
        return None

    return (
        tendered_number
        / accepted_number
    )


def _share(
    amount,
    total,
):
    amount_number = _number(
        amount
    )

    total_number = _number(
        total
    )

    if (
        amount_number is None
        or total_number is None
        or total_number == 0
    ):
        return None

    return (
        amount_number
        / total_number
        * 100.0
    )


def _date_value(row):
    return _text(
        _first(
            row,
            "auction_date",
            "auctionDate",
        )
    )[:10]


def _cusip(row):
    return _text(
        _first(
            row,
            "cusip",
            "cusip_number",
            "cusipNumber",
        )
    )


def _security_term(row):
    term = _text(
        _first(
            row,
            "security_term",
            "securityTerm",
            "term",
        )
    )

    security_type = _text(
        _first(
            row,
            "security_type",
            "securityType",
            "type",
        )
    )

    if (
        term
        and security_type
        and security_type.lower()
        not in term.lower()
    ):
        return (
            f"{term} {security_type}"
        )

    return (
        term
        or security_type
        or "Treasury Security"
    )


def _stable_id(row):
    auction_date = _date_value(
        row
    )

    cusip = _cusip(
        row
    )

    issue_date = _text(
        _first(
            row,
            "issue_date",
            "issueDate",
        )
    )[:10]

    return (
        "TREASURY-AUCTION:"
        f"{auction_date}:"
        f"{cusip}:"
        f"{issue_date}"
    )


def _download_rows():
    today = datetime.now(
        timezone.utc
    ).date()

    start = (
        today
        - timedelta(
            days=45
        )
    )

    params = {
        "filter": (
            "auction_date:gte:"
            f"{start.isoformat()},"
            "auction_date:lte:"
            f"{today.isoformat()}"
        ),
        "sort": (
            "-auction_date,"
            "-issue_date"
        ),
        "page[size]": "100",
    }

    url = (
        API_URL
        + "?"
        + urllib.parse.urlencode(
            params
        )
    )

    raw = download(
        url
    )

    data = json.loads(
        raw.decode(
            "utf-8",
            errors="replace",
        )
    )

    rows = data.get(
        "data"
    )

    if not isinstance(
        rows,
        list,
    ):
        raise RuntimeError(
            "Treasury Fiscal Data API "
            "returned no data list"
        )

    return [
        row
        for row in rows
        if isinstance(
            row,
            dict,
        )
    ]


def _is_result_available(row):
    accepted = _first(
        row,
        "total_accepted",
        "totalAccepted",
        "accepted",
    )

    competitive_accepted = _first(
        row,
        "competitive_accepted",
        "competitiveAccepted",
    )

    high_yield = _first(
        row,
        "high_yield",
        "highYield",
        "high_rate",
        "highRate",
        "high_discount_rate",
        "highDiscountRate",
        "high_discount_margin",
        "highDiscountMargin",
    )

    return any([
        accepted not in (
            None,
            "",
        ),
        competitive_accepted not in (
            None,
            "",
        ),
        high_yield not in (
            None,
            "",
        ),
    ])


def _high_result(row):
    candidates = [
        (
            "High Yield",
            _first(
                row,
                "high_yield",
                "highYield",
            ),
        ),
        (
            "High Rate",
            _first(
                row,
                "high_rate",
                "highRate",
            ),
        ),
        (
            "High Discount Rate",
            _first(
                row,
                "high_discount_rate",
                "highDiscountRate",
            ),
        ),
        (
            "High Discount Margin",
            _first(
                row,
                "high_discount_margin",
                "highDiscountMargin",
            ),
        ),
    ]

    for (
        label,
        value,
    ) in candidates:
        if value not in (
            None,
            "",
        ):
            return (
                label,
                value,
            )

    return (
        "",
        "",
    )


def _auction_metrics(row):
    competitive_tendered = _first(
        row,
        "competitive_tendered",
        "competitiveTendered",
    )

    competitive_accepted = _first(
        row,
        "competitive_accepted",
        "competitiveAccepted",
    )

    total_tendered = _first(
        row,
        "total_tendered",
        "totalTendered",
    )

    total_accepted = _first(
        row,
        "total_accepted",
        "totalAccepted",
    )

    subtotal_tendered = _first(
        row,
        "subtotal_tendered",
        "subtotalTendered",
    )

    subtotal_accepted = _first(
        row,
        "subtotal_accepted",
        "subtotalAccepted",
    )

    bid_to_cover = _first(
        row,
        "bid_to_cover_ratio",
        "bidToCoverRatio",
    )

    if bid_to_cover in (
        None,
        "",
    ):
        bid_to_cover = _ratio(
            subtotal_tendered
            or total_tendered
            or competitive_tendered,
            subtotal_accepted
            or total_accepted
            or competitive_accepted,
        )

    return {
        "competitive_tendered": (
            competitive_tendered
        ),
        "competitive_accepted": (
            competitive_accepted
        ),
        "total_tendered": (
            total_tendered
        ),
        "total_accepted": (
            total_accepted
        ),
        "bid_to_cover": (
            bid_to_cover
        ),
    }


def _bidder_metrics(row):
    primary = _first(
        row,
        "primary_dealer_accepted",
        "primaryDealerAccepted",
        "primary_dealers_accepted",
    )

    direct = _first(
        row,
        "direct_bidder_accepted",
        "directBidderAccepted",
        "direct_bidders_accepted",
    )

    indirect = _first(
        row,
        "indirect_bidder_accepted",
        "indirectBidderAccepted",
        "indirect_bidders_accepted",
    )

    competitive = _first(
        row,
        "competitive_accepted",
        "competitiveAccepted",
    )

    return {
        "primary": primary,
        "direct": direct,
        "indirect": indirect,
        "competitive": competitive,
    }


def _details(row):
    auction_date = _date_value(
        row
    )

    issue_date = _text(
        _first(
            row,
            "issue_date",
            "issueDate",
        )
    )[:10]

    maturity_date = _text(
        _first(
            row,
            "maturity_date",
            "maturityDate",
        )
    )[:10]

    security = _security_term(
        row
    )

    cusip = _cusip(
        row
    )

    high_label, high_value = (
        _high_result(
            row
        )
    )

    metrics = _auction_metrics(
        row
    )

    bidders = _bidder_metrics(
        row
    )

    lines = [
        (
            "Market: U.S. Treasury "
            "primary auction"
        ),
        f"Security: {security}",
    ]

    if cusip:
        lines.append(
            f"CUSIP: {cusip}"
        )

    if auction_date:
        lines.append(
            f"Auction date: "
            f"{auction_date}"
        )

    if issue_date:
        lines.append(
            f"Issue date: "
            f"{issue_date}"
        )

    if maturity_date:
        lines.append(
            f"Maturity date: "
            f"{maturity_date}"
        )

    if high_label:
        lines.append(
            f"{high_label}: "
            f"{_percent(high_value)}"
        )

    bid_to_cover = metrics[
        "bid_to_cover"
    ]

    if bid_to_cover not in (
        None,
        "",
    ):
        number = _number(
            bid_to_cover
        )

        if number is not None:
            lines.append(
                "Bid-to-Cover: "
                f"{number:.2f}"
            )
        else:
            lines.append(
                "Bid-to-Cover: "
                f"{bid_to_cover}"
            )

    if metrics[
        "competitive_tendered"
    ] not in (
        None,
        "",
    ):
        lines.append(
            "Competitive tendered: "
            + _money(
                metrics[
                    "competitive_tendered"
                ]
            )
        )

    if metrics[
        "competitive_accepted"
    ] not in (
        None,
        "",
    ):
        lines.append(
            "Competitive accepted: "
            + _money(
                metrics[
                    "competitive_accepted"
                ]
            )
        )

    competitive = bidders[
        "competitive"
    ]

    bidder_rows = [
        (
            "Primary Dealer",
            bidders["primary"],
        ),
        (
            "Direct Bidder",
            bidders["direct"],
        ),
        (
            "Indirect Bidder",
            bidders["indirect"],
        ),
    ]

    for (
        label,
        amount,
    ) in bidder_rows:
        if amount in (
            None,
            "",
        ):
            continue

        share = _share(
            amount,
            competitive,
        )

        if share is None:
            lines.append(
                f"{label} accepted: "
                f"{_money(amount)}"
            )
        else:
            lines.append(
                f"{label} accepted: "
                f"{_money(amount)} "
                f"({share:.1f}%)"
            )

    lines.extend([
        (
            "Signal: auction demand, "
            "dealer absorption and "
            "domestic/indirect bidder "
            "participation."
        ),
        (
            "Source: U.S. Department "
            "of the Treasury / "
            "Bureau of the Fiscal Service"
        ),
    ])

    return "\n".join(
        lines
    )


def _title(row):
    security = _security_term(
        row
    )

    high_label, high_value = (
        _high_result(
            row
        )
    )

    metrics = _auction_metrics(
        row
    )

    parts = [
        f"Treasury Auction — {security}"
    ]

    bid_to_cover = metrics[
        "bid_to_cover"
    ]

    if bid_to_cover not in (
        None,
        "",
    ):
        number = _number(
            bid_to_cover
        )

        if number is not None:
            parts.append(
                f"BTC {number:.2f}"
            )

    if high_label:
        parts.append(
            f"{high_label} "
            f"{_percent(high_value)}"
        )

    return " — ".join(
        parts
    )


def fetch_treasury_auction_results():
    source = (
        "U.S. Treasury Auction Results"
    )

    try:
        rows = _download_rows()

        rows = [
            row
            for row in rows
            if _is_result_available(
                row
            )
        ]

        if not rows:
            raise RuntimeError(
                "official Treasury API "
                "returned no completed "
                "auction results"
            )

        rows.sort(
            key=lambda row: (
                _date_value(
                    row
                ),
                _cusip(
                    row
                ),
            )
        )

        current_ids = [
            _stable_id(
                row
            )
            for row in rows
        ]

        state = read_state(
            STATE_FILE
        )

        if not state[
            "initialized"
        ]:
            write_state(
                STATE_FILE,
                current_ids,
            )

            print(
                "U.S. Treasury Auction Results: "
                "initialized baseline with "
                f"{len(rows)} completed "
                "auction result(s); "
                "no historical messages sent."
            )

            return

        known = set(
            state["ids"]
        )

        unseen = [
            row
            for row in rows
            if _stable_id(
                row
            ) not in known
        ]

        if not unseen:
            latest = rows[-1]

            print(
                "No new U.S. Treasury "
                "auction results; "
                "latest completed auction is "
                f"{_security_term(latest)} "
                f"({_date_value(latest)})."
            )

            return

        for row in unseen:
            send_one(
                source,
                "🇺🇸",
                _title(
                    row
                ),
                PUBLIC_URL,
                STATE_FILE,
                item_id=_stable_id(
                    row
                ),
                details=_details(
                    row
                ),
            )

        write_state(
            STATE_FILE,
            state["ids"]
            + current_ids,
        )

    except Exception as error:
        print(
            f"{source} failed, "
            f"skipping: {error}"
        )

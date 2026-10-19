import html
import urllib.parse
import xml.etree.ElementTree as ET

from core.network import download
from core.state import read_state, write_state
from core.telegram import send_one


HALT_CODE_NAMES = {
    "T1": "News Pending",
    "T2": "News Released",
    "T5": "Single-Stock Volatility Pause",
    "T6": "Extraordinary Market Activity",
    "T8": "ETF / ETP Halt",
    "T12": "Additional Information Requested",
    "H4": "Non-Compliance",
    "H9": "Not Current in SEC Filings",
    "H10": "SEC Trading Suspension",
    "H11": "Regulatory Concern",
    "LUDP": "Limit Up-Limit Down Pause",
    "MWC1": "Market-Wide Circuit Breaker Level 1",
    "MWC2": "Market-Wide Circuit Breaker Level 2",
    "MWC3": "Market-Wide Circuit Breaker Level 3",
}


def _text(node, name):
    value = node.findtext(name)

    if value is None:
        value = node.findtext(
            f"{{*}}{name}"
        )

    return " ".join(
        html.unescape(
            str(value or "")
        ).split()
    )


def fetch_nasdaq_trading_halts():
    source = "Nasdaq Trading Halts"
    state_file = ".last_nasdaq_halts"

    try:
        url = (
            "https://www.nasdaqtrader.com/"
            "rss.aspx?feed=tradehalts"
        )

        root = ET.fromstring(
            download(url)
        )

        items = root.findall(
            ".//item"
        )

        if not items:
            items = root.findall(
                ".//{*}item"
            )

        if not items:
            raise RuntimeError(
                "Nasdaq Trading Halts RSS "
                "returned no halt records"
            )

        rows = []

        for item in items:
            title = _text(
                item,
                "title",
            )

            link = _text(
                item,
                "link",
            )

            if link:
                link = urllib.parse.urljoin(
                    url,
                    link,
                )

            symbol = (
                _text(item, "IssueSymbol")
                or _text(item, "Symbol")
            )

            company = (
                _text(item, "IssueName")
                or _text(item, "CompanyName")
            )

            market = (
                _text(item, "Market")
                or _text(item, "MarketCategory")
            )

            reason_code = (
                _text(item, "ReasonCode")
                or _text(item, "HaltReason")
            )

            halt_date = (
                _text(item, "HaltDate")
                or _text(item, "Date")
            )

            halt_time = (
                _text(item, "HaltTime")
                or _text(item, "Time")
            )

            resume_date = _text(
                item,
                "ResumptionDate",
            )

            resume_quote_time = _text(
                item,
                "ResumptionQuoteTime",
            )

            resume_trade_time = _text(
                item,
                "ResumptionTradeTime",
            )

            description = _text(
                item,
                "description",
            )

            if not symbol:
                symbol = title

            if not symbol:
                continue

            stable_id = ":".join([
                "NASDAQ-HALT",
                halt_date,
                halt_time,
                symbol,
                reason_code,
            ])

            rows.append({
                "id": stable_id,
                "symbol": symbol,
                "company": company,
                "market": market,
                "reason_code": reason_code,
                "halt_date": halt_date,
                "halt_time": halt_time,
                "resume_date": resume_date,
                "resume_quote_time": resume_quote_time,
                "resume_trade_time": resume_trade_time,
                "description": description,
                "link": (
                    link
                    or (
                        "https://www.nasdaqtrader.com/"
                        "Trader.aspx?id=TradeHalts"
                    )
                ),
            })

        if not rows:
            raise RuntimeError(
                "Nasdaq Trading Halts RSS "
                "contained no usable halt records"
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
                "Nasdaq Trading Halts: "
                "initialized baseline with "
                f"{len(rows)} current halt record(s); "
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
                "No new Nasdaq Trading Halts."
            )
            return

        for row in reversed(unseen):
            reason_code = row[
                "reason_code"
            ]

            reason_name = (
                HALT_CODE_NAMES.get(
                    reason_code,
                    reason_code,
                )
                or "Not specified"
            )

            details = [
                f"Symbol: {row['symbol']}",
            ]

            if row["company"]:
                details.append(
                    f"Company: {row['company']}"
                )

            if row["market"]:
                details.append(
                    f"Market: {row['market']}"
                )

            details.append(
                "Reason: "
                f"{reason_name}"
            )

            if reason_code:
                details.append(
                    "Reason code: "
                    f"{reason_code}"
                )

            if row["halt_date"]:
                details.append(
                    "Halt date: "
                    f"{row['halt_date']}"
                )

            if row["halt_time"]:
                details.append(
                    "Halt time: "
                    f"{row['halt_time']}"
                )

            if row["resume_date"]:
                details.append(
                    "Resumption date: "
                    f"{row['resume_date']}"
                )

            if row["resume_quote_time"]:
                details.append(
                    "Quote resumption: "
                    f"{row['resume_quote_time']}"
                )

            if row["resume_trade_time"]:
                details.append(
                    "Trade resumption: "
                    f"{row['resume_trade_time']}"
                )

            details.append(
                "Source: Nasdaq Trader "
                "official Trading Halts feed"
            )

            send_one(
                source,
                "🚨",
                (
                    f"{row['symbol']} "
                    f"Trading Halt — "
                    f"{reason_name}"
                ),
                row["link"],
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

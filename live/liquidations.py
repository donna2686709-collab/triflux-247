"""
TriFlux 24/7
Global Crypto Liquidation Radar

Stage 6:
- Bybit + Binance public WebSocket
- BTCUSDT / ETHUSDT
- Unified liquidation normalization
- Per-exchange + global rolling totals
- 1m / 5m / 15m windows
- Risk-level engine
- Risk escalation bypasses cooldown
- Safe deterministic self-test
- Telegram alerts for REAL market risk only

SELF TEST alerts NEVER go to Telegram.
"""

import asyncio
import json
import sys
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import websockets


# --------------------------------------------------
# Project root
# --------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(PROJECT_ROOT),
    )

from core.telegram import send_telegram


# --------------------------------------------------
# Configuration
# --------------------------------------------------

BYBIT_WS_URL = (
    "wss://stream.bybit.com/v5/public/linear"
)

BINANCE_WS_URL = (
    "wss://fstream.binance.com/market/ws/"
    "!forceOrder@arr"
)

SYMBOLS = [
    "BTCUSDT",
    "ETHUSDT",
]

EXCHANGES = [
    "BYBIT",
    "BINANCE",
]

HEARTBEAT_SECONDS = 30

ROLLING_WINDOWS = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
}

ALERT_THRESHOLDS = {
    "BTCUSDT": {
        "WATCH": 50_000,
        "MEDIUM": 150_000,
        "HIGH": 500_000,
        "CRITICAL": 1_500_000,
    },
    "ETHUSDT": {
        "WATCH": 30_000,
        "MEDIUM": 100_000,
        "HIGH": 300_000,
        "CRITICAL": 1_000_000,
    },
}

RISK_RANK = {
    "WATCH": 1,
    "MEDIUM": 2,
    "HIGH": 3,
    "CRITICAL": 4,
}

RISK_EMOJI = {
    "WATCH": "🟡",
    "MEDIUM": "🟠",
    "HIGH": "🔴",
    "CRITICAL": "🚨",
}

ALERT_COOLDOWN_SECONDS = 300


# --------------------------------------------------
# Runtime state
# --------------------------------------------------

ticker_state = {
    symbol: {}
    for symbol in SYMBOLS
}

last_heartbeat = {
    symbol: 0.0
    for symbol in SYMBOLS
}

alert_state = {
    symbol: {
        "time": 0.0,
        "level": None,
    }
    for symbol in SYMBOLS
}

liquidation_events = deque()


# --------------------------------------------------
# Helpers
# --------------------------------------------------

def utc_now():
    return datetime.now(
        timezone.utc
    ).isoformat()


def safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def format_money(value):
    return f"${value:,.2f}"


def format_price(value):
    number = safe_float(value)

    if number <= 0:
        return "N/A"

    return f"${number:,.2f}"


def format_funding(value):
    number = safe_float(value)

    return f"{number * 100:.4f}%"


def liquidation_value(
    price,
    size,
):
    return (
        safe_float(price)
        * safe_float(size)
    )


# --------------------------------------------------
# Rolling calculations
# --------------------------------------------------

def cleanup_liquidations(now):
    oldest_allowed = (
        now
        - max(
            ROLLING_WINDOWS.values()
        )
    )

    while liquidation_events:
        event = liquidation_events[0]

        if (
            event["time"]
            >= oldest_allowed
        ):
            break

        liquidation_events.popleft()


def calculate_window(
    symbol,
    seconds,
    now,
    exchange=None,
):
    long_value = 0.0
    short_value = 0.0
    event_count = 0

    cutoff = now - seconds

    for event in liquidation_events:
        if event["time"] < cutoff:
            continue

        if event["symbol"] != symbol:
            continue

        if (
            exchange is not None
            and event["exchange"] != exchange
        ):
            continue

        event_count += 1

        if event["position"] == "LONG":
            long_value += event["value"]

        elif event["position"] == "SHORT":
            short_value += event["value"]

    return {
        "long": long_value,
        "short": short_value,
        "total": (
            long_value
            + short_value
        ),
        "count": event_count,
    }


# --------------------------------------------------
# Risk engine
# --------------------------------------------------

def get_risk_level(
    symbol,
    total_value,
):
    thresholds = ALERT_THRESHOLDS.get(
        symbol,
        {},
    )

    if total_value >= thresholds.get(
        "CRITICAL",
        float("inf"),
    ):
        return "CRITICAL"

    if total_value >= thresholds.get(
        "HIGH",
        float("inf"),
    ):
        return "HIGH"

    if total_value >= thresholds.get(
        "MEDIUM",
        float("inf"),
    ):
        return "MEDIUM"

    if total_value >= thresholds.get(
        "WATCH",
        float("inf"),
    ):
        return "WATCH"

    return None


def dominant_side(stats):
    if stats["long"] > stats["short"]:
        return "LONG"

    if stats["short"] > stats["long"]:
        return "SHORT"

    return "BALANCED"


def should_alert(
    symbol,
    new_level,
    now,
):
    state = alert_state[symbol]

    previous_level = state["level"]
    previous_time = state["time"]

    if previous_level is None:
        return True, "NEW"

    previous_rank = RISK_RANK.get(
        previous_level,
        0,
    )

    new_rank = RISK_RANK.get(
        new_level,
        0,
    )

    if new_rank > previous_rank:
        return True, "ESCALATION"

    if (
        now - previous_time
        >= ALERT_COOLDOWN_SECONDS
    ):
        return True, "COOLDOWN_EXPIRED"

    return False, "COOLDOWN"


# --------------------------------------------------
# Telegram
# --------------------------------------------------

def build_telegram_alert(
    symbol,
    level,
    stats,
    reason,
    exchange_stats,
):
    state = ticker_state.get(
        symbol,
        {},
    )

    emoji = RISK_EMOJI.get(
        level,
        "⚠️",
    )

    side = dominant_side(
        stats
    )

    price = format_price(
        state.get("lastPrice")
    )

    mark_price = format_price(
        state.get("markPrice")
    )

    oi_value = format_money(
        safe_float(
            state.get(
                "openInterestValue"
            )
        )
    )

    funding = format_funding(
        state.get("fundingRate")
    )

    bybit_total = exchange_stats[
        "BYBIT"
    ]["total"]

    binance_total = exchange_stats[
        "BINANCE"
    ]["total"]

    if reason == "ESCALATION":
        trigger = "Risk level escalated"

    elif reason == "NEW":
        trigger = "New risk signal"

    else:
        trigger = (
            "Risk signal remains active"
        )

    lines = [
        (
            f"{emoji} GLOBAL CRYPTO "
            "LIQUIDATION ALERT"
        ),
        "",
        f"{level} | {symbol}",
        "",
        (
            "Global 1m: "
            f"{format_money(stats['total'])}"
        ),
        (
            "LONG: "
            f"{format_money(stats['long'])}"
        ),
        (
            "SHORT: "
            f"{format_money(stats['short'])}"
        ),
        f"Dominant: {side}",
        f"Events: {stats['count']}",
        "",
        (
            "Bybit: "
            f"{format_money(bybit_total)}"
        ),
        (
            "Binance: "
            f"{format_money(binance_total)}"
        ),
        "",
        f"Price: {price}",
        f"Mark: {mark_price}",
        f"Open Interest: {oi_value}",
        f"Funding: {funding}",
        "",
        f"Trigger: {trigger}",
        "",
        "Sources: Bybit + Binance",
        "TriFlux 24/7",
    ]

    return "\n".join(lines)


def send_real_market_alert(
    symbol,
    level,
    stats,
    reason,
    exchange_stats,
):
    message = build_telegram_alert(
        symbol,
        level,
        stats,
        reason,
        exchange_stats,
    )

    try:
        send_telegram(
            message
        )

        print(
            f"[{utc_now()}] "
            "TELEGRAM SENT | "
            f"{level} | "
            f"{symbol}",
            flush=True,
        )

        return True

    except Exception as exc:
        print(
            f"[{utc_now()}] "
            "TELEGRAM ERROR | "
            f"{type(exc).__name__}: "
            f"{exc}",
            flush=True,
        )

        return False


# --------------------------------------------------
# Alert handling
# --------------------------------------------------

def maybe_process_risk_alert(
    symbol,
    stats,
    exchange_stats,
    self_test=False,
):
    level = get_risk_level(
        symbol,
        stats["total"],
    )

    if level is None:
        return False

    now = time.time()

    allowed, reason = should_alert(
        symbol,
        level,
        now,
    )

    if not allowed:
        return False

    previous_level = (
        alert_state[symbol]["level"]
    )

    alert_state[symbol] = {
        "time": now,
        "level": level,
    }

    side = dominant_side(
        stats
    )

    if reason == "ESCALATION":
        transition = (
            f"{previous_level}->{level}"
        )
    else:
        transition = level

    prefix = (
        "SELF TEST ALERT"
        if self_test
        else "GLOBAL RISK ALERT"
    )

    print(
        f"[{utc_now()}] "
        f"{prefix} | "
        f"{level} | "
        f"{symbol} | "
        f"reason={reason} | "
        f"transition={transition} | "
        "1m liquidation="
        f"{format_money(stats['total'])} | "
        "LONG="
        f"{format_money(stats['long'])} | "
        "SHORT="
        f"{format_money(stats['short'])} | "
        f"dominant={side} | "
        f"events={stats['count']}",
        flush=True,
    )

    if not self_test:
        send_real_market_alert(
            symbol,
            level,
            stats,
            reason,
            exchange_stats,
        )

    return True


# --------------------------------------------------
# Deterministic self-test
# --------------------------------------------------

def run_escalation_self_test():
    test_symbol = "ETHUSDT"

    original_state = dict(
        alert_state[test_symbol]
    )

    print(
        "=" * 64,
        flush=True,
    )

    print(
        "TRIFLUX SELF TEST: "
        "risk escalation bypasses cooldown",
        flush=True,
    )

    print(
        "SELF TEST SAFETY: "
        "Telegram disabled for "
        "simulated alerts.",
        flush=True,
    )

    alert_state[test_symbol] = {
        "time": 0.0,
        "level": None,
    }

    test_cases = [
        ("WATCH", 35_000.0),
        ("MEDIUM", 120_000.0),
        ("HIGH", 350_000.0),
        ("CRITICAL", 1_100_000.0),
    ]

    passed = True

    for expected, total in test_cases:
        detected = get_risk_level(
            test_symbol,
            total,
        )

        stats = {
            "long": 0.0,
            "short": total,
            "total": total,
            "count": 10,
        }

        exchange_stats = {
            "BYBIT": {
                "long": 0.0,
                "short": total / 2,
                "total": total / 2,
                "count": 5,
            },
            "BINANCE": {
                "long": 0.0,
                "short": total / 2,
                "total": total / 2,
                "count": 5,
            },
        }

        processed = (
            maybe_process_risk_alert(
                test_symbol,
                stats,
                exchange_stats,
                self_test=True,
            )
        )

        if (
            detected != expected
            or not processed
        ):
            passed = False

            print(
                "SELF TEST FAILURE | "
                f"expected={expected} | "
                f"detected={detected}",
                flush=True,
            )

    alert_state[test_symbol] = (
        original_state
    )

    if passed:
        print(
            "SELF TEST RESULT: PASS | "
            "WATCH -> MEDIUM -> HIGH -> "
            "CRITICAL escalation confirmed.",
            flush=True,
        )

    else:
        print(
            "SELF TEST RESULT: FAIL",
            flush=True,
        )

        raise RuntimeError(
            "Risk escalation self-test failed."
        )

    print(
        "=" * 64,
        flush=True,
    )


# --------------------------------------------------
# Unified event storage
# --------------------------------------------------

def add_liquidation_event(
    exchange,
    symbol,
    position,
    price,
    size,
):
    if symbol not in SYMBOLS:
        return

    value = liquidation_value(
        price,
        size,
    )

    if value <= 0:
        return

    event = {
        "time": time.time(),
        "exchange": exchange,
        "symbol": symbol,
        "position": position,
        "price": safe_float(price),
        "size": safe_float(size),
        "value": value,
    }

    liquidation_events.append(
        event
    )

    cleanup_liquidations(
        event["time"]
    )

    print(
        f"[{utc_now()}] "
        "LIQUIDATION | "
        f"{exchange} | "
        f"{symbol} | "
        f"{position} | "
        f"price={price} | "
        f"size={size} | "
        f"value={format_money(value)}",
        flush=True,
    )

    print_global_summary(
        symbol
    )


# --------------------------------------------------
# Global rolling summary
# --------------------------------------------------

def print_global_summary(symbol):
    now = time.time()

    cleanup_liquidations(
        now
    )

    global_summaries = {}
    output_parts = []

    for label, seconds in (
        ROLLING_WINDOWS.items()
    ):
        stats = calculate_window(
            symbol,
            seconds,
            now,
        )

        global_summaries[label] = stats

        output_parts.append(
            f"{label}: "
            f"LONG={format_money(stats['long'])} | "
            f"SHORT={format_money(stats['short'])} | "
            f"TOTAL={format_money(stats['total'])} | "
            f"events={stats['count']}"
        )

    print(
        f"[{utc_now()}] "
        "GLOBAL ROLLING | "
        f"{symbol} | "
        + " || ".join(output_parts),
        flush=True,
    )

    exchange_stats = {}

    for exchange in EXCHANGES:
        exchange_stats[exchange] = (
            calculate_window(
                symbol,
                ROLLING_WINDOWS["1m"],
                now,
                exchange=exchange,
            )
        )

    print(
        f"[{utc_now()}] "
        "EXCHANGE SPLIT | "
        f"{symbol} | "
        "1m | "
        "BYBIT="
        f"{format_money(exchange_stats['BYBIT']['total'])} | "
        "BINANCE="
        f"{format_money(exchange_stats['BINANCE']['total'])}",
        flush=True,
    )

    maybe_process_risk_alert(
        symbol,
        global_summaries["1m"],
        exchange_stats,
        self_test=False,
    )


# --------------------------------------------------
# Bybit
# --------------------------------------------------

async def subscribe_bybit(
    websocket,
):
    topics = []

    for symbol in SYMBOLS:
        topics.append(
            f"tickers.{symbol}"
        )

        topics.append(
            f"allLiquidation.{symbol}"
        )

    await websocket.send(
        json.dumps({
            "op": "subscribe",
            "args": topics,
        })
    )

    print(
        "BYBIT subscribed to: "
        + ", ".join(topics),
        flush=True,
    )


def update_bybit_ticker(
    topic,
    data,
):
    if not isinstance(
        data,
        dict,
    ):
        return

    symbol = (
        data.get("symbol")
        or topic.split(".")[-1]
    )

    if symbol not in ticker_state:
        return

    ticker_state[symbol].update(
        data
    )

    now = time.monotonic()

    previous = last_heartbeat.get(
        symbol,
        0.0,
    )

    if (
        now - previous
        < HEARTBEAT_SECONDS
    ):
        return

    last_heartbeat[symbol] = now

    state = ticker_state[symbol]

    print(
        f"[{utc_now()}] "
        "MARKET HEARTBEAT | "
        "BYBIT | "
        f"{symbol} | "
        f"last={state.get('lastPrice', 'N/A')} | "
        f"mark={state.get('markPrice', 'N/A')} | "
        f"OI={state.get('openInterest', 'N/A')} | "
        "OI_value="
        f"{state.get('openInterestValue', 'N/A')} | "
        f"funding={state.get('fundingRate', 'N/A')}",
        flush=True,
    )


def handle_bybit_liquidation(
    data,
):
    if isinstance(
        data,
        dict,
    ):
        data = [data]

    if not isinstance(
        data,
        list,
    ):
        return

    for item in data:
        if not isinstance(
            item,
            dict,
        ):
            continue

        symbol = item.get(
            "s",
            "",
        )

        side = item.get(
            "S",
            "",
        )

        price = item.get(
            "p",
            "0",
        )

        size = item.get(
            "v",
            "0",
        )

        # Existing verified TriFlux
        # Bybit normalization.
        if side == "Buy":
            position = "LONG"

        elif side == "Sell":
            position = "SHORT"

        else:
            continue

        add_liquidation_event(
            "BYBIT",
            symbol,
            position,
            price,
            size,
        )


async def handle_bybit_message(
    message,
):
    try:
        payload = json.loads(
            message
        )

    except json.JSONDecodeError:
        return

    if (
        payload.get("op")
        == "subscribe"
    ):
        print(
            f"[{utc_now()}] "
            "BYBIT SUBSCRIPTION | "
            f"success={payload.get('success')} | "
            f"message={payload.get('ret_msg', '')}",
            flush=True,
        )

        return

    topic = payload.get(
        "topic",
        "",
    )

    data = payload.get(
        "data"
    )

    if topic.startswith(
        "tickers."
    ):
        update_bybit_ticker(
            topic,
            data,
        )

    elif topic.startswith(
        "allLiquidation."
    ):
        handle_bybit_liquidation(
            data
        )


async def run_bybit():
    while True:
        try:
            async with websockets.connect(
                BYBIT_WS_URL,
                ping_interval=20,
                ping_timeout=20,
                close_timeout=10,
            ) as websocket:

                print(
                    f"[{utc_now()}] "
                    "Connected to BYBIT.",
                    flush=True,
                )

                await subscribe_bybit(
                    websocket
                )

                async for message in websocket:
                    await handle_bybit_message(
                        message
                    )

        except asyncio.CancelledError:
            raise

        except Exception as exc:
            print(
                f"[{utc_now()}] "
                "BYBIT ERROR | "
                f"{type(exc).__name__}: "
                f"{exc}",
                flush=True,
            )

            print(
                "BYBIT reconnecting in "
                "5 seconds...",
                flush=True,
            )

            await asyncio.sleep(5)


# --------------------------------------------------
# Binance
# --------------------------------------------------

def handle_binance_liquidation(
    payload,
):
    if not isinstance(
        payload,
        dict,
    ):
        return

    order = payload.get(
        "o",
        {},
    )

    if not isinstance(
        order,
        dict,
    ):
        return

    symbol = order.get(
        "s",
        "",
    )

    if symbol not in SYMBOLS:
        return

    side = order.get(
        "S",
        "",
    )

    size = order.get(
        "q",
        "0",
    )

    average_price = order.get(
        "ap",
        "0",
    )

    order_price = order.get(
        "p",
        "0",
    )

    price = (
        average_price
        if safe_float(average_price) > 0
        else order_price
    )

    # Binance forceOrder:
    # SELL liquidation order closes LONG.
    # BUY liquidation order closes SHORT.
    if side == "SELL":
        position = "LONG"

    elif side == "BUY":
        position = "SHORT"

    else:
        return

    add_liquidation_event(
        "BINANCE",
        symbol,
        position,
        price,
        size,
    )


async def handle_binance_message(
    message,
):
    try:
        payload = json.loads(
            message
        )

    except json.JSONDecodeError:
        return

    handle_binance_liquidation(
        payload
    )


async def run_binance():
    while True:
        try:
            async with websockets.connect(
                BINANCE_WS_URL,
                ping_interval=20,
                ping_timeout=20,
                close_timeout=10,
            ) as websocket:

                print(
                    f"[{utc_now()}] "
                    "Connected to BINANCE "
                    "force-order stream.",
                    flush=True,
                )

                async for message in websocket:
                    await handle_binance_message(
                        message
                    )

        except asyncio.CancelledError:
            raise

        except Exception as exc:
            print(
                f"[{utc_now()}] "
                "BINANCE ERROR | "
                f"{type(exc).__name__}: "
                f"{exc}",
                flush=True,
            )

            print(
                "BINANCE reconnecting in "
                "5 seconds...",
                flush=True,
            )

            await asyncio.sleep(5)


# --------------------------------------------------
# Main
# --------------------------------------------------

async def run():
    run_escalation_self_test()

    print(
        "=" * 64,
        flush=True,
    )

    print(
        "TriFlux 24/7 "
        "Global Crypto Liquidation Radar",
        flush=True,
    )

    print(
        "Stage 6: "
        "Bybit + Binance",
        flush=True,
    )

    print(
        "Markets: BTCUSDT, ETHUSDT",
        flush=True,
    )

    print(
        "Aggregation: "
        "1m / 5m / 15m",
        flush=True,
    )

    print(
        "REAL global risk alerts "
        "-> Telegram",
        flush=True,
    )

    print(
        "SELF TEST alerts -> LOG ONLY",
        flush=True,
    )

    print(
        "=" * 64,
        flush=True,
    )

    await asyncio.gather(
        run_bybit(),
        run_binance(),
    )


if __name__ == "__main__":
    try:
        asyncio.run(
            run()
        )

    except KeyboardInterrupt:
        print(
            "TriFlux Live Radar stopped.",
            flush=True,
        )

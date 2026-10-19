"""
TriFlux 24/7
Global Crypto Liquidation Radar

Stage 4 Verification:
- Bybit public WebSocket
- BTCUSDT / ETHUSDT
- Persistent ticker state
- Correct liquidation position-side mapping
- Rolling 1m / 5m / 15m liquidation totals
- Risk-level engine
- Alert cooldown
- Immediate alert on risk-level escalation
- Safe startup self-test for escalation logic

No Bybit API key is required.
Telegram sending is NOT enabled yet.
"""

import asyncio
import json
import time
from collections import deque
from datetime import datetime, timezone

import websockets


BYBIT_WS_URL = "wss://stream.bybit.com/v5/public/linear"

SYMBOLS = [
    "BTCUSDT",
    "ETHUSDT",
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

ALERT_COOLDOWN_SECONDS = 300


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


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def format_money(value):
    return f"${value:,.2f}"


def liquidation_value(price, size):
    return safe_float(price) * safe_float(size)


def cleanup_liquidations(now):
    oldest_allowed = (
        now - max(ROLLING_WINDOWS.values())
    )

    while liquidation_events:
        event = liquidation_events[0]

        if event["time"] >= oldest_allowed:
            break

        liquidation_events.popleft()


def calculate_window(symbol, seconds, now):
    long_value = 0.0
    short_value = 0.0
    event_count = 0

    cutoff = now - seconds

    for event in liquidation_events:
        if event["time"] < cutoff:
            continue

        if event["symbol"] != symbol:
            continue

        event_count += 1

        if event["position"] == "LONG":
            long_value += event["value"]

        elif event["position"] == "SHORT":
            short_value += event["value"]

    return {
        "long": long_value,
        "short": short_value,
        "total": long_value + short_value,
        "count": event_count,
    }


def get_risk_level(symbol, total_value):
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


def should_alert(symbol, new_level, now):
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


def maybe_print_risk_alert(
    symbol,
    stats,
    prefix="RISK ALERT",
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

    previous_level = alert_state[
        symbol
    ]["level"]

    alert_state[symbol] = {
        "time": now,
        "level": level,
    }

    side = dominant_side(stats)

    if reason == "ESCALATION":
        transition = (
            f"{previous_level}->{level}"
        )
    else:
        transition = level

    print(
        f"[{utc_now()}] "
        f"{prefix} | "
        f"{level} | "
        f"{symbol} | "
        f"reason={reason} | "
        f"transition={transition} | "
        f"1m liquidation="
        f"{format_money(stats['total'])} | "
        f"LONG="
        f"{format_money(stats['long'])} | "
        f"SHORT="
        f"{format_money(stats['short'])} | "
        f"dominant={side} | "
        f"events={stats['count']}",
        flush=True,
    )

    return True


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

    alert_state[test_symbol] = {
        "time": 0.0,
        "level": None,
    }

    test_cases = [
        {
            "expected": "WATCH",
            "total": 35_000.0,
        },
        {
            "expected": "MEDIUM",
            "total": 120_000.0,
        },
        {
            "expected": "HIGH",
            "total": 350_000.0,
        },
        {
            "expected": "CRITICAL",
            "total": 1_100_000.0,
        },
    ]

    passed = True

    for test_case in test_cases:
        expected = test_case["expected"]
        total = test_case["total"]

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

        printed = maybe_print_risk_alert(
            test_symbol,
            stats,
            prefix="SELF TEST ALERT",
        )

        if (
            detected != expected
            or not printed
        ):
            passed = False

            print(
                f"SELF TEST FAILURE | "
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


def print_liquidation_summary(symbol):
    now = time.time()

    cleanup_liquidations(now)

    summaries = {}
    parts = []

    for label, seconds in (
        ROLLING_WINDOWS.items()
    ):
        stats = calculate_window(
            symbol,
            seconds,
            now,
        )

        summaries[label] = stats

        parts.append(
            f"{label}: "
            f"LONG="
            f"{format_money(stats['long'])} | "
            f"SHORT="
            f"{format_money(stats['short'])} | "
            f"TOTAL="
            f"{format_money(stats['total'])} | "
            f"events={stats['count']}"
        )

    print(
        f"[{utc_now()}] "
        f"LIQUIDATION ROLLING | "
        f"{symbol} | "
        + " || ".join(parts),
        flush=True,
    )

    maybe_print_risk_alert(
        symbol,
        summaries["1m"],
    )


async def subscribe(websocket):
    topics = []

    for symbol in SYMBOLS:
        topics.append(
            f"tickers.{symbol}"
        )

        topics.append(
            f"allLiquidation.{symbol}"
        )

    message = {
        "op": "subscribe",
        "args": topics,
    }

    await websocket.send(
        json.dumps(message)
    )

    print(
        "TriFlux Live Radar subscribed to: "
        + ", ".join(topics),
        flush=True,
    )


def update_ticker_state(topic, data):
    if not isinstance(data, dict):
        return

    symbol = data.get("symbol")

    if not symbol:
        symbol = topic.split(".")[-1]

    if symbol not in ticker_state:
        ticker_state[symbol] = {}

    ticker_state[symbol].update(data)

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
        f"MARKET HEARTBEAT | "
        f"{symbol} | "
        f"last="
        f"{state.get('lastPrice', 'N/A')} | "
        f"mark="
        f"{state.get('markPrice', 'N/A')} | "
        f"index="
        f"{state.get('indexPrice', 'N/A')} | "
        f"OI="
        f"{state.get('openInterest', 'N/A')} | "
        f"OI_value="
        f"{state.get('openInterestValue', 'N/A')} | "
        f"funding="
        f"{state.get('fundingRate', 'N/A')} | "
        f"turnover24h="
        f"{state.get('turnover24h', 'N/A')} | "
        f"volume24h="
        f"{state.get('volume24h', 'N/A')}",
        flush=True,
    )


def handle_liquidation(data):
    if isinstance(data, dict):
        data = [data]

    if not isinstance(data, list):
        return

    for item in data:
        if not isinstance(item, dict):
            continue

        symbol = item.get(
            "s",
            "UNKNOWN",
        )

        side = item.get(
            "S",
            "",
        )

        size = item.get(
            "v",
            "0",
        )

        price = item.get(
            "p",
            "0",
        )

        value = liquidation_value(
            price,
            size,
        )

        # Bybit allLiquidation:
        # Buy  = LONG position liquidated
        # Sell = SHORT position liquidated
        if side == "Buy":
            liquidated_position = "LONG"

        elif side == "Sell":
            liquidated_position = "SHORT"

        else:
            liquidated_position = "UNKNOWN"

        event = {
            "time": time.time(),
            "symbol": symbol,
            "position": liquidated_position,
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
            f"LIQUIDATION | "
            f"{symbol} | "
            f"{liquidated_position} | "
            f"price={price} | "
            f"size={size} | "
            f"value={format_money(value)}",
            flush=True,
        )

        print_liquidation_summary(
            symbol
        )


async def handle_message(message):
    try:
        payload = json.loads(
            message
        )

    except json.JSONDecodeError:
        return

    if payload.get("op") == "subscribe":
        print(
            f"[{utc_now()}] "
            f"SUBSCRIPTION RESPONSE | "
            f"success="
            f"{payload.get('success')} | "
            f"message="
            f"{payload.get('ret_msg', '')}",
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
        update_ticker_state(
            topic,
            data,
        )

        return

    if topic.startswith(
        "allLiquidation."
    ):
        handle_liquidation(
            data
        )


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
        "Source: Bybit Public WebSocket",
        flush=True,
    )

    print(
        "Markets: BTCUSDT, ETHUSDT",
        flush=True,
    )

    print(
        "Stage 4 Verification: "
        "self-test + live market data",
        flush=True,
    )

    print(
        "=" * 64,
        flush=True,
    )

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
                    "Connected to Bybit "
                    "public WebSocket.",
                    flush=True,
                )

                await subscribe(
                    websocket
                )

                async for message in websocket:
                    await handle_message(
                        message
                    )

        except asyncio.CancelledError:
            raise

        except Exception as exc:
            print(
                f"[{utc_now()}] "
                f"WebSocket error: "
                f"{type(exc).__name__}: "
                f"{exc}",
                flush=True,
            )

            print(
                "Reconnecting in 5 seconds...",
                flush=True,
            )

            await asyncio.sleep(5)


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

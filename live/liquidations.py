"""
TriFlux 24/7
Global Crypto Liquidation Radar

Stage 2:
- Bybit public WebSocket
- BTCUSDT / ETHUSDT
- Persistent ticker state
- Real-time liquidation capture
- Rolling 1m / 5m / 15m liquidation totals

No Bybit API key is required.
No Telegram messages are sent in this stage.
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


ticker_state = {
    symbol: {}
    for symbol in SYMBOLS
}

last_heartbeat = {
    symbol: 0.0
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
    oldest_allowed = now - max(ROLLING_WINDOWS.values())

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

    total_value = long_value + short_value

    return {
        "long": long_value,
        "short": short_value,
        "total": total_value,
        "count": event_count,
    }


def print_liquidation_summary(symbol):
    now = time.time()

    cleanup_liquidations(now)

    parts = []

    for label, seconds in ROLLING_WINDOWS.items():
        stats = calculate_window(
            symbol,
            seconds,
            now,
        )

        parts.append(
            f"{label}: "
            f"LONG={format_money(stats['long'])} | "
            f"SHORT={format_money(stats['short'])} | "
            f"TOTAL={format_money(stats['total'])} | "
            f"events={stats['count']}"
        )

    print(
        f"[{utc_now()}] "
        f"LIQUIDATION ROLLING | "
        f"{symbol} | "
        + " || ".join(parts),
        flush=True,
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

    last_price = state.get(
        "lastPrice",
        "N/A",
    )

    mark_price = state.get(
        "markPrice",
        "N/A",
    )

    index_price = state.get(
        "indexPrice",
        "N/A",
    )

    open_interest = state.get(
        "openInterest",
        "N/A",
    )

    open_interest_value = state.get(
        "openInterestValue",
        "N/A",
    )

    funding_rate = state.get(
        "fundingRate",
        "N/A",
    )

    turnover_24h = state.get(
        "turnover24h",
        "N/A",
    )

    volume_24h = state.get(
        "volume24h",
        "N/A",
    )

    print(
        f"[{utc_now()}] "
        f"MARKET HEARTBEAT | "
        f"{symbol} | "
        f"last={last_price} | "
        f"mark={mark_price} | "
        f"index={index_price} | "
        f"OI={open_interest} | "
        f"OI_value={open_interest_value} | "
        f"funding={funding_rate} | "
        f"turnover24h={turnover_24h} | "
        f"volume24h={volume_24h}",
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

        if side == "Buy":
            liquidated_position = "SHORT"

        elif side == "Sell":
            liquidated_position = "LONG"

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
        success = payload.get(
            "success"
        )

        print(
            f"[{utc_now()}] "
            f"SUBSCRIPTION RESPONSE | "
            f"success={success} | "
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
        "Source: "
        "Bybit Public WebSocket",
        flush=True,
    )

    print(
        "Markets: "
        "BTCUSDT, ETHUSDT",
        flush=True,
    )

    print(
        "Stage 2: "
        "persistent ticker state + "
        "1m/5m/15m liquidation rolling totals",
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
                "Reconnecting in "
                "5 seconds...",
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

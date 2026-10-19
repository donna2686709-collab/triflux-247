"""
TriFlux 24/7
Global Crypto Liquidation Radar

Stage 1 verification:
- Bybit public WebSocket
- BTCUSDT
- ETHUSDT
- Real-time ticker heartbeat
- Real-time liquidation events

No Bybit API key is required.
No Telegram messages are sent in this verification stage.
"""

import asyncio
import json
import time
from datetime import datetime, timezone

import websockets


BYBIT_WS_URL = "wss://stream.bybit.com/v5/public/linear"

SYMBOLS = [
    "BTCUSDT",
    "ETHUSDT",
]

HEARTBEAT_SECONDS = 30

last_heartbeat = {}


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def liquidation_value(price, size):
    return safe_float(price) * safe_float(size)


async def subscribe(websocket):
    topics = []

    for symbol in SYMBOLS:
        topics.append(f"tickers.{symbol}")
        topics.append(f"allLiquidation.{symbol}")

    message = {
        "op": "subscribe",
        "args": topics,
    }

    await websocket.send(json.dumps(message))

    print(
        "TriFlux Live Radar subscribed to: "
        + ", ".join(topics),
        flush=True,
    )


def handle_ticker(topic, data):
    if not isinstance(data, dict):
        return

    symbol = data.get("symbol")

    if not symbol:
        symbol = topic.split(".")[-1]

    now = time.monotonic()
    previous = last_heartbeat.get(symbol, 0)

    if now - previous < HEARTBEAT_SECONDS:
        return

    last_heartbeat[symbol] = now

    last_price = data.get("lastPrice", "N/A")
    mark_price = data.get("markPrice", "N/A")
    index_price = data.get("indexPrice", "N/A")
    open_interest = data.get("openInterest", "N/A")
    open_interest_value = data.get("openInterestValue", "N/A")
    funding_rate = data.get("fundingRate", "N/A")
    turnover_24h = data.get("turnover24h", "N/A")
    volume_24h = data.get("volume24h", "N/A")

    print(
        f"[{utc_now()}] MARKET HEARTBEAT | "
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

        symbol = item.get("s", "UNKNOWN")
        side = item.get("S", "")
        size = item.get("v", "0")
        price = item.get("p", "0")

        value = liquidation_value(price, size)

        if side == "Buy":
            liquidated_position = "SHORT"
        elif side == "Sell":
            liquidated_position = "LONG"
        else:
            liquidated_position = "UNKNOWN"

        print(
            f"[{utc_now()}] "
            f"LIQUIDATION | "
            f"{symbol} | "
            f"{liquidated_position} | "
            f"price={price} | "
            f"size={size} | "
            f"value=${value:,.2f}",
            flush=True,
        )


async def handle_message(message):
    try:
        payload = json.loads(message)
    except json.JSONDecodeError:
        return

    if payload.get("op") == "subscribe":
        success = payload.get("success")

        print(
            f"[{utc_now()}] "
            f"SUBSCRIPTION RESPONSE | "
            f"success={success} | "
            f"message={payload.get('ret_msg', '')}",
            flush=True,
        )
        return

    topic = payload.get("topic", "")
    data = payload.get("data")

    if topic.startswith("tickers."):
        handle_ticker(topic, data)
        return

    if topic.startswith("allLiquidation."):
        handle_liquidation(data)


async def run():
    print("=" * 64, flush=True)
    print(
        "TriFlux 24/7 Global Crypto Liquidation Radar",
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
        "Verification: ticker heartbeat + liquidation stream",
        flush=True,
    )
    print("=" * 64, flush=True)

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
                    "Connected to Bybit public WebSocket.",
                    flush=True,
                )

                await subscribe(websocket)

                async for message in websocket:
                    await handle_message(message)

        except asyncio.CancelledError:
            raise

        except Exception as exc:
            print(
                f"[{utc_now()}] "
                f"WebSocket error: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )

            print(
                "Reconnecting in 5 seconds...",
                flush=True,
            )

            await asyncio.sleep(5)


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print(
            "TriFlux Live Radar stopped.",
            flush=True,
        )

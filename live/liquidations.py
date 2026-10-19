"""
TriFlux 24/7
Global Crypto Liquidation Radar

Stage 1:
- Bybit public market data
- BTCUSDT
- ETHUSDT
- Real-time liquidation stream

This module does not require a Bybit API key.
"""

import asyncio
import json
from datetime import datetime, timezone

import websockets


BYBIT_WS_URL = "wss://stream.bybit.com/v5/public/linear"

SYMBOLS = [
    "BTCUSDT",
    "ETHUSDT",
]


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def liquidation_value(price, size):
    try:
        return float(price) * float(size)
    except (TypeError, ValueError):
        return 0.0


async def subscribe(websocket):
    topics = [
        f"allLiquidation.{symbol}"
        for symbol in SYMBOLS
    ]

    message = {
        "op": "subscribe",
        "args": topics,
    }

    await websocket.send(json.dumps(message))

    print(
        "TriFlux Live Radar: subscribed to "
        + ", ".join(topics)
    )


async def handle_message(message):
    try:
        payload = json.loads(message)
    except json.JSONDecodeError:
        return

    topic = payload.get("topic", "")

    if not topic.startswith("allLiquidation."):
        return

    data = payload.get("data", [])

    if isinstance(data, dict):
        data = [data]

    for item in data:
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
            f"{symbol} "
            f"{liquidated_position} liquidation | "
            f"price={price} | "
            f"size={size} | "
            f"value=${value:,.2f}"
        )


async def run():
    print("=" * 60)
    print("TriFlux 24/7 Global Crypto Liquidation Radar")
    print("Source: Bybit Public WebSocket")
    print("Markets: BTCUSDT, ETHUSDT")
    print("=" * 60)

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
                    "Connected to Bybit public WebSocket."
                )

                await subscribe(websocket)

                async for message in websocket:
                    await handle_message(message)

        except asyncio.CancelledError:
            raise

        except Exception as exc:
            print(
                f"[{utc_now()}] "
                f"WebSocket error: {exc}"
            )
            print("Reconnecting in 5 seconds...")
            await asyncio.sleep(5)


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("TriFlux Live Radar stopped.")

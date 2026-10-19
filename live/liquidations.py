"""
TriFlux 24/7
Global Crypto Liquidation Radar

Stage 7:
- Bybit + Binance + Gate + Bitget
- BTCUSDT / ETHUSDT
- Exchange-specific normalization
- Global 1m / 5m / 15m aggregation
- Per-exchange contribution
- Risk escalation
- Telegram alerts for REAL market signals only
- Deterministic self-test NEVER sends Telegram
"""

import asyncio
import json
import sys
import time
import urllib.request
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import websockets


# ==================================================
# Project
# ==================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.telegram import send_telegram


# ==================================================
# Configuration
# ==================================================

BYBIT_WS_URL = "wss://stream.bybit.com/v5/public/linear"

BINANCE_WS_URL = (
    "wss://fstream.binance.com/market/ws/"
    "!forceOrder@arr"
)

GATE_WS_URL = "wss://fx-ws.gateio.ws/v4/ws/usdt"

# Bitget UTA / v3 public websocket.
BITGET_WS_URL = "wss://ws.bitget.com/v3/ws/public"

SYMBOLS = [
    "BTCUSDT",
    "ETHUSDT",
]

GATE_CONTRACTS = {
    "BTC_USDT": "BTCUSDT",
    "ETH_USDT": "ETHUSDT",
}

EXCHANGES = [
    "BYBIT",
    "BINANCE",
    "GATE",
    "BITGET",
]

ROLLING_WINDOWS = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
}

HEARTBEAT_SECONDS = 30

ALERT_COOLDOWN_SECONDS = 300


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


# ==================================================
# Runtime state
# ==================================================

liquidation_events = deque()


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


# Gate multiplier is loaded from official
# contract metadata before the websocket starts.
gate_multiplier = {
    "BTC_USDT": None,
    "ETH_USDT": None,
}


# ==================================================
# Basic helpers
# ==================================================

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
    value = safe_float(value)

    if value <= 0:
        return "N/A"

    return f"${value:,.2f}"


def format_funding(value):
    value = safe_float(value)

    return f"{value * 100:.4f}%"


# ==================================================
# Rolling event store
# ==================================================

def cleanup_liquidations(now):
    oldest = now - max(
        ROLLING_WINDOWS.values()
    )

    while liquidation_events:
        if (
            liquidation_events[0]["time"]
            >= oldest
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
    count = 0

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

        count += 1

        if event["position"] == "LONG":
            long_value += event["value"]

        elif event["position"] == "SHORT":
            short_value += event["value"]

    return {
        "long": long_value,
        "short": short_value,
        "total": long_value + short_value,
        "count": count,
    }


# ==================================================
# Risk engine
# ==================================================

def get_risk_level(
    symbol,
    total,
):
    thresholds = ALERT_THRESHOLDS.get(
        symbol,
        {},
    )

    if total >= thresholds.get(
        "CRITICAL",
        float("inf"),
    ):
        return "CRITICAL"

    if total >= thresholds.get(
        "HIGH",
        float("inf"),
    ):
        return "HIGH"

    if total >= thresholds.get(
        "MEDIUM",
        float("inf"),
    ):
        return "MEDIUM"

    if total >= thresholds.get(
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


# ==================================================
# Telegram
# ==================================================

def build_telegram_alert(
    symbol,
    level,
    stats,
    reason,
    exchange_stats,
):
    emoji = RISK_EMOJI.get(
        level,
        "⚠️",
    )

    side = dominant_side(
        stats
    )

    market = ticker_state.get(
        symbol,
        {},
    )

    if reason == "ESCALATION":
        trigger = "Risk level escalated"

    elif reason == "NEW":
        trigger = "New risk signal"

    else:
        trigger = "Risk signal remains active"

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
    ]

    for exchange in EXCHANGES:
        exchange_total = (
            exchange_stats
            .get(exchange, {})
            .get("total", 0.0)
        )

        lines.append(
            f"{exchange.title()}: "
            f"{format_money(exchange_total)}"
        )

    lines.extend([
        "",
        (
            "Price: "
            f"{format_price(market.get('lastPrice'))}"
        ),
        (
            "Mark: "
            f"{format_price(market.get('markPrice'))}"
        ),
        (
            "Open Interest: "
            f"{format_money(safe_float(
                market.get('openInterestValue')
            ))}"
        ),
        (
            "Funding: "
            f"{format_funding(
                market.get('fundingRate')
            )}"
        ),
        "",
        f"Trigger: {trigger}",
        "",
        (
            "Sources: "
            "Bybit + Binance + Gate + Bitget"
        ),
        "TriFlux 24/7",
    ])

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
        send_telegram(message)

        print(
            f"[{utc_now()}] "
            "TELEGRAM SENT | "
            f"{level} | {symbol}",
            flush=True,
        )

        return True

    except Exception as exc:
        print(
            f"[{utc_now()}] "
            "TELEGRAM ERROR | "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )

        return False


# ==================================================
# Alert processing
# ==================================================

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
        "dominant="
        f"{dominant_side(stats)} | "
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


# ==================================================
# Self-test
# ==================================================

def run_escalation_self_test():
    symbol = "ETHUSDT"

    original_state = dict(
        alert_state[symbol]
    )

    print(
        "=" * 68,
        flush=True,
    )

    print(
        "TRIFLUX SELF TEST: "
        "risk escalation bypasses cooldown",
        flush=True,
    )

    print(
        "SELF TEST SAFETY: "
        "Telegram disabled for simulated alerts.",
        flush=True,
    )

    alert_state[symbol] = {
        "time": 0.0,
        "level": None,
    }

    tests = [
        ("WATCH", 35_000.0),
        ("MEDIUM", 120_000.0),
        ("HIGH", 350_000.0),
        ("CRITICAL", 1_100_000.0),
    ]

    passed = True

    for expected, total in tests:
        stats = {
            "long": total,
            "short": 0.0,
            "total": total,
            "count": 10,
        }

        quarter = total / 4

        exchange_stats = {}

        for exchange in EXCHANGES:
            exchange_stats[exchange] = {
                "long": quarter,
                "short": 0.0,
                "total": quarter,
                "count": 2,
            }

        detected = get_risk_level(
            symbol,
            total,
        )

        processed = (
            maybe_process_risk_alert(
                symbol,
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

    alert_state[symbol] = original_state

    if not passed:
        raise RuntimeError(
            "Risk escalation self-test failed."
        )

    print(
        "SELF TEST RESULT: PASS | "
        "WATCH -> MEDIUM -> HIGH -> "
        "CRITICAL escalation confirmed.",
        flush=True,
    )

    print(
        "=" * 68,
        flush=True,
    )


# ==================================================
# Unified event handling
# ==================================================

def add_liquidation_event(
    exchange,
    symbol,
    position,
    value,
    price=0.0,
    raw_size=0.0,
):
    if symbol not in SYMBOLS:
        return

    value = abs(
        safe_float(value)
    )

    if value <= 0:
        return

    now = time.time()

    event = {
        "time": now,
        "exchange": exchange,
        "symbol": symbol,
        "position": position,
        "value": value,
        "price": safe_float(price),
        "raw_size": safe_float(raw_size),
    }

    liquidation_events.append(
        event
    )

    cleanup_liquidations(now)

    print(
        f"[{utc_now()}] "
        "LIQUIDATION | "
        f"{exchange} | "
        f"{symbol} | "
        f"{position} | "
        f"price={price} | "
        f"raw_size={raw_size} | "
        f"value={format_money(value)}",
        flush=True,
    )

    print_global_summary(symbol)


def print_global_summary(symbol):
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
            f"LONG={format_money(stats['long'])} | "
            f"SHORT={format_money(stats['short'])} | "
            f"TOTAL={format_money(stats['total'])} | "
            f"events={stats['count']}"
        )

    print(
        f"[{utc_now()}] "
        "GLOBAL ROLLING | "
        f"{symbol} | "
        + " || ".join(parts),
        flush=True,
    )

    exchange_stats = {}

    split_parts = []

    for exchange in EXCHANGES:
        stats = calculate_window(
            symbol,
            ROLLING_WINDOWS["1m"],
            now,
            exchange=exchange,
        )

        exchange_stats[exchange] = stats

        split_parts.append(
            f"{exchange}="
            f"{format_money(stats['total'])}"
        )

    print(
        f"[{utc_now()}] "
        "EXCHANGE SPLIT | "
        f"{symbol} | 1m | "
        + " | ".join(split_parts),
        flush=True,
    )

    maybe_process_risk_alert(
        symbol,
        summaries["1m"],
        exchange_stats,
        self_test=False,
    )


# ==================================================
# Gate contract metadata
# ==================================================

def fetch_gate_multiplier(
    contract,
):
    url = (
        "https://api.gateio.ws/api/v4/"
        "futures/usdt/contracts/"
        f"{contract}"
    )

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "TriFlux-247/1.0",
            "Accept": "application/json",
        },
    )

    with urllib.request.urlopen(
        request,
        timeout=15,
    ) as response:
        payload = json.loads(
            response.read().decode("utf-8")
        )

    multiplier = safe_float(
        payload.get("quanto_multiplier")
    )

    if multiplier <= 0:
        raise RuntimeError(
            f"Invalid Gate multiplier "
            f"for {contract}"
        )

    return multiplier


def load_gate_multipliers():
    for contract in GATE_CONTRACTS:
        multiplier = fetch_gate_multiplier(
            contract
        )

        gate_multiplier[contract] = (
            multiplier
        )

        print(
            f"[{utc_now()}] "
            "GATE CONTRACT | "
            f"{contract} | "
            f"quanto_multiplier={multiplier}",
            flush=True,
        )


# ==================================================
# Bybit
# ==================================================

async def subscribe_bybit(ws):
    topics = []

    for symbol in SYMBOLS:
        topics.append(
            f"tickers.{symbol}"
        )

        topics.append(
            f"allLiquidation.{symbol}"
        )

    await ws.send(
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
    if not isinstance(data, dict):
        return

    symbol = (
        data.get("symbol")
        or topic.split(".")[-1]
    )

    if symbol not in SYMBOLS:
        return

    ticker_state[symbol].update(
        data
    )

    now = time.monotonic()

    if (
        now - last_heartbeat[symbol]
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


def handle_bybit_liquidation(data):
    if isinstance(data, dict):
        data = [data]

    if not isinstance(data, list):
        return

    for item in data:
        if not isinstance(item, dict):
            continue

        symbol = item.get("s", "")

        if symbol not in SYMBOLS:
            continue

        side = item.get("S", "")

        price = safe_float(
            item.get("p")
        )

        size = safe_float(
            item.get("v")
        )

        # Bybit official semantics:
        # Buy = long position liquidated.
        # Sell = short position liquidated.
        if side == "Buy":
            position = "LONG"

        elif side == "Sell":
            position = "SHORT"

        else:
            continue

        value = price * size

        add_liquidation_event(
            "BYBIT",
            symbol,
            position,
            value,
            price,
            size,
        )


async def handle_bybit_message(message):
    try:
        payload = json.loads(message)

    except json.JSONDecodeError:
        return

    if payload.get("op") == "subscribe":
        print(
            f"[{utc_now()}] "
            "BYBIT SUBSCRIPTION | "
            f"success={payload.get('success')} | "
            f"message={payload.get('ret_msg', '')}",
            flush=True,
        )

        return

    topic = payload.get("topic", "")

    data = payload.get("data")

    if topic.startswith("tickers."):
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
            ) as ws:

                print(
                    f"[{utc_now()}] "
                    "Connected to BYBIT.",
                    flush=True,
                )

                await subscribe_bybit(ws)

                async for message in ws:
                    await handle_bybit_message(
                        message
                    )

        except asyncio.CancelledError:
            raise

        except Exception as exc:
            print(
                f"[{utc_now()}] "
                "BYBIT ERROR | "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )

            await asyncio.sleep(5)


# ==================================================
# Binance
# ==================================================

def handle_binance_liquidation(
    payload,
):
    if not isinstance(payload, dict):
        return

    order = payload.get("o", {})

    if not isinstance(order, dict):
        return

    symbol = order.get("s", "")

    if symbol not in SYMBOLS:
        return

    side = order.get("S", "")

    price = safe_float(
        order.get("ap")
    )

    if price <= 0:
        price = safe_float(
            order.get("p")
        )

    # Prefer accumulated filled quantity
    # when available; fall back to original
    # quantity for compatibility.
    size = safe_float(
        order.get("z")
    )

    if size <= 0:
        size = safe_float(
            order.get("q")
        )

    # SELL force order closes a long.
    # BUY force order closes a short.
    if side == "SELL":
        position = "LONG"

    elif side == "BUY":
        position = "SHORT"

    else:
        return

    value = price * size

    add_liquidation_event(
        "BINANCE",
        symbol,
        position,
        value,
        price,
        size,
    )


async def run_binance():
    while True:
        try:
            async with websockets.connect(
                BINANCE_WS_URL,
                ping_interval=20,
                ping_timeout=20,
                close_timeout=10,
            ) as ws:

                print(
                    f"[{utc_now()}] "
                    "Connected to BINANCE "
                    "force-order stream.",
                    flush=True,
                )

                async for message in ws:
                    try:
                        payload = json.loads(
                            message
                        )

                    except json.JSONDecodeError:
                        continue

                    handle_binance_liquidation(
                        payload
                    )

        except asyncio.CancelledError:
            raise

        except Exception as exc:
            print(
                f"[{utc_now()}] "
                "BINANCE ERROR | "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )

            await asyncio.sleep(5)


# ==================================================
# Gate
# ==================================================

async def subscribe_gate(ws):
    request = {
        "time": int(time.time()),
        "channel": (
            "futures.public_liquidates"
        ),
        "event": "subscribe",
        "payload": [
            "BTC_USDT",
            "ETH_USDT",
        ],
    }

    await ws.send(
        json.dumps(request)
    )

    print(
        "GATE subscribed to: "
        "BTC_USDT, ETH_USDT",
        flush=True,
    )


def handle_gate_liquidation(
    payload,
):
    if (
        payload.get("channel")
        != "futures.public_liquidates"
    ):
        return

    if payload.get("event") != "update":
        return

    result = payload.get(
        "result",
        [],
    )

    if isinstance(result, dict):
        result = [result]

    if not isinstance(result, list):
        return

    for item in result:
        if not isinstance(item, dict):
            continue

        contract = item.get(
            "contract",
            "",
        )

        symbol = GATE_CONTRACTS.get(
            contract
        )

        if symbol is None:
            continue

        multiplier = gate_multiplier.get(
            contract
        )

        if (
            multiplier is None
            or multiplier <= 0
        ):
            print(
                f"[{utc_now()}] "
                "GATE SKIP | "
                f"missing multiplier | "
                f"{contract}",
                flush=True,
            )

            continue

        price = safe_float(
            item.get("price")
        )

        signed_size = safe_float(
            item.get("size")
        )

        if signed_size == 0:
            continue

        contracts = abs(
            signed_size
        )

        # Gate USDT futures:
        # contracts * multiplier =
        # underlying asset quantity.
        value = (
            contracts
            * multiplier
            * price
        )

        # Gate public liquidation size is
        # signed order quantity.
        # Negative = sell liquidation order
        # -> long position liquidated.
        # Positive = buy liquidation order
        # -> short position liquidated.
        if signed_size < 0:
            position = "LONG"

        else:
            position = "SHORT"

        add_liquidation_event(
            "GATE",
            symbol,
            position,
            value,
            price,
            signed_size,
        )


async def run_gate():
    while True:
        try:
            async with websockets.connect(
                GATE_WS_URL,
                ping_interval=20,
                ping_timeout=20,
                close_timeout=10,
            ) as ws:

                print(
                    f"[{utc_now()}] "
                    "Connected to GATE.",
                    flush=True,
                )

                await subscribe_gate(ws)

                async for message in ws:
                    try:
                        payload = json.loads(
                            message
                        )

                    except json.JSONDecodeError:
                        continue

                    if (
                        payload.get("event")
                        == "subscribe"
                    ):
                        print(
                            f"[{utc_now()}] "
                            "GATE SUBSCRIPTION | "
                            f"{payload.get('result')}",
                            flush=True,
                        )

                    handle_gate_liquidation(
                        payload
                    )

        except asyncio.CancelledError:
            raise

        except Exception as exc:
            print(
                f"[{utc_now()}] "
                "GATE ERROR | "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )

            await asyncio.sleep(5)


# ==================================================
# Bitget
# ==================================================

async def subscribe_bitget(ws):
    request = {
        "op": "subscribe",
        "args": [
            {
                "instType": "usdt-futures",
                "topic": "liquidation",
            }
        ],
    }

    await ws.send(
        json.dumps(request)
    )

    print(
        "BITGET subscribed to: "
        "usdt-futures liquidation",
        flush=True,
    )


def handle_bitget_liquidation(
    payload,
):
    arg = payload.get(
        "arg",
        {},
    )

    if not isinstance(arg, dict):
        return

    if arg.get("topic") != "liquidation":
        return

    data = payload.get(
        "data",
        [],
    )

    if isinstance(data, dict):
        data = [data]

    if not isinstance(data, list):
        return

    for item in data:
        if not isinstance(item, dict):
            continue

        symbol = item.get(
            "symbol",
            "",
        ).upper()

        if symbol not in SYMBOLS:
            continue

        side = (
            item.get("side", "")
            .lower()
        )

        price = safe_float(
            item.get("price")
        )

        amount = abs(
            safe_float(
                item.get("amount")
            )
        )

        if amount <= 0:
            continue

        # Bitget official liquidation
        # channel semantics:
        # buy = long position liquidation
        # sell = short position liquidation.
        if side == "buy":
            position = "LONG"

        elif side == "sell":
            position = "SHORT"

        else:
            continue

        # Bitget documentation defines
        # amount in quote coin.
        # Therefore amount itself is the
        # normalized quote value and must
        # NOT be multiplied by price again.
        value = amount

        add_liquidation_event(
            "BITGET",
            symbol,
            position,
            value,
            price,
            amount,
        )


async def run_bitget():
    while True:
        try:
            async with websockets.connect(
                BITGET_WS_URL,
                ping_interval=20,
                ping_timeout=20,
                close_timeout=10,
            ) as ws:

                print(
                    f"[{utc_now()}] "
                    "Connected to BITGET.",
                    flush=True,
                )

                await subscribe_bitget(ws)

                async for message in ws:
                    # Bitget may use textual
                    # ping/pong messages.
                    if message == "ping":
                        await ws.send("pong")
                        continue

                    try:
                        payload = json.loads(
                            message
                        )

                    except json.JSONDecodeError:
                        continue

                    if (
                        payload.get("event")
                        == "subscribe"
                    ):
                        print(
                            f"[{utc_now()}] "
                            "BITGET SUBSCRIPTION | "
                            f"{payload.get('arg')}",
                            flush=True,
                        )

                    if (
                        payload.get("event")
                        == "error"
                    ):
                        print(
                            f"[{utc_now()}] "
                            "BITGET SUBSCRIPTION ERROR | "
                            f"{payload}",
                            flush=True,
                        )

                        continue

                    handle_bitget_liquidation(
                        payload
                    )

        except asyncio.CancelledError:
            raise

        except Exception as exc:
            print(
                f"[{utc_now()}] "
                "BITGET ERROR | "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )

            await asyncio.sleep(5)


# ==================================================
# Main
# ==================================================

async def run():
    run_escalation_self_test()

    print(
        "Loading Gate contract metadata...",
        flush=True,
    )

    await asyncio.to_thread(
        load_gate_multipliers
    )

    print(
        "=" * 68,
        flush=True,
    )

    print(
        "TriFlux 24/7 "
        "Global Crypto Liquidation Radar",
        flush=True,
    )

    print(
        "Stage 7: "
        "Bybit + Binance + Gate + Bitget",
        flush=True,
    )

    print(
        "Markets: BTCUSDT, ETHUSDT",
        flush=True,
    )

    print(
        "Aggregation: 1m / 5m / 15m",
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
        "=" * 68,
        flush=True,
    )

    await asyncio.gather(
        run_bybit(),
        run_binance(),
        run_gate(),
        run_bitget(),
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

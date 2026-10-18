import html
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from core.state import normalize_url, read_state, write_state


BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()


def send_telegram(message):
    if not BOT_TOKEN:
        print("Telegram skipped: TELEGRAM_BOT_TOKEN is missing.")
        return False

    if not CHAT_ID:
        print("Telegram skipped: TELEGRAM_CHAT_ID is missing.")
        return False

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    payload = urllib.parse.urlencode(
        {
            "chat_id": CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        }
    ).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )

    last_error = None

    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                result = json.loads(response.read().decode("utf-8"))

            if result.get("ok"):
                return True

            last_error = RuntimeError(
                f"Telegram API returned: {result}"
            )

        except (
            urllib.error.HTTPError,
            urllib.error.URLError,
            TimeoutError,
            json.JSONDecodeError,
        ) as exc:
            last_error = exc

        if attempt < 3:
            time.sleep(2 ** attempt)

    print(f"Telegram send error: {last_error}")
    return False


def make_message(source, title, link, category="Financial Risk"):
    safe_source = html.escape(str(source))
    safe_title = html.escape(str(title))

    clean_link = normalize_url(link)

    parts = [
        f"<b>TriFlux 24/7 | {html.escape(str(category))}</b>",
        "",
        f"<b>{safe_title}</b>",
        "",
        f"Source: {safe_source}",
    ]

    if clean_link:
        safe_link = html.escape(clean_link, quote=True)
        parts.extend(
            [
                "",
                f'<a href="{safe_link}">Open official source</a>',
            ]
        )

    return "\n".join(parts)


def send_one(
    source,
    title,
    link,
    state_file,
    item_id=None,
    category="Financial Risk",
):
    key = str(item_id or normalize_url(link) or title).strip()

    if not key:
        print(f"{source}: skipped item with no usable ID.")
        return False

    seen = read_state(state_file)

    if key in seen:
        print(f"No new {source}; duplicate already recorded.")
        return False

    message = make_message(
        source=source,
        title=title,
        link=link,
        category=category,
    )

    if not send_telegram(message):
        return False

    updated = [key] + seen
    write_state(state_file, updated)

    print(f"Sent new {source}: {title}")
    return True

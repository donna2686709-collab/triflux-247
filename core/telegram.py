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
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is not configured"
        )

    if not CHAT_ID:
        raise RuntimeError(
            "TELEGRAM_CHAT_ID is not configured"
        )

    url = (
        "https://api.telegram.org/bot"
        f"{BOT_TOKEN}/sendMessage"
    )

    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": message[:4000],
        "disable_web_page_preview": "true",
    }).encode("utf-8")

    for attempt in range(4):
        try:
            request = urllib.request.Request(
                url,
                data=data,
                method="POST",
            )

            with urllib.request.urlopen(
                request,
                timeout=30,
            ) as response:
                result = json.loads(
                    response.read().decode(
                        "utf-8",
                        errors="replace",
                    )
                )

            if not result.get("ok"):
                raise RuntimeError(str(result))

            time.sleep(1.2)
            return

        except urllib.error.HTTPError as error:
            if (
                error.code == 429
                and attempt < 3
            ):
                wait = 20 * (attempt + 1)

                print(
                    "Telegram rate limit; "
                    f"waiting {wait}s..."
                )

                time.sleep(wait)
                continue

            raise


def make_message(
    source,
    flag,
    title,
    link,
    details=None,
):
    parts = [
        f"{flag} {source}",
        "",
        title,
    ]

    if details:
        parts.extend([
            "",
            details,
        ])

    if link:
        parts.extend([
            "",
            link,
        ])

    return "\n".join(parts)


def send_one(
    source,
    flag,
    title,
    link,
    state_file,
    item_id=None,
    details=None,
):
    link = normalize_url(link)
    item_id = str(item_id or "").strip()

    state = read_state(state_file)

    known = set(
        state.get("ids", [])
    )

    identifiers = []

    if item_id:
        identifiers.append(item_id)

    if link:
        identifiers.append(link)

    if (
        state.get("initialized")
        and identifiers
        and any(
            identifier in known
            for identifier in identifiers
        )
    ):
        print(
            f"No new {source}; "
            "duplicate already recorded."
        )
        return False

    message = make_message(
        source,
        flag,
        title,
        link,
        details=details,
    )

    send_telegram(message)

    updated = list(
        state.get("ids", [])
    )

    for identifier in identifiers:
        if identifier not in updated:
            updated.append(identifier)

    write_state(
        state_file,
        updated,
    )

    print(
        f"Sent new {source}: {title}"
    )

    return True

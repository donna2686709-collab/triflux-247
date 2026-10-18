import json
import os
import urllib.parse


MAX_STATE_ITEMS = 500


def normalize_url(url):
    if not url:
        return ""

    url = url.strip()

    try:
        parsed = urllib.parse.urlsplit(url)

        scheme = parsed.scheme.lower()
        netloc = parsed.netloc.lower()

        path = parsed.path or "/"

        if path != "/":
            path = path.rstrip("/")

        return urllib.parse.urlunsplit(
            (
                scheme,
                netloc,
                path,
                parsed.query,
                "",
            )
        )

    except Exception:
        return url


def read_state(path):
    if not os.path.exists(path):
        return []

    try:
        with open(path, "r", encoding="utf-8") as file:
            content = file.read().strip()

        if not content:
            return []

        try:
            data = json.loads(content)

            if isinstance(data, list):
                return [str(item) for item in data if item]

            if isinstance(data, str):
                return [data] if data else []

        except json.JSONDecodeError:
            pass

        return [
            line.strip()
            for line in content.splitlines()
            if line.strip()
        ]

    except Exception as exc:
        print(f"State read error ({path}): {exc}")
        return []


def write_state(path, items):
    if isinstance(items, str):
        items = [items]

    cleaned = []
    seen = set()

    for item in items:
        if item is None:
            continue

        value = str(item).strip()

        if not value or value in seen:
            continue

        seen.add(value)
        cleaned.append(value)

    cleaned = cleaned[:MAX_STATE_ITEMS]

    try:
        with open(path, "w", encoding="utf-8") as file:
            json.dump(
                cleaned,
                file,
                ensure_ascii=False,
                indent=2,
            )

    except Exception as exc:
        print(f"State write error ({path}): {exc}")
        raise

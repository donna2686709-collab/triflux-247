import json
import os
import urllib.parse


MAX_STATE_ITEMS = 500


def normalize_url(url):
    if not url:
        return ""

    url = str(url).strip()

    try:
        parsed = urllib.parse.urlsplit(url)

        return urllib.parse.urlunsplit(
            (
                parsed.scheme.lower(),
                parsed.netloc.lower(),
                parsed.path,
                parsed.query,
                "",
            )
        )

    except Exception:
        return url


def read_state(path):
    if not os.path.exists(path):
        return {
            "initialized": False,
            "ids": [],
        }

    try:
        with open(
            path,
            "r",
            encoding="utf-8",
        ) as file:
            raw = file.read().strip()

        if not raw:
            return {
                "initialized": False,
                "ids": [],
            }

        try:
            data = json.loads(raw)

            if (
                isinstance(data, dict)
                and isinstance(
                    data.get("ids"),
                    list,
                )
            ):
                return {
                    "initialized": bool(
                        data.get(
                            "initialized",
                            True,
                        )
                    ),
                    "ids": [
                        str(item)
                        for item in data["ids"]
                        if item
                    ],
                }

            # Compatibility with the temporary
            # list format used during refactoring.
            if isinstance(data, list):
                return {
                    "initialized": True,
                    "ids": [
                        str(item)
                        for item in data
                        if item
                    ],
                }

        except json.JSONDecodeError:
            pass

        return {
            "initialized": True,
            "ids": [
                normalize_url(raw)
            ],
        }

    except Exception:
        return {
            "initialized": False,
            "ids": [],
        }


def write_state(path, ids):
    unique = list(
        dict.fromkeys(
            str(item)
            for item in ids
            if item
        )
    )[-MAX_STATE_ITEMS:]

    temp_path = path + ".tmp"

    with open(
        temp_path,
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            {
                "initialized": True,
                "ids": unique,
            },
            file,
            ensure_ascii=False,
        )

    os.replace(
        temp_path,
        path,
    )

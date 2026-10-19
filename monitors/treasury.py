import html
import re
import urllib.parse

from core.network import download
from core.telegram import send_one


def _extract_page_title(page):
    patterns = [
        r'<h1[^>]*>(.*?)</h1>',
        (
            r'<meta[^>]+'
            r'property=["\']og:title["\']'
            r'[^>]+content=["\']([^"\']+)'
        ),
        (
            r'<meta[^>]+'
            r'content=["\']([^"\']+)["\']'
            r'[^>]+property=["\']og:title["\']'
        ),
        r'<title[^>]*>(.*?)</title>',
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            page,
            re.I | re.S,
        )

        if not match:
            continue

        title = " ".join(
            html.unescape(
                re.sub(
                    r"<[^>]+>",
                    " ",
                    match.group(1),
                )
            ).split()
        )

        if title:
            return title

    return ""


def fetch_treasury_tic():
    source = "U.S. Treasury TIC"

    try:
        index_url = (
            "https://home.treasury.gov/"
            "news/press-releases"
        )

        page = download(
            index_url
        ).decode(
            "utf-8",
            errors="ignore",
        )

        clean_page = html.unescape(page)

        matches = re.findall(
            r'/news/press-releases/'
            r'[A-Za-z]{1,10}[0-9]{2,10}',
            clean_page,
            re.I,
        )

        paths = []

        for path in matches:
            path = path.rstrip("/")

            if path not in paths:
                paths.append(path)

        print(
            "Treasury TIC DEBUG: "
            f"found {len(paths)} unique "
            "press-release links."
        )

        if not paths:
            raise RuntimeError(
                "No Treasury press release "
                "links found"
            )

        # Print and inspect only the newest 20 releases.
        for number, path in enumerate(
            paths[:20],
            start=1,
        ):
            link = urllib.parse.urljoin(
                "https://home.treasury.gov",
                path,
            )

            try:
                article = download(
                    link
                ).decode(
                    "utf-8",
                    errors="ignore",
                )

                title = _extract_page_title(
                    article
                )

                print(
                    "Treasury TIC DEBUG "
                    f"#{number}: "
                    f"{link} | "
                    f"title={title!r}"
                )

                if (
                    "treasury international capital data"
                    in title.casefold()
                ):
                    print(
                        "Treasury TIC: "
                        "found latest release: "
                        f"{title}"
                    )

                    send_one(
                        source,
                        "🇺🇸",
                        title,
                        link,
                        ".last_treasury_tic",
                    )

                    return

            except Exception as error:
                print(
                    "Treasury TIC DEBUG "
                    f"#{number} failed: "
                    f"{error}"
                )

        raise RuntimeError(
            "No Treasury TIC release found "
            "among newest 20 releases"
        )

    except Exception as error:
        print(
            f"{source} failed, "
            f"skipping: {error}"
        )

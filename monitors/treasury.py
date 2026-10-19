import html
import re
import urllib.parse

from core.network import download
from core.telegram import send_one


def fetch_treasury_tic():
    source = "U.S. Treasury TIC"

    try:
        url = (
            "https://home.treasury.gov/"
            "news/press-releases"
        )

        page = download(
            url
        ).decode(
            "utf-8",
            errors="ignore",
        )

        # Treasury press-release URLs currently use IDs
        # such as /news/press-releases/sb0662
        paths = re.findall(
            r'href\s*=\s*["\']'
            r'([^"\']*/news/press-releases/'
            r'[A-Za-z]{1,10}[0-9]{2,10}/?)'
            r'["\']',
            page,
            re.I,
        )

        candidates = []
        seen = set()

        for path in paths:
            link = urllib.parse.urljoin(
                "https://home.treasury.gov",
                html.unescape(
                    path.strip()
                ),
            )

            link = link.rstrip("/")

            if link in seen:
                continue

            seen.add(link)

            try:
                article = download(
                    link
                ).decode(
                    "utf-8",
                    errors="ignore",
                )

            except Exception:
                continue

            title = ""

            patterns = [
                (
                    r'<meta[^>]+'
                    r'property=["\']og:title["\']'
                    r'[^>]+content=["\']'
                    r'([^"\']+)'
                ),
                (
                    r'<meta[^>]+'
                    r'content=["\']([^"\']+)'
                    r'["\'][^>]+'
                    r'property=["\']og:title["\']'
                ),
                r'<h1[^>]*>(.*?)</h1>',
                r'<title[^>]*>(.*?)</title>',
            ]

            for pattern in patterns:
                match = re.search(
                    pattern,
                    article,
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
                    break

            if (
                title
                and "treasury international capital data"
                in title.casefold()
            ):
                candidates.append(
                    (
                        link,
                        title,
                    )
                )

                # Press releases are newest first.
                break

        if not candidates:
            raise RuntimeError(
                "No Treasury TIC "
                "press release found"
            )

        link, title = candidates[0]

        print(
            "Treasury TIC: found latest release: "
            f"{title}"
        )

        send_one(
            source,
            "🇺🇸",
            title,
            link,
            ".last_treasury_tic",
        )

    except Exception as error:
        print(
            f"{source} failed, "
            f"skipping: {error}"
        )

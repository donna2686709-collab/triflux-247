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

        matches = re.findall(
            r'<a\b[^>]*\bhref\s*=\s*["\']'
            r'([^"\']+)["\'][^>]*>'
            r'(.*?)</a>',
            page,
            re.I | re.S,
        )

        candidates = []
        seen = set()

        for link, raw_title in matches:
            title = " ".join(
                html.unescape(
                    re.sub(
                        r"<[^>]+>",
                        " ",
                        raw_title,
                    )
                ).split()
            )

            if not title:
                continue

            if (
                "treasury international capital data"
                not in title.casefold()
            ):
                continue

            absolute_link = urllib.parse.urljoin(
                "https://home.treasury.gov/",
                html.unescape(
                    link.strip()
                ),
            )

            parsed = urllib.parse.urlparse(
                absolute_link
            )

            if (
                parsed.netloc.lower()
                != "home.treasury.gov"
            ):
                continue

            if (
                "/news/press-releases/"
                not in parsed.path.lower()
            ):
                continue

            if absolute_link in seen:
                continue

            seen.add(
                absolute_link
            )

            candidates.append(
                (
                    absolute_link,
                    title,
                )
            )

        if not candidates:
            raise RuntimeError(
                "No Treasury TIC "
                "press release found"
            )

        link, title = candidates[0]

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

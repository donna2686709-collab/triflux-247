import html
import re
import urllib.parse

from core.network import download
from core.telegram import send_one


def fetch_treasury_tic():
    source = "U.S. Treasury TIC"

    try:
        # Official Treasury TIC release archive.
        url = (
            "https://home.treasury.gov/"
            "data/tic-press-releases-by-topic/"
        )

        page = download(
            url
        ).decode(
            "utf-8",
            errors="ignore",
        )

        # Find links on the official TIC page that point
        # to Treasury press releases.
        matches = re.findall(
            r'<a\b[^>]*\bhref\s*=\s*["\']'
            r'([^"\']+)["\'][^>]*>'
            r'(.*?)</a>',
            page,
            re.I | re.S,
        )

        candidates = []
        seen = set()

        for raw_link, raw_title in matches:
            link = urllib.parse.urljoin(
                url,
                html.unescape(
                    raw_link.strip()
                ),
            )

            parsed = urllib.parse.urlparse(
                link
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

            lower_title = title.casefold()

            # The TIC archive uses titles such as:
            # "TIC Data for July 2026"
            # or similar monthly TIC descriptions.
            if (
                "tic data" not in lower_title
                and
                "treasury international capital"
                not in lower_title
            ):
                continue

            link = link.rstrip("/")

            if link in seen:
                continue

            seen.add(link)

            candidates.append(
                (
                    link,
                    title,
                )
            )

        if not candidates:
            raise RuntimeError(
                "No monthly TIC release "
                "found on official TIC page"
            )

        # Treasury lists the newest release first.
        link, archive_title = candidates[0]

        # Open the actual Treasury press release and
        # extract its official page title.
        article = download(
            link
        ).decode(
            "utf-8",
            errors="ignore",
        )

        title = ""

        patterns = [
            r'<h1[^>]*>(.*?)</h1>',
            (
                r'<meta[^>]+'
                r'property=["\']og:title["\']'
                r'[^>]+content=["\']([^"\']+)'
            ),
            (
                r'<meta[^>]+'
                r'content=["\']([^"\']+)'
                r'["\'][^>]+'
                r'property=["\']og:title["\']'
            ),
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

        if not title:
            title = archive_title

        if (
            "treasury international capital"
            not in title.casefold()
            and
            "tic data"
            not in title.casefold()
        ):
            raise RuntimeError(
                "Latest TIC link did not "
                "resolve to a TIC release"
            )

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

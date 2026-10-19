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

        # Convert HTML entities so the page is easier
        # to search reliably.
        clean_page = html.unescape(page)

        # Find every Treasury press-release link.
        matches = list(
            re.finditer(
                r'/news/press-releases/'
                r'[A-Za-z]{1,10}[0-9]{2,10}',
                clean_page,
                re.I,
            )
        )

        if not matches:
            raise RuntimeError(
                "No Treasury press release "
                "links found"
            )

        candidates = []
        seen = set()

        for match in matches:
            path = match.group(0).rstrip("/")

            if path in seen:
                continue

            seen.add(path)

            # Look at the HTML surrounding this link.
            start = max(
                0,
                match.start() - 2500,
            )

            end = min(
                len(clean_page),
                match.end() + 2500,
            )

            context = clean_page[
                start:end
            ]

            context_text = " ".join(
                html.unescape(
                    re.sub(
                        r"<[^>]+>",
                        " ",
                        context,
                    )
                ).split()
            )

            if (
                "treasury international capital data"
                not in context_text.casefold()
            ):
                continue

            link = urllib.parse.urljoin(
                "https://home.treasury.gov",
                path,
            )

            candidates.append(link)

        if not candidates:
            raise RuntimeError(
                "No Treasury TIC link found "
                "on press releases page"
            )

        # Verify candidate pages and use the first
        # one whose official title is a TIC release.
        for link in candidates:
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
                    r'[^>]+content=["\']'
                    r'([^"\']+)'
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
                title_match = re.search(
                    pattern,
                    article,
                    re.I | re.S,
                )

                if not title_match:
                    continue

                title = " ".join(
                    html.unescape(
                        re.sub(
                            r"<[^>]+>",
                            " ",
                            title_match.group(1),
                        )
                    ).split()
                )

                if title:
                    break

            if not title:
                continue

            if (
                "treasury international capital data"
                not in title.casefold()
            ):
                continue

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

            return

        raise RuntimeError(
            "Treasury TIC candidate links "
            "could not be verified"
        )

    except Exception as error:
        print(
            f"{source} failed, "
            f"skipping: {error}"
        )

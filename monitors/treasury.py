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

        clean_page = html.unescape(page)

        # Find all Treasury press-release links.
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

            # Read the HTML surrounding this release.
            start = max(
                0,
                match.start() - 500,
            )

            end = min(
                len(clean_page),
                match.end() + 3000,
            )

            context = clean_page[
                start:end
            ]

            text = " ".join(
                html.unescape(
                    re.sub(
                        r"<[^>]+>",
                        " ",
                        context,
                    )
                ).split()
            )

            lower_text = text.casefold()

            if (
                "treasury international capital data"
                not in lower_text
            ):
                continue

            link = urllib.parse.urljoin(
                "https://home.treasury.gov",
                path,
            )

            candidates.append(
                (
                    link,
                    text,
                )
            )

        if not candidates:
            raise RuntimeError(
                "No Treasury TIC release "
                "found on press releases page"
            )

        link, context_text = candidates[0]

        # Extract the official TIC title directly
        # from the surrounding release-list text.
        title_match = re.search(
            r'Treasury International Capital Data'
            r'(?:\s+for\s+'
            r'(?:January|February|March|April|May|June|'
            r'July|August|September|October|November|December)'
            r'\s+\d{4})?',
            context_text,
            re.I,
        )

        if title_match:
            title = title_match.group(0)

            # Normalize capitalization while preserving
            # the month/year portion.
            if title.casefold().startswith(
                "treasury international capital data"
            ):
                suffix = title[
                    len(
                        "Treasury International Capital Data"
                    ):
                ]

                title = (
                    "Treasury International Capital Data"
                    + suffix
                )

        else:
            title = (
                "Treasury International Capital Data"
            )

        print(
            "Treasury TIC: found latest release: "
            f"{title}"
        )

        print(
            "Treasury TIC: official link: "
            f"{link}"
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

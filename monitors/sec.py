import re
import time
import urllib.parse
import xml.etree.ElementTree as ET

from core.feed import item_id, item_link, item_title
from core.network import SEC_USER_AGENT, download
from core.state import read_state, write_state
from core.telegram import send_one


def fetch_sec_news():
    source = (
        "U.S. Securities and "
        "Exchange Commission "
        "(SEC) News"
    )

    try:
        url = (
            "https://www.sec.gov/"
            "news/pressreleases.rss"
        )

        root = ET.fromstring(
            download(
                url,
                sec=True,
            )
        )

        items = (
            root.findall(".//item")
            or root.findall(".//{*}entry")
        )

        if not items:
            raise RuntimeError(
                "No SEC news entries found"
            )

        item = items[0]

        title = item_title(item)
        link = item_link(item)

        if link:
            link = urllib.parse.urljoin(
                url,
                link,
            )

        stable_id = item_id(item)

        if not title or not link:
            raise RuntimeError(
                "Newest SEC news entry "
                "has no title/link"
            )

        send_one(
            source,
            "🇺🇸",
            title,
            link,
            ".last_sec_news",
            item_id=stable_id,
        )

    except Exception as error:
        print(
            f"{source} failed, "
            f"skipping: {error}"
        )


SEC_FORMS = [
    (
        "Form 4",
        "4",
        ".last_sec_form4",
        (
            "Insider ownership change filing; "
            "Form 4 alone does not necessarily indicate "
            "an open-market purchase or sale"
        ),
    ),
    (
        "Schedule 13D",
        "SCHEDULE 13D",
        ".last_sec_13d",
        (
            "Beneficial ownership disclosure "
            "for certain holders above 5%"
        ),
    ),
    (
        "Schedule 13D/A",
        "SCHEDULE 13D/A",
        ".last_sec_13da",
        "Amendment to Schedule 13D",
    ),
    (
        "Schedule 13G",
        "SCHEDULE 13G",
        ".last_sec_13g",
        (
            "Beneficial ownership disclosure "
            "for certain holders above 5%"
        ),
    ),
    (
        "Schedule 13G/A",
        "SCHEDULE 13G/A",
        ".last_sec_13ga",
        "Amendment to Schedule 13G",
    ),
    (
        "Form 8-K",
        "8-K",
        ".last_sec_8k",
        (
            "Current report covering material "
            "corporate events"
        ),
    ),
    (
        "Form 13F-HR",
        "13F-HR",
        ".last_sec_13f",
        (
            "Quarterly institutional holdings report; "
            "this is delayed disclosure, "
            "not real-time trading activity"
        ),
    ),
    (
        "Form 13F-HR/A",
        "13F-HR/A",
        ".last_sec_13fa",
        (
            "Amendment to quarterly institutional "
            "holdings report; this is delayed disclosure"
        ),
    ),
    (
        "Form 10-Q",
        "10-Q",
        ".last_sec_10q",
        (
            "Quarterly financial report used to monitor "
            "revenue, earnings, cash flow, balance sheet, "
            "and changes in business conditions"
        ),
    ),
    (
        "Form 10-K",
        "10-K",
        ".last_sec_10k",
        (
            "Annual financial report used to monitor "
            "revenue, earnings, cash flow, balance sheet, "
            "risk factors, and changes in business conditions"
        ),
    ),
]


def _title_form_type(title):
    if not title:
        return ""

    match = re.match(
        r"^\s*(.*?)\s+-\s+",
        title,
    )

    if not match:
        return ""

    return (
        " ".join(
            match.group(1).split()
        )
        .upper()
    )


def _form_matches(
    title,
    expected_form,
):
    actual_form = _title_form_type(
        title
    )

    expected_form = (
        " ".join(
            expected_form.split()
        )
        .upper()
    )

    return (
        actual_form
        == expected_form
    )


def fetch_sec_form(
    name,
    form_type,
    state_file,
    description,
):
    try:
        query = urllib.parse.urlencode({
            "action": "getcurrent",
            "type": form_type,
            "company": "",
            "dateb": "",
            "owner": "include",
            "start": "0",
            "count": "40",
            "output": "atom",
        })

        url = (
            "https://www.sec.gov/"
            "cgi-bin/browse-edgar?"
            + query
        )

        root = ET.fromstring(
            download(
                url,
                sec=True,
            )
        )

        entries = root.findall(
            ".//{*}entry"
        )

        rows = []

        ignored_wrong_form = 0

        for entry in entries:
            title = item_title(entry)

            if not _form_matches(
                title,
                form_type,
            ):
                ignored_wrong_form += 1
                continue

            link = item_link(entry)

            if link:
                link = urllib.parse.urljoin(
                    url,
                    link,
                )

            stable_id = (
                item_id(entry)
                or link
            )

            if (
                title
                and link
                and stable_id
            ):
                rows.append(
                    (
                        stable_id,
                        title,
                        link,
                    )
                )

        if ignored_wrong_form:
            print(
                f"SEC {name}: ignored "
                f"{ignored_wrong_form} filing(s) "
                "with a different form type."
            )

        if not rows:
            print(
                f"SEC {name}: "
                "no matching current filings returned; "
                "nothing sent."
            )
            return

        state = read_state(
            state_file
        )

        if not state["initialized"]:
            seed = []

            for (
                stable_id,
                _title,
                link,
            ) in rows:
                seed.extend([
                    stable_id,
                    link,
                ])

            write_state(
                state_file,
                seed,
            )

            print(
                f"SEC {name}: "
                "initialized baseline with "
                f"{len(rows)} current filings; "
                "no historical messages sent."
            )

            return

        known = set(
            state["ids"]
        )

        unseen = [
            row
            for row in rows
            if (
                row[0] not in known
                and row[2] not in known
            )
        ]

        if not unseen:
            print(
                f"No new SEC "
                f"{name} filings."
            )
            return

        for (
            stable_id,
            title,
            link,
        ) in reversed(unseen):

            details = (
                f"Type: {name}\n"
                f"Description: {description}\n"
                "Source: Official SEC EDGAR filing"
            )

            send_one(
                f"SEC {name}",
                "🇺🇸",
                title,
                link,
                state_file,
                item_id=stable_id,
                details=details,
            )

    except Exception as error:
        print(
            f"SEC {name} failed, "
            f"skipping: {error}"
        )


def fetch_sec_filings():
    if not SEC_USER_AGENT:
        print(
            "SEC filings skipped: "
            "SEC_USER_AGENT "
            "is not configured."
        )
        return

    for row in SEC_FORMS:
        fetch_sec_form(
            *row
        )

        time.sleep(1.0)

import os
import time
import urllib.error
import urllib.request


SEC_USER_AGENT = os.environ.get("SEC_USER_AGENT", "").strip()

GENERAL_USER_AGENT = "Mozilla/5.0 (compatible; TriFlux247/2.0)"


def download(url, retries=4, sec=False):
    headers = {
        "User-Agent": SEC_USER_AGENT if sec and SEC_USER_AGENT else GENERAL_USER_AGENT,
        "Accept": "*/*",
    }

    last_error = None

    for attempt in range(retries):
        try:
            request = urllib.request.Request(url, headers=headers)

            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read()

        except (
            urllib.error.HTTPError,
            urllib.error.URLError,
            TimeoutError,
        ) as exc:
            last_error = exc

            if attempt < retries - 1:
                time.sleep(2 ** attempt)

    if last_error:
        raise last_error

    raise RuntimeError(f"Download failed: {url}")

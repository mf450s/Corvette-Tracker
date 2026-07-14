from __future__ import annotations

import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

USER_AGENT = "corvetteTracker/0.1 (+https://github.com/mf450s/corvetteTracker)"


class FetchError(RuntimeError):
    pass


class CloudflareBlocked(FetchError):
    """Raised when the target site is behind a Cloudflare challenge that
    cannot be bypassed with a plain HTTP request."""

    pass


def is_cloudflare_challenge(html: str) -> bool:
    """Detect if the response is a Cloudflare JS challenge page
    (no real content, just a captcha/browser-check placeholder)."""
    return bool(
        html
        and "Just a moment" in html[:500]
        and "challenges.cloudflare.com" in html[:2000]
        and "cf_chl_opt" in html
    )


def fetch_html(url: str, *, timeout: int = 30, retries: int = 2) -> str:
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        request = Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "de-DE,de;q=0.9,en;q=0.5",
            },
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                raw = response.read()
                charset = response.headers.get_content_charset() or "utf-8"
                body = raw.decode(charset, errors="replace")
                if is_cloudflare_challenge(body):
                    raise CloudflareBlocked(f"cloudflare challenge at {url}")
                return body
        except (HTTPError, URLError, TimeoutError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(1 + attempt)
    raise FetchError(f"failed to fetch {url}: {last_error}")

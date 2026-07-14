from corvette_tracker.http import CloudflareBlocked, is_cloudflare_challenge


def test_is_cloudflare_challenge_detects_js_challenge_page():
    html = """
    <!DOCTYPE html><html lang="en-US"><head>
    <title>Just a moment...</title>
    <meta http-equiv="content-security-policy"
          content="default-src &#39;none&#39;; script-src &#39;nonce-abc&#39; &#39;unsafe-eval&#39; https://challenges.cloudflare.com">
    </head><body>
    <script>window._cf_chl_opt = {cType: "managed"};</script>
    <script src="/cdn-cgi/challenge-platform/scripts/main.js"></script>
    </body></html>
    """
    assert is_cloudflare_challenge(html) is True


def test_is_cloudflare_challenge_returns_false_for_normal_page():
    html = "<html><body><h1>Chevrolet Corvette 28.900 €</h1></body></html>"
    assert is_cloudflare_challenge(html) is False


def test_is_cloudflare_challenge_returns_false_for_empty():
    assert is_cloudflare_challenge("") is False
    assert is_cloudflare_challenge("  ") is False


def test_is_cloudflare_challenge_short_input():
    """Should not crash on input shorter than check boundary."""
    assert is_cloudflare_challenge("<html>Just a moment") is False

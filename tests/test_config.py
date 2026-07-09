import yaml
from urllib.parse import parse_qs, urlparse

from corvette_tracker.cli import DEFAULT_CONFIG, collect_live, load_config
from corvette_tracker.sources.autouncle import DEFAULT_URL as AUTOUNCLE_URL
from corvette_tracker.sources.autoscout24 import DEFAULT_URL as AUTOSCOUT24_URL
from corvette_tracker.sources.classic_trader import DEFAULT_URL as CLASSIC_TRADER_URL
from corvette_tracker.sources.kleinanzeigen import DEFAULT_URL as KLEINANZEIGEN_URL
from corvette_tracker.sources.mobile_de import DEFAULT_URL as MOBILE_DE_URL

EXPECTED_SOURCE_URLS = {
    "autoscout24": AUTOSCOUT24_URL,
    "kleinanzeigen": KLEINANZEIGEN_URL,
    "autouncle": AUTOUNCLE_URL,
    "classic_trader": CLASSIC_TRADER_URL,
    "mobile_de": MOBILE_DE_URL,
}


def test_example_config_uses_standard_source_urls():
    with open("config.example.yaml", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)

    for source, expected_url in EXPECTED_SOURCE_URLS.items():
        assert config["sources"][source]["url"] == expected_url


def test_default_config_uses_standard_source_urls():
    for source, expected_url in EXPECTED_SOURCE_URLS.items():
        assert DEFAULT_CONFIG["sources"][source]["url"] == expected_url


def test_standard_source_urls_are_broad_enough_to_catch_c6_listings_without_c6_in_title():
    autoscout_query = parse_qs(urlparse(AUTOSCOUT24_URL).query)

    assert urlparse(AUTOSCOUT24_URL).path == "/lst/chevrolet/corvette"
    assert "cat" not in autoscout_query
    assert autoscout_query["fregfrom"] == ["2005"]
    assert autoscout_query["fregto"] == ["2013"]
    assert "/corvette-c6/" not in KLEINANZEIGEN_URL
    assert "freetext=C6" not in AUTOUNCLE_URL
    assert not CLASSIC_TRADER_URL.rstrip("/").endswith("/c6")


def test_active_config_uses_broadened_standard_source_urls():
    with open("config.yaml", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)

    for source, expected_url in EXPECTED_SOURCE_URLS.items():
        assert config["sources"][source]["url"] == expected_url


def test_configs_can_crawl_multiple_urls_per_source():
    with open("config.example.yaml", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)

    assert config["sources"]["autoscout24"]["url"] in config["sources"]["autoscout24"]["urls"]
    assert len(config["sources"]["autoscout24"]["urls"]) >= 2
    assert config["sources"]["kleinanzeigen"]["url"] in config["sources"]["kleinanzeigen"]["urls"]
    assert len(config["sources"]["kleinanzeigen"]["urls"]) >= 2


def test_collect_live_fetches_all_configured_urls_for_source(monkeypatch):
    calls: list[str] = []

    def fake_fetch(url: str):
        calls.append(url)
        return []

    monkeypatch.setattr("corvette_tracker.cli.fetch_autoscout24", fake_fetch)
    config = {
        "sources": {
            "autoscout24": {"enabled": True, "urls": ["https://example.test/a", "https://example.test/b"]},
            "kleinanzeigen": {"enabled": False},
            "autouncle": {"enabled": False},
            "classic_trader": {"enabled": False},
            "mobile_de": {"enabled": False},
        }
    }

    listings, warnings = collect_live(config)

    assert listings == []
    assert warnings == []
    assert calls == ["https://example.test/a", "https://example.test/b"]


def test_default_config_contains_user_preference_scoring_weights():
    weights = DEFAULT_CONFIG["scoring"]["weights"]

    assert weights["manual_transmission"] > weights["non_convertible"]
    assert weights["non_convertible"] == weights["non_ls2"]
    assert weights["preferred_trim"] < weights["non_ls2"]
    assert DEFAULT_CONFIG["scoring"]["preferred_trims"] == ["Grand Sport", "Z06", "ZR1"]


def test_load_config_deep_merges_scoring_weights(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
scoring:
  weights:
    manual_transmission: 42
""", encoding="utf-8")

    config = load_config(str(config_file))

    assert config["scoring"]["weights"]["manual_transmission"] == 42
    assert config["scoring"]["weights"]["non_convertible"] == DEFAULT_CONFIG["scoring"]["weights"]["non_convertible"]

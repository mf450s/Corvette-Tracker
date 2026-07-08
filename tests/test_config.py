import yaml

from corvette_tracker.cli import DEFAULT_CONFIG
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

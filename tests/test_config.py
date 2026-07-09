import yaml

from corvette_tracker.cli import DEFAULT_CONFIG, load_config
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

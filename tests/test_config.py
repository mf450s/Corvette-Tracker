import yaml
from urllib.parse import parse_qs, urlparse

from corvette_tracker.cli import collect_live, load_config
from corvette_tracker.config import make_default_config
from corvette_tracker.sources.autouncle import DEFAULT_URL as AUTOUNCLE_URL
from corvette_tracker.sources.autoscout24 import DEFAULT_URL as AUTOSCOUT24_URL
from corvette_tracker.sources.classic_trader import DEFAULT_URL as CLASSIC_TRADER_URL
from corvette_tracker.sources.kleinanzeigen import DEFAULT_URL as KLEINANZEIGEN_URL
from corvette_tracker.sources.mobile_de import DEFAULT_URL as MOBILE_DE_URL

REQUESTED_AUTOSCOUT24_URL = "https://www.autoscout24.de/lst?cat=ma16380mo19141%2Cma16380mo19140%2Cma16380mo20782%2Cma16380mo75462%2Cma16380mo21061%2Cma16380mo74838%2Cma16380mo19142%2Cma16380mo19143&cy=D&damaged_listing=exclude&desc=0&ocs_listing=include&powertype=kw&sort=standard&ustate=N%2CU&atype=C&search_id=nfg3gad0ed&source=homepage_search-mask"
REQUESTED_KLEINANZEIGEN_URL = "https://www.kleinanzeigen.de/s-autos/sortierung:neuste/corvette-c6/k0c216"

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
    default = make_default_config()
    for source, expected_url in EXPECTED_SOURCE_URLS.items():
        assert default.sources[source].url == expected_url


def test_standard_source_urls_use_requested_marketplace_urls():
    autoscout_query = parse_qs(urlparse(AUTOSCOUT24_URL).query)

    assert AUTOSCOUT24_URL == REQUESTED_AUTOSCOUT24_URL
    assert KLEINANZEIGEN_URL == REQUESTED_KLEINANZEIGEN_URL
    assert autoscout_query["cat"] == ["ma16380mo19141,ma16380mo19140,ma16380mo20782,ma16380mo75462,ma16380mo21061,ma16380mo74838,ma16380mo19142,ma16380mo19143"]
    assert autoscout_query["cy"] == ["D"]
    assert autoscout_query["damaged_listing"] == ["exclude"]
    assert autoscout_query["ustate"] == ["N,U"]
    assert "sortierung:neuste" in KLEINANZEIGEN_URL
    assert "corvette-c6" in KLEINANZEIGEN_URL


def test_active_config_uses_requested_standard_source_urls():
    with open("config.yaml", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)

    for source, expected_url in EXPECTED_SOURCE_URLS.items():
        assert config["sources"][source]["url"] == expected_url


def test_configs_keep_primary_url_in_optional_url_list():
    with open("config.example.yaml", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)

    assert config["sources"]["autoscout24"]["url"] in config["sources"]["autoscout24"]["urls"]
    assert config["sources"]["kleinanzeigen"]["url"] in config["sources"]["kleinanzeigen"]["urls"]


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
    default = make_default_config()
    weights = default.scoring.weights

    assert weights.manual_transmission > weights.non_convertible
    assert weights.non_convertible == weights.non_ls2
    assert weights.preferred_trim < weights.non_ls2
    assert default.scoring.preferred_trims == ["Grand Sport", "Z06", "ZR1"]


def test_load_config_deep_merges_scoring_weights(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
scoring:
  weights:
    manual_transmission: 42
""", encoding="utf-8")

    config = load_config(str(config_file))
    default = make_default_config().to_flat_dict()

    assert config["scoring"]["weights"]["manual_transmission"] == 42
    assert config["scoring"]["weights"]["non_convertible"] == default["scoring"]["weights"]["non_convertible"]


def test_load_config_validates_unknown_source(tmp_path):
    """Unknown source names should raise a clear validation error."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
sources:
  unknown_source:
    enabled: true
""", encoding="utf-8")

    import pydantic
    import pytest
    with pytest.raises(pydantic.ValidationError):
        load_config(str(config_file))


def test_load_config_rejects_negative_base_score(tmp_path):
    """Negative base score should fail validation."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
scoring:
  base_score: -5
""", encoding="utf-8")

    import pydantic
    import pytest
    with pytest.raises(pydantic.ValidationError):
        load_config(str(config_file))


def test_load_config_rejects_zero_max_images(tmp_path):
    """max_images < 1 should fail validation."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
ai_enrichment:
  max_images: 0
""", encoding="utf-8")

    import pydantic
    import pytest
    with pytest.raises(pydantic.ValidationError):
        load_config(str(config_file))

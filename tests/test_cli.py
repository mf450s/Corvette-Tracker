import json
import subprocess
import sys
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from corvette_tracker.cli import run_hide, run_scrape, run_unhide
from corvette_tracker.models import Listing
from corvette_tracker.storage import TrackerStore


def test_cli_run_with_fixture_writes_site_and_exports(tmp_path: Path):
    fixture = tmp_path / "sample.html"
    fixture.write_text("""
    <article data-testid="list-item" id="as24-1">
      <a href="/angebote/corvette-c6-z06">Chevrolet Corvette C6 Z06 LS7</a>
      <img src="https://img.example/c6.jpg" />
      <p>59.900 €</p><p>72.000 km</p><p>05/2008</p><p>512 PS</p><p>München</p>
      <span>unfallfrei HU 06/2027</span>
    </article>
    """)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "corvette_tracker.cli",
            "run",
            "--fixture",
            str(fixture),
            "--output-dir",
            str(tmp_path),
        ],
        text=True,
        capture_output=True,
        check=True,
    )

    assert "1 listings" in result.stdout
    assert (tmp_path / "site" / "index.html").exists()
    payload = json.loads((tmp_path / "data" / "exports" / "latest.json").read_text())
    assert payload["summary"]["total_active"] == 1


# ── CLI scrape command tests ───────────────────────────────────────────────


def test_cli_scrape_prints_message(tmp_path: Path) -> None:
    """run_scrape prints a status message and returns 0 on success."""
    db = tmp_path / "test_cli_scrape.sqlite"
    store = TrackerStore(db)
    listing = Listing(
        id="clitest_001",
        source="Kleinanzeigen",
        source_listing_id="99999",
        url="https://www.kleinanzeigen.de/s-anzeige/test-99999-216-1406",
        title="CLI Test Corvette",
        price_eur=25000,
        mileage_km=50000,
        score=60,
    )
    store.upsert_listings([listing])
    db_path_str = str(db)

    args = Namespace(
        offer_id="clitest_001",
        url=None,
        database=db_path_str,
        config=None,
        output_dir=None,
    )

    with patch("corvette_tracker.cli.re_scrape_offer") as mock_re_scrape:
        mock_re_scrape.return_value = {
            "success": True,
            "listing_id": "clitest_001",
            "source": "Kleinanzeigen",
            "action": "re_scraped",
            "change_type": "price_change",
            "message": "Angebot clitest_001 (CLI Test Corvette) neu gescraped: price_change, 25000 €, 50000 km",
        }
        exit_code = run_scrape(args)

    assert exit_code == 0
    mock_re_scrape.assert_called_once()
    call_kwargs = mock_re_scrape.call_args.kwargs
    assert call_kwargs["offer_id"] == "clitest_001"
    assert call_kwargs["url"] is None


def test_cli_scrape_failure_returns_1(tmp_path: Path) -> None:
    """run_scrape returns exit code 1 when re_scrape fails."""
    db = tmp_path / "test_cli_scrape_fail.sqlite"
    TrackerStore(db)  # create DB
    db_path_str = str(db)

    args = Namespace(
        offer_id="nonexistent",
        url=None,
        database=db_path_str,
        config=None,
        output_dir=None,
    )

    with patch("corvette_tracker.cli.re_scrape_offer") as mock_re_scrape:
        mock_re_scrape.return_value = {
            "success": False,
            "listing_id": "nonexistent",
            "action": "not_found",
            "message": "Kein Listing mit ID nonexistent in der Datenbank",
        }
        exit_code = run_scrape(args)

    assert exit_code == 1
    mock_re_scrape.assert_called_once()


def test_cli_scrape_via_url(tmp_path: Path) -> None:
    """run_scrape works with --url instead of --offer-id."""
    db = tmp_path / "test_cli_scrape_url.sqlite"
    TrackerStore(db)
    db_path_str = str(db)
    url = "https://www.kleinanzeigen.de/s-anzeige/url-test-54321-216-1406"

    args = Namespace(
        offer_id=None,
        url=url,
        database=db_path_str,
        config=None,
        output_dir=None,
    )

    with patch("corvette_tracker.cli.re_scrape_offer") as mock_re_scrape:
        mock_re_scrape.return_value = {
            "success": True,
            "listing_id": None,
            "source": "Kleinanzeigen",
            "action": "re_scraped",
            "message": f"Angebot über URL {url} neu gescraped",
        }
        exit_code = run_scrape(args)

    assert exit_code == 0
    mock_re_scrape.assert_called_once()
    assert mock_re_scrape.call_args.kwargs["url"] == url


def test_cli_scrape_help_text_via_subprocess() -> None:
    """The scrape subcommand appears in --help."""
    result = subprocess.run(
        [sys.executable, "-m", "corvette_tracker.cli", "--help"],
        text=True,
        capture_output=True,
        check=True,
    )
    assert "scrape" in result.stdout
    assert "re-scrape" in result.stdout


def test_cli_scrape_args_via_subprocess() -> None:
    """The scrape subcommand shows --offer-id and --url in its help."""
    result = subprocess.run(
        [sys.executable, "-m", "corvette_tracker.cli", "scrape", "--help"],
        text=True,
        capture_output=True,
        check=True,
    )
    assert "--offer-id" in result.stdout
    assert "--url" in result.stdout
    assert "--database" in result.stdout


# ── CLI hide / unhide tests ────────────────────────────────────────────


def test_cli_hide_help_text_via_subprocess() -> None:
    """The hide subcommand appears in --help."""
    result = subprocess.run(
        [sys.executable, "-m", "corvette_tracker.cli", "--help"],
        text=True,
        capture_output=True,
        check=True,
    )
    assert "hide" in result.stdout
    assert "unhide" in result.stdout


def test_cli_hide_args_via_subprocess() -> None:
    """The hide subcommand shows listing_id arg in its help."""
    result = subprocess.run(
        [sys.executable, "-m", "corvette_tracker.cli", "hide", "--help"],
        text=True,
        capture_output=True,
        check=True,
    )
    assert "listing_id" in result.stdout
    assert "--database" in result.stdout


def test_cli_unhide_help_via_subprocess() -> None:
    """The unhide subcommand shows listing_id arg in its help."""
    result = subprocess.run(
        [sys.executable, "-m", "corvette_tracker.cli", "unhide", "--help"],
        text=True,
        capture_output=True,
        check=True,
    )
    assert "listing_id" in result.stdout


def test_cli_hide_and_unhide_roundtrip(tmp_path: Path) -> None:
    """hide and unhide commands work end-to-end on a real listing."""
    db = tmp_path / "test_cli_hide.sqlite"
    store = TrackerStore(db)
    listing = Listing(
        id="hide_test_001",
        source="AutoScout24",
        source_listing_id="hide999",
        url="https://example.test/hide-test",
        title="Corvette C6 Hide Test",
        price_eur=30000,
        mileage_km=40000,
        score=70,
    )
    store.upsert_listings([listing])

    # Hide via CLI
    exit_code = run_hide(
        Namespace(
            listing_id="hide_test_001",
            database=str(db),
            config=None,
            output_dir=None,
        )
    )
    assert exit_code == 0

    row = store.conn.execute(
        "SELECT hidden FROM listings WHERE id = ?", ("hide_test_001",)
    ).fetchone()
    assert row["hidden"] == 1

    # Unhide via CLI
    exit_code = run_unhide(
        Namespace(
            listing_id="hide_test_001",
            database=str(db),
            config=None,
            output_dir=None,
        )
    )
    assert exit_code == 0

    row = store.conn.execute(
        "SELECT hidden FROM listings WHERE id = ?", ("hide_test_001",)
    ).fetchone()
    assert row["hidden"] == 0

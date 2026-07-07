import json
import subprocess
import sys
from pathlib import Path


def test_cli_run_with_fixture_writes_site_and_exports(tmp_path: Path):
    fixture = tmp_path / "sample.html"
    fixture.write_text('''
    <article data-testid="list-item" id="as24-1">
      <a href="/angebote/corvette-c6-z06">Chevrolet Corvette C6 Z06 LS7</a>
      <img src="https://img.example/c6.jpg" />
      <p>59.900 €</p><p>72.000 km</p><p>05/2008</p><p>512 PS</p><p>München</p>
      <span>unfallfrei HU 06/2027</span>
    </article>
    ''')

    result = subprocess.run(
        [sys.executable, "-m", "corvette_tracker.cli", "run", "--fixture", str(fixture), "--output-dir", str(tmp_path)],
        text=True,
        capture_output=True,
        check=True,
    )

    assert "1 listings" in result.stdout
    assert (tmp_path / "site" / "index.html").exists()
    payload = json.loads((tmp_path / "data" / "exports" / "latest.json").read_text())
    assert payload["summary"]["total_active"] == 1

import re
from pathlib import Path

from corvette_tracker.storage import SCHEMA


def test_runtime_tables_are_documented_as_schema_tables() -> None:
    dbml = (Path(__file__).parents[1] / "database" / "schema.dbml").read_text()
    runtime_tables = set(re.findall(r"CREATE TABLE IF NOT EXISTS (\\w+)", SCHEMA))
    documented_tables = set(re.findall(r"^Table (\\w+)", dbml, flags=re.MULTILINE))

    assert runtime_tables <= documented_tables
    assert "Runtime note:" in dbml

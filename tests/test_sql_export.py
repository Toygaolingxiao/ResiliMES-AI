"""The committed Zetaris seed stays generated from data/sample."""

from pathlib import Path

from resilimes.data.sql_export import TABLES, render_csv, render_sql


def test_seed_matches_sample_documents() -> None:
    assert Path("data/sql/seed.sql").read_text(encoding="utf-8") == render_sql()
    for name in TABLES:
        committed = Path(f"data/zetaris/{name}.csv").read_text(encoding="utf-8")
        assert committed == render_csv(name)
    text = Path("data/sql/seed.sql").read_text(encoding="utf-8")
    assert "LITHO-02" in text
    assert "RESIST-UV" in text
    assert "DROP " not in text.upper()

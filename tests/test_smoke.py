"""Smoke tests — не требуют внешних API."""
import json
import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent


def test_imports():
    import tools  # noqa: F401
    import scraper  # noqa: F401
    import analyze  # noqa: F401
    import agent  # noqa: F401
    import pipeline  # noqa: F401


def test_config_companies_valid_json():
    path = PROJECT_ROOT / "config" / "companies.json"
    assert path.exists(), "config/companies.json не найден"
    data = json.loads(path.read_text())
    assert isinstance(data, list)
    assert len(data) > 0
    for company in data:
        assert "id" in company
        assert "name" in company
        assert "url" in company


def test_config_pricing_valid_json():
    path = PROJECT_ROOT / "config" / "models_pricing.json"
    assert path.exists(), "config/models_pricing.json не найден"
    data = json.loads(path.read_text())
    assert "models" in data
    assert len(data["models"]) > 0


def test_db_exists():
    path = PROJECT_ROOT / "data" / "reviews.db"
    assert path.exists(), "data/reviews.db не найден"


def test_db_tables_exist():
    db_path = PROJECT_ROOT / "data" / "reviews.db"
    conn = sqlite3.connect(db_path)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert "reviews" in tables
    assert "categories" in tables


def test_db_reviews_not_empty():
    db_path = PROJECT_ROOT / "data" / "reviews.db"
    conn = sqlite3.connect(db_path)
    count = conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]
    conn.close()
    assert count > 0, "Таблица reviews пуста"


def test_db_reviews_has_company_column():
    db_path = PROJECT_ROOT / "data" / "reviews.db"
    conn = sqlite3.connect(db_path)
    columns = {r[1] for r in conn.execute("PRAGMA table_info(reviews)")}
    conn.close()
    assert "company" in columns
    assert "reply_date" in columns


def test_cache_dir_exists():
    path = PROJECT_ROOT / "data" / "cache"
    assert path.exists(), "data/cache не найден"


def test_reports_dir_exists():
    path = PROJECT_ROOT / "reports"
    assert path.exists(), "reports/ не найден"

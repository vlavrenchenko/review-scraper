"""Тесты FTS5 полнотекстового поиска."""
import sqlite3
import pytest
from importlib import reload
from unittest.mock import patch


@pytest.fixture
def search_db(tmp_path):
    """Тестовая БД с FTS5 индексом и несколькими отзывами."""
    db_path = tmp_path / "search_test.db"
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE reviews (
            id TEXT PRIMARY KEY, company TEXT, title TEXT, text TEXT,
            published_date TEXT, rating INTEGER, reply TEXT,
            reply_date TEXT, author_hash TEXT, scraped_at TEXT
        )
    """)
    reviews = [
        ("r1", "rentumo", "Great support team", "The support was very helpful and fast", "2026-01-01", 5, None, None, "a", "2026-01-01"),
        ("r2", "rentumo", "Hidden fees problem", "They charged hidden fees without notice", "2026-01-02", 1, None, None, "b", "2026-01-01"),
        ("r3", "immobilienscout24", "Support ignored me", "I contacted support but got no reply", "2026-01-03", 2, None, None, "c", "2026-01-01"),
        ("r4", "immobilienscout24", "Good platform", "Easy to find apartments in Berlin", "2026-01-04", 5, None, None, "d", "2026-01-01"),
        ("r5", "rentumo", "Betrug!", "Das ist ein kompletter Betrug, ich verlange Rückerstattung", "2026-01-05", 1, None, None, "e", "2026-01-01"),
    ]
    conn.executemany("INSERT INTO reviews VALUES (?,?,?,?,?,?,?,?,?,?)", reviews)
    conn.commit()
    conn.close()
    return db_path


def test_search_finds_keyword(search_db):
    """Поиск по ключевому слову возвращает релевантные отзывы."""
    import tools
    reload(tools)
    with patch("tools.DB_PATH", search_db):
        results = tools.search_reviews("support")
    ids = [r["id"] for r in results]
    assert "r1" in ids
    assert "r3" in ids
    assert "r4" not in ids  # нет слова support


def test_search_with_company_filter(search_db):
    """Фильтр по компании ограничивает результаты."""
    import tools
    reload(tools)
    with patch("tools.DB_PATH", search_db):
        results = tools.search_reviews("support", company="rentumo")
    assert all(r["company"] == "rentumo" for r in results)
    ids = [r["id"] for r in results]
    assert "r1" in ids
    assert "r3" not in ids  # r3 — immobilienscout24


def test_search_no_results(search_db):
    """Поиск несуществующего слова возвращает пустой список."""
    import tools
    reload(tools)
    with patch("tools.DB_PATH", search_db):
        results = tools.search_reviews("xyznonexistent123")
    assert results == []


def test_search_german_text(search_db):
    """Поиск по немецкому слову работает корректно."""
    import tools
    reload(tools)
    with patch("tools.DB_PATH", search_db):
        results = tools.search_reviews("Betrug")
    assert len(results) == 1
    assert results[0]["id"] == "r5"


def test_search_limit(search_db):
    """Параметр limit ограничивает количество результатов."""
    import tools
    reload(tools)
    with patch("tools.DB_PATH", search_db):
        results = tools.search_reviews("support", limit=1)
    assert len(results) == 1


def test_search_result_fields(search_db):
    """Результат содержит все нужные поля."""
    import tools
    reload(tools)
    with patch("tools.DB_PATH", search_db):
        results = tools.search_reviews("support", limit=1)
    assert len(results) > 0
    r = results[0]
    assert "id" in r
    assert "company" in r
    assert "rating" in r
    assert "title" in r
    assert "text" in r
    assert "published_date" in r


def test_fts_index_rebuilt_for_new_db(search_db):
    """init_fts корректно строит индекс на новой БД."""
    import tools
    reload(tools)
    with patch("tools.DB_PATH", search_db):
        conn = sqlite3.connect(search_db)
        tools.init_fts(conn)
        count = conn.execute("SELECT COUNT(*) FROM reviews_fts").fetchone()[0]
        conn.close()
    assert count == 5

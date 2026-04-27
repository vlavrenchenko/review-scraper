"""Тесты гибридного поиска: FTS5 + ChromaDB + RRF."""
import sqlite3
import pytest
from importlib import reload
from unittest.mock import patch, MagicMock


@pytest.fixture
def hybrid_db(tmp_path):
    """Тестовая БД с отзывами для проверки поиска."""
    db_path = tmp_path / "hybrid_test.db"
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE reviews (
            id TEXT PRIMARY KEY, company TEXT, title TEXT, text TEXT,
            published_date TEXT, rating INTEGER, reply TEXT,
            reply_date TEXT, author_hash TEXT, scraped_at TEXT
        )
    """)
    reviews = [
        ("r1", "rentumo", "Hidden fees charged", "They charged hidden fees without warning", "2026-01-01", 1, None, None, "a", "2026-01-01"),
        ("r2", "rentumo", "Great service", "Very helpful and responsive team", "2026-01-02", 5, None, None, "b", "2026-01-01"),
        ("r3", "immobilienscout24", "Payment issues", "Unexpected payment charges on my account", "2026-01-03", 2, None, None, "c", "2026-01-01"),
        ("r4", "immobilienscout24", "Good platform", "Easy to find apartments in Berlin", "2026-01-04", 4, None, None, "d", "2026-01-01"),
    ]
    conn.executemany("INSERT INTO reviews VALUES (?,?,?,?,?,?,?,?,?,?)", reviews)
    conn.commit()
    conn.close()
    return db_path


def test_rrf_merges_results():
    """_rrf корректно объединяет два списка через RRF."""
    import tools
    reload(tools)

    fts = ["r1", "r2", "r3"]
    semantic = ["r3", "r1", "r4"]
    merged = tools._rrf(fts, semantic)

    # r1 и r3 присутствуют в обоих списках — должны быть выше
    assert merged.index("r1") < merged.index("r4")
    assert merged.index("r3") < merged.index("r2")


def test_rrf_deduplicates():
    """_rrf не дублирует одинаковые id."""
    import tools
    reload(tools)

    merged = tools._rrf(["r1", "r2"], ["r1", "r3"])
    assert len(merged) == len(set(merged))


def test_rrf_empty_lists():
    """_rrf корректно обрабатывает пустые списки."""
    import tools
    reload(tools)

    assert tools._rrf([], []) == []
    assert tools._rrf(["r1"], []) == ["r1"]
    assert tools._rrf([], ["r1"]) == ["r1"]


def test_search_fts_only_when_no_chroma(hybrid_db):
    """search_reviews работает только через FTS если ChromaDB недоступна."""
    import tools
    reload(tools)

    with patch("tools.DB_PATH", hybrid_db), \
         patch("tools._semantic_search", return_value=[]):
        results = tools.search_reviews("fees", company="rentumo")

    assert len(results) > 0
    assert all(r["company"] == "rentumo" for r in results)


def test_search_semantic_only_when_fts_empty(hybrid_db):
    """search_reviews работает только через семантику если FTS ничего не нашёл."""
    import tools
    reload(tools)

    with patch("tools.DB_PATH", hybrid_db), \
         patch("tools._fts_search", return_value=[]), \
         patch("tools._semantic_search", return_value=["r2", "r4"]):
        results = tools.search_reviews("great experience")

    ids = [r["id"] for r in results]
    assert "r2" in ids or "r4" in ids


def test_search_hybrid_merges_both(hybrid_db):
    """search_reviews объединяет результаты FTS и семантики через RRF."""
    import tools
    reload(tools)

    with patch("tools.DB_PATH", hybrid_db), \
         patch("tools._fts_search", return_value=["r1", "r3"]), \
         patch("tools._semantic_search", return_value=["r3", "r2"]):
        results = tools.search_reviews("payment fees")

    ids = [r["id"] for r in results]
    # r3 присутствует в обоих списках — должен быть в результатах
    assert "r3" in ids


def test_search_respects_limit(hybrid_db):
    """search_reviews возвращает не больше limit результатов."""
    import tools
    reload(tools)

    with patch("tools.DB_PATH", hybrid_db), \
         patch("tools._semantic_search", return_value=[]):
        results = tools.search_reviews("fees OR payment OR service", limit=1)

    assert len(results) <= 1


def test_fts_search_handles_bad_query(hybrid_db):
    """_fts_search возвращает пустой список при невалидном запросе."""
    import tools
    reload(tools)

    with patch("tools.DB_PATH", hybrid_db):
        # Невалидный FTS5 синтаксис
        result = tools._fts_search("AND OR", None, 5)

    assert result == []

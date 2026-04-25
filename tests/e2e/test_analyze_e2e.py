"""
E2E тест анализатора — реальный OpenAI, реальные отзывы из БД.
Запуск: pytest -m e2e
"""
import sqlite3
import pytest


@pytest.mark.e2e
def test_analyze_returns_valid_categories(require_openai, db_has_data):
    """analyze_group возвращает корректно структурированные категории."""
    from openai import OpenAI
    from dotenv import load_dotenv
    import analyze

    load_dotenv(override=True)

    conn = sqlite3.connect(db_has_data)
    rows = conn.execute(
        "SELECT id, title, text, rating FROM reviews WHERE rating <= 3 LIMIT 10"
    ).fetchall()
    conn.close()

    if not rows:
        pytest.skip("Нет негативных отзывов в БД")

    reviews = [{"id": r[0], "title": r[1], "text": r[2], "rating": r[3]} for r in rows]
    client = OpenAI()
    result, usage = analyze._analyze_batch(client, reviews, "негативные", "gpt-4o-mini")

    assert "categories" in result
    assert isinstance(result["categories"], list)
    assert len(result["categories"]) > 0

    for cat in result["categories"]:
        assert "name" in cat
        assert "count" in cat
        assert isinstance(cat["count"], int)

    assert usage["input"] > 0
    assert usage["output"] > 0


@pytest.mark.e2e
def test_analyze_positive_reviews(require_openai, db_has_data):
    """analyze_group корректно обрабатывает позитивные отзывы."""
    import sqlite3
    from openai import OpenAI
    from dotenv import load_dotenv
    import analyze

    load_dotenv(override=True)

    conn = sqlite3.connect(db_has_data)
    rows = conn.execute(
        "SELECT id, title, text, rating FROM reviews WHERE rating >= 4 LIMIT 10"
    ).fetchall()
    conn.close()

    if not rows:
        pytest.skip("Нет позитивных отзывов в БД")

    reviews = [{"id": r[0], "title": r[1], "text": r[2], "rating": r[3]} for r in rows]
    client = OpenAI()
    result, _ = analyze._analyze_batch(client, reviews, "позитивные", "gpt-4o-mini")

    assert "categories" in result
    assert len(result["categories"]) > 0

"""Unit тесты для tools.py — работают с тестовой БД."""
import pytest
from importlib import reload
from unittest.mock import patch


def test_get_stats_returns_correct_fields(test_db):
    import tools
    reload(tools)
    with patch("tools.DB_PATH", test_db):
        result = tools.get_stats("rentumo")

    assert result["company"] == "rentumo"
    assert result["total_reviews"] == 3
    assert result["avg_rating"] == 3.0
    assert result["negative_total"] == 2  # rating 1 и 3
    assert result["negative_with_reply"] == 1  # только r3 имеет reply
    assert "rating_distribution" in result


def test_get_stats_all_companies(test_db):
    import tools
    reload(tools)
    with patch("tools.DB_PATH", test_db):
        result = tools.get_stats()

    assert isinstance(result, list)
    companies = {r["company"] for r in result}
    assert "rentumo" in companies
    assert "immobilienscout24" in companies


def test_get_reviews_returns_list(test_db):
    import tools
    reload(tools)
    with patch("tools.DB_PATH", test_db):
        result = tools.get_reviews("rentumo")

    assert isinstance(result, list)
    assert len(result) == 3
    for r in result:
        assert "id" in r
        assert "rating" in r
        assert "text" in r
        assert "has_reply" in r


def test_get_reviews_filter_by_rating(test_db):
    import tools
    reload(tools)
    with patch("tools.DB_PATH", test_db):
        result = tools.get_reviews("rentumo", min_rating=1, max_rating=1)

    assert len(result) == 1
    assert result[0]["rating"] == 1


def test_get_reviews_limit(test_db):
    import tools
    reload(tools)
    with patch("tools.DB_PATH", test_db):
        result = tools.get_reviews("rentumo", limit=2)

    assert len(result) == 2


def test_get_categories_negative(test_db):
    import tools
    reload(tools)
    with patch("tools.DB_PATH", test_db):
        result = tools.get_categories("rentumo", "negative")

    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["group_type"] == "negative"
    assert result[0]["name"] == "Нет ответов"


def test_get_categories_both(test_db):
    import tools
    reload(tools)
    with patch("tools.DB_PATH", test_db):
        result = tools.get_categories("rentumo", "both")

    types = {r["group_type"] for r in result}
    assert "negative" in types
    assert "positive" in types


def test_call_tool_dispatcher(test_db):
    import tools
    reload(tools)
    with patch("tools.DB_PATH", test_db):
        result = tools.call_tool("get_stats", {"company": "rentumo"})
        assert result["company"] == "rentumo"

        result = tools.call_tool("get_reviews", {"company": "rentumo", "limit": 1})
        assert len(result) == 1


def test_call_tool_unknown_raises(test_db):
    import tools
    reload(tools)
    with patch("tools.DB_PATH", test_db):
        with pytest.raises(ValueError):
            tools.call_tool("unknown_tool", {})

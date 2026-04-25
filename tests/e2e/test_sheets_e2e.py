"""
E2E тест экспорта в Google Sheets — реальный Google API.
Запуск: pytest -m e2e
"""
import pytest


@pytest.mark.e2e
def test_export_stats_returns_url(require_sheets, db_has_data):
    """Экспорт статистики возвращает URL и список обновлённых листов."""
    from unittest.mock import patch
    import tools
    from importlib import reload

    with patch("tools.DB_PATH", db_has_data):
        reload(tools)
        result = tools.export_to_sheets(data_type="stats")

    assert "url" in result
    assert result["url"].startswith("https://docs.google.com/spreadsheets")
    assert "sheets_updated" in result
    assert len(result["sheets_updated"]) > 0


@pytest.mark.e2e
def test_export_reviews_with_filter(require_sheets, db_has_data):
    """Экспорт отзывов с фильтром по рейтингу проходит без ошибок."""
    from unittest.mock import patch
    import tools
    from importlib import reload

    with patch("tools.DB_PATH", db_has_data):
        reload(tools)
        result = tools.export_to_sheets(data_type="reviews", min_rating=4, max_rating=5)

    assert "url" in result
    assert any("⭐4" in s or "⭐5" in s or "4–5" in s for s in result["sheets_updated"])

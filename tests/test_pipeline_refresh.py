"""Тесты pipeline_refresh.py — скрапер и анализатор замоканы."""
import sqlite3
from importlib import reload
from types import SimpleNamespace
from unittest.mock import patch, MagicMock


def test_run_scraper_returns_new_count(test_db):
    """run_scraper возвращает количество новых отзывов по компании."""
    import pipeline_refresh
    reload(pipeline_refresh)

    args = SimpleNamespace(reviews=100, all_new=False)

    def fake_scrape(browser, company, scrape_args, conn):
        conn.execute(
            "INSERT INTO reviews (id, company, title, text, published_date, rating, "
            "reply, reply_date, author_hash, scraped_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("new_r1", company["id"], "T", "T", "2026-01-01", 5, None, None, "x", "2026-01-01")
        )
        conn.commit()

    targets = [{"id": "rentumo", "name": "Rentumo", "url": "http://x"}]

    with patch("pipeline_refresh.scrape_company", side_effect=fake_scrape), \
         patch("pipeline_refresh.sync_playwright") as mock_pw:
        mock_pw.return_value.__enter__.return_value.chromium.launch.return_value = MagicMock()
        conn = sqlite3.connect(test_db)
        results = pipeline_refresh.run_scraper(targets, args, conn)
        conn.close()

    assert results["rentumo"] == 1


def test_run_scraper_zero_when_no_new(test_db):
    """run_scraper возвращает 0 если новых отзывов не появилось."""
    import pipeline_refresh
    reload(pipeline_refresh)

    args = SimpleNamespace(reviews=100, all_new=False)

    def fake_scrape(browser, company, scrape_args, conn):
        pass  # ничего не добавляет

    targets = [{"id": "rentumo", "name": "Rentumo", "url": "http://x"}]

    with patch("pipeline_refresh.scrape_company", side_effect=fake_scrape), \
         patch("pipeline_refresh.sync_playwright") as mock_pw:
        mock_pw.return_value.__enter__.return_value.chromium.launch.return_value = MagicMock()
        conn = sqlite3.connect(test_db)
        results = pipeline_refresh.run_scraper(targets, args, conn)
        conn.close()

    assert results["rentumo"] == 0


def test_skip_analyze_flag(test_db):
    """--skip-analyze пропускает анализ и не вызывает OpenAI."""
    import pipeline_refresh
    reload(pipeline_refresh)

    analyze_called = []

    def fake_scrape(browser, company, scrape_args, conn):
        pass

    with patch("pipeline_refresh.scrape_company", side_effect=fake_scrape), \
         patch("pipeline_refresh.sync_playwright") as mock_pw, \
         patch("pipeline_refresh.run_analyzer", side_effect=lambda *a, **kw: analyze_called.append(1) or {}), \
         patch("pipeline_refresh.init_db", return_value=sqlite3.connect(test_db)):
        mock_pw.return_value.__enter__.return_value.chromium.launch.return_value = MagicMock()
        import sys
        with patch.object(sys, "argv", ["pipeline_refresh.py", "--company", "rentumo", "--skip-analyze"]):
            pipeline_refresh.main()

    assert len(analyze_called) == 0


def test_unknown_company_exits_early(test_db, capsys):
    """Неизвестная компания печатает ошибку и завершает работу."""
    import pipeline_refresh
    import sys
    reload(pipeline_refresh)

    with patch.object(sys, "argv", ["pipeline_refresh.py", "--company", "unknown_co"]), \
         patch("pipeline_refresh.init_db", return_value=sqlite3.connect(test_db)):
        pipeline_refresh.main()

    captured = capsys.readouterr()
    assert "Неизвестные компании" in captured.out

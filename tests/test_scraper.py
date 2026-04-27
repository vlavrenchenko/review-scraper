"""Тесты парсинга scraper.py — без Playwright и сети."""
from importlib import reload
from unittest.mock import patch


def test_parse_next_data_returns_reviews(sample_trustpilot_html):
    """Парсинг __NEXT_DATA__ возвращает список отзывов."""
    html, expected_reviews = sample_trustpilot_html

    start = html.find('id="__NEXT_DATA__"')
    assert start != -1
    start = html.find(">", start) + 1
    end = html.find("</script>", start)

    import json
    data = json.loads(html[start:end])
    reviews = data["props"]["pageProps"]["reviews"]

    assert len(reviews) == 2
    assert reviews[0]["id"] == "abc123"
    assert reviews[1]["rating"] == 1


def test_parse_review_fields(sample_trustpilot_html):
    """Все нужные поля присутствуют в отзыве."""
    _, reviews = sample_trustpilot_html
    r = reviews[0]

    assert r["id"] == "abc123"
    assert r["title"] == "Great platform"
    assert r["rating"] == 5
    assert r["dates"]["publishedDate"] == "2026-01-01T12:00:00.000Z"
    assert r["consumer"]["displayName"] == "Anna"
    assert r["reply"] is None


def test_parse_reply_fields(sample_trustpilot_html):
    """Поля reply корректно парсятся."""
    _, reviews = sample_trustpilot_html
    r = reviews[1]

    assert r["reply"] is not None
    assert r["reply"]["message"] == "We are sorry to hear that."
    assert r["reply"]["publishedDate"] == "2026-01-03T09:00:00.000Z"


def test_missing_next_data_returns_empty():
    """Если __NEXT_DATA__ нет — возвращаем пустой список."""
    html = "<html><body>Not found</body></html>"

    start = html.find('id="__NEXT_DATA__"')
    assert start == -1


def test_save_reviews_inserts_new(test_db):
    """save_reviews вставляет новые записи в БД."""
    import scraper
    reload(scraper)
    with patch("scraper.DB_PATH", test_db), patch("scraper.COMPANIES_PATH"):
        import sqlite3
        conn = sqlite3.connect(test_db)
        before = conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]

        new_reviews = [
            {
                "id": "new123",
                "title": "New review",
                "text": "Test text",
                "rating": 4,
                "dates": {"publishedDate": "2026-02-01T00:00:00.000Z"},
                "consumer": {"displayName": "TestUser"},
                "reply": None,
            }
        ]
        scraper.save_reviews(conn, new_reviews, "rentumo")
        after = conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]
        conn.close()

    assert after == before + 1


def _make_review(rid, rating=5):
    return {
        "id": rid,
        "title": "Title",
        "text": "Text",
        "rating": rating,
        "dates": {"publishedDate": "2026-01-01T00:00:00.000Z"},
        "consumer": {"displayName": "User"},
        "reply": None,
    }


def test_incremental_stops_when_all_known(test_db):
    """scrape_company останавливается если все отзывы страницы уже в БД."""
    import sqlite3
    import scraper
    from unittest.mock import MagicMock
    reload(scraper)

    with patch("scraper.DB_PATH", test_db), patch("scraper.COMPANIES_PATH"):
        conn = sqlite3.connect(test_db)

        # Страница содержит только уже известные ID (r1, r2, r3 — из conftest)
        page_all_known = [_make_review("r1"), _make_review("r2"), _make_review("r3")]

        args = MagicMock()
        args.reviews = 50
        args.no_cache = True
        args.cache_ttl = 60

        pages_fetched = []

        def fake_get_page(browser, url, company_id, page_num, no_cache, ttl):
            pages_fetched.append(page_num)
            return page_all_known

        with patch("scraper.get_page", side_effect=fake_get_page), \
             patch("scraper.random_timeout", return_value=0):
            scraper.scrape_company(MagicMock(), {"id": "rentumo", "name": "Rentumo", "url": "http://x"}, args, conn)

        conn.close()

    assert len(pages_fetched) == 1  # остановился после первой страницы


def test_incremental_collects_only_new(test_db):
    """scrape_company сохраняет только новые отзывы, пропускает дубли."""
    import sqlite3
    import scraper
    from unittest.mock import MagicMock
    reload(scraper)

    with patch("scraper.DB_PATH", test_db), patch("scraper.COMPANIES_PATH"):
        conn = sqlite3.connect(test_db)
        before = conn.execute("SELECT COUNT(*) FROM reviews WHERE company='rentumo'").fetchone()[0]

        # Страница содержит 1 известный и 1 новый отзыв
        mixed_page = [_make_review("r1"), _make_review("new_review_x")]

        args = MagicMock()
        args.reviews = 50
        args.no_cache = True
        args.cache_ttl = 60

        def fake_get_page(browser, url, company_id, page_num, no_cache, ttl):
            if page_num == 1:
                return mixed_page
            return []

        with patch("scraper.get_page", side_effect=fake_get_page), \
             patch("scraper.random_timeout", return_value=0):
            scraper.scrape_company(MagicMock(), {"id": "rentumo", "name": "Rentumo", "url": "http://x"}, args, conn)

        after = conn.execute("SELECT COUNT(*) FROM reviews WHERE company='rentumo'").fetchone()[0]
        conn.close()

    assert after == before + 1  # добавился только новый


def test_all_new_mode_collects_across_pages(test_db):
    """--all-new скачивает новые отзывы со всех страниц пока не встретит известные."""
    import sqlite3
    import scraper
    from unittest.mock import MagicMock
    reload(scraper)

    with patch("scraper.DB_PATH", test_db), patch("scraper.COMPANIES_PATH"):
        conn = sqlite3.connect(test_db)
        before = conn.execute("SELECT COUNT(*) FROM reviews WHERE company='rentumo'").fetchone()[0]

        args = MagicMock()
        args.reviews = 100
        args.all_new = True
        args.no_cache = True
        args.cache_ttl = 60

        pages = {
            1: [_make_review("new_a"), _make_review("new_b")],
            2: [_make_review("new_c"), _make_review("new_d")],
            3: [_make_review("r1"), _make_review("r2")],  # все известны → стоп
        }

        def fake_get_page(browser, url, company_id, page_num, no_cache, ttl):
            return pages.get(page_num, [])

        with patch("scraper.get_page", side_effect=fake_get_page), \
             patch("scraper.random_timeout", return_value=0):
            scraper.scrape_company(MagicMock(), {"id": "rentumo", "name": "Rentumo", "url": "http://x"}, args, conn)

        after = conn.execute("SELECT COUNT(*) FROM reviews WHERE company='rentumo'").fetchone()[0]
        conn.close()

    assert after == before + 4  # new_a, new_b, new_c, new_d


def test_save_reviews_ignores_duplicates(test_db):
    """save_reviews не дублирует уже существующие записи."""
    import scraper
    reload(scraper)
    with patch("scraper.DB_PATH", test_db), patch("scraper.COMPANIES_PATH"):
        import sqlite3
        conn = sqlite3.connect(test_db)
        before = conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]

        # r1 уже есть в тестовой БД (из conftest)
        duplicate = [
            {
                "id": "r1",
                "title": "Great service",
                "text": "Really helpful platform",
                "rating": 5,
                "dates": {"publishedDate": "2026-01-01T00:00:00.000Z"},
                "consumer": {"displayName": "Someone"},
                "reply": None,
            }
        ]
        inserted, _ = scraper.save_reviews(conn, duplicate, "rentumo")
        after = conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]
        conn.close()

    assert after == before
    assert inserted == 0

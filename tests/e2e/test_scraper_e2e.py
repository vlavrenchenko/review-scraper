"""
E2E тест скрапера — реальный Playwright, реальный Trustpilot.
Запуск: pytest -m e2e (медленный, ~30с)
"""
import pytest


@pytest.mark.e2e
def test_scraper_fetches_real_reviews():
    """Скрапер получает отзывы с Trustpilot и возвращает корректную структуру."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("Playwright не установлен")

    from scraper import fetch_page_from_web, _build_url

    url = "https://www.trustpilot.com/review/rentumo.de"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        reviews = fetch_page_from_web(browser, url, 1)
        browser.close()

    assert isinstance(reviews, list), "Должен вернуть список"
    assert len(reviews) > 0, "Список отзывов не должен быть пустым"

    first = reviews[0]
    assert "id" in first
    assert "rating" in first
    assert 1 <= first["rating"] <= 5
    assert "dates" in first


@pytest.mark.e2e
def test_build_url_languages_param():
    """_build_url добавляет languages=all и корректно строит URL для пагинации."""
    from scraper import _build_url

    base = "https://www.trustpilot.com/review/rentumo.de"
    assert "languages=all" in _build_url(base, 1)
    assert "languages=all" in _build_url(base, 2)
    assert "page=2" in _build_url(base, 2)
    assert "page=1" not in _build_url(base, 1)

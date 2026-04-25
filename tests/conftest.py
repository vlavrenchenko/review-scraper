import json
import sqlite3
import pytest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent


@pytest.fixture
def test_db(tmp_path):
    """Временная БД с тестовыми данными."""
    db_path = tmp_path / "test_reviews.db"
    conn = sqlite3.connect(db_path)

    conn.execute("""
        CREATE TABLE reviews (
            id TEXT PRIMARY KEY, company TEXT, title TEXT, text TEXT,
            published_date TEXT, rating INTEGER, reply TEXT,
            reply_date TEXT, author_hash TEXT, scraped_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT, company TEXT,
            group_type TEXT NOT NULL, name TEXT NOT NULL,
            description TEXT, count INTEGER, review_ids TEXT,
            model TEXT, analyzed_at TEXT
        )
    """)

    reviews = [
        ("r1", "rentumo", "Great service", "Really helpful platform", "2026-01-01", 5, None, None, "abc1", "2026-01-01"),
        ("r2", "rentumo", "Bad experience", "Never got a reply", "2026-01-02", 1, None, None, "abc2", "2026-01-01"),
        ("r3", "rentumo", "Okay", "Average service", "2026-01-03", 3, "Thank you", "2026-01-04", "abc3", "2026-01-01"),
        ("r4", "immobilienscout24", "Good", "Found apartment quickly", "2026-01-01", 4, None, None, "def1", "2026-01-01"),
        ("r5", "immobilienscout24", "Scam", "Hidden fees everywhere", "2026-01-02", 1, "We are sorry", "2026-01-03", "def2", "2026-01-01"),
    ]
    conn.executemany(
        "INSERT INTO reviews VALUES (?,?,?,?,?,?,?,?,?,?)", reviews
    )

    categories = [
        ("rentumo", "negative", "Нет ответов", "Компания не отвечает", 3, '["r2"]', "gpt-4o-mini", "2026-01-01"),
        ("rentumo", "positive", "Удобный поиск", "Легко найти жильё", 2, '["r1"]', "gpt-4o-mini", "2026-01-01"),
        ("immobilienscout24", "negative", "Скрытые платежи", "Неожиданные списания", 4, '["r5"]', "gpt-4o-mini", "2026-01-01"),
    ]
    conn.executemany(
        "INSERT INTO categories (company, group_type, name, description, count, review_ids, model, analyzed_at) VALUES (?,?,?,?,?,?,?,?)",
        categories
    )

    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def sample_trustpilot_html():
    """Минимальный HTML с __NEXT_DATA__ как у Trustpilot."""
    reviews = [
        {
            "id": "abc123",
            "title": "Great platform",
            "text": "Found my apartment in 2 weeks!",
            "rating": 5,
            "dates": {"publishedDate": "2026-01-01T12:00:00.000Z"},
            "consumer": {"displayName": "Anna"},
            "reply": None,
        },
        {
            "id": "def456",
            "title": "Hidden fees",
            "text": "They charged me twice for Schufa.",
            "rating": 1,
            "dates": {"publishedDate": "2026-01-02T10:00:00.000Z"},
            "consumer": {"displayName": "Max"},
            "reply": {
                "message": "We are sorry to hear that.",
                "publishedDate": "2026-01-03T09:00:00.000Z",
                "updatedDate": None,
            },
        },
    ]
    next_data = {
        "props": {
            "pageProps": {
                "reviews": reviews
            }
        }
    }
    html = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(next_data)}</script>'
    return html, reviews

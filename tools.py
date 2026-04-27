import sqlite3
from pathlib import Path
from typing import Optional, Union

DB_PATH = Path(__file__).parent / "data" / "reviews.db"


def _conn():
    return sqlite3.connect(DB_PATH)


def init_fts(conn: sqlite3.Connection):
    """Создаёт FTS5 таблицу и триггеры если их ещё нет."""
    table_exists = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='reviews_fts'"
    ).fetchone()[0]

    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS reviews_fts
        USING fts5(id UNINDEXED, title, text, company UNINDEXED, rating UNINDEXED,
                   content='reviews', content_rowid='rowid')
    """)
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS reviews_fts_insert
        AFTER INSERT ON reviews BEGIN
            INSERT INTO reviews_fts(rowid, id, title, text, company, rating)
            VALUES (new.rowid, new.id, new.title, new.text, new.company, new.rating);
        END
    """)
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS reviews_fts_delete
        AFTER DELETE ON reviews BEGIN
            INSERT INTO reviews_fts(reviews_fts, rowid, id, title, text, company, rating)
            VALUES ('delete', old.rowid, old.id, old.title, old.text, old.company, old.rating);
        END
    """)
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS reviews_fts_update
        AFTER UPDATE ON reviews BEGIN
            INSERT INTO reviews_fts(reviews_fts, rowid, id, title, text, company, rating)
            VALUES ('delete', old.rowid, old.id, old.title, old.text, old.company, old.rating);
            INSERT INTO reviews_fts(rowid, id, title, text, company, rating)
            VALUES (new.rowid, new.id, new.title, new.text, new.company, new.rating);
        END
    """)
    # Rebuild при первом создании таблицы
    if not table_exists:
        conn.execute("INSERT INTO reviews_fts(reviews_fts) VALUES('rebuild')")
    conn.commit()


def get_reviews(company: str, min_rating: int = 1, max_rating: int = 5, limit: int = 20) -> list:
    conn = _conn()
    rows = conn.execute(
        """
        SELECT id, rating, title, text, reply, published_date
        FROM reviews
        WHERE company = ? AND rating BETWEEN ? AND ?
        ORDER BY published_date DESC
        LIMIT ?
        """,
        (company, min_rating, max_rating, limit),
    ).fetchall()
    conn.close()
    return [
        {
            "id": r[0],
            "rating": r[1],
            "title": r[2],
            "text": (r[3] or "")[:200],
            "has_reply": r[4] is not None,
            "published_date": r[5],
        }
        for r in rows
    ]


def get_categories(company: str, group_type: str = "both") -> list:
    conn = _conn()
    if group_type == "both":
        rows = conn.execute(
            """
            SELECT c.group_type, c.name, c.description, c.count
            FROM categories c
            JOIN (
                SELECT company, MAX(analyzed_at) AS last_run
                FROM categories GROUP BY company
            ) lr ON c.company = lr.company AND c.analyzed_at = lr.last_run
            WHERE c.company = ?
            ORDER BY c.group_type, c.count DESC
            """,
            (company,),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT c.group_type, c.name, c.description, c.count
            FROM categories c
            JOIN (
                SELECT company, MAX(analyzed_at) AS last_run
                FROM categories GROUP BY company
            ) lr ON c.company = lr.company AND c.analyzed_at = lr.last_run
            WHERE c.company = ? AND c.group_type = ?
            ORDER BY c.count DESC
            """,
            (company, group_type),
        ).fetchall()
    conn.close()
    return [
        {"group_type": r[0], "name": r[1], "description": r[2], "count": r[3]}
        for r in rows
    ]


def get_stats(company: Optional[str] = None) -> Union[dict, list]:
    conn = _conn()
    companies = (
        [company]
        if company
        else [r[0] for r in conn.execute("SELECT DISTINCT company FROM reviews").fetchall()]
    )
    result = []
    for c in companies:
        total = conn.execute(
            "SELECT COUNT(*) FROM reviews WHERE company = ?", (c,)
        ).fetchone()[0]
        avg = conn.execute(
            "SELECT ROUND(AVG(rating), 2) FROM reviews WHERE company = ?", (c,)
        ).fetchone()[0]
        dist = {
            str(r): cnt
            for r, cnt in conn.execute(
                "SELECT rating, COUNT(*) FROM reviews WHERE company = ? GROUP BY rating ORDER BY rating",
                (c,),
            ).fetchall()
        }
        neg_total = conn.execute(
            "SELECT COUNT(*) FROM reviews WHERE company = ? AND rating <= 3", (c,)
        ).fetchone()[0]
        neg_reply = conn.execute(
            "SELECT COUNT(*) FROM reviews WHERE company = ? AND rating <= 3 AND reply IS NOT NULL",
            (c,),
        ).fetchone()[0]
        result.append({
            "company": c,
            "total_reviews": total,
            "avg_rating": avg,
            "rating_distribution": dist,
            "negative_total": neg_total,
            "negative_with_reply": neg_reply,
            "negative_reply_rate_pct": round(neg_reply / neg_total * 100, 1) if neg_total else 0,
        })
    conn.close()
    return result[0] if company else result


def search_reviews(query: str, company: Optional[str] = None,
                   limit: int = 5) -> list:
    conn = _conn()
    init_fts(conn)
    if company:
        rows = conn.execute(
            """
            SELECT r.id, r.company, r.rating, r.title, r.text, r.published_date,
                   rank
            FROM reviews_fts
            JOIN reviews r ON reviews_fts.id = r.id
            WHERE reviews_fts MATCH ? AND r.company = ?
            ORDER BY rank
            LIMIT ?
            """,
            (query, company, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT r.id, r.company, r.rating, r.title, r.text, r.published_date,
                   rank
            FROM reviews_fts
            JOIN reviews r ON reviews_fts.id = r.id
            WHERE reviews_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (query, limit),
        ).fetchall()
    conn.close()
    return [
        {
            "id": r[0],
            "company": r[1],
            "rating": r[2],
            "title": r[3],
            "text": (r[4] or "")[:300],
            "published_date": r[5],
        }
        for r in rows
    ]


def export_to_sheets(company: Optional[str] = None, data_type: str = "all",
                     min_rating: int = 1, max_rating: int = 5) -> dict:
    from sheets import export
    return export(company=company, data_type=data_type,
                  min_rating=min_rating, max_rating=max_rating)


def call_tool(name: str, args: dict):
    if name == "get_reviews":
        return get_reviews(**args)
    if name == "get_categories":
        return get_categories(**args)
    if name == "get_stats":
        return get_stats(**args)
    if name == "export_to_sheets":
        return export_to_sheets(**args)
    if name == "search_reviews":
        return search_reviews(**args)
    raise ValueError(f"Unknown tool: {name}")


TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "get_reviews",
            "description": "Возвращает отзывы компании из базы данных с возможностью фильтрации по рейтингу.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company": {
                        "type": "string",
                        "description": "ID компании: immobilienscout24, rentumo, immosurf, immowelt"
                    },
                    "min_rating": {
                        "type": "integer",
                        "description": "Минимальный рейтинг (1-5), по умолчанию 1"
                    },
                    "max_rating": {
                        "type": "integer",
                        "description": "Максимальный рейтинг (1-5), по умолчанию 5"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Количество отзывов, по умолчанию 20"
                    }
                },
                "required": ["company"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_categories",
            "description": "Возвращает категории жалоб или похвал компании, выделенные LLM-анализом.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company": {
                        "type": "string",
                        "description": "ID компании: immobilienscout24, rentumo, immosurf, immowelt"
                    },
                    "group_type": {
                        "type": "string",
                        "enum": ["negative", "positive", "both"],
                        "description": "Тип категорий: negative, positive или both (по умолчанию both)"
                    }
                },
                "required": ["company"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_stats",
            "description": "Возвращает агрегированную статистику: количество отзывов, средний рейтинг, распределение оценок, долю негативных с ответом.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company": {
                        "type": "string",
                        "description": "ID компании. Если не указан — вернёт статистику по всем компаниям."
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_reviews",
            "description": "Полнотекстовый поиск по отзывам. Используй когда нужно найти отзывы по ключевым словам или теме: 'жалобы на поддержку', 'проблемы с оплатой', 'долго ждали'. Если поиск по всем компаниям — вызывай отдельно для каждой компании с limit=5.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Поисковый запрос. Можно использовать AND, OR, NOT и фразы в кавычках: 'support AND slow', '\"hidden fees\"'"
                    },
                    "company": {
                        "type": "string",
                        "description": "ID компании: immobilienscout24, rentumo, immosurf, immowelt. Всегда указывай конкретную компанию и вызывай инструмент отдельно для каждой."
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Максимальное количество результатов на компанию (по умолчанию 5)"
                    }
                },
                "required": ["query", "company"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "export_to_sheets",
            "description": "Экспортирует данные из базы в Google Sheets и возвращает ссылку на таблицу.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company": {
                        "type": "string",
                        "description": "ID компании: immobilienscout24, rentumo, immosurf, immowelt. Если не указан — экспортируются все компании."
                    },
                    "data_type": {
                        "type": "string",
                        "enum": ["stats", "reviews", "categories", "all"],
                        "description": "Что экспортировать: stats — статистика, reviews — отзывы, categories — категории анализа, all — всё (по умолчанию)"
                    },
                    "min_rating": {
                        "type": "integer",
                        "description": "Минимальный рейтинг отзывов для экспорта (1-5). Для позитивных отзывов используй 4 или 5."
                    },
                    "max_rating": {
                        "type": "integer",
                        "description": "Максимальный рейтинг отзывов для экспорта (1-5). Для негативных отзывов используй 1, 2 или 3."
                    }
                },
                "required": []
            }
        }
    }
]

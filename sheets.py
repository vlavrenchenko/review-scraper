import json
import time
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

from tools import get_stats, get_reviews, get_categories
from logger import get_logger

log = get_logger("sheets")

CREDENTIALS_PATH = Path(__file__).parent / "config" / "google_credentials.json"
SHEETS_CONFIG_PATH = Path(__file__).parent / "config" / "sheets_config.json"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
]

COMPANY_NAMES = {
    "immobilienscout24": "ImmobilienScout24",
    "rentumo": "Rentumo",
    "immosurf": "ImmoSurf",
    "immowelt": "Immowelt",
}


def _authenticate() -> gspread.Client:
    creds = Credentials.from_service_account_file(str(CREDENTIALS_PATH), scopes=SCOPES)
    return gspread.authorize(creds)


def _load_config() -> dict:
    if SHEETS_CONFIG_PATH.exists():
        return json.loads(SHEETS_CONFIG_PATH.read_text())
    return {}


def _save_config(config: dict):
    SHEETS_CONFIG_PATH.write_text(json.dumps(config, indent=2, ensure_ascii=False))


def _get_spreadsheet(client: gspread.Client) -> gspread.Spreadsheet:
    config = _load_config()
    spreadsheet_id = config.get("spreadsheet_id")

    if not spreadsheet_id:
        raise ValueError(
            "Spreadsheet ID не задан. Добавь его в config/sheets_config.json."
        )

    return client.open_by_key(spreadsheet_id)


def _get_or_add_sheet(spreadsheet: gspread.Spreadsheet, title: str) -> gspread.Worksheet:
    try:
        ws = spreadsheet.worksheet(title)
        ws.clear()
        return ws
    except gspread.exceptions.WorksheetNotFound:
        return spreadsheet.add_worksheet(title=title, rows=1000, cols=20)


def _write_stats(spreadsheet: gspread.Spreadsheet, companies: list[str]):
    ws = _get_or_add_sheet(spreadsheet, "Статистика")

    headers = [
        "Компания", "Всего отзывов", "Средний рейтинг",
        "⭐1", "⭐2", "⭐3", "⭐4", "⭐5",
        "Негативных", "Ответов на негатив", "% ответов",
    ]
    rows = [headers]

    for company in companies:
        s = get_stats(company)
        assert isinstance(s, dict)
        dist = s.get("rating_distribution", {})
        rows.append([
            COMPANY_NAMES.get(company, company),
            s["total_reviews"],
            s["avg_rating"],
            dist.get("1", 0),
            dist.get("2", 0),
            dist.get("3", 0),
            dist.get("4", 0),
            dist.get("5", 0),
            s["negative_total"],
            s["negative_with_reply"],
            s["negative_reply_rate_pct"],
        ])

    ws.update(rows, "A1")
    ws.format("A1:K1", {"textFormat": {"bold": True}})


def _write_reviews(spreadsheet: gspread.Spreadsheet, company: str,
                   min_rating: int = 1, max_rating: int = 5):
    name = COMPANY_NAMES.get(company, company)
    if min_rating == max_rating:
        title = f"Отзывы — {name} (⭐{min_rating})"
    elif min_rating > 1 or max_rating < 5:
        title = f"Отзывы — {name} (⭐{min_rating}–{max_rating})"
    else:
        title = f"Отзывы — {name}"
    ws = _get_or_add_sheet(spreadsheet, title)

    headers = ["ID", "Рейтинг", "Заголовок", "Текст", "Дата", "Есть ответ"]
    rows = [headers]

    reviews = get_reviews(company, min_rating=min_rating, max_rating=max_rating, limit=500)
    for r in reviews:
        rows.append([
            r["id"],
            r["rating"],
            r.get("title", ""),
            r.get("text", ""),
            r.get("published_date", ""),
            "Да" if r["has_reply"] else "Нет",
        ])

    ws.update(rows, "A1")
    ws.format("A1:F1", {"textFormat": {"bold": True}})


def _write_categories(spreadsheet: gspread.Spreadsheet, companies: list[str]):
    ws = _get_or_add_sheet(spreadsheet, "Категории")

    headers = ["Компания", "Тип", "Категория", "Описание", "Упоминаний"]
    rows = [headers]

    for company in companies:
        cats = get_categories(company, "both")
        for c in cats:
            rows.append([
                COMPANY_NAMES.get(company, company),
                "Негативная" if c["group_type"] == "negative" else "Позитивная",
                c["name"],
                c.get("description", ""),
                c.get("count", 0),
            ])

    ws.update(rows, "A1")
    ws.format("A1:E1", {"textFormat": {"bold": True}})


def export(company: str | None = None, data_type: str = "all",
           min_rating: int = 1, max_rating: int = 5) -> dict:
    """
    Экспортирует данные из БД в Google Sheets.

    company:    ID компании или None (все компании)
    data_type:  "stats" | "reviews" | "categories" | "all"
    min_rating: минимальный рейтинг для фильтрации отзывов (1–5)
    max_rating: максимальный рейтинг для фильтрации отзывов (1–5)

    Возвращает {"url": "...", "sheets_updated": [...]}
    """
    if not CREDENTIALS_PATH.exists():
        raise FileNotFoundError(
            f"Файл credentials не найден: {CREDENTIALS_PATH}. "
            "Скачай JSON-ключ service account из Google Cloud Console."
        )

    log.info("export_start", extra={
        "company": company, "data_type": data_type,
        "min_rating": min_rating, "max_rating": max_rating,
    })
    t0 = time.monotonic()

    client = _authenticate()
    spreadsheet = _get_spreadsheet(client)

    import sqlite3
    from tools import DB_PATH
    conn = sqlite3.connect(DB_PATH)
    all_companies = [
        r[0] for r in conn.execute(
            "SELECT DISTINCT company FROM reviews ORDER BY company"
        ).fetchall()
    ]
    conn.close()

    companies = [company] if company else all_companies
    sheets_updated = []

    if data_type in ("stats", "all"):
        _write_stats(spreadsheet, companies)
        sheets_updated.append("Статистика")
        log.debug("sheet_written", extra={"sheet": "Статистика"})

    if data_type in ("reviews", "all"):
        for c in companies:
            _write_reviews(spreadsheet, c, min_rating=min_rating, max_rating=max_rating)
            sheet_name = f"Отзывы — {COMPANY_NAMES.get(c, c)}"
            if min_rating > 1 or max_rating < 5:
                sheet_name += f" (⭐{min_rating}–{max_rating})" if min_rating != max_rating else f" (⭐{min_rating})"
            sheets_updated.append(sheet_name)
            log.debug("sheet_written", extra={"sheet": sheet_name})

    if data_type in ("categories", "all"):
        _write_categories(spreadsheet, companies)
        sheets_updated.append("Категории")
        log.debug("sheet_written", extra={"sheet": "Категории"})

    log.info("export_done", extra={
        "duration_sec": round(time.monotonic() - t0, 2),
        "sheets_updated": sheets_updated,
        "url": spreadsheet.url,
    })

    return {
        "url": spreadsheet.url,
        "sheets_updated": sheets_updated,
    }

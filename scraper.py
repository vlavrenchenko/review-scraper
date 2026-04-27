import json
import time
import random
from typing import Optional
import argparse
import sqlite3
import hashlib
from pathlib import Path
from urllib.parse import urlparse, urlencode, parse_qs, urlunparse

CACHE_DIR = Path(__file__).parent / "data" / "cache"
DB_PATH = Path(__file__).parent / "data" / "reviews.db"
COMPANIES_PATH = Path(__file__).parent / "config" / "companies.json"


def load_companies() -> dict:
    return {c["id"]: c for c in json.loads(COMPANIES_PATH.read_text())}


def parse_args():
    companies = load_companies()
    parser = argparse.ArgumentParser(description="Парсер отзывов Trustpilot")
    parser.add_argument(
        "--company", type=str, default="immobilienscout24",
        help=f"Компания или список через запятую (по умолчанию immobilienscout24). "
             f"Доступные: {', '.join(companies.keys())}, all"
    )
    parser.add_argument(
        "--reviews", type=int, default=50,
        help="Количество отзывов для скачивания на компанию (по умолчанию 50)"
    )
    parser.add_argument(
        "--no-cache", action="store_true",
        help="Игнорировать кеш и загрузить свежие данные"
    )
    parser.add_argument(
        "--cache-ttl", type=int, default=60,
        help="Время жизни кеша в минутах (по умолчанию 60)"
    )
    return parser.parse_args()


def random_timeout() -> float:
    return random.choice([round(x * 0.1, 1) for x in range(10, 31)])


def cache_path(company_id: str, page_num: int) -> Path:
    return CACHE_DIR / company_id / f"page_{page_num}.json"


def read_cache(company_id: str, page_num: int, ttl_minutes: int) -> Optional[list]:
    path = cache_path(company_id, page_num)
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    age_minutes = (time.time() - data["timestamp"]) / 60
    if age_minutes > ttl_minutes:
        print(f"   🕐 Кеш страницы {page_num} устарел ({age_minutes:.0f} мин > {ttl_minutes} мин).")
        return None
    print(f"   💾 Читаем из кеша (возраст: {age_minutes:.0f} мин).")
    return data["reviews"]


def write_cache(company_id: str, page_num: int, reviews: list):
    path = cache_path(company_id, page_num)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "timestamp": time.time(),
        "reviews": reviews,
    }, ensure_ascii=False, indent=2))


def _build_url(base_url: str, page_num: int) -> str:
    parsed = urlparse(base_url)
    params = parse_qs(parsed.query, keep_blank_values=True)
    params["languages"] = ["all"]
    if page_num > 1:
        params["page"] = [str(page_num)]
    return urlunparse(parsed._replace(query=urlencode(params, doseq=True)))


def fetch_page_from_web(browser, url: str, page_num: int) -> list:
    page_url = _build_url(url, page_num)
    page = browser.new_page()
    page.goto(page_url, wait_until="networkidle", timeout=30000)
    content = page.content()
    page.close()

    start = content.find('id="__NEXT_DATA__"')
    if start == -1:
        return []

    start = content.find(">", start) + 1
    end = content.find("</script>", start)
    data = json.loads(content[start:end])
    return data.get("props", {}).get("pageProps", {}).get("reviews", [])


def get_page(browser, url: str, company_id: str, page_num: int, no_cache: bool, ttl_minutes: int) -> list:
    if not no_cache:
        cached = read_cache(company_id, page_num, ttl_minutes)
        if cached is not None:
            return cached

    print("   🌐 Загружаем с сайта...")
    reviews = fetch_page_from_web(browser, url, page_num)
    write_cache(company_id, page_num, reviews)
    print("   💾 Кеш сохранён.")
    return reviews


def init_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reviews (
            id TEXT PRIMARY KEY,
            company TEXT,
            title TEXT,
            text TEXT,
            published_date TEXT,
            rating INTEGER,
            reply TEXT,
            reply_date TEXT,
            author_hash TEXT,
            scraped_at TEXT
        )
    """)
    conn.commit()
    for column in ("reply_date", "company"):
        try:
            conn.execute(f"ALTER TABLE reviews ADD COLUMN {column} TEXT")
            conn.commit()
        except sqlite3.OperationalError:
            pass
    # проставить company для старых записей без неё
    conn.execute(
        "UPDATE reviews SET company = 'immobilienscout24' WHERE company IS NULL"
    )
    conn.commit()
    return conn


def get_known_ids(conn: sqlite3.Connection, company_id: str) -> set:
    rows = conn.execute("SELECT id FROM reviews WHERE company = ?", (company_id,)).fetchall()
    return {row[0] for row in rows}


def save_reviews(conn: sqlite3.Connection, reviews: list, company_id: str) -> tuple[int, int]:
    scraped_at = time.strftime("%Y-%m-%dT%H:%M:%S")
    insert_rows = []
    update_rows = []

    existing_ids = {row[0] for row in conn.execute(
        "SELECT id FROM reviews WHERE company = ?", (company_id,)
    ).fetchall()}

    for r in reviews:
        reply = r.get("reply")
        author = r.get("consumer", {}).get("displayName") or ""
        author_hash = hashlib.sha256(author.encode()).hexdigest()[:16]
        reply_message = reply.get("message") if reply else None
        reply_date = reply.get("publishedDate") if reply else None

        if r["id"] not in existing_ids:
            insert_rows.append((
                r["id"],
                company_id,
                r.get("title"),
                (r.get("text") or "")[:300],
                r.get("dates", {}).get("publishedDate"),
                r.get("rating"),
                reply_message,
                reply_date,
                author_hash,
                scraped_at,
            ))
        elif reply_message:
            update_rows.append((reply_message, reply_date, scraped_at, r["id"]))

    conn.executemany(
        "INSERT INTO reviews "
        "(id, company, title, text, published_date, rating, reply, reply_date, author_hash, scraped_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        insert_rows,
    )
    updated_count = 0
    for row in update_rows:
        cursor = conn.execute(
            "UPDATE reviews SET reply = ?, reply_date = ?, scraped_at = ? "
            "WHERE id = ? AND (reply IS NULL OR reply_date IS NULL)",
            row,
        )
        updated_count += cursor.rowcount
    conn.commit()
    return len(insert_rows), updated_count


def scrape_company(browser, company: dict, args, conn: sqlite3.Connection):
    company_id = company["id"]
    company_name = company["name"]
    url = company["url"]

    known_ids = get_known_ids(conn, company_id)
    print(f"\n🏢 {company_name}  (в базе: {len(known_ids)} отзывов, скачиваем: {args.reviews})")

    collected: list[dict] = []
    page_num = 1

    while len(collected) < args.reviews:
        print(f"📥 Страница {page_num}...")
        page_reviews = get_page(browser, url, company_id, page_num, args.no_cache, args.cache_ttl)

        if not page_reviews:
            print("❌ Отзывы не найдены.")
            break

        new_on_page = [r for r in page_reviews if r["id"] not in known_ids]
        if not new_on_page:
            print("   ✅ Все отзывы на странице уже в БД — останавливаемся.")
            break

        remaining = args.reviews - len(collected)
        collected.extend(new_on_page[:remaining])
        print(f"✅ Новых скачано: {len(collected)}")

        if len(collected) < args.reviews:
            timeout = random_timeout()
            print(f"⏳ Пауза {timeout}с...\n")
            time.sleep(timeout)
            page_num += 1

    inserted, updated = save_reviews(conn, collected, company_id)
    total = conn.execute(
        "SELECT COUNT(*) FROM reviews WHERE company = ?", (company_id,)
    ).fetchone()[0]

    print(f"   Новых сохранено:  {inserted}")
    print(f"   Обновлено reply:  {updated}")
    print(f"   Всего в базе:     {total}")


def main():
    args = parse_args()
    companies = load_companies()
    start_time = time.time()

    if args.no_cache:
        print("⚠️  Режим --no-cache: кеш игнорируется.\n")

    if args.company == "all":
        targets = list(companies.values())
    else:
        ids = [c.strip() for c in args.company.split(",")]
        unknown = [i for i in ids if i not in companies]
        if unknown:
            print(f"❌ Неизвестные компании: {', '.join(unknown)}")
            print(f"   Доступные: {', '.join(companies.keys())}")
            return
        targets = [companies[i] for i in ids]

    conn = init_db()

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for company in targets:
            scrape_company(browser, company, args, conn)
        browser.close()

    conn.close()

    elapsed = time.time() - start_time
    print(f"\n{'='*50}")
    print(f"✅ Готово за {elapsed:.1f}с")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()

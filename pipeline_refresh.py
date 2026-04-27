import argparse
import os
import sqlite3
import time
from types import SimpleNamespace

from dotenv import load_dotenv
from openai import OpenAI

from playwright.sync_api import sync_playwright
from scraper import load_companies, init_db, scrape_company
from analyze import analyze_company, load_companies as analyze_load_companies
from logger import get_logger

load_dotenv(override=True)

log = get_logger("refresh")


def parse_args():
    companies = load_companies()
    parser = argparse.ArgumentParser(
        description="Скачать новые отзывы и проанализировать их за одну команду"
    )
    parser.add_argument(
        "--company", type=str, default="all",
        help=f"Компания или список через запятую (по умолчанию all). "
             f"Доступные: {', '.join(companies.keys())}, all"
    )
    parser.add_argument(
        "--all-new", action="store_true",
        help="Скачать все новые отзывы без ограничения по количеству"
    )
    parser.add_argument(
        "--reviews", type=int, default=100,
        help="Защитная граница скачивания (по умолчанию 100). Игнорируется при --all-new"
    )
    parser.add_argument(
        "--model", type=str, default="gpt-4o-mini",
        help="Модель OpenAI для анализа (по умолчанию gpt-4o-mini)"
    )
    parser.add_argument(
        "--skip-analyze", action="store_true",
        help="Только скачать отзывы, пропустить анализ"
    )
    return parser.parse_args()


def run_scraper(targets: list, args, conn: sqlite3.Connection) -> dict[str, int]:
    scrape_args = SimpleNamespace(
        reviews=args.reviews,
        all_new=args.all_new,
        no_cache=True,
        cache_ttl=60,
    )

    results: dict[str, int] = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for company in targets:
            before = conn.execute(
                "SELECT COUNT(*) FROM reviews WHERE company = ?", (company["id"],)
            ).fetchone()[0]
            scrape_company(browser, company, scrape_args, conn)
            after = conn.execute(
                "SELECT COUNT(*) FROM reviews WHERE company = ?", (company["id"],)
            ).fetchone()[0]
            results[company["id"]] = after - before
        browser.close()
    return results


def run_analyzer(targets: list, args, conn: sqlite3.Connection) -> dict[str, int]:
    assert os.environ.get("OPENAI_API_KEY"), "Задайте OPENAI_API_KEY в .env файле"

    analyze_args = SimpleNamespace(
        model=args.model,
        limit=None,
        save=True,
    )

    client = OpenAI()
    results: dict[str, int] = {}
    companies_dict = analyze_load_companies()

    for company in targets:
        company_dict = companies_dict.get(company["id"])
        if not company_dict:
            continue
        _, _, saved = analyze_company(client, company_dict, analyze_args, conn)
        results[company["id"]] = saved

    return results


def main():
    args = parse_args()
    companies = load_companies()
    t0 = time.monotonic()

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

    log.info("refresh_start", extra={
        "companies": [t["id"] for t in targets],
        "all_new": args.all_new,
        "skip_analyze": args.skip_analyze,
        "model": args.model,
    })

    conn = init_db()

    print(f"\n{'='*55}")
    print(f"🔄 REFRESH — {', '.join(t['name'] for t in targets)}")
    print(f"{'='*55}\n")

    # Шаг 1 — скрапинг
    print("📥 ШАГ 1: Скачиваем новые отзывы...\n")
    scrape_results = run_scraper(targets, args, conn)
    total_new = sum(scrape_results.values())

    # Шаг 2 — анализ
    analyze_results: dict[str, int] = {}
    if not args.skip_analyze:
        print(f"\n🔬 ШАГ 2: Анализируем отзывы через {args.model}...\n")
        analyze_results = run_analyzer(targets, args, conn)
    else:
        print("\n⏭️  Анализ пропущен (--skip-analyze)\n")

    conn.close()
    elapsed = round(time.monotonic() - t0, 1)

    # Итоговая сводка
    print(f"\n{'='*55}")
    print(f"✅ ГОТОВО за {elapsed}с")
    print(f"{'='*55}")
    for company in targets:
        cid = company["id"]
        new = scrape_results.get(cid, 0)
        cats = analyze_results.get(cid, 0)
        analyze_str = f", сохранено категорий: {cats}" if not args.skip_analyze else ""
        print(f"  {company['name']}: новых отзывов: {new}{analyze_str}")
    print(f"{'='*55}")
    print(f"  Всего новых отзывов: {total_new}")

    log.info("refresh_done", extra={
        "duration_sec": elapsed,
        "total_new_reviews": total_new,
        "scrape_results": scrape_results,
        "analyze_results": analyze_results,
    })


if __name__ == "__main__":
    main()

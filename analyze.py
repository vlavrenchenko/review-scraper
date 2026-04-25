import json
import sqlite3
import argparse
import os
import time
from typing import Optional, Tuple
from pathlib import Path
from openai import OpenAI
from dotenv import load_dotenv

DB_PATH = Path(__file__).parent / "data" / "reviews.db"
PRICING_PATH = Path(__file__).parent / "config" / "models_pricing.json"
COMPANIES_PATH = Path(__file__).parent / "config" / "companies.json"


def load_model_prices() -> dict:
    if not PRICING_PATH.exists():
        return {}
    raw = json.loads(PRICING_PATH.read_text())
    prices = {}
    for model_id, model_data in raw.get("models", {}).items():
        standard = model_data.get("pricing", {}).get("standard", {})
        if "input" in standard:
            input_price = standard["input"]
            output_price = standard["output"]
        elif "short_context" in standard:
            input_price = standard["short_context"]["input"]
            output_price = standard["short_context"]["output"]
        else:
            continue
        if input_price is not None and output_price is not None:
            prices[model_id] = {"input": input_price, "output": output_price}
    return prices


MODEL_PRICES = load_model_prices()


def load_companies() -> dict:
    return {c["id"]: c for c in json.loads(COMPANIES_PATH.read_text())}


def parse_args():
    companies = load_companies()
    parser = argparse.ArgumentParser(description="Анализ отзывов через OpenAI")
    parser.add_argument("--model", type=str, default="gpt-4o-mini",
                        help="Модель OpenAI (по умолчанию gpt-4o-mini). "
                             "Список доступных моделей: --list-models")
    parser.add_argument(
        "--company", type=str, default="all",
        help=f"Компания или список через запятую (по умолчанию all). "
             f"Доступные: {', '.join(companies.keys())}, all"
    )
    parser.add_argument("--limit", type=int, default=None,
                        help="Лимит отзывов на группу (по умолчанию все)")
    parser.add_argument("--save", action="store_true",
                        help="Сохранить результаты анализа в БД")
    parser.add_argument("--list-models", action="store_true",
                        help="Показать доступные модели OpenAI и выйти")
    return parser.parse_args()


def list_models(client: OpenAI):
    models = client.models.list().data
    chat_models = sorted(
        [m for m in models if m.id.startswith(("gpt-", "o1", "o3", "o4"))],
        key=lambda m: m.id,
    )
    print(f"\nДоступные модели OpenAI ({len(chat_models)}):\n")
    for m in chat_models:
        print(f"  {m.id}")
    print()


def init_db(conn: sqlite3.Connection):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company TEXT,
            group_type TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT,
            count INTEGER,
            review_ids TEXT,
            model TEXT,
            analyzed_at TEXT
        )
    """)
    conn.commit()
    try:
        conn.execute("ALTER TABLE categories ADD COLUMN company TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass


def load_reviews(company_id: str, limit: Optional[int]) -> Tuple[list, list]:
    conn = sqlite3.connect(DB_PATH)
    query = "SELECT id, title, text, rating FROM reviews WHERE company = ? ORDER BY published_date DESC"
    params: list = [company_id]
    if limit:
        query += f" LIMIT {limit * 2}"
    rows = conn.execute(query, params).fetchall()
    conn.close()

    reviews = [
        {"id": r[0], "title": r[1], "text": r[2], "rating": r[3]}
        for r in rows if r[3] is not None
    ]
    negative = [r for r in reviews if r["rating"] <= 3]
    positive = [r for r in reviews if r["rating"] >= 4]

    if limit:
        negative = negative[:limit]
        positive = positive[:limit]

    return negative, positive


BATCH_SIZE = 50


def _analyze_batch(client: OpenAI, reviews: list, group_label: str, model: str) -> tuple[dict, dict]:
    reviews_text = json.dumps(reviews, ensure_ascii=False, indent=2)
    last_exc: Exception = RuntimeError("no attempts made")
    for attempt in range(4):
        if attempt > 0:
            wait = 5 * (2 ** (attempt - 1))  # 5s, 10s, 20s
            print(f"      повтор {attempt}/3 через {wait}с...")
            time.sleep(wait)
        try:
            response = client.chat.completions.create(
                model=model,
                response_format={"type": "json_object"},
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Ты аналитик клиентских отзывов. "
                            "Выделяй категории из отзывов. "
                            "Отвечай только на русском языке. Возвращай только JSON."
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"""Проанализируй следующие {group_label} отзывы и выдели подкатегории.

Для каждой категории верни:
- name: короткое название (2-4 слова)
- description: описание в 1-2 предложения
- count: количество отзывов, в которых упоминается эта категория
- review_ids: список ID отзывов

Верни JSON: {{"categories": [...]}}

Отзывы:
{reviews_text}""",
                    },
                ],
            )
            assert response.usage is not None
            assert response.choices[0].message.content is not None
            usage = {
                "input": response.usage.prompt_tokens,
                "output": response.usage.completion_tokens,
            }
            return json.loads(response.choices[0].message.content), usage
        except Exception as e:
            last_exc = e
            print(f"      ошибка ({e.__class__.__name__}), {'повторяем' if attempt < 3 else 'все попытки исчерпаны'}")
    raise last_exc


def analyze_group(client: OpenAI, reviews: list, group_label: str, model: str) -> tuple[dict, dict]:
    if len(reviews) <= BATCH_SIZE:
        return _analyze_batch(client, reviews, group_label, model)

    merged: dict[str, dict] = {}
    total_input = total_output = 0
    batches = [reviews[i:i + BATCH_SIZE] for i in range(0, len(reviews), BATCH_SIZE)]

    for idx, batch in enumerate(batches, 1):
        print(f"      батч {idx}/{len(batches)} ({len(batch)} отзывов)...")
        result, usage = _analyze_batch(client, batch, group_label, model)
        total_input += usage["input"]
        total_output += usage["output"]
        for cat in result.get("categories", []):
            name = cat["name"]
            if name in merged:
                merged[name]["count"] += cat.get("count", 0)
                merged[name]["review_ids"].extend(cat.get("review_ids", []))
            else:
                merged[name] = {
                    "name": name,
                    "description": cat.get("description", ""),
                    "count": cat.get("count", 0),
                    "review_ids": list(cat.get("review_ids", [])),
                }

    return {"categories": list(merged.values())}, {"input": total_input, "output": total_output}


def save_categories(conn: sqlite3.Connection, company_id: str, group_type: str, result: dict, model: str) -> int:
    analyzed_at = time.strftime("%Y-%m-%dT%H:%M:%S")
    rows = [
        (
            company_id,
            group_type,
            cat["name"],
            cat.get("description"),
            cat.get("count"),
            json.dumps(cat.get("review_ids", []), ensure_ascii=False),
            model,
            analyzed_at,
        )
        for cat in result.get("categories", [])
    ]
    conn.executemany(
        "INSERT INTO categories (company, group_type, name, description, count, review_ids, model, analyzed_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    return len(rows)


def print_group(label: str, result: dict, total: int):
    categories = sorted(
        result.get("categories", []),
        key=lambda c: c.get("count", 0),
        reverse=True,
    )
    print(f"\n{'='*55}")
    print(f"{label}  ({total} отзывов, {len(categories)} категорий)")
    print(f"{'='*55}")
    for i, cat in enumerate(categories, 1):
        print(f"\n  {i}. {cat['name']}  [{cat['count']} упоминаний]")
        print(f"     {cat['description']}")


def analyze_company(client: OpenAI, company: dict, args, conn: sqlite3.Connection) -> tuple[int, int, int]:
    company_id = company["id"]
    company_name = company["name"]

    negative, positive = load_reviews(company_id, args.limit)
    print(f"\n🏢 {company_name}  ({len(negative)} негативных, {len(positive)} позитивных)\n")

    if not negative and not positive:
        print("   ⚠️  Нет отзывов в базе.")
        return 0, 0, 0

    input_tokens = output_tokens = saved = 0
    neg_result = pos_result = None

    if negative:
        print(f"🔴 Анализируем негативные через {args.model}...")
        neg_result, neg_usage = analyze_group(client, negative, "негативные (рейтинг ≤ 3)", args.model)
        input_tokens += neg_usage["input"]
        output_tokens += neg_usage["output"]
        print_group("🔴 НЕГАТИВНЫЕ  (рейтинг ≤ 3)", neg_result, len(negative))

    if positive:
        print(f"\n🟢 Анализируем позитивные через {args.model}...")
        pos_result, pos_usage = analyze_group(client, positive, "позитивные (рейтинг 4-5)", args.model)
        input_tokens += pos_usage["input"]
        output_tokens += pos_usage["output"]
        print_group("🟢 ПОЗИТИВНЫЕ  (рейтинг 4-5)", pos_result, len(positive))

    if args.save:
        if neg_result:
            saved += save_categories(conn, company_id, "negative", neg_result, args.model)
        if pos_result:
            saved += save_categories(conn, company_id, "positive", pos_result, args.model)

    return input_tokens, output_tokens, saved


def main():
    load_dotenv(override=True)
    assert os.environ.get("OPENAI_API_KEY"), "Задайте OPENAI_API_KEY в .env файле"

    args = parse_args()
    companies = load_companies()
    client = OpenAI()

    if args.list_models:
        list_models(client)
        return

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

    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    start_time = time.time()
    total_input = total_output = total_saved = 0

    for company in targets:
        inp, out, saved = analyze_company(client, company, args, conn)
        total_input += inp
        total_output += out
        total_saved += saved

    conn.close()

    elapsed = time.time() - start_time
    prices = MODEL_PRICES.get(args.model)
    cost_str = (
        f"${(total_input * prices['input'] + total_output * prices['output']) / 1_000_000:.5f}"
        if prices else "н/д (модель не в таблице цен)"
    )

    print(f"\n{'='*55}")
    print(f"⏱️  Время выполнения:  {elapsed:.1f}с")
    print(f"📨 Токены отправлено: {total_input:,}")
    print(f"📩 Токены получено:   {total_output:,}")
    print(f"📊 Итого токенов:     {total_input + total_output:,}")
    print(f"💰 Стоимость запроса: {cost_str}")
    if args.save:
        print(f"💾 Сохранено категорий: {total_saved}")
    else:
        print("💡 Для сохранения в БД добавь флаг --save")
    print(f"{'='*55}")


if __name__ == "__main__":
    main()

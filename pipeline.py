import json
import os
import sqlite3
import argparse
import time
from typing import TypedDict
from dotenv import load_dotenv
from langgraph.graph import StateGraph, START, END
from openai import OpenAI
from tools import get_stats, get_categories, DB_PATH
from logger import get_logger

load_dotenv(override=True)

log = get_logger("pipeline")


class PipelineState(TypedDict):
    companies: list[str]
    threshold: int
    stats: dict
    neg_categories: dict
    pos_categories: dict
    warnings: list[str]
    report: str


# --- Узлы графа ---

def check_data(state: PipelineState) -> dict:
    """Проверяет достаточность данных в БД для каждой компании."""
    print("🔍 Проверяем данные в БД...")
    log.info("check_data_start", extra={"companies": state["companies"], "threshold": state["threshold"]})
    stats = {}
    warnings = []
    for company in state["companies"]:
        s = get_stats(company)
        assert isinstance(s, dict)
        stats[company] = s
        if s["total_reviews"] < state["threshold"]:
            msg = (
                f"{company}: {s['total_reviews']} отзывов "
                f"(минимум {state['threshold']}). "
                f"Запусти: python3 trustpilot_test.py --company {company} --reviews 50"
            )
            warnings.append(msg)
            log.warning("low_data", extra={"company": company, "total": s["total_reviews"], "threshold": state["threshold"]})
    log.info("check_data_done", extra={"warnings_count": len(warnings)})
    return {"stats": stats, "warnings": warnings}


def show_warnings(state: PipelineState) -> dict:
    """Выводит предупреждения о нехватке данных и продолжает с тем что есть."""
    print("⚠️  Недостаточно данных для некоторых компаний:")
    for w in state["warnings"]:
        print(f"   • {w}")
    print("   Продолжаем с имеющимися данными...\n")
    return {}


def fetch_analysis(state: PipelineState) -> dict:
    """Загружает категории из БД для всех компаний."""
    print("📂 Загружаем категории из БД...")
    log.info("fetch_analysis_start", extra={"companies": state["companies"]})
    neg_categories = {}
    pos_categories = {}
    for company in state["companies"]:
        neg_categories[company] = get_categories(company, "negative")
        pos_categories[company] = get_categories(company, "positive")
        print(f"   ✅ {company}")
    print()
    log.info("fetch_analysis_done")
    return {"neg_categories": neg_categories, "pos_categories": pos_categories}


def generate_report(state: PipelineState) -> dict:
    """Генерирует markdown отчёт через LLM."""
    print("✍️  Генерируем отчёт через LLM...")
    log.info("generate_report_start", extra={"companies": state["companies"]})
    t0 = time.monotonic()
    client = OpenAI()

    context = [
        {
            "company": company,
            "stats": state["stats"].get(company, {}),
            "top_negative": state["neg_categories"].get(company, [])[:5],
            "top_positive": state["pos_categories"].get(company, [])[:5],
        }
        for company in state["companies"]
    ]

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": (
                    "Ты аналитик платформ аренды недвижимости в Германии. "
                    "Создай структурированный аналитический отчёт на русском языке в формате Markdown."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Создай отчёт по данным ниже. Структура отчёта:\n"
                    "1. Общая статистика по каждой компании\n"
                    "2. Топ-5 жалоб по каждой компании\n"
                    "3. Топ-5 достоинств по каждой компании\n"
                    "4. Сравнение компаний между собой\n"
                    "5. Ключевые выводы\n\n"
                    f"{json.dumps(context, ensure_ascii=False, indent=2)}"
                ),
            },
        ],
    )
    report = response.choices[0].message.content or ""
    print("   ✅ Отчёт готов\n")
    log.info("generate_report_done", extra={"duration_sec": round(time.monotonic() - t0, 2), "report_len": len(report)})
    return {"report": report}


# --- Условное ветвление ---

def route_after_check(state: PipelineState) -> str:
    return "warn" if state["warnings"] else "analyze"


# --- Сборка графа ---

def build_graph():
    graph = StateGraph(PipelineState)

    graph.add_node("check_data", check_data)
    graph.add_node("show_warnings", show_warnings)
    graph.add_node("fetch_analysis", fetch_analysis)
    graph.add_node("generate_report", generate_report)

    graph.add_edge(START, "check_data")
    graph.add_conditional_edges(
        "check_data",
        route_after_check,
        {"warn": "show_warnings", "analyze": "fetch_analysis"},
    )
    graph.add_edge("show_warnings", "fetch_analysis")
    graph.add_edge("fetch_analysis", "generate_report")
    graph.add_edge("generate_report", END)

    return graph.compile()


# --- CLI ---

def parse_args():
    conn = sqlite3.connect(DB_PATH)
    available = [r[0] for r in conn.execute("SELECT DISTINCT company FROM reviews").fetchall()]
    conn.close()

    parser = argparse.ArgumentParser(description="Генерация отчёта через LangGraph pipeline")
    parser.add_argument(
        "--company", type=str, default="all",
        help=f"Компания, список через запятую или all (по умолчанию all). "
             f"Доступные: {', '.join(available)}"
    )
    parser.add_argument(
        "--threshold", type=int, default=20,
        help="Минимальное количество отзывов для анализа (по умолчанию 20)"
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="Сохранить отчёт в файл (по умолчанию reports/report_YYYYMMDD.md)"
    )
    return parser.parse_args()


def main():
    assert os.environ.get("OPENAI_API_KEY"), "Задайте OPENAI_API_KEY в .env файле"

    args = parse_args()

    conn = sqlite3.connect(DB_PATH)
    all_companies = [r[0] for r in conn.execute("SELECT DISTINCT company FROM reviews").fetchall()]
    conn.close()

    if args.company == "all":
        companies = all_companies
    else:
        ids = [c.strip() for c in args.company.split(",")]
        unknown = [i for i in ids if i not in all_companies]
        if unknown:
            print(f"❌ Неизвестные компании: {', '.join(unknown)}")
            return
        companies = ids

    print(f"\n🚀 Запускаем pipeline для: {', '.join(companies)}\n")

    pipeline = build_graph()
    result = pipeline.invoke({
        "companies": companies,
        "threshold": args.threshold,
        "stats": {},
        "neg_categories": {},
        "pos_categories": {},
        "warnings": [],
        "report": "",
    })

    print("=" * 60)
    print(result["report"])
    print("=" * 60)

    from pathlib import Path
    import datetime
    output = args.output or str(
        Path(__file__).parent / "reports" / f"report_{datetime.date.today().strftime('%Y%m%d')}.md"
    )
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        f.write(result["report"])
    print(f"\n💾 Отчёт сохранён в {output}")


if __name__ == "__main__":
    main()

import json
import datetime
import sqlite3
import os
import streamlit as st
from dotenv import load_dotenv

load_dotenv(override=True)

from tools import get_stats, DB_PATH  # noqa: E402
from agent import run_agent  # noqa: E402
from pipeline import check_data, fetch_analysis, generate_report  # noqa: E402

st.set_page_config(
    page_title="Trustpilot Analytics",
    page_icon="🏠",
    layout="wide",
)

COMPANY_NAMES = {
    "immobilienscout24": "ImmobilienScout24",
    "rentumo": "Rentumo",
    "immosurf": "ImmoSurf",
    "immowelt": "Immowelt",
}

QUICK_QUESTIONS = [
    "Сколько отзывов у каждой компании?",
    "Сравни средние рейтинги всех компаний",
    "Какие главные жалобы у Rentumo?",
    "У какой компании лучше всего отвечают на негативные отзывы?",
]


@st.cache_data(ttl=60)
def load_all_stats():
    return get_stats()


@st.cache_data(ttl=60)
def load_companies():
    conn = sqlite3.connect(DB_PATH)
    result = [r[0] for r in conn.execute(
        "SELECT DISTINCT company FROM reviews ORDER BY company"
    ).fetchall()]
    conn.close()
    return result


# --- Sidebar ---

with st.sidebar:
    st.title("🏠 Trustpilot\nAnalytics")
    st.caption("Платформы аренды жилья в Германии")
    st.divider()

    st.subheader("📊 База данных")
    try:
        stats = load_all_stats()
        for s in stats:
            name = COMPANY_NAMES.get(s["company"], s["company"])
            neg_pct = s["negative_reply_rate_pct"]
            st.markdown(f"**{name}**")
            col1, col2 = st.columns(2)
            col1.metric("Отзывов", s["total_reviews"])
            col2.metric("Рейтинг", f"⭐ {s['avg_rating']}")
            st.caption(f"Ответов на негатив: {neg_pct}%")
            st.divider()
    except Exception as e:
        st.error(f"Ошибка загрузки БД: {e}")

    if not os.environ.get("OPENAI_API_KEY"):
        st.warning("⚠️ OPENAI_API_KEY не задан")
    else:
        st.success("OpenAI API подключён")

    st.divider()
    st.subheader("📤 Экспорт")

    export_type = st.selectbox(
        "Что экспортировать:",
        options=["all", "stats", "reviews", "categories"],
        format_func=lambda x: {
            "all": "Всё",
            "stats": "Статистика",
            "reviews": "Отзывы",
            "categories": "Категории",
        }[x],
        label_visibility="collapsed",
    )

    if st.button("Экспорт в Google Sheets", use_container_width=True):
        with st.spinner("Экспортируем..."):
            try:
                from sheets import export
                result = export(data_type=export_type)
                st.session_state["sheets_url"] = result["url"]
                st.session_state["sheets_updated"] = result["sheets_updated"]
            except Exception as e:
                st.error(f"Ошибка: {e}")

    if "sheets_url" in st.session_state:
        st.success("Готово!")
        st.markdown(f"[Открыть таблицу]({st.session_state['sheets_url']})")
        st.caption("Обновлено: " + ", ".join(st.session_state.get("sheets_updated", [])))


# --- Tabs ---

tab_agent, tab_report = st.tabs(["💬 Агент", "📄 Отчёт"])


# =========================================================
# Tab 1: Агент
# =========================================================

with tab_agent:
    st.header("Вопрос к агенту")
    st.caption("Агент сам выбирает нужные инструменты и запрашивает данные из БД")

    # Быстрые вопросы
    st.write("Быстрые вопросы:")
    cols = st.columns(len(QUICK_QUESTIONS))
    for col, q in zip(cols, QUICK_QUESTIONS):
        if col.button(q, use_container_width=True, key=f"quick_{q}"):
            st.session_state["agent_question_text"] = q

    question = st.text_area(
        "Или введи свой вопрос:",
        value=st.session_state.get("agent_question_text", ""),
        height=80,
        placeholder="Например: сколько негативных отзывов у Immowelt за 2025 год?",
    )

    if st.button("Задать вопрос ➤", type="primary"):
        if not question.strip():
            st.warning("Введи вопрос перед отправкой")
        else:
            tool_calls_log = []

            def on_tool_call(name, args):
                tool_calls_log.append((name, args))

            with st.spinner("Агент думает..."):
                try:
                    answer = run_agent(question.strip(), on_tool_call=on_tool_call)
                    st.session_state["agent_answer"] = answer
                    st.session_state["agent_tool_calls"] = tool_calls_log
                except Exception as e:
                    st.error(f"Ошибка: {e}")
                    st.session_state.pop("agent_answer", None)

    if "agent_answer" in st.session_state:
        if st.session_state.get("agent_tool_calls"):
            calls = st.session_state["agent_tool_calls"]
            with st.expander(f"🔧 Вызовы инструментов ({len(calls)})", expanded=False):
                for name, args in calls:
                    args_str = json.dumps(args, ensure_ascii=False)
                    st.code(f"{name}({args_str})", language="python")

        st.markdown("**Ответ агента:**")
        st.markdown(st.session_state["agent_answer"])


# =========================================================
# Tab 2: Отчёт
# =========================================================

with tab_report:
    st.header("Аналитический отчёт")
    st.caption("Отчёт генерируется LLM на основе категорий из БД. Перед запуском убедись, что анализ выполнен (`analyze.py`).")

    available = load_companies()

    selected = st.multiselect(
        "Компании для анализа:",
        options=available,
        default=available,
        format_func=lambda x: COMPANY_NAMES.get(x, x),
    )

    threshold = st.slider(
        "Минимальное кол-во отзывов (компании с меньшим числом попадут в предупреждения):",
        min_value=5,
        max_value=100,
        value=20,
        step=5,
    )

    if st.button("Сгенерировать отчёт ➤", type="primary"):
        if not selected:
            st.warning("Выбери хотя бы одну компанию")
        else:
            state = {
                "companies": selected,
                "threshold": threshold,
                "stats": {},
                "neg_categories": {},
                "pos_categories": {},
                "warnings": [],
                "report": "",
            }

            try:
                with st.status("Генерируем отчёт...", expanded=True) as status:
                    st.write("🔍 Проверяем данные в БД...")
                    state.update(check_data(state))  # type: ignore[arg-type]

                    if state["warnings"]:
                        for w in state["warnings"]:  # type: ignore[attr-defined]
                            st.warning(w)

                    st.write("📂 Загружаем категории...")
                    state.update(fetch_analysis(state))  # type: ignore[arg-type]

                    st.write("✍️ Генерируем отчёт через LLM...")
                    state.update(generate_report(state))  # type: ignore[arg-type]

                    status.update(label="Отчёт готов!", state="complete")

                st.session_state["report"] = state["report"]
                st.session_state["report_date"] = datetime.datetime.now().strftime("%Y%m%d_%H%M")

            except Exception as e:
                st.error(f"Ошибка генерации отчёта: {e}")

    if "report" in st.session_state:
        fname = f"report_{st.session_state.get('report_date', 'latest')}.md"
        st.download_button(
            label="💾 Скачать отчёт (.md)",
            data=st.session_state["report"],
            file_name=fname,
            mime="text/markdown",
        )
        st.divider()
        st.markdown(st.session_state["report"])

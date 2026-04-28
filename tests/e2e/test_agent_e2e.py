"""
E2E тесты агента — реальный OpenAI, реальная БД.
Запуск: pytest -m e2e
"""
import pytest
from importlib import reload
from unittest.mock import patch


def _load_agent(db_path):
    """Перезагружает tools и agent с указанной БД."""
    import tools
    import agent
    reload(tools)
    reload(agent)
    return agent, tools


@pytest.mark.e2e
def test_agent_answers_stats_question(require_openai, db_has_data):
    """Агент отвечает на вопрос о статистике и возвращает непустой ответ."""
    agent, tools = _load_agent(db_has_data)
    with patch("tools.DB_PATH", db_has_data):
        answer, history = agent.run_agent("Сколько всего отзывов в базе?")

    assert isinstance(answer, str)
    assert len(answer) > 20
    assert isinstance(history, list)


@pytest.mark.e2e
def test_agent_uses_get_stats_tool(require_openai, db_has_data):
    """Агент вызывает get_stats при вопросе о статистике компании."""
    agent, tools = _load_agent(db_has_data)
    called_tools = []

    with patch("tools.DB_PATH", db_has_data):
        agent.run_agent(
            "Какой средний рейтинг у immobilienscout24?",
            on_tool_call=lambda name, args: called_tools.append(name),
        )

    assert "get_stats" in called_tools


@pytest.mark.e2e
def test_agent_uses_get_reviews_tool(require_openai, db_has_data):
    """Агент вызывает get_reviews при запросе отзывов."""
    agent, tools = _load_agent(db_has_data)
    called_tools = []

    with patch("tools.DB_PATH", db_has_data):
        agent.run_agent(
            "Покажи негативные отзывы immobilienscout24",
            on_tool_call=lambda name, args: called_tools.append(name),
        )

    assert "get_reviews" in called_tools


@pytest.mark.e2e
def test_agent_uses_search_reviews_tool(require_openai, db_has_data):
    """Агент вызывает search_reviews при поисковом запросе."""
    agent, tools = _load_agent(db_has_data)
    called_tools = []

    with patch("tools.DB_PATH", db_has_data):
        agent.run_agent(
            "Найди жалобы на скрытые платежи в immobilienscout24",
            on_tool_call=lambda name, args: called_tools.append(name),
        )

    assert "search_reviews" in called_tools


@pytest.mark.e2e
def test_agent_search_uses_english_query(require_openai, db_has_data):
    """Агент переводит запрос на английский перед вызовом search_reviews."""
    agent, tools = _load_agent(db_has_data)
    search_args = []

    with patch("tools.DB_PATH", db_has_data):
        agent.run_agent(
            "Найди жалобы на скрытые платежи в immobilienscout24",
            on_tool_call=lambda name, args: search_args.append(args) if name == "search_reviews" else None,
        )

    assert len(search_args) > 0
    query = search_args[0].get("query", "").lower()
    # Запрос должен содержать английские слова, не русские
    russian_words = ["скрытые", "платежи", "жалобы"]
    assert not any(w in query for w in russian_words), f"Запрос содержит русские слова: {query}"


@pytest.mark.e2e
def test_agent_filters_by_rating(require_openai, db_has_data):
    """Агент передаёт правильный фильтр рейтинга при запросе однозвёздочных отзывов."""
    agent, tools = _load_agent(db_has_data)
    called_args = []

    with patch("tools.DB_PATH", db_has_data):
        agent.run_agent(
            "Покажи только однозвёздочные отзывы immobilienscout24",
            on_tool_call=lambda name, args: called_args.append(args) if name == "get_reviews" else None,
        )

    assert len(called_args) > 0
    assert called_args[0].get("max_rating", 5) <= 2


@pytest.mark.e2e
def test_agent_dialog_context(require_openai, db_has_data):
    """Агент помнит контекст предыдущего вопроса в диалоге."""
    agent, tools = _load_agent(db_has_data)

    with patch("tools.DB_PATH", db_has_data):
        answer1, history = agent.run_agent("Сколько отзывов у immobilienscout24?")
        assert len(history) > 0

        answer2, history2 = agent.run_agent("А у rentumo?", history=history)

    assert isinstance(answer2, str)
    assert len(answer2) > 10
    assert len(history2) > len(history)

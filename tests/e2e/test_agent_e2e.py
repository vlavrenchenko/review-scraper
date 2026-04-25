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
        answer = agent.run_agent("Сколько всего отзывов в базе?")

    assert isinstance(answer, str)
    assert len(answer) > 20


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

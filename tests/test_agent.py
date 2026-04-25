"""Тесты agent.py — OpenAI замокирован."""
import json
from importlib import reload
from unittest.mock import patch, MagicMock


def make_openai_response(tool_name=None, tool_args=None, content=None, tool_call_id="call_1"):
    """Создаёт мок-ответ OpenAI."""
    message = MagicMock()
    if tool_name:
        tool_call = MagicMock()
        tool_call.id = tool_call_id
        tool_call.function.name = tool_name
        tool_call.function.arguments = json.dumps(tool_args or {})
        message.tool_calls = [tool_call]
        message.content = None
    else:
        message.tool_calls = None
        message.content = content or "Тестовый ответ"

    response = MagicMock()
    response.choices[0].message = message
    return response


def test_agent_calls_get_stats_for_count_question(test_db):
    """Вопрос про количество отзывов → агент вызывает get_stats."""
    import tools
    import agent
    reload(tools)
    reload(agent)

    called_tools = []

    def mock_call_tool(name, args):
        called_tools.append(name)
        if name == "get_stats":
            return {"company": "rentumo", "total_reviews": 3, "avg_rating": 3.0,
                    "rating_distribution": {}, "negative_total": 2,
                    "negative_with_reply": 1, "negative_reply_rate_pct": 50.0}
        return []

    responses = [
        make_openai_response(tool_name="get_stats", tool_args={"company": "rentumo"}),
        make_openai_response(content="У Rentumo 3 отзыва."),
    ]

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = responses

    with patch("agent.OpenAI", return_value=mock_client), \
         patch("agent.call_tool", side_effect=mock_call_tool), \
         patch("tools.DB_PATH", test_db):
        answer = agent.run_agent("Сколько отзывов у Rentumo?")

    assert "get_stats" in called_tools
    assert answer == "У Rentumo 3 отзыва."


def test_agent_calls_get_reviews_for_rating_filter(test_db):
    """Вопрос про отзывы с 1 звездой → агент вызывает get_reviews с max_rating=1."""
    import tools
    import agent
    reload(tools)
    reload(agent)

    called_tools = []
    called_args = []

    def mock_call_tool(name, args):
        called_tools.append(name)
        called_args.append(args)
        return []

    responses = [
        make_openai_response(
            tool_name="get_reviews",
            tool_args={"company": "rentumo", "min_rating": 1, "max_rating": 1}
        ),
        make_openai_response(content="Вот отзывы с 1 звездой."),
    ]

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = responses

    with patch("agent.OpenAI", return_value=mock_client), \
         patch("agent.call_tool", side_effect=mock_call_tool):
        agent.run_agent("Дай отзывы с 1 звездой для Rentumo")

    assert "get_reviews" in called_tools
    args = called_args[called_tools.index("get_reviews")]
    assert args.get("max_rating") == 1


def test_agent_returns_final_answer(test_db):
    """Агент возвращает текст финального ответа."""
    import agent
    reload(agent)

    responses = [
        make_openai_response(content="Финальный ответ агента."),
    ]

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = responses

    with patch("agent.OpenAI", return_value=mock_client):
        answer = agent.run_agent("Привет")

    assert answer == "Финальный ответ агента."


def test_agent_handles_multiple_tool_calls(test_db):
    """Агент может вызвать несколько инструментов подряд."""
    import agent
    reload(agent)

    called_tools = []

    def mock_call_tool(name, args):
        called_tools.append(name)
        return {"company": args.get("company"), "total_reviews": 5,
                "avg_rating": 3.0, "rating_distribution": {},
                "negative_total": 2, "negative_with_reply": 1,
                "negative_reply_rate_pct": 50.0}

    responses = [
        make_openai_response(tool_name="get_stats", tool_args={"company": "rentumo"}, tool_call_id="c1"),
        make_openai_response(tool_name="get_stats", tool_args={"company": "immobilienscout24"}, tool_call_id="c2"),
        make_openai_response(content="Сравнение компаний готово."),
    ]

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = responses

    with patch("agent.OpenAI", return_value=mock_client), \
         patch("agent.call_tool", side_effect=mock_call_tool):
        answer = agent.run_agent("Сравни Rentumo и ImmobilienScout24")

    assert called_tools.count("get_stats") == 2
    assert answer == "Сравнение компаний готово."

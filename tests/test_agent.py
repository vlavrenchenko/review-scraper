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
    response.usage = None
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
        answer, history = agent.run_agent("Сколько отзывов у Rentumo?")

    assert "get_stats" in called_tools
    assert answer == "У Rentumo 3 отзыва."
    assert len(history) > 0


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

    responses = [make_openai_response(content="Финальный ответ агента.")]
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = responses

    with patch("agent.OpenAI", return_value=mock_client):
        answer, history = agent.run_agent("Привет")

    assert answer == "Финальный ответ агента."
    assert isinstance(history, list)


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
        answer, _ = agent.run_agent("Сравни Rentumo и ImmobilienScout24")

    assert called_tools.count("get_stats") == 2
    assert answer == "Сравнение компаний готово."


def test_agent_history_passed_to_messages(test_db):
    """История передаётся в messages при следующем вызове."""
    import agent
    reload(agent)

    captured_messages = []

    def fake_create(**kwargs):
        captured_messages.extend(kwargs.get("messages", []))
        return make_openai_response(content="Ответ с историей.")

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = fake_create

    history = [
        {"role": "user", "content": "Первый вопрос"},
        {"role": "assistant", "content": "Первый ответ"},
    ]

    with patch("agent.OpenAI", return_value=mock_client):
        agent.run_agent("Второй вопрос", history=history)

    roles = [m["role"] if isinstance(m, dict) else m.role for m in captured_messages]
    assert "system" in roles
    assert roles.count("user") >= 2


def test_agent_history_trimmed_to_max(test_db):
    """История обрезается до MAX_HISTORY сообщений."""
    import agent
    reload(agent)

    long_history = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"msg {i}"}
        for i in range(20)
    ]
    trimmed = agent._trim_history(long_history)
    assert len(trimmed) == agent.MAX_HISTORY


def test_agent_history_short_not_trimmed():
    """Короткая история не обрезается."""
    import agent
    reload(agent)

    short_history = [{"role": "user", "content": "msg"}] * 3
    assert agent._trim_history(short_history) == short_history


def test_agent_returns_updated_history(test_db):
    """run_agent возвращает обновлённую историю включая новый вопрос и ответ."""
    import agent
    reload(agent)

    responses = [make_openai_response(content="Ответ агента.")]
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = responses

    with patch("agent.OpenAI", return_value=mock_client):
        _, history = agent.run_agent("Мой вопрос")

    contents = [m["content"] if isinstance(m, dict) else m.content for m in history]
    assert "Мой вопрос" in contents
    assert "Ответ агента." in contents

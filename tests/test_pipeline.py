"""Тесты pipeline.py — LangGraph граф с моком OpenAI."""
from importlib import reload
from unittest.mock import patch, MagicMock


def make_llm_response(content):
    response = MagicMock()
    response.choices[0].message.tool_calls = None
    response.choices[0].message.content = content
    return response


def test_pipeline_check_data_sufficient(test_db):
    """check_data не добавляет warnings если данных достаточно."""
    import tools
    import pipeline
    reload(tools)
    reload(pipeline)
    with patch("tools.DB_PATH", test_db):
        state = pipeline.check_data({
            "companies": ["rentumo"],
            "threshold": 2,
            "stats": {}, "neg_categories": {}, "pos_categories": {},
            "warnings": [], "report": "",
        })

    assert state["warnings"] == []
    assert "rentumo" in state["stats"]
    assert state["stats"]["rentumo"]["total_reviews"] == 3


def test_pipeline_check_data_triggers_warning(test_db):
    """check_data добавляет warning если данных меньше threshold."""
    import tools
    import pipeline
    reload(tools)
    reload(pipeline)
    with patch("tools.DB_PATH", test_db):
        state = pipeline.check_data({
            "companies": ["rentumo"],
            "threshold": 100,
            "stats": {}, "neg_categories": {}, "pos_categories": {},
            "warnings": [], "report": "",
        })

    assert len(state["warnings"]) == 1
    assert "rentumo" in state["warnings"][0]


def test_pipeline_routing_no_warnings():
    """route_after_check возвращает 'analyze' если warnings пустой."""
    import pipeline
    result = pipeline.route_after_check({"warnings": []})
    assert result == "analyze"


def test_pipeline_routing_with_warnings():
    """route_after_check возвращает 'warn' если есть warnings."""
    import pipeline
    result = pipeline.route_after_check({"warnings": ["some warning"]})
    assert result == "warn"


def test_pipeline_fetch_analysis(test_db):
    """fetch_analysis загружает категории для всех компаний."""
    import tools
    import pipeline
    reload(tools)
    reload(pipeline)
    with patch("tools.DB_PATH", test_db):
        state = pipeline.fetch_analysis({
            "companies": ["rentumo", "immobilienscout24"],
            "threshold": 1, "stats": {}, "neg_categories": {},
            "pos_categories": {}, "warnings": [], "report": "",
        })

    assert "rentumo" in state["neg_categories"]
    assert "immobilienscout24" in state["neg_categories"]
    assert len(state["neg_categories"]["rentumo"]) > 0


def test_pipeline_generates_report(test_db):
    """generate_report вызывает LLM и возвращает отчёт."""
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = make_llm_response("# Отчёт\n\nТестовый отчёт.")

    import tools
    import pipeline
    reload(tools)
    reload(pipeline)
    with patch("pipeline.OpenAI", return_value=mock_client), \
         patch("tools.DB_PATH", test_db):
        state = pipeline.generate_report({
            "companies": ["rentumo"],
            "threshold": 1,
            "stats": {"rentumo": {"total_reviews": 3, "avg_rating": 3.0,
                                   "negative_total": 2, "negative_with_reply": 1,
                                   "negative_reply_rate_pct": 50.0, "rating_distribution": {}}},
            "neg_categories": {"rentumo": [{"name": "Нет ответов", "count": 2}]},
            "pos_categories": {"rentumo": [{"name": "Удобный поиск", "count": 1}]},
            "warnings": [], "report": "",
        })

    assert "report" in state
    assert len(state["report"]) > 0
    assert mock_client.chat.completions.create.called


def test_full_pipeline_runs(test_db, tmp_path):
    """Полный прогон графа от START до END."""
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = make_llm_response("# Финальный отчёт")

    import tools
    import pipeline
    reload(tools)
    reload(pipeline)
    with patch("pipeline.OpenAI", return_value=mock_client), \
         patch("tools.DB_PATH", test_db), \
         patch("pipeline.DB_PATH", test_db):
        graph = pipeline.build_graph()
        result = graph.invoke({
            "companies": ["rentumo"],
            "threshold": 2,
            "stats": {}, "neg_categories": {}, "pos_categories": {},
            "warnings": [], "report": "",
        })

    assert result["report"] == "# Финальный отчёт"
    assert "rentumo" in result["stats"]

"""
E2E тесты гибридного поиска — реальный OpenAI, реальная ChromaDB.
Запуск: pytest -m e2e
"""
import pytest


@pytest.mark.e2e
def test_chroma_collection_has_reviews(require_openai):
    """ChromaDB содержит проиндексированные отзывы."""
    import chromadb
    from pathlib import Path

    chroma_path = Path(__file__).parent.parent.parent / "data" / "chroma"
    if not chroma_path.exists():
        pytest.skip("ChromaDB не инициализирован — запусти embed.py")

    client = chromadb.PersistentClient(path=str(chroma_path))
    col = client.get_collection("reviews")
    assert col.count() > 0, "ChromaDB пуста — запусти embed.py"


@pytest.mark.e2e
def test_semantic_search_returns_results(require_openai):
    """Семантический поиск возвращает релевантные результаты."""
    from pathlib import Path
    import chromadb
    from openai import OpenAI

    chroma_path = Path(__file__).parent.parent.parent / "data" / "chroma"
    if not chroma_path.exists():
        pytest.skip("ChromaDB не инициализирован")

    client_oai = OpenAI()
    client_chroma = chromadb.PersistentClient(path=str(chroma_path))
    col = client_chroma.get_collection("reviews")

    embedding = client_oai.embeddings.create(
        model="text-embedding-3-small", input="hidden fees payment"
    ).data[0].embedding

    results = col.query(
        query_embeddings=[embedding],
        n_results=3,
        include=["documents", "metadatas"],
    )

    assert len(results["ids"][0]) > 0
    for meta in results["metadatas"][0]:
        assert "company" in meta
        assert "rating" in meta


@pytest.mark.e2e
def test_hybrid_search_returns_results(require_openai, db_has_data):
    """Гибридный search_reviews возвращает результаты по смысловому запросу."""
    from unittest.mock import patch
    import tools
    from importlib import reload
    reload(tools)

    with patch("tools.DB_PATH", db_has_data):
        results = tools.search_reviews(
            "hidden OR fees OR payment OR charge",
            company="immobilienscout24",
            limit=5,
        )

    assert isinstance(results, list)
    for r in results:
        assert "id" in r
        assert "company" in r
        assert "rating" in r
        assert "title" in r
        assert "text" in r


@pytest.mark.e2e
def test_hybrid_search_all_companies(require_openai, db_has_data):
    """Гибридный поиск работает для всех четырёх компаний."""
    from unittest.mock import patch
    import tools
    from importlib import reload
    reload(tools)

    companies = ["immobilienscout24", "rentumo", "immosurf", "immowelt"]
    with patch("tools.DB_PATH", db_has_data):
        for company in companies:
            results = tools.search_reviews("support OR service", company=company, limit=3)
            assert isinstance(results, list), f"Ошибка для {company}"

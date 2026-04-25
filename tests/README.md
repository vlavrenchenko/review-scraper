# Тесты проекта Trustpilot Scraper

## Требования

- Python 3.14 (venv проекта: `~/jupyter-worspace/.venv`)
- `pytest` установлен в venv: `pip install pytest`

---

## Запуск

```bash
# Активировать venv (если не активирован)
source ~/jupyter-worspace/.venv/bin/activate

# Перейти в корень проекта
cd ~/jupyter-worspace/trustpilot_scraper

# Все тесты
pytest tests/ -v

# Один файл
pytest tests/test_tools.py -v

# Один тест
pytest tests/test_tools.py::test_get_stats_returns_correct_fields -v
```

Конфигурация находится в `pytest.ini` в корне проекта — он добавляет корень в `sys.path`, чтобы `import tools`, `import agent` и т.д. работали без установки пакета.

---

## Структура

```
tests/
├── conftest.py      # фикстуры: тестовая БД и HTML-заглушка
├── test_smoke.py    # целостность окружения и файловой структуры проекта
├── test_tools.py    # unit-тесты инструментов агента (tools.py)
├── test_scraper.py  # парсинг HTML и запись в БД (scraper.py)
├── test_agent.py    # агент с моком OpenAI (agent.py)
└── test_pipeline.py # LangGraph-пайплайн с моком OpenAI (pipeline.py)
```

**35 тестов · всё проходит · ~0.5 сек**

---

## conftest.py — фикстуры

### `test_db`

Временная SQLite-база в `tmp_path`. Создаётся заново для каждого теста, удаляется автоматически после него.

Таблица `reviews` — 5 записей:

| id | company | rating | reply |
|----|---------|--------|-------|
| r1 | rentumo | 5 | нет |
| r2 | rentumo | 1 | нет |
| r3 | rentumo | 3 | есть (`reply_date` заполнен) |
| r4 | immobilienscout24 | 4 | нет |
| r5 | immobilienscout24 | 1 | есть |

Таблица `categories` — 3 записи:

| company | group_type | name | count |
|---------|------------|------|-------|
| rentumo | negative | Нет ответов | 3 |
| rentumo | positive | Удобный поиск | 2 |
| immobilienscout24 | negative | Скрытые платежи | 4 |

### `sample_trustpilot_html`

HTML-строка с тегом `<script id="__NEXT_DATA__">`, имитирующая страницу Trustpilot. Содержит два отзыва: рейтинг 5 без reply и рейтинг 1 с reply.

---

## test_smoke.py — 9 тестов

Проверяют целостность проекта: все файлы на месте, конфиги валидны, БД заполнена. Работают с реальными файлами проекта, не используют тестовые фикстуры.

| Тест | Что проверяет |
|------|--------------|
| `test_imports` | Все модули (`tools`, `scraper`, `analyze`, `agent`, `pipeline`) импортируются без ошибок |
| `test_config_companies_valid_json` | `config/companies.json` — валидный JSON, массив объектов с полями `id`, `name`, `url` |
| `test_config_pricing_valid_json` | `config/models_pricing.json` — валидный JSON, ключ `models` непустой |
| `test_db_exists` | Файл `data/reviews.db` существует |
| `test_db_tables_exist` | В БД есть таблицы `reviews` и `categories` |
| `test_db_reviews_not_empty` | В `reviews` есть хотя бы одна запись |
| `test_db_reviews_has_company_column` | В `reviews` есть колонки `company` и `reply_date` |
| `test_cache_dir_exists` | Директория `data/cache/` существует |
| `test_reports_dir_exists` | Директория `reports/` существует |

---

## test_tools.py — 9 тестов

Unit-тесты функций `tools.py`. Каждый тест работает с изолированной `test_db`.

| Тест | Что проверяет |
|------|--------------|
| `test_get_stats_returns_correct_fields` | `get_stats("rentumo")` → `total_reviews=3`, `avg_rating=3.0`, `negative_total=2` (рейтинг ≤3: r2 и r3), `negative_with_reply=1` (только r3 имеет reply) |
| `test_get_stats_all_companies` | `get_stats()` без аргументов → список, содержащий обе компании |
| `test_get_reviews_returns_list` | `get_reviews("rentumo")` → список из 3 элементов, каждый с полями `id`, `rating`, `text`, `has_reply` |
| `test_get_reviews_filter_by_rating` | `get_reviews("rentumo", min_rating=1, max_rating=1)` → ровно 1 отзыв с рейтингом 1 |
| `test_get_reviews_limit` | `get_reviews("rentumo", limit=2)` → не более 2 записей |
| `test_get_categories_negative` | `get_categories("rentumo", "negative")` → 1 запись с `group_type="negative"` и `name="Нет ответов"` |
| `test_get_categories_both` | `get_categories("rentumo", "both")` → записи обоих типов: `negative` и `positive` |
| `test_call_tool_dispatcher` | `call_tool("get_stats", {...})` и `call_tool("get_reviews", {...})` вызывают нужные функции |
| `test_call_tool_unknown_raises` | `call_tool("unknown_tool", {})` → `ValueError` |

---

## test_scraper.py — 6 тестов

Тесты без сети и без запуска Playwright.

**Парсинг HTML** (фикстура `sample_trustpilot_html`):

| Тест | Что проверяет |
|------|--------------|
| `test_parse_next_data_returns_reviews` | Из HTML извлекается JSON с 2 отзывами; `id` и `rating` совпадают с ожидаемыми |
| `test_parse_review_fields` | Первый отзыв: все поля присутствуют (`id`, `title`, `rating`, `dates.publishedDate`, `consumer.displayName`, `reply=None`) |
| `test_parse_reply_fields` | Второй отзыв: `reply` непустой, содержит `message` и `publishedDate` |
| `test_missing_next_data_returns_empty` | HTML без `__NEXT_DATA__` → поиск тега возвращает `-1` |

**Запись в БД** (фикстура `test_db`):

| Тест | Что проверяет |
|------|--------------|
| `test_save_reviews_inserts_new` | `save_reviews()` с новым отзывом увеличивает `COUNT(*)` на 1 |
| `test_save_reviews_ignores_duplicates` | `save_reviews()` с `id="r1"` (уже есть в БД) не меняет `COUNT(*)`; `inserted == 0` |

---

## test_agent.py — 4 теста

Тесты агента с полностью замоканным OpenAI. Реальных запросов к API нет.

Вспомогательная функция `make_openai_response()` строит мок-ответ `chat.completions.create()`:
- если передан `tool_name` — имитирует вызов инструмента (заполняет `tool_calls`)
- если передан `content` — имитирует финальный текстовый ответ (`tool_calls = None`)

| Тест | Что проверяет |
|------|--------------|
| `test_agent_calls_get_stats_for_count_question` | На вопрос «Сколько отзывов у Rentumo?» агент вызывает `get_stats`; возвращает мок-текст финального ответа |
| `test_agent_calls_get_reviews_for_rating_filter` | На вопрос про отзывы с 1 звездой агент вызывает `get_reviews` с `max_rating=1` |
| `test_agent_returns_final_answer` | Если первый ответ LLM уже текстовый (нет `tool_calls`), агент сразу возвращает его |
| `test_agent_handles_multiple_tool_calls` | Агент обрабатывает цепочку из 2 вызовов `get_stats` (для разных компаний) перед финальным ответом |

---

## test_pipeline.py — 7 тестов

Тесты LangGraph-графа из `pipeline.py`. OpenAI замокирован аналогично тестам агента.

**Узлы графа по отдельности:**

| Тест | Что проверяет |
|------|--------------|
| `test_pipeline_check_data_sufficient` | `check_data` при `threshold=2` и 3 отзывах: `warnings=[]`, `stats["rentumo"]["total_reviews"] == 3` |
| `test_pipeline_check_data_triggers_warning` | `check_data` при `threshold=100`: добавляет 1 warning, содержащий название компании |
| `test_pipeline_routing_no_warnings` | `route_after_check({"warnings": []})` → `"analyze"` |
| `test_pipeline_routing_with_warnings` | `route_after_check({"warnings": [...]})` → `"warn"` |
| `test_pipeline_fetch_analysis` | `fetch_analysis` заполняет `neg_categories` для обеих компаний из тестовой БД |
| `test_pipeline_generates_report` | `generate_report` вызывает LLM и записывает результат в `state["report"]` |

**Интеграционный тест:**

| Тест | Что проверяет |
|------|--------------|
| `test_full_pipeline_runs` | `graph.invoke({...})` проходит от START до END; итоговый `report` совпадает с мок-ответом LLM; `stats["rentumo"]` заполнен |

---

## Как устроена изоляция

### Тестовая БД вместо реальной

Модули хранят путь к БД в модульной константе `DB_PATH`. Чтобы тест работал с временной БД, а не реальной, используется `patch` + `reload`:

```python
import tools
from importlib import reload

reload(tools)                           # сбросить модуль в чистое состояние
with patch("tools.DB_PATH", test_db):  # подменить путь к БД
    result = tools.get_stats("rentumo")
```

`reload` должен быть **до** `with patch(...)`. Если поставить его внутри — он перезапишет `DB_PATH` реальным путём, отменив патч.

### Мок OpenAI

Ни один тест не делает реальных запросов к OpenAI. Мок подставляется через `patch("agent.OpenAI", return_value=mock_client)` — это заменяет сам конструктор класса, поэтому любой `OpenAI()` внутри модуля вернёт `mock_client` с заданными ответами.

По той же причине `reload(agent)` или `reload(pipeline)` нужно делать **до** `with patch(...)`.

### Playwright не нужен для тестов

`scraper.py` импортирует `playwright` лениво — внутри функции, которая запускает браузер. Поэтому `import scraper` работает без установленного Playwright, и тесты `save_reviews` не зависят от браузера.

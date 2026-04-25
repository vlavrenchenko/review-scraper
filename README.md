# Trustpilot Scraper & Analytics

Инструмент для сбора и анализа отзывов платформ аренды жилья в Германии с Trustpilot.

**Компании:** ImmobilienScout24, Rentumo, ImmoSurf, Immowelt

---

## Быстрый старт

```bash
cd ~/jupyter-worspace/trustpilot_scraper
source ../.venv/bin/activate
```

Создай файл `.env` в директории `~/jupyter-worspace/` (если ещё нет):
```
OPENAI_API_KEY=sk-...
```

---

## Архитектура

```
scraper.py   →  data/reviews.db  →  analyze.py  →  categories в БД
                                                         ↓
                                          agent.py / pipeline.py / app.py
```

| Файл | Роль |
|------|------|
| `scraper.py` | Загружает отзывы с Trustpilot через Playwright, сохраняет в SQLite |
| `analyze.py` | Кластеризует отзывы по категориям через OpenAI, сохраняет в БД |
| `agent.py` | Q&A агент с инструментами для запросов к БД |
| `pipeline.py` | LangGraph-пайплайн генерации аналитического отчёта |
| `app.py` | Streamlit веб-интерфейс (агент + отчёт) |
| `tools.py` | Общие функции запросов к БД, используются агентом и пайплайном |

---

## Веб-интерфейс (app.py)

```bash
streamlit run app.py
```

Откроется на `http://localhost:8501`.

**Таб «Агент»** — задавай вопросы на русском языке, агент сам выбирает нужные инструменты и запрашивает данные из БД. Есть кнопки быстрых вопросов. После ответа показывает список вызванных инструментов.

**Таб «Отчёт»** — выбери компании и минимальный порог отзывов, нажми кнопку. Показывает прогресс по шагам и отрисовывает готовый Markdown-отчёт. Можно скачать как `.md` файл.

**Сайдбар** — статистика по каждой компании из БД: количество отзывов, средний рейтинг, процент ответов на негативные отзывы.

---

## Сбор отзывов (scraper.py)

Использует Playwright (headless Chromium) для обхода защиты Trustpilot. Данные берутся из встроенного JSON `__NEXT_DATA__` на странице.

```bash
# Одна компания — 50 отзывов (по умолчанию)
python3 scraper.py

# Конкретная компания
python3 scraper.py --company rentumo

# Несколько компаний
python3 scraper.py --company rentumo,immowelt

# Все компании
python3 scraper.py --company all

# Задать количество отзывов
python3 scraper.py --company all --reviews 100

# Игнорировать кеш (загрузить свежие данные)
python3 scraper.py --company rentumo --no-cache

# Изменить TTL кеша (по умолчанию 60 минут)
python3 scraper.py --company all --cache-ttl 120
```

**Кеш** хранится в `data/cache/{company}/page_N.json`. При повторном запуске страницы читаются из кеша, если не истёк TTL.

**Дедупликация:** повторный запуск не создаёт дублей — уже существующие отзывы пропускаются. Если у отзыва появился ответ компании — запись обновляется.

---

## Анализ отзывов (analyze.py)

Кластеризует отзывы по темам через OpenAI. Выделяет категории для негативных (рейтинг ≤ 3) и позитивных (рейтинг ≥ 4) отзывов отдельно. По умолчанию только выводит результат — для сохранения нужен флаг `--save`.

```bash
# Анализ всех компаний, вывод без сохранения
python3 analyze.py

# Сохранить результаты в БД
python3 analyze.py --save

# Конкретная компания
python3 analyze.py --company rentumo --save

# Несколько компаний
python3 analyze.py --company rentumo,immowelt --save

# Выбрать модель
python3 analyze.py --model gpt-4o --save

# Ограничить количество отзывов на группу
python3 analyze.py --limit 50 --save

# Показать список доступных моделей OpenAI
python3 analyze.py --list-models
```

После выполнения выводит статистику: количество токенов, стоимость запроса в USD, количество сохранённых категорий.

Цены моделей берутся из `config/models_pricing.json` — обновляй при необходимости.

---

## Агент (agent.py)

OpenAI-агент с инструментами для работы с БД. Использует function calling: сам решает, какие данные запросить, на основе вопроса.

**Доступные инструменты агента:**
- `get_stats` — статистика по компании (total, avg_rating, доля ответов на негатив)
- `get_reviews` — список отзывов с фильтрацией по рейтингу и лимитом
- `get_categories` — категории жалоб/похвал из последнего анализа

```bash
# Одиночный вопрос
python3 agent.py "Сколько отзывов у Rentumo?"

# Сравнение
python3 agent.py "Сравни рейтинги всех компаний"

# Интерактивный режим
python3 agent.py
```

В интерактивном режиме введи `exit` для выхода.

---

## Генерация отчёта (pipeline.py)

LangGraph-пайплайн: проверяет наличие данных → загружает категории из БД → генерирует структурированный Markdown-отчёт через LLM.

**Структура отчёта:** общая статистика → топ-5 жалоб по каждой компании → топ-5 достоинств → сравнение компаний → ключевые выводы.

```bash
# Отчёт по всем компаниям (сохраняется в reports/report_YYYYMMDD.md)
python3 pipeline.py

# Конкретные компании
python3 pipeline.py --company rentumo,immobilienscout24

# Изменить минимальный порог отзывов (компании ниже порога попадут в предупреждения)
python3 pipeline.py --threshold 50

# Сохранить в конкретный файл
python3 pipeline.py --output my_report.md
```

Если для какой-то компании отзывов меньше порога — пайплайн выдаёт предупреждение, но продолжает с имеющимися данными.

---

## Типичный рабочий процесс

```bash
# 1. Собрать свежие отзывы
python3 scraper.py --company all --reviews 100

# 2. Запустить анализ и сохранить категории
python3 analyze.py --company all --save

# 3. Открыть веб-интерфейс
streamlit run app.py
```

Или вместо шага 3 — сгенерировать отчёт из CLI:
```bash
python3 pipeline.py
```

---

## Структура проекта

```
trustpilot_scraper/
├── app.py                  # Streamlit веб-интерфейс
├── scraper.py              # Парсер Trustpilot
├── analyze.py              # LLM-анализ отзывов
├── agent.py                # Q&A агент
├── pipeline.py             # LangGraph-пайплайн отчёта
├── tools.py                # Функции запросов к БД
├── config/
│   ├── companies.json      # Список компаний и URL
│   └── models_pricing.json # Цены моделей OpenAI
├── data/
│   ├── reviews.db          # SQLite база данных
│   └── cache/              # Кеш страниц по компаниям
├── reports/                # Сгенерированные отчёты
├── tests/                  # Автотесты (pytest)
└── pytest.ini              # Конфигурация pytest
```

### Схема БД

**Таблица `reviews`**

| Колонка | Тип | Описание |
|---------|-----|----------|
| id | TEXT PK | ID отзыва с Trustpilot |
| company | TEXT | ID компании |
| title | TEXT | Заголовок отзыва |
| text | TEXT | Текст отзыва |
| rating | INTEGER | Оценка 1–5 |
| published_date | TEXT | Дата публикации |
| reply | TEXT | Текст ответа компании |
| reply_date | TEXT | Дата ответа |
| author_hash | TEXT | Хеш имени автора |
| scraped_at | TEXT | Дата последнего обновления записи |

**Таблица `categories`**

| Колонка | Тип | Описание |
|---------|-----|----------|
| company | TEXT | ID компании |
| group_type | TEXT | `negative` или `positive` |
| name | TEXT | Название категории |
| description | TEXT | Описание категории |
| count | INTEGER | Количество отзывов в категории |
| review_ids | TEXT | JSON-массив ID отзывов |
| model | TEXT | Использованная модель OpenAI |
| analyzed_at | TEXT | Дата анализа |

---

## Тесты

```bash
pytest tests/ -v
```

35 тестов покрывают все модули. Документация по тестам: [`tests/README.md`](tests/README.md).

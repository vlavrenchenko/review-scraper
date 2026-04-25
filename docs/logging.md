# Логирование

## Где лежат логи

```
logs/
└── agent.log          # текущий файл
    agent.log.2026-04-24  # вчерашний (ротация по дням)
    agent.log.2026-04-23
    ...                # хранится 30 дней, потом удаляется автоматически
```

Все модули пишут в один файл `logs/agent.log`.

---

## Формат записи

Каждая строка — валидный JSON:

```json
{
  "ts": "2026-04-25T08:22:41",
  "level": "INFO",
  "logger": "agent",
  "msg": "tool_call",
  "tool": "get_stats",
  "tool_args": {"company": "rentumo"}
}
```

| Поле | Всегда есть | Описание |
|------|-------------|----------|
| `ts` | да | Время события (ISO 8601, с точностью до секунды) |
| `level` | да | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `logger` | да | Модуль-источник: `agent`, `pipeline`, `sheets` |
| `msg` | да | Тип события (см. таблицы ниже) |
| `exc` | при ошибке | Полный traceback |
| остальные | зависит от события | Контекст события |

---

## Уровни логирования

| Уровень | Куда пишется | Что означает |
|---------|-------------|--------------|
| `DEBUG` | только файл | Детали: результаты инструментов, отдельные листы |
| `INFO` | только файл | Нормальный ход работы: старт, завершение |
| `WARNING` | только файл | Ситуации, требующие внимания: мало данных |
| `ERROR` | файл **и терминал** | Ошибки выполнения с трейсбеком |

В терминале при нормальной работе ничего не появляется — только `ERROR`.

---

## События агента (`logger: "agent"`)

| `msg` | `level` | Поля | Когда |
|-------|---------|------|-------|
| `agent_start` | INFO | `question`, `model` | Получен вопрос от пользователя |
| `tool_call` | INFO | `tool`, `tool_args` | Агент решил вызвать инструмент |
| `tool_result` | DEBUG | `tool`, `duration_sec`, `result_preview` | Инструмент вернул результат |
| `agent_done` | INFO | `duration_sec`, `tool_calls_count`, `answer_len` | Агент вернул финальный ответ |
| `agent_error` | ERROR | `question`, `error`, `exc` | Необработанное исключение |

**Пример полного цикла одного запроса:**

```
INFO  [agent] agent_start        {"question": "Сколько отзывов у Rentumo?", "model": "gpt-4o-mini"}
INFO  [agent] tool_call          {"tool": "get_stats", "tool_args": {"company": "rentumo"}}
DEBUG [agent] tool_result        {"tool": "get_stats", "duration_sec": 0.001, "result_preview": "{\"total_reviews\": 37...}"}
INFO  [agent] agent_done         {"duration_sec": 4.05, "tool_calls_count": 1, "answer_len": 36}
```

---

## События пайплайна (`logger: "pipeline"`)

| `msg` | `level` | Поля | Когда |
|-------|---------|------|-------|
| `check_data_start` | INFO | `companies`, `threshold` | Начало проверки данных в БД |
| `low_data` | WARNING | `company`, `total`, `threshold` | Отзывов меньше порога |
| `check_data_done` | INFO | `warnings_count` | Проверка завершена |
| `fetch_analysis_start` | INFO | `companies` | Начало загрузки категорий |
| `fetch_analysis_done` | INFO | — | Категории загружены |
| `generate_report_start` | INFO | `companies` | Начало генерации отчёта через LLM |
| `generate_report_done` | INFO | `duration_sec`, `report_len` | Отчёт готов |

**Пример:**

```
INFO    [pipeline] check_data_start     {"companies": ["rentumo", "immowelt"], "threshold": 20}
WARNING [pipeline] low_data             {"company": "immowelt", "total": 5, "threshold": 20}
INFO    [pipeline] check_data_done      {"warnings_count": 1}
INFO    [pipeline] fetch_analysis_start {"companies": ["rentumo", "immowelt"]}
INFO    [pipeline] fetch_analysis_done
INFO    [pipeline] generate_report_start {"companies": ["rentumo", "immowelt"]}
INFO    [pipeline] generate_report_done  {"duration_sec": 12.3, "report_len": 4201}
```

---

## События экспорта (`logger: "sheets"`)

| `msg` | `level` | Поля | Когда |
|-------|---------|------|-------|
| `export_start` | INFO | `company`, `data_type` | Начало экспорта |
| `sheet_written` | DEBUG | `sheet` | Один лист записан |
| `export_done` | INFO | `duration_sec`, `sheets_updated`, `url` | Экспорт завершён |

**Пример:**

```
INFO  [sheets] export_start   {"company": null, "data_type": "all"}
DEBUG [sheets] sheet_written  {"sheet": "Статистика"}
DEBUG [sheets] sheet_written  {"sheet": "Отзывы — Rentumo"}
DEBUG [sheets] sheet_written  {"sheet": "Категории"}
INFO  [sheets] export_done    {"duration_sec": 18.4, "sheets_updated": ["Статистика", ...], "url": "https://..."}
```

---

## Как читать логи

### Смотреть последние события

```bash
tail -f logs/agent.log | python3 -c "
import sys, json
for line in sys.stdin:
    d = json.loads(line.strip())
    extra = {k:v for k,v in d.items() if k not in ('ts','level','logger','msg')}
    print(f\"{d['ts']}  {d['level']:<7} [{d['logger']}] {d['msg']}  {extra if extra else ''}\")
"
```

`tail -f` — следит за файлом в реальном времени, удобно держать открытым рядом с терминалом Streamlit.

### Смотреть все события за сегодня

```bash
cat logs/agent.log | python3 -c "
import sys, json
for line in sys.stdin:
    d = json.loads(line.strip())
    extra = {k:v for k,v in d.items() if k not in ('ts','level','logger','msg')}
    print(f\"{d['ts']}  {d['level']:<7} [{d['logger']}] {d['msg']}  {extra if extra else ''}\")
"
```

### Только ошибки

```bash
grep '"level": "ERROR"' logs/agent.log | python3 -m json.tool
```

### Только вызовы инструментов

```bash
grep '"msg": "tool_call"' logs/agent.log | python3 -c "
import sys, json
for line in sys.stdin:
    d = json.loads(line.strip())
    print(f\"{d['ts']}  {d['tool']}({d['tool_args']})\")
"
```

### История вопросов агенту

```bash
grep '"msg": "agent_start"' logs/agent.log | python3 -c "
import sys, json
for line in sys.stdin:
    d = json.loads(line.strip())
    print(f\"{d['ts']}  {d['question']}\")
"
```

### Статистика времени выполнения

```bash
grep '"msg": "agent_done"' logs/agent.log | python3 -c "
import sys, json
for line in sys.stdin:
    d = json.loads(line.strip())
    print(f\"{d['ts']}  {d['duration_sec']}s  tools={d['tool_calls_count']}  answer={d['answer_len']} chars\")
"
```

### Предупреждения о нехватке данных

```bash
grep '"msg": "low_data"' logs/agent.log | python3 -c "
import sys, json
for line in sys.stdin:
    d = json.loads(line.strip())
    print(f\"{d['ts']}  {d['company']}: {d['total']} отзывов (нужно {d['threshold']})\")
"
```

### Логи за конкретный день

```bash
# Вчерашний файл
cat logs/agent.log.2026-04-24 | python3 -c "..."

# Найти все файлы за апрель
ls logs/agent.log.2026-04*
```

---

## Как добавить логирование в новый модуль

```python
from logger import get_logger

log = get_logger("my_module")

# Информационное событие с контекстом
log.info("operation_done", extra={"duration_sec": 1.2, "rows": 42})

# Предупреждение
log.warning("low_data", extra={"company": "rentumo", "total": 3})

# Ошибка с трейсбеком
try:
    ...
except Exception as e:
    log.error("operation_failed", extra={"error": str(e)}, exc_info=True)
    raise
```

**Правила именования полей в `extra`:**

- Не использовать зарезервированные имена Python logging: `args`, `message`, `msg`, `name`, `levelname` и другие из `_BUILTIN_ATTRS` в `logger.py`
- Имена в `snake_case`
- Для аргументов инструментов использовать `tool_args`, а не `args`

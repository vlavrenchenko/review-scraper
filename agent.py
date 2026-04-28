import json
import os
import sys
import time
from pathlib import Path
from openai import OpenAI
from dotenv import load_dotenv
from tools import TOOL_DEFINITIONS, call_tool
from logger import get_logger, get_cost_logger

_PRICING_PATH = Path(__file__).parent / "config" / "models_pricing.json"


def _clean_input(text: str) -> str:
    return text.encode("utf-8", errors="replace").decode("utf-8")


def _load_prices() -> dict:
    if not _PRICING_PATH.exists():
        return {}
    raw = json.loads(_PRICING_PATH.read_text())
    result = {}
    for model_id, data in raw.get("models", {}).items():
        std = data.get("pricing", {}).get("standard", {})
        inp = std.get("input")
        out = std.get("output")
        if inp is not None and out is not None:
            result[model_id] = {"input": inp, "output": out}
    return result


PRICES = _load_prices()
log = get_logger("agent")
cost_log = get_cost_logger()

SYSTEM_PROMPT = """Ты аналитик отзывов платформ аренды недвижимости в Германии.
У тебя есть доступ к базе данных отзывов с Trustpilot для четырёх компаний:
- immobilienscout24 (ImmobilienScout24)
- rentumo (Rentumo)
- immosurf (ImmoSurf)
- immowelt (Immowelt)

Используй инструменты чтобы получить нужные данные и дай конкретный, структурированный ответ.
Отвечай на русском языке.

Правила использования search_reviews:
- Отзывы написаны на английском и немецком языках.
- Перед вызовом search_reviews всегда переводи запрос пользователя на английский.
- Если тема подразумевает несколько слов — используй OR для охвата вариантов: "payment OR fees OR charge OR Gebühr".
- Если пользователь не указал компанию — вызывай search_reviews отдельно для каждой из четырёх компаний."""


MAX_HISTORY = 10


def _trim_history(history: list) -> list:
    """Обрезает историю до последних MAX_HISTORY сообщений."""
    if len(history) <= MAX_HISTORY:
        return history
    return history[-MAX_HISTORY:]


def run_agent(question: str, model: str = "gpt-4o-mini",
              history: list | None = None,
              on_tool_call=None) -> tuple[str, list]:
    load_dotenv(override=True)
    client = OpenAI()

    log.info("agent_start", extra={"question": question, "model": model})
    started_at = time.monotonic()

    trimmed_history = _trim_history(history or [])
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        *trimmed_history,
        {"role": "user", "content": question},
    ]

    tool_calls_count = 0
    total_input_tokens = 0
    total_output_tokens = 0

    try:
        while True:
            response = client.chat.completions.create(  # type: ignore[call-overload]
                model=model,
                messages=messages,
                tools=TOOL_DEFINITIONS,
                tool_choice="auto",
            )

            if response.usage:
                total_input_tokens += response.usage.prompt_tokens
                total_output_tokens += response.usage.completion_tokens

            message = response.choices[0].message
            messages.append(message)

            if not message.tool_calls:
                duration = round(time.monotonic() - started_at, 2)
                prices = PRICES.get(model)
                cost = round(
                    (total_input_tokens * prices["input"] + total_output_tokens * prices["output"]) / 1_000_000, 6
                ) if prices else None

                log.info("agent_done", extra={
                    "duration_sec": duration,
                    "tool_calls_count": tool_calls_count,
                    "answer_len": len(message.content or ""),
                    "input_tokens": total_input_tokens,
                    "output_tokens": total_output_tokens,
                    "cost_usd": cost,
                })
                cost_log.info("agent_cost", extra={
                    "model": model,
                    "question_preview": question[:80],
                    "input_tokens": total_input_tokens,
                    "output_tokens": total_output_tokens,
                    "total_tokens": total_input_tokens + total_output_tokens,
                    "cost_usd": cost,
                    "duration_sec": duration,
                    "tool_calls_count": tool_calls_count,
                })
                new_history = messages[1:]  # срезаем system prompt
                return message.content or "", new_history

            for tool_call in message.tool_calls:
                name = tool_call.function.name
                args = json.loads(tool_call.function.arguments)
                tool_calls_count += 1

                log.info("tool_call", extra={"tool": name, "tool_args": args})
                if on_tool_call:
                    on_tool_call(name, args)

                t0 = time.monotonic()
                result = call_tool(name, args)
                tool_duration = round(time.monotonic() - t0, 3)

                log.debug("tool_result", extra={
                    "tool": name,
                    "duration_sec": tool_duration,
                    "result_preview": json.dumps(result, ensure_ascii=False)[:300],
                })

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result, ensure_ascii=False),
                })

    except Exception as e:
        log.error("agent_error", extra={"question": question, "error": str(e)}, exc_info=True)
        raise


def main():
    load_dotenv(override=True)
    assert os.environ.get("OPENAI_API_KEY"), "Задайте OPENAI_API_KEY в .env файле"

    if len(sys.argv) > 1:
        question = _clean_input(" ".join(sys.argv[1:]))
        print(f"\n❓ {question}\n")
        answer, _ = run_agent(question)
        print(f"\n💬 {answer}\n")
        return

    print("🤖 Агент готов. Задавай вопросы про отзывы (exit для выхода, /new для нового диалога)\n")
    history: list = []
    while True:
        try:
            question = _clean_input(input("❓ Вопрос: ").strip())
        except (EOFError, KeyboardInterrupt):
            break
        if not question:
            continue
        if question.lower() in ("exit", "quit", "выход", "q"):
            break
        if question.lower() in ("/new", "/reset"):
            history = []
            print("🔄 Диалог сброшен\n")
            continue
        answer, history = run_agent(question, history=history)
        print(f"\n💬 {answer}\n")


if __name__ == "__main__":
    main()

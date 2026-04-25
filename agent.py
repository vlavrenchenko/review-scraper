import json
import os
import sys
import time
from openai import OpenAI
from dotenv import load_dotenv
from tools import TOOL_DEFINITIONS, call_tool
from logger import get_logger

log = get_logger("agent")

SYSTEM_PROMPT = """Ты аналитик отзывов платформ аренды недвижимости в Германии.
У тебя есть доступ к базе данных отзывов с Trustpilot для четырёх компаний:
- immobilienscout24 (ImmobilienScout24)
- rentumo (Rentumo)
- immosurf (ImmoSurf)
- immowelt (Immowelt)

Используй инструменты чтобы получить нужные данные и дай конкретный, структурированный ответ.
Отвечай на русском языке."""


def run_agent(question: str, model: str = "gpt-4o-mini", on_tool_call=None) -> str:
    load_dotenv(override=True)
    client = OpenAI()

    log.info("agent_start", extra={"question": question, "model": model})
    started_at = time.monotonic()

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]

    tool_calls_count = 0

    try:
        while True:
            response = client.chat.completions.create(  # type: ignore[call-overload]
                model=model,
                messages=messages,
                tools=TOOL_DEFINITIONS,
                tool_choice="auto",
            )

            message = response.choices[0].message
            messages.append(message)

            if not message.tool_calls:
                duration = round(time.monotonic() - started_at, 2)
                log.info("agent_done", extra={
                    "duration_sec": duration,
                    "tool_calls_count": tool_calls_count,
                    "answer_len": len(message.content or ""),
                })
                return message.content

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
        question = " ".join(sys.argv[1:])
        print(f"\n❓ {question}\n")
        answer = run_agent(question)
        print(f"\n💬 {answer}\n")
        return

    print("🤖 Агент готов. Задавай вопросы про отзывы (exit для выхода)\n")
    while True:
        try:
            question = input("❓ Вопрос: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not question:
            continue
        if question.lower() in ("exit", "quit", "выход", "q"):
            break
        answer = run_agent(question)
        print(f"\n💬 {answer}\n")


if __name__ == "__main__":
    main()

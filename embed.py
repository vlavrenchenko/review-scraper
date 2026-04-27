import argparse
import os
import sqlite3
import time
from pathlib import Path

import chromadb
from dotenv import load_dotenv
from openai import OpenAI

from logger import get_logger

load_dotenv(override=True)

log = get_logger("embed")

DB_PATH = Path(__file__).parent / "data" / "reviews.db"
CHROMA_PATH = Path(__file__).parent / "data" / "chroma"
COLLECTION_NAME = "reviews"
EMBED_MODEL = "text-embedding-3-small"
BATCH_SIZE = 100


def get_chroma_collection() -> chromadb.Collection:
    client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


def get_embedded_ids(collection: chromadb.Collection) -> set:
    result = collection.get(include=[])
    return set(result["ids"])


def fetch_reviews_to_embed(conn: sqlite3.Connection, embedded_ids: set) -> list[dict]:
    rows = conn.execute(
        "SELECT id, company, title, text, rating, published_date FROM reviews"
    ).fetchall()
    return [
        {
            "id": r[0],
            "company": r[1],
            "title": r[2] or "",
            "text": r[3] or "",
            "rating": r[4],
            "published_date": r[5] or "",
        }
        for r in rows
        if r[0] not in embedded_ids
    ]


def make_document(review: dict) -> str:
    return f"{review['title']}. {review['text']}".strip()


def embed_batch(client: OpenAI, texts: list[str]) -> list[list[float]]:
    response = client.embeddings.create(model=EMBED_MODEL, input=texts)
    return [item.embedding for item in response.data]


def run(force: bool = False):
    assert os.environ.get("OPENAI_API_KEY"), "Задайте OPENAI_API_KEY в .env файле"

    collection = get_chroma_collection()
    embedded_ids = set() if force else get_embedded_ids(collection)

    conn = sqlite3.connect(DB_PATH)
    reviews = fetch_reviews_to_embed(conn, embedded_ids)
    conn.close()

    if not reviews:
        print("✅ Все отзывы уже проиндексированы.")
        log.info("embed_done", extra={"new": 0, "total": len(embedded_ids)})
        return 0

    print(f"📥 Новых отзывов для индексации: {len(reviews)}")
    log.info("embed_start", extra={"new": len(reviews), "force": force})
    t0 = time.monotonic()

    client = OpenAI()
    total = 0
    batches = [reviews[i:i + BATCH_SIZE] for i in range(0, len(reviews), BATCH_SIZE)]

    for idx, batch in enumerate(batches, 1):
        print(f"  батч {idx}/{len(batches)} ({len(batch)} отзывов)...")
        texts = [make_document(r) for r in batch]
        embeddings = embed_batch(client, texts)
        collection.add(
            ids=[r["id"] for r in batch],
            embeddings=embeddings,
            documents=texts,
            metadatas=[{
                "company": r["company"],
                "rating": r["rating"],
                "published_date": r["published_date"],
                "title": r["title"],
            } for r in batch],
        )
        total += len(batch)

    elapsed = round(time.monotonic() - t0, 2)
    print(f"✅ Проиндексировано {total} отзывов за {elapsed}с")
    log.info("embed_done", extra={"new": total, "duration_sec": elapsed})
    return total


def main():
    parser = argparse.ArgumentParser(description="Генерация эмбеддингов для ChromaDB")
    parser.add_argument("--force", action="store_true",
                        help="Переиндексировать все отзывы, игнорируя существующие")
    args = parser.parse_args()
    run(force=args.force)


if __name__ == "__main__":
    main()

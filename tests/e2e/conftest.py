import logging
import os
import shutil
import sqlite3
import pytest
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent.parent

load_dotenv(override=True)

# Логи e2e тестов идут в отдельный файл, не засоряя logs/agent.log
_e2e_log = PROJECT_ROOT / "logs" / "e2e.log"
_e2e_log.parent.mkdir(exist_ok=True)
logging.getLogger().addHandler(logging.FileHandler(_e2e_log))


@pytest.fixture(scope="session")
def require_openai():
    if not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY не задан")


@pytest.fixture(scope="session")
def require_sheets():
    creds = PROJECT_ROOT / "config" / "google_credentials.json"
    cfg = PROJECT_ROOT / "config" / "sheets_config.json"
    if not creds.exists() or not cfg.exists():
        pytest.skip("Google credentials не найдены")


@pytest.fixture(scope="session")
def real_db():
    """Read-only копия основной БД для e2e тестов."""
    src = PROJECT_ROOT / "data" / "reviews.db"
    if not src.exists():
        pytest.skip("reviews.db не найден")
    dst = PROJECT_ROOT / "data" / "reviews_e2e_copy.db"
    shutil.copy2(src, dst)
    yield dst
    dst.unlink(missing_ok=True)


@pytest.fixture(scope="session")
def db_has_data(real_db):
    """Пропускает тест если в БД нет отзывов."""
    conn = sqlite3.connect(real_db)
    count = conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]
    conn.close()
    if count == 0:
        pytest.skip("reviews.db пуста")
    return real_db

"""
Ortak test altyapisi.
  - eyotek_agent/ dizinini sys.path'a ekler (modul import'lari icin)
  - Canli DB testleri icin 'db' marker + SKIP_DB env skip
  - fast_responses._pool her testte sifirla (async event loop bagimsizligi)
Not: Windows cp1254 emoji icin PYTHONIOENCODING=utf-8 env ile calistir:
  set PYTHONIOENCODING=utf-8 && pytest
"""
import os
import sys
import pytest
from pathlib import Path

# eyotek_agent/ dizinini path'a ekle
EYOTEK_DIR = Path(__file__).resolve().parent.parent
if str(EYOTEK_DIR) not in sys.path:
    sys.path.insert(0, str(EYOTEK_DIR))


def pytest_collection_modifyitems(config, items):
    """SKIP_DB=1 olduğunda db marker'li testleri atla."""
    if os.getenv("SKIP_DB") == "1":
        skip_db = pytest.mark.skip(reason="SKIP_DB=1 set")
        for item in items:
            if "db" in item.keywords:
                item.add_marker(skip_db)


@pytest.fixture(autouse=True)
async def _reset_db_pool():
    """
    pytest-asyncio her test icin yeni event loop acar.
    db_pool._pool eski loop'a bagli kalir -> InterfaceError.
    Her testte merkezi pool'u sifirla, taze bir tane olussun.
    (Oturum 21: fast_responses, analytics_cache, rag_engine vb. hepsi db_pool kullaniyor)
    """
    import db_pool as _dp
    if getattr(_dp, "_pool", None) is not None:
        try:
            await _dp._pool.close()
        except Exception:
            pass
        _dp._pool = None
    yield
    if getattr(_dp, "_pool", None) is not None:
        try:
            await _dp._pool.close()
        except Exception:
            pass
        _dp._pool = None

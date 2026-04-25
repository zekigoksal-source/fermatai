"""pytest fixtures (Oturum 25.9 - T4)"""
import os, sys, pytest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    monkeypatch.setenv("ENABLE_GROQ_TOOLS", "false")
    monkeypatch.setenv("JSON_LOGGING", "false")
    yield

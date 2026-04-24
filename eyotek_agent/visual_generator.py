"""
Visual Generator — Matplotlib + Mermaid (23 Nisan)
=====================================================
Konu anlatımında görsel üretim: grafik (matematik/fizik) ve
diagram (biyoloji/kimya/tarih şema).
"""
from __future__ import annotations
import os
import re
import hashlib
from datetime import datetime
from loguru import logger

VISUAL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "visuals")
os.makedirs(VISUAL_DIR, exist_ok=True)


def _safe_filename(prefix: str, content: str) -> str:
    h = hashlib.md5(content.encode()).hexdigest()[:8]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{prefix}_{ts}_{h}.png"


async def plot_function(
    expr: str,
    x_range: tuple = (-10, 10),
    points: int = 200,
    title: str = "",
    label: str = "",
) -> str | None:
    """Matematik fonksiyon grafiği (türev, integral, parabolik vb.).

    expr: "x**2 + 3*x - 5" tarzı Python expression (eval güvenli değil!
    sadece güvenilir iç kaynaktan çağrılmalı, user input DEGIL.)
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np

        x = np.linspace(x_range[0], x_range[1], points)
        # GÜVENLİK: sadece güvenilir sayısal ifadeler
        safe_expr = re.sub(r'[^\d\w\s\+\-\*\/\(\)\.\,\*\*]', '', expr)
        if any(kw in safe_expr.lower() for kw in ["import", "eval", "exec", "open", "__"]):
            return None
        # numpy namespace
        allowed = {
            "x": x, "np": np,
            "sin": np.sin, "cos": np.cos, "tan": np.tan,
            "exp": np.exp, "log": np.log, "sqrt": np.sqrt,
            "pi": np.pi, "e": np.e, "abs": np.abs,
        }
        y = eval(safe_expr, {"__builtins__": {}}, allowed)

        fig, ax = plt.subplots(figsize=(8, 5), dpi=100)
        ax.plot(x, y, linewidth=2, color="#3d5afe", label=label or expr)
        ax.axhline(y=0, color="gray", linewidth=0.5)
        ax.axvline(x=0, color="gray", linewidth=0.5)
        ax.grid(alpha=0.3)
        ax.set_xlabel("x")
        ax.set_ylabel("y")
        ax.legend(loc="best")
        if title:
            ax.set_title(title, fontsize=12, pad=10)
        fig.tight_layout()

        filename = _safe_filename("plot", expr)
        path = os.path.join(VISUAL_DIR, filename)
        fig.savefig(path, bbox_inches="tight", facecolor="white")
        plt.close(fig)
        return path
    except Exception as e:
        logger.debug(f"plot_function: {e}")
        return None


async def mermaid_diagram(mermaid_code: str, title: str = "") -> str:
    """Mermaid.js diagram text olarak döner (client render eder).

    Returns: mermaid code (markdown ```mermaid ... ``` block)
    """
    return f"```mermaid\n{mermaid_code}\n```"


def suggest_visual(soru: str) -> dict | None:
    """Soruya uygun görsel tipini öner (plot vs diagram)."""
    msg = soru.lower()
    # Matematik/fizik → plot
    if re.search(r"\b(turev|türev|integral|limit|parabol|fonksiyon|grafik|sinus|cosinus|çiz)\b", msg):
        return {"tip": "plot", "sebep": "matematik fonksiyon grafiği"}
    # Biyoloji/kimya/tarih → diagram
    if re.search(r"\b(besin\s*zincir|ekosistem|dongu|döngü|reaksiyon|sureç|süreç|hiyerarşi|akis|akış|moleku|molekü)\b", msg):
        return {"tip": "mermaid", "sebep": "süreç/şema diagram"}
    return None


async def biology_flowchart(konu: str) -> str | None:
    """Biyoloji için hazır flowchart şablonları."""
    templates = {
        "fotosentez": """graph LR
    A[Güneş Işığı ☀️] --> B[Yapraktaki Klorofil]
    C[CO₂ Hava] --> B
    D[Su H₂O Kök] --> B
    B --> E[Glikoz C₆H₁₂O₆]
    B --> F[Oksijen O₂]
    E --> G[Bitki Beslenmesi]
    F --> H[Atmosfer]""",
        "solunum": """graph LR
    A[Glikoz C₆H₁₂O₆] --> B[Hücre Mitokondri]
    C[Oksijen O₂] --> B
    B --> D[Enerji ATP]
    B --> E[CO₂ Dışarı]
    B --> F[Su H₂O Dışarı]""",
        "besin zinciri": """graph LR
    A[Güneş] --> B[Üreticiler 🌿]
    B --> C[Otçullar 🐄]
    C --> D[Etçiller 🦁]
    D --> E[Ayrıştırıcılar 🦠]
    E --> B""",
    }
    k = konu.lower()
    for key, code in templates.items():
        if key in k:
            return await mermaid_diagram(code, title=konu.title())
    return None

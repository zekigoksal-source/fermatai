"""
F3 — TTS Sesli Yanıt (Oturum 25.28)
==============================================

Bot çıktısını ses dosyasına çevirir.
- Web chat: HTML5 audio player'da inline çalsın (WP'sız)
- WP: TTS_WP_ACTIVE=true ise ses dosyası gönderilir (Neo onayıyla, yeni sezon)

Provider: OpenAI TTS (tts-1, ~$0.015/dakika).
Cache: tts_audio_cache tablosunda hash bazlı (aynı metin tekrar üretilmesin).

ŞU AN: WP_ACTIVE=False — sadece web chat'te + admin test endpoint'inde kullanılabilir.
"""
from __future__ import annotations
import asyncio
import hashlib
import os
from datetime import datetime
from pathlib import Path
from typing import Optional
from loguru import logger


# Ses dosyaları için lokal dizin (VPS: /opt/fermatai/static/tts/)
_TTS_DIR = Path(os.getenv("TTS_DIR") or "static/tts")
_TTS_DIR.mkdir(parents=True, exist_ok=True)

# Voice secimi (OpenAI TTS-1)
_DEFAULT_VOICE = os.getenv("TTS_VOICE", "nova")  # alloy/echo/fable/onyx/nova/shimmer
_DEFAULT_MODEL = os.getenv("TTS_MODEL", "tts-1")  # tts-1 | tts-1-hd
_MAX_CHARS = 1500   # OpenAI limit 4096 ama kısa tutmak iyi (latency + cost)


def _hash_text(text: str, voice: str, model: str) -> str:
    """Cache key — aynı metin/ses/model kombosu için."""
    s = f"{model}|{voice}|{text}"
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:32]


async def is_wp_active() -> bool:
    try:
        from db_pool import db_fetchval
        v = await db_fetchval(
            "SELECT value FROM sistem_ayar WHERE key='TTS_WP_ACTIVE'"
        )
        return (v or "").lower() == "true"
    except Exception:
        return False


async def get_cached_audio(text_hash: str) -> Optional[dict]:
    """tts_audio_cache'ten kayıt al, last_used_at güncelle."""
    from db_pool import db_fetchrow, db_execute
    row = await db_fetchrow(
        "SELECT * FROM tts_audio_cache WHERE text_hash = $1",
        text_hash
    )
    if row:
        await db_execute(
            "UPDATE tts_audio_cache SET last_used_at=NOW(), use_count=use_count+1 WHERE id=$1",
            row["id"]
        )
        return dict(row)
    return None


async def synthesize_speech(text: str,
                              voice: str = None,
                              model: str = None,
                              cache: bool = True) -> Optional[dict]:
    """Metni sese çevir. Cache hit varsa eski dosyayı döner.

    Returns: {audio_url, audio_path, duration_ms, size_bytes, cached: bool}
            None — başarısızlık.
    """
    voice = voice or _DEFAULT_VOICE
    model = model or _DEFAULT_MODEL
    text = text.strip()
    if not text:
        return None
    if len(text) > _MAX_CHARS:
        text = text[:_MAX_CHARS] + "..."

    text_hash = _hash_text(text, voice, model)

    # Cache kontrol
    if cache:
        cached = await get_cached_audio(text_hash)
        if cached and cached.get("audio_path") and Path(cached["audio_path"]).exists():
            return {
                "audio_url": cached["audio_url"],
                "audio_path": cached["audio_path"],
                "duration_ms": cached.get("duration_ms"),
                "size_bytes": cached.get("size_bytes"),
                "cached": True,
            }

    # OpenAI TTS API çağrısı
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.warning("[TTS] OPENAI_API_KEY yok")
        return None

    file_path = _TTS_DIR / f"{text_hash}.mp3"
    audio_bytes = b""
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=api_key)

        # Streaming response API ile MP3 al
        async with client.audio.speech.with_streaming_response.create(
            model=model,
            voice=voice,
            input=text,
            response_format="mp3",
        ) as response:
            await response.stream_to_file(file_path)
        audio_bytes = file_path.read_bytes()
    except Exception as e:
        logger.error(f"[TTS] OpenAI API/dosya fail: {e}")
        return None

    audio_url = f"/static/tts/{text_hash}.mp3"
    size_bytes = len(audio_bytes)
    # Approx duration (mp3 bitrate ~128kbps for tts-1)
    duration_ms = int((size_bytes / (128 * 1024 / 8)) * 1000)

    # Cache'e yaz
    if cache:
        try:
            from db_pool import db_execute
            await db_execute(
                """INSERT INTO tts_audio_cache
                   (text_hash, text_preview, voice_model, voice_id,
                    audio_url, audio_path, duration_ms, size_bytes)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                   ON CONFLICT (text_hash) DO UPDATE SET last_used_at=NOW(),
                       use_count=tts_audio_cache.use_count+1""",
                text_hash, text[:200], model, voice,
                audio_url, str(file_path), duration_ms, size_bytes
            )
        except Exception as e:
            logger.debug(f"[TTS] cache write fail: {e}")

    return {
        "audio_url": audio_url,
        "audio_path": str(file_path),
        "duration_ms": duration_ms,
        "size_bytes": size_bytes,
        "cached": False,
    }


async def cleanup_old_cache(days: int = 30) -> int:
    """Eskiyen ses dosyalarını sil — disk doldurmasın."""
    from db_pool import db_fetch, db_execute
    rows = await db_fetch(
        "SELECT id, audio_path FROM tts_audio_cache "
        "WHERE last_used_at < NOW() - ($1 || ' days')::interval",
        str(days)
    )
    deleted = 0
    for r in rows:
        try:
            p = Path(r["audio_path"])
            if p.exists():
                p.unlink()
        except Exception:
            pass
        await db_execute("DELETE FROM tts_audio_cache WHERE id=$1", r["id"])
        deleted += 1
    return deleted


# ─── CLI ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    async def _main():
        if len(sys.argv) > 1 and sys.argv[1] == "test":
            text = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else \
                "Merhaba, ben Fermat. Sesli yanıt sistemi test edildi."
            r = await synthesize_speech(text)
            if r:
                print(f"audio_url: {r['audio_url']}")
                print(f"audio_path: {r['audio_path']}")
                print(f"size: {r['size_bytes']} bytes, duration: {r['duration_ms']} ms")
                print(f"cached: {r['cached']}")
            else:
                print("FAIL")
        elif len(sys.argv) > 1 and sys.argv[1] == "cleanup":
            days = int(sys.argv[2]) if len(sys.argv) > 2 else 30
            n = await cleanup_old_cache(days)
            print(f"deleted {n} old files")
        else:
            print("Kullanim: python tts_handler.py [test <text>|cleanup [days]]")
    asyncio.run(_main())

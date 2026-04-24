"""
PostgreSQL Otomatik Yedek Sistemi (Oturum 22.1d — ASAP)
========================================================

Docker exec ile fermat_postgres container icinde pg_dump calistirir.
Yedekleri C:\\Users\\zekig\\OneDrive\\Desktop\\FermatAI\\backups\\ altinda saklar.
Eski yedekleri 30 gun sonra siler.

Kullanim:
    python db_backup.py              # tek seferlik backup
    python db_backup.py --cleanup    # sadece eski yedekleri sil
    python db_backup.py --list       # son 10 yedegi listele

Cron/Scheduled Task:
    python db_backup.py  # gunluk 03:00
"""
import asyncio
import os
import sys
import io
import subprocess
import argparse
from datetime import datetime, timedelta
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# Ayarlar — platform-bagimsiz path (Oturum 25 D1 fix)
# Laptop: C:\...\FermatAI\backups | VPS: /opt/fermatai/backups
# Override: FERMAT_BACKUP_DIR env
BACKUP_DIR = Path(
    os.getenv("FERMAT_BACKUP_DIR")
    or (Path(__file__).resolve().parent.parent / "backups")
)
CONTAINER_NAME = "fermat_postgres"
DB_NAME = "fermatai"
DB_USER = "fermat"
RETENTION_DAYS = 30


def run_backup() -> Path | None:
    """Docker exec ile pg_dump, cikti BACKUP_DIR'a yazilir."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    out_file = BACKUP_DIR / f"fermatai_{ts}.sql"

    print(f"🔄 Backup baslatiliyor: {out_file.name}")

    try:
        # Docker exec ile pg_dump — cikti stdout uzerinden al
        cmd = [
            "docker", "exec", CONTAINER_NAME,
            "pg_dump", "-U", DB_USER, "-d", DB_NAME,
            "--no-owner", "--no-acl",
        ]
        with out_file.open("wb") as f:
            result = subprocess.run(cmd, stdout=f, stderr=subprocess.PIPE, timeout=600)

        if result.returncode != 0:
            err = result.stderr.decode("utf-8", errors="replace")
            print(f"❌ pg_dump hata (rc={result.returncode}): {err[:300]}")
            # Basarisiz dosyayi sil
            if out_file.exists():
                out_file.unlink()
            return None

        size_mb = out_file.stat().st_size / (1024 * 1024)
        print(f"✅ Backup tamam: {out_file.name} ({size_mb:.1f} MB)")
        return out_file
    except subprocess.TimeoutExpired:
        print("❌ Backup timeout (10dk asildi)")
        return None
    except FileNotFoundError:
        print("❌ 'docker' komutu bulunamadi. Docker Desktop calisiyor mu?")
        return None
    except Exception as e:
        print(f"❌ Backup hata: {e}")
        return None


def cleanup_old_backups(retention_days: int = RETENTION_DAYS) -> int:
    """RETENTION_DAYS'dan eski .sql dosyalarini sil."""
    if not BACKUP_DIR.exists():
        return 0

    cutoff = datetime.now() - timedelta(days=retention_days)
    removed = 0
    for f in BACKUP_DIR.glob("fermatai_*.sql"):
        try:
            mtime = datetime.fromtimestamp(f.stat().st_mtime)
            if mtime < cutoff:
                print(f"🗑️  Siliniyor: {f.name} ({(datetime.now()-mtime).days} gun eski)")
                f.unlink()
                removed += 1
        except Exception as e:
            print(f"⚠️  Sil hatasi {f.name}: {e}")

    if removed == 0:
        print(f"♻️  {retention_days} gunden eski yedek yok (temiz)")
    else:
        print(f"♻️  {removed} eski yedek silindi")
    return removed


def list_backups(limit: int = 10):
    """Son N yedegi listele (tarih sirasina gore)."""
    if not BACKUP_DIR.exists():
        print(f"❌ Backup dizini yok: {BACKUP_DIR}")
        return

    backups = sorted(
        BACKUP_DIR.glob("fermatai_*.sql"),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )

    if not backups:
        print("📭 Yedek bulunamadi")
        return

    print(f"📁 Son {min(limit, len(backups))} yedek (toplam: {len(backups)}):")
    total_mb = 0
    for i, f in enumerate(backups[:limit], 1):
        mb = f.stat().st_size / (1024 * 1024)
        total_mb += mb
        mtime = datetime.fromtimestamp(f.stat().st_mtime).strftime("%d.%m.%Y %H:%M")
        print(f"  {i:2d}. {f.name}  {mb:>7.1f} MB  {mtime}")
    print(f"\n📊 Toplam (tum yedekler): {sum(b.stat().st_size for b in backups)/(1024*1024):.1f} MB")


def verify_latest_backup() -> bool:
    """Son backup dosyasini hizli kontrol — sema + COPY/INSERT + kritik tablo."""
    if not BACKUP_DIR.exists():
        return False
    latest = max(BACKUP_DIR.glob("fermatai_*.sql"),
                 key=lambda f: f.stat().st_mtime, default=None)
    if not latest:
        return False
    # Dosyayi chunk chunk oku, marker ara (buyuk dosyada etkin)
    has_create = False
    has_data = False
    has_students = False
    with latest.open("rb") as f:
        while chunk := f.read(256 * 1024):  # 256KB chunk
            text = chunk.decode("utf-8", errors="replace")
            if not has_create and "CREATE TABLE" in text:
                has_create = True
            if not has_data and ("COPY " in text or "INSERT INTO" in text):
                has_data = True
            if not has_students and ("COPY fermat.students" in text or "COPY public.students" in text):
                has_students = True
            if has_create and has_data and has_students:
                break

    size_mb = latest.stat().st_size / (1024 * 1024)
    print(f"🔍 Son yedek dogrulama: {latest.name} ({size_mb:.1f} MB)")
    print(f"   CREATE TABLE: {'✅' if has_create else '❌'}")
    print(f"   COPY/INSERT:  {'✅' if has_data else '❌'}")
    print(f"   students data: {'✅' if has_students else '❌'}")
    return has_create and has_data and has_students


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cleanup", action="store_true", help="Sadece eski yedekleri sil")
    parser.add_argument("--list", action="store_true", help="Yedekleri listele")
    parser.add_argument("--verify", action="store_true", help="Son yedegi dogrula")
    parser.add_argument("--retention", type=int, default=RETENTION_DAYS)
    args = parser.parse_args()

    if args.list:
        list_backups()
        return
    if args.verify:
        verify_latest_backup()
        return
    if args.cleanup:
        cleanup_old_backups(args.retention)
        return

    # Default: backup + cleanup + verify
    print("=" * 60)
    print(f"📦 FermatAI DB Backup — {datetime.now().strftime('%d.%m.%Y %H:%M')}")
    print("=" * 60)

    backup_file = run_backup()
    if backup_file:
        cleanup_old_backups(args.retention)
        verify_latest_backup()
        print("\n✅ Backup akisi tamamlandi")
        sys.exit(0)
    else:
        print("\n❌ Backup basarisiz — admin bildirim gerekli")
        sys.exit(1)


if __name__ == "__main__":
    main()

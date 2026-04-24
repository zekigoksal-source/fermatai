"""
FermatAI — Neo Kontrol Merkezi v2.0

Tek dosya ile tum sistemi baslat + admin paneli.
Matrix tarzı terminal arayuz: dashboard + chat + sistem yonetimi.
"""
import asyncio
import subprocess
import sys
import os
import json
import time
import signal
from pathlib import Path
from datetime import datetime, date, timedelta

# Proje dizini
PROJECT_DIR = Path(__file__).parent
os.chdir(PROJECT_DIR)

# .env yukle
try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
except ImportError:
    pass

# Log — sadece dosyaya, terminale temiz cikti
import logging
logging.getLogger().setLevel(logging.WARNING)
try:
    from loguru import logger as _loguru
    _loguru.remove()
    _loguru.add(
        str(PROJECT_DIR / "logs" / "fermat_{time:YYYY-MM-DD}.log"),
        level="DEBUG", rotation="1 day", retention="7 days",
    )
except Exception:
    pass

# ── Renkli terminal (Windows ANSI) ──────────────────────────────────────────
os.system("")

G  = "\033[92m"   # Green
R  = "\033[91m"   # Red
Y  = "\033[93m"   # Yellow
C  = "\033[96m"   # Cyan
M  = "\033[95m"   # Magenta
B  = "\033[1m"    # Bold
D  = "\033[2m"    # Dim
X  = "\033[0m"    # Reset
BG = "\033[40m"   # Black bg

from db_pool import DB_URL as DB_DSN, get_pool as _get_pool


def clear():
    os.system("cls" if os.name == "nt" else "clear")


def _bar(val, max_val=100, width=15):
    """Mini progress bar olustur."""
    filled = int(width * val / max_val) if max_val > 0 else 0
    filled = min(filled, width)
    bar = "#" * filled + "-" * (width - filled)
    return f"[{bar}]"


def banner():
    print(f"""
{G}
     ___________                            __     _____  .___
     \\_   _____/___________  _____ _____ _/  |_  /  _  \\ |   |
      |    __)/ __ \\_  __ \\/     \\\\__  \\\\   __\\/  /_\\  \\|   |
      |     \\  ___/|  | \\/  Y Y  \\/ __ \\|  | /    |    \\   |
      \\___  / \\___  >__|  |__|_|  (____  /__| \\____|__  /___|
          \\/      \\/            \\/     \\/              \\/
{C}
      N E O   K O N T R O L   M E R K E Z I   v 2 . 0
      {D}Otonom Egitim Ekosistemi | Fermat Egitim Kurumlari{X}
""")


# ═══════════════════════════════════════════════════════════════════════════════
# SISTEM DURUMU
# ═══════════════════════════════════════════════════════════════════════════════

async def get_system_status() -> dict:
    """Tum servislerin durumunu kontrol et."""
    import httpx
    status = {}

    # PostgreSQL (Oturum 23 audit: db_pool helper'ı kullan)
    try:
        from db_pool import db_fetchval
        status["db"] = True
        status["db_ogrenci"] = await db_fetchval("SELECT COUNT(*) FROM students") or 0
        status["db_personel"] = await db_fetchval("SELECT COUNT(*) FROM staff") or 0
        status["db_etut"] = await db_fetchval("SELECT COUNT(*) FROM etut_history") or 0
        status["db_konusma"] = await db_fetchval("SELECT COUNT(*) FROM agent_conversations") or 0
    except Exception:
        status["db"] = False

    # WP Bridge
    try:
        async with httpx.AsyncClient(timeout=3) as c:
            r = await c.get("http://localhost:8001/health")
            d = r.json()
            status["bridge"] = d.get("status") == "ok"
            status["bridge_sessions"] = d.get("active_sessions", 0)
    except Exception:
        status["bridge"] = False

    # ngrok
    try:
        async with httpx.AsyncClient(timeout=3) as c:
            r = await c.get("http://localhost:4040/api/tunnels")
            tunnels = r.json().get("tunnels", [])
            status["ngrok"] = len(tunnels) > 0
            status["ngrok_url"] = tunnels[0]["public_url"] if tunnels else "?"
    except Exception:
        status["ngrok"] = False

    # Ollama
    try:
        async with httpx.AsyncClient(timeout=3) as c:
            r = await c.get("http://localhost:11434/api/tags")
            status["ollama"] = r.status_code == 200
    except Exception:
        status["ollama"] = False

    # Chrome CDP
    try:
        async with httpx.AsyncClient(timeout=3) as c:
            r = await c.get("http://localhost:9222/json/version")
            status["cdp"] = r.status_code == 200
    except Exception:
        status["cdp"] = False

    return status


async def get_usage_today() -> dict:
    """Bugunun kullanim istatistikleri — agent_conversations + usage_log birlikte."""
    try:
        # Oturum 23 audit: db_pool helper'ı
        from db_pool import db_fetchrow, db_fetchval

        # usage_log'dan kaynak bazlı
        row = await db_fetchrow("""
            SELECT COUNT(*) as msg, COUNT(DISTINCT phone) as users,
                COUNT(*) FILTER (WHERE response_source='fast_response') as fast,
                COUNT(*) FILTER (WHERE response_source='claude') as claude,
                COUNT(*) FILTER (WHERE response_source='ollama') as ollama,
                COUNT(*) FILTER (WHERE response_source='groq') as groq,
                COALESCE(AVG(response_ms) FILTER (WHERE response_ms>0),0)::int as avg_ms
            FROM usage_log WHERE created_at::date = CURRENT_DATE
        """)
        result = dict(row) if row else {}

        # Eğer usage_log boşsa agent_conversations'dan say
        if result.get('msg', 0) == 0:
            row2 = await db_fetchrow("""
                SELECT COUNT(*) FILTER (WHERE message_role='user') as msg,
                       COUNT(DISTINCT phone) as users
                FROM agent_conversations WHERE created_at::date = CURRENT_DATE
            """)
            if row2:
                result['msg'] = row2['msg'] or 0
                result['users'] = row2['users'] or 0

        # Toplam konuşma sayısı (tüm zamanlar)
        result['total_conversations'] = await db_fetchval(
            "SELECT COUNT(*) FROM agent_conversations") or 0

        # Lead sayısı
        try:
            result['leads'] = await db_fetchval(
                "SELECT COUNT(DISTINCT phone) FROM lead_contacts") or 0
        except Exception:
            result['leads'] = 0

        return result
    except Exception:
        return {}


def get_hw_info() -> dict:
    """CPU, RAM, GPU, Disk — anlık donanım bilgileri."""
    info = {}
    try:
        import psutil
        # CPU
        info["cpu"] = psutil.cpu_percent(interval=1)
        freq = psutil.cpu_freq()
        info["cpu_freq"] = f"{freq.current:.0f}" if freq else "?"
        info["cpu_cores"] = f"{psutil.cpu_count(logical=False)}C/{psutil.cpu_count()}T"

        # RAM
        mem = psutil.virtual_memory()
        info["ram"] = mem.percent
        info["ram_used"] = round(mem.used / (1024**3), 1)
        info["ram_total"] = round(mem.total / (1024**3), 1)

        # Disk
        disk = psutil.disk_usage('C:/')
        info["disk"] = disk.percent
        info["disk_used"] = round(disk.used / (1024**3), 0)
        info["disk_total"] = round(disk.total / (1024**3), 0)

        # Uptime
        import time as _t
        boot = psutil.boot_time()
        uptime_sec = _t.time() - boot
        hours = int(uptime_sec // 3600)
        mins = int((uptime_sec % 3600) // 60)
        info["uptime"] = f"{hours}s {mins}dk"

    except ImportError:
        info["cpu"] = "?"
        info["ram"] = "?"

    # GPU — nvidia-smi
    try:
        import subprocess
        r = subprocess.run(
            ['nvidia-smi', '--query-gpu=temperature.gpu,utilization.gpu,memory.used,memory.total,power.draw',
             '--format=csv,noheader,nounits'],
            capture_output=True, text=True, timeout=3)
        if r.returncode == 0:
            parts = r.stdout.strip().split(', ')
            info["gpu_temp"] = parts[0].strip()
            info["gpu_util"] = parts[1].strip()
            info["gpu_vram_used"] = round(int(parts[2].strip()) / 1024, 1)
            info["gpu_vram_total"] = round(int(parts[3].strip()) / 1024, 1)
            info["gpu_power"] = parts[4].strip()
    except Exception:
        pass

    return info


async def show_dashboard():
    """Ana dashboard — sistem durumu + kullanim + hardware."""
    s = await get_system_status()
    u = await get_usage_today()
    hw = get_hw_info()

    def st(ok): return f"{G}ONLINE{X}" if ok else f"{R}OFFLINE{X}"

    msg = u.get('msg', 0)
    users = u.get('users', 0)
    fast = u.get('fast', 0)
    claude = u.get('claude', 0)
    ollama = u.get('ollama', 0)
    total = fast + claude + ollama or 1
    fast_pct = round(fast / total * 100)

    leads = u.get('leads', 0)
    total_conv = u.get('total_conversations', 0)

    cpu_v = hw.get('cpu', 0)
    ram_v = hw.get('ram', 0)
    gpu_v = int(hw.get('gpu_util', 0) or 0)
    disk_v = hw.get('disk', 0)

    try:
        cpu_v = float(cpu_v)
        ram_v = float(ram_v)
        disk_v = float(disk_v)
    except (ValueError, TypeError):
        cpu_v = ram_v = disk_v = 0

    # Servis durumları (renksiz text + renk ayrı)
    def _st(ok):
        return (f"{G}ONLINE {X}", "ONLINE ") if ok else (f"{R}OFFLINE{X}", "OFFLINE")

    db_c, db_t = _st(s.get('db'))
    br_c, br_t = _st(s.get('bridge'))
    ng_c, ng_t = _st(s.get('ngrok'))
    ol_c, ol_t = _st(s.get('ollama'))
    cd_c, cd_t = _st(s.get('cdp'))
    model_name = os.getenv('OLLAMA_MODEL', 'llama3')

    print(f"""
{C}{B}  SISTEM DURUMU{X}
  {"="*55}
  PostgreSQL   {db_c}  {s.get('db_ogrenci','?')} ogrenci, {s.get('db_personel','?')} personel
  WP Bridge    {br_c}  session: {s.get('bridge_sessions',0)}
  ngrok        {ng_c}  sabit domain
  Ollama       {ol_c}  {model_name}
  Chrome CDP   {cd_c}  Eyotek
  {"="*55}

{Y}{B}  BUGUNUN KULLANIMI{X}
  {"-"*55}
  Mesaj        {C}{msg}{X} ({users} kullanici)
  Fast         {G}{fast}{X} (%{fast_pct}) {_bar(fast_pct)}
  Ollama       {C}{ollama}{X}
  Claude       {Y}{claude}{X}
  Ort. Yanit   {u.get('avg_ms', 0)}ms
  Lead         {M}{leads}{X} potansiyel
  {"-"*55}

{M}{B}  DONANIM{X}
  {"-"*55}
  CPU  {C}{cpu_v:5.1f}%{X} {_bar(cpu_v)} {hw.get('cpu_freq','?')}MHz {hw.get('cpu_cores','?')}
  RAM  {C}{ram_v:5.1f}%{X} {_bar(ram_v)} {hw.get('ram_used','?')}/{hw.get('ram_total','?')}GB
  GPU  {G}{gpu_v:5d}%{X} {_bar(gpu_v)} {hw.get('gpu_temp','?')}C {hw.get('gpu_vram_used','?')}/{hw.get('gpu_vram_total','?')}GB
  Disk {disk_v:5.1f}% {_bar(disk_v)} {int(hw.get('disk_used',0))}/{int(hw.get('disk_total',0))}GB
  Up   {hw.get('uptime','?')}
  {"-"*55}
  {D}DB: {s.get('db_etut',0)} etut | {total_conv} konusma | {datetime.now().strftime('%d.%m.%Y %H:%M')}{X}
""")


def show_menu():
    """Komut menusu."""
    print(f"""
{C}{B}  KOMUTLAR{X}
  {"="*55}
  {G}Dogrudan yazin{X} > Agent ile sohbet (admin yetkisi)
  {D}ornek: "Ali Kucukuysal akademik durumu nasil"{X}

  {C}durum{X}    sistem durumu      {C}log{X}      WP loglar
  {C}yenile{X}   restart            {C}analiz{X}   AI rapor
  {C}token{X}    WA token           {C}sql ..{X}   DB sorgu
  {C}temizle{X}  ekrani yenile      {C}cikis{X}    kapat
  {"="*55}
""")


# ═══════════════════════════════════════════════════════════════════════════════
# SERVIS YONETIMI
# ═══════════════════════════════════════════════════════════════════════════════

wp_proc = None

def start_ollama():
    """Ollama baslat + model warmup."""
    import subprocess as sp
    # Zaten calisiyor mu?
    result = sp.run(["netstat", "-ano"], capture_output=True, text=True)
    if ":11434" in result.stdout and "LISTEN" in result.stdout:
        print(f"  {G}Ollama zaten calisiyor{X}")
        return True
    print(f"  {Y}Ollama baslatiliyor...{X}")
    si = sp.STARTUPINFO()
    si.dwFlags |= sp.STARTF_USESHOWWINDOW
    si.wShowWindow = 0  # SW_HIDE — pencere acilir ama gorunmez
    sp.Popen(
        [r"C:\Users\zekig\AppData\Local\Programs\Ollama\ollama.exe", "serve"],
        stdout=sp.DEVNULL, stderr=sp.DEVNULL,
        startupinfo=si,
        creationflags=0x00000010,  # CREATE_NEW_CONSOLE (gerekli) ama SW_HIDE ile gorunmez
    )
    # Port acilana kadar bekle (max 15s)
    import socket
    for i in range(15):
        time.sleep(1)
        try:
            s = socket.create_connection(("127.0.0.1", 11434), timeout=1)
            s.close()
            break
        except Exception:
            pass
    # Model warmup — arka planda (ilk load 60-90s surebilir, kullaniciyi bekletme)
    import threading
    def _warmup():
        try:
            import httpx
            httpx.post("http://localhost:11434/api/chat", json={
                "model": os.getenv("OLLAMA_MODEL", "qwen2.5:7b"),
                "messages": [{"role": "user", "content": "test"}],
                "stream": False,
                "options": {"num_predict": 3},
            }, timeout=120)
        except Exception:
            pass
    threading.Thread(target=_warmup, daemon=True).start()
    print(f"  {G}Ollama ONLINE — model arka planda GPU'ya yukleniyor{X}")
    return True


def start_bridge():
    """WP Bridge baslat."""
    global wp_proc
    if wp_proc and wp_proc.poll() is None:
        print(f"  {Y}WP Bridge zaten calisiyor (PID: {wp_proc.pid}){X}")
        return True

    # Port mesgul mu? — tüm eski process'leri temizle
    import subprocess as sp
    result = sp.run(["netstat", "-ano"], capture_output=True, text=True)
    killed = False
    for line in result.stdout.split("\n"):
        if ":8001" in line and "LISTEN" in line:
            pid = line.strip().split()[-1]
            print(f"  {Y}Port 8001 mesgul (PID: {pid}), temizleniyor...{X}")
            sp.run(["taskkill", "//F", "//PID", pid], capture_output=True)
            killed = True
    if killed:
        time.sleep(5)  # Port'un tamamen serbest kalmasını bekle

    # Windows'ta pythonw.exe tercih et (windowless) — ekrana yeni pencere acmaz
    _py_exec = sys.executable
    if os.name == 'nt':
        _pyw = Path(sys.executable).parent / "pythonw.exe"
        if _pyw.exists():
            _py_exec = str(_pyw)
    # CREATE_NO_WINDOW flag — Windows'ta konsol penceresi acilmasini engelle
    _creation_flags = 0
    if os.name == 'nt':
        _creation_flags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS

    # Retry mekanizması — 2 deneme
    for attempt in range(2):
        print(f"  {Y}WhatsApp Bridge baslatiliyor (port 8001, headless)...{X}")
        wp_proc = subprocess.Popen(
            [_py_exec, "-m", "uvicorn", "whatsapp_bridge:app",
             "--host", "0.0.0.0", "--port", "8001"],
            cwd=str(PROJECT_DIR),
            stdout=open(str(PROJECT_DIR / "logs" / "wp_bridge.log"), "w"),
            stderr=subprocess.STDOUT,
            creationflags=_creation_flags,
            close_fds=True,
        )
        time.sleep(5)
        if wp_proc.poll() is None:
            print(f"  {G}WP Bridge ONLINE — PID: {wp_proc.pid}{X}")
            return True
        elif attempt == 0:
            print(f"  {Y}Tekrar deneniyor...{X}")
            time.sleep(3)

    # Health check ile kontrol — belki eski process hala çalışıyordur
    try:
        import httpx
        r = httpx.get("http://localhost:8001/health", timeout=3)
        if r.json().get("status") == "ok":
            print(f"  {G}WP Bridge ONLINE (mevcut process){X}")
            return True
    except Exception:
        pass

    print(f"  {R}WP Bridge baslatma HATASI — log kontrol edin{X}")
    return False


def start_ngrok():
    """ngrok sabit domain ile baslat."""
    import subprocess as sp

    # Zaten calisiyor mu?
    try:
        import httpx
        r = httpx.get("http://localhost:4040/api/tunnels", timeout=2)
        if r.json().get("tunnels"):
            print(f"  {G}ngrok zaten calisiyor{X}")
            return True
    except Exception:
        pass

    # Authtoken ayarla
    authtoken = os.getenv("NGROK_AUTHTOKEN", "")
    domain = os.getenv("NGROK_DOMAIN", "")
    if authtoken:
        sp.run(["ngrok", "config", "add-authtoken", authtoken], capture_output=True)

    # Eski ngrok kapat
    sp.run(["taskkill", "//F", "//IM", "ngrok.exe"], capture_output=True)
    time.sleep(1)

    # Baslat
    cmd = ["ngrok", "http", "8001"]
    if domain:
        cmd.extend(["--domain", domain])
    cmd.extend(["--log=stdout"])

    print(f"  {Y}ngrok baslatiliyor (headless)...{X}")
    _ngrok_flags = 0
    if os.name == 'nt':
        _ngrok_flags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
    ngrok_proc = subprocess.Popen(
        cmd,
        stdout=open(str(PROJECT_DIR / "logs" / "ngrok.log"), "w"),
        stderr=subprocess.STDOUT,
        creationflags=_ngrok_flags,
        close_fds=True,
    )
    time.sleep(5)

    # Kontrol
    try:
        import httpx
        r = httpx.get("http://localhost:4040/api/tunnels", timeout=3)
        tunnels = r.json().get("tunnels", [])
        if tunnels:
            url = tunnels[0]["public_url"]
            print(f"  {G}ngrok ONLINE: {url}{X}")
            return True
    except Exception:
        pass
    print(f"  {R}ngrok baslatma HATASI{X}")
    return False


def stop_bridge():
    """WP Bridge durdur."""
    global wp_proc
    if wp_proc and wp_proc.poll() is None:
        wp_proc.terminate()
        print(f"  {Y}WP Bridge durduruldu.{X}")
        wp_proc = None


async def restart_services():
    """Tum servisleri yeniden baslat."""
    print(f"\n  {Y}Servisler yeniden baslatiliyor...{X}\n")
    stop_bridge()
    time.sleep(2)
    start_ollama()
    start_bridge()
    start_ngrok()
    print(f"\n  {G}Servisler yeniden baslatildi!{X}")
    await show_dashboard()


async def check_and_refresh_token():
    """WA token durumunu kontrol et."""
    import httpx
    token = os.getenv("WA_ACCESS_TOKEN", "")
    if not token:
        print(f"  {R}WA_ACCESS_TOKEN tanimli degil!{X}")
        return

    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(f"https://graph.facebook.com/v25.0/me?access_token={token}")
            if r.status_code == 200:
                data = r.json()
                print(f"  {G}Token GECERLI{X} — Hesap: {data.get('name','?')}")
            else:
                print(f"  {R}Token GECERSIZ!{X} Otomatik yenileme deneniyor...")
                # Yenile
                app_id = os.getenv("FB_APP_ID", "")
                app_secret = os.getenv("FB_APP_SECRET", "")
                if app_id and app_secret:
                    r2 = await c.get(
                        f"https://graph.facebook.com/v25.0/oauth/access_token",
                        params={
                            "grant_type": "fb_exchange_token",
                            "client_id": app_id,
                            "client_secret": app_secret,
                            "fb_exchange_token": token,
                        }
                    )
                    new_token = r2.json().get("access_token")
                    if new_token:
                        # .env guncelle
                        import re
                        env_path = PROJECT_DIR / ".env"
                        content = env_path.read_text(encoding="utf-8")
                        content = re.sub(r"WA_ACCESS_TOKEN=.*", f"WA_ACCESS_TOKEN={new_token}", content)
                        env_path.write_text(content, encoding="utf-8")
                        os.environ["WA_ACCESS_TOKEN"] = new_token
                        print(f"  {G}Token yenilendi!{X} (yeni uzunluk: {len(new_token)})")
                    else:
                        print(f"  {R}Token yenileme basarisiz. Developer Portal'dan manuel alin.{X}")
                else:
                    print(f"  {R}FB_APP_ID/FB_APP_SECRET .env'de yok — yenileyemiyorum{X}")
    except Exception as e:
        print(f"  {R}Token kontrol hatasi: {e}{X}")


# ═══════════════════════════════════════════════════════════════════════════════
# LOG & ANALIZ
# ═══════════════════════════════════════════════════════════════════════════════

async def show_recent_logs(count: int = 15):
    """Kategorize log menusu — kullanici bazli, son aktifler uste."""
    try:
        # Oturum 23 audit: db_pool helper'ı (3 query → tek pool, acquire/release otomatik)
        from db_pool import db_fetch

        # Son 24 saatteki aktif kullanıcılar
        users = await db_fetch("""
            SELECT phone, role,
                   COUNT(*) FILTER (WHERE message_role='user') as mesaj,
                   to_char(MAX(created_at), 'HH24:MI') as son_aktif,
                   LEFT(MAX(CASE WHEN message_role='user' THEN content END), 60) as son_mesaj
            FROM agent_conversations
            WHERE created_at >= NOW() - INTERVAL '24 hours'
            AND content NOT LIKE '[tool_calls%'
            GROUP BY phone, role
            ORDER BY MAX(created_at) DESC
        """)

        # ACL'den isim eşleştirme
        names = {}
        name_rows = await db_fetch("SELECT phone, full_name FROM acl_users WHERE is_active=TRUE")
        for nr in name_rows:
            names[nr['phone']] = nr['full_name']
        # students'dan da
        student_names = await db_fetch("SELECT phone, full_name FROM students WHERE phone IS NOT NULL")
        for sn in student_names:
            if sn['phone']:
                clean = sn['phone'].replace('+','').replace(' ','')
                if clean not in names:
                    names[clean] = sn['full_name']

        if not users:
            print(f"  {D}Son 24 saatte konusma yok.{X}")
            return

        # Rol emojileri
        role_emoji = {"admin": "👑", "mudur": "👔", "yonetim": "💼",
                      "rehber": "📋", "ogretmen": "👨‍🏫", "ogrenci": "🎓", "unknown": "👤"}

        print(f"\n{C}{B}  KONUSMA LOGLARI (son 24 saat){X}")
        print(f"  {'='*55}")
        print(f"  {B}{'#':>3} {'Kullanici':<22} {'Rol':<10} {'Mesaj':>5} {'Son':>6}{X}")
        print(f"  {'-'*55}")

        for i, u in enumerate(users, 1):
            ph = u['phone'] or '?'
            name = names.get(ph, names.get(ph.replace('+',''), ph[-4:]))
            if len(name) > 20:
                name = name[:20]
            emoji = role_emoji.get(u['role'], '❓')
            son = u['son_mesaj'] or ''
            son = son.replace('\n',' ')[:40]

            print(f"  {D}{i:>3}{X} {emoji} {name:<20} {u['role']:<9} {u['mesaj']:>5} {u['son_aktif']:>6}")

        print(f"  {'-'*55}")
        print(f"  {D}Detay icin: log [isim] veya log [son 4 hane]{X}")
        print()

    except Exception as e:
        print(f"  {R}Log hatasi: {e}{X}")


async def show_user_log(query: str):
    """Belirli kullanıcının konuşma detayı."""
    try:
        # Oturum 23 audit: db_pool helper'ı
        from db_pool import db_fetch, db_fetchrow

        # İsim, sıra numarası veya telefon son haneleri ile ara
        phone = None
        clean_q = query.replace('+','').replace(' ','').replace('-','')
        if clean_q.isdigit():
            num = int(clean_q)
            if num <= 30:
                # Kucuk sayi = sira numarasi (log listesindeki #)
                users = await db_fetch("""
                    SELECT DISTINCT phone FROM agent_conversations
                    WHERE created_at >= NOW() - INTERVAL '24 hours'
                    GROUP BY phone ORDER BY MAX(created_at) DESC
                """)
                if num <= len(users):
                    phone = users[num - 1]['phone']
                else:
                    # Sira numarasi gecersiz — son hane olarak dene
                    row = await db_fetchrow(
                        "SELECT DISTINCT phone FROM agent_conversations WHERE phone LIKE $1 AND created_at >= NOW() - INTERVAL '48 hours' LIMIT 1",
                        f"%{clean_q}")
                    if row:
                        phone = row['phone']
            elif len(clean_q) >= 10:
                phone = clean_q
            else:
                # 4 haneli numara (2648, 6802 gibi)
                row = await db_fetchrow(
                    "SELECT DISTINCT phone FROM agent_conversations WHERE phone LIKE $1 AND created_at >= NOW() - INTERVAL '48 hours' LIMIT 1",
                    f"%{clean_q}")
                if row:
                    phone = row['phone']
        else:
            # İsimle ara — acl_users + students
            row = await db_fetchrow(
                "SELECT phone FROM acl_users WHERE LOWER(full_name) LIKE LOWER($1) LIMIT 1",
                f"%{query}%")
            if not row:
                row = await db_fetchrow(
                    "SELECT phone FROM students WHERE LOWER(full_name) LIKE LOWER($1) AND phone IS NOT NULL LIMIT 1",
                    f"%{query}%")
            if row:
                phone = row['phone'].replace('+','').replace(' ','')

        if not phone:
            # Son care — konusma gecmisinde isim ara
            row = await db_fetchrow(
                "SELECT DISTINCT phone FROM agent_conversations WHERE content ILIKE $1 LIMIT 1",
                f"%{query}%")
            if row:
                phone = row['phone']

        if not phone:
            print(f"  {R}'{query}' bulunamadi.{X}")
            return

        rows = await db_fetch("""
            SELECT to_char(created_at, 'HH24:MI') as saat, message_role,
                   LEFT(content, 100) as icerik
            FROM agent_conversations
            WHERE phone LIKE $1 AND content NOT LIKE '[tool_calls%'
            AND message_role IN ('user','assistant')
            AND created_at >= NOW() - INTERVAL '24 hours'
            ORDER BY created_at DESC LIMIT 30
        """, f"%{phone[-4:]}%")

        if not rows:
            print(f"  {D}Bu kullanici icin son 24 saatte konusma yok.{X}")
            return

        print(f"\n{C}{B}  {query.upper()} — Son konusmalar{X}")
        print(f"  {'='*55}")
        for r in reversed(rows):
            mr = r['message_role']
            icon = f"{G}>>>{X}" if mr == 'user' else f"{C}<<<{X}"
            icerik = (r['icerik'] or '').replace('\n', ' ')
            print(f"  {D}{r['saat']}{X} {icon} {icerik}")
        print()

    except Exception as e:
        print(f"  {R}Log hatasi: {e}{X}")


async def run_analysis():
    """Konusma analizi ve ogrenme raporu."""
    try:
        from conversation_learner import generate_learning_report
        print(f"\n  {Y}Analiz calistiriliyor...{X}\n")
        summary = await generate_learning_report()
        print(summary)
    except Exception as e:
        print(f"  {R}Analiz hatasi: {e}{X}")


async def run_sql(query: str):
    """SQL sorgusu calistir."""
    try:
        # Oturum 23 audit: db_pool helper'ı
        from db_pool import db_fetch
        rows = await db_fetch(query)
        if rows:
            cols = list(rows[0].keys())
            print(f"\n  {D}{' | '.join(cols)}{X}")
            print(f"  {'-' * 60}")
            for r in rows[:20]:
                vals = [str(r[c])[:30] for c in cols]
                print(f"  {' | '.join(vals)}")
            if len(rows) > 20:
                print(f"  {D}... ve {len(rows)-20} satir daha{X}")
        else:
            print(f"  {D}Sonuc yok.{X}")
    except Exception as e:
        print(f"  {R}SQL hatasi: {e}{X}")


# ═══════════════════════════════════════════════════════════════════════════════
# AGENT CHAT
# ═══════════════════════════════════════════════════════════════════════════════

_agent = None

async def chat(message: str):
    """Agent ile sohbet — admin yetkisi."""
    global _agent
    try:
        if _agent is None:
            from fermat_core_agent import FermatCoreAgent
            _agent = FermatCoreAgent()

        print(f"\n  {D}Dusunuyor...{X}", end="", flush=True)
        response = await _agent.run(user_input=message, caller_phone="")
        print(f"\r" + " " * 40 + "\r", end="")
        print(f"\n  {G}{response}{X}")
    except Exception as e:
        print(f"\r" + " " * 40 + "\r", end="")
        print(f"  {R}Hata: {e}{X}")


# ═══════════════════════════════════════════════════════════════════════════════
# ANA DONGU
# ═══════════════════════════════════════════════════════════════════════════════

async def interactive():
    """Interaktif komut dongusu."""
    while True:
        try:
            cmd = input(f"\n  {G}{B}neo>{X} ").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n  {Y}Cikiliyor...{X}")
            stop_bridge()
            break

        if not cmd:
            continue

        lower = cmd.lower().strip()

        if lower in ("cikis", "exit", "quit", "q"):
            print(f"  {Y}FermatAI kapatiliyor...{X}")
            stop_bridge()
            import subprocess as _sp
            print(f"  {Y}Ollama kapatiliyor (VRAM serbest)...{X}")
            _sp.run(["taskkill", "/F", "/IM", "ollama app.exe"], capture_output=True)
            time.sleep(1)
            _sp.run(["taskkill", "/F", "/IM", "ollama.exe"], capture_output=True)
            print(f"  {Y}Chrome CDP kapatiliyor...{X}")
            _sp.run(["taskkill", "/F", "/IM", "chrome.exe"], capture_output=True)
            time.sleep(1)
            print(f"  {G}GPU serbest! Docker calisiyor (postgres/redis).{X}")
            break
        elif lower in ("durum", "status", "d"):
            await show_dashboard()
        elif lower in ("menu", "help", "yardim", "h", "?"):
            show_menu()
        elif lower in ("yenile", "restart", "r"):
            await restart_services()
        elif lower in ("log", "loglar", "l"):
            await show_recent_logs()
        elif lower.startswith("log "):
            await show_user_log(cmd[4:].strip())
        elif lower in ("analiz", "rapor", "a"):
            await run_analysis()
        elif lower in ("token", "t"):
            await check_and_refresh_token()
        elif lower in ("temizle", "cls", "clear"):
            clear()
            os.system("")  # ANSI renkleri tekrar aktif et
            banner()
            await show_dashboard()
            show_menu()
        elif lower.startswith("sql "):
            await run_sql(cmd[4:].strip())
        elif lower.startswith("logn "):
            try:
                n = int(cmd[5:].strip())
                await show_recent_logs(n)
            except ValueError:
                await show_recent_logs()
        else:
            await chat(cmd)


async def main():
    # 22.1l — --autostart flag: logon'da sessiz mod (bridge + servisler başlat, interactive atla)
    autostart = "--autostart" in sys.argv

    if not autostart:
        clear()
        banner()
        print(f"  {Y}Sistem baslatiliyor...{X}\n")

    # 1. Servisleri baslat (Ollama BASLAT.bat'ta baslatiliyor)
    if not autostart:
        print(f"  {C}[1/4]{X} Servisler kontrol ediliyor...")
    start_bridge()
    start_ngrok()

    # 2. Token kontrol
    if not autostart:
        print(f"\n  {C}[2/4]{X} WA Token kontrol ediliyor...")
    await check_and_refresh_token()

    # 3. Analytics cache
    if not autostart:
        print(f"\n  {C}[3/4]{X} Analitik cache olusturuluyor...")
    try:
        from analytics_cache import build_all_caches
        await build_all_caches()
        if not autostart:
            print(f"  {G}Cache hazir!{X}")
    except Exception as e:
        if not autostart:
            print(f"  {Y}Cache olusturulamadi: {e}{X}")

    if autostart:
        # Autostart modunda interactive'e GIRMEDEN bekle (bridge arka planda calisir)
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] FermatAI autostart: bridge+ngrok+token ready")
        # Process'i canli tut (bridge ve scheduler'lar arka planda calisiyor)
        try:
            while True:
                await asyncio.sleep(3600)  # 1 saatte bir heartbeat
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] autostart heartbeat")
        except (KeyboardInterrupt, SystemExit):
            pass
        return

    # 4. Dashboard — temiz ekranla başla (başlatma logları silinir)
    clear()
    os.system("")  # ANSI renkleri aktif
    banner()
    await show_dashboard()
    show_menu()

    # Interaktif dongu
    await interactive()

    print(f"\n  {G}FermatAI kapatildi. Iyi gunler Neo!{X}\n")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n  {Y}FermatAI kapatildi.{X}")
    if os.name == "nt":
        input("\n  Kapatmak icin ENTER basin...")

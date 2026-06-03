"""
FermatAI — Konuşma Görüntüleyici
==================================
DB'deki tüm konuşmaları WhatsApp tarzı HTML sayfası olarak oluşturur.
Kişi klasörleri, tam mesajlar, sayfa sayfa görüntüleme.

Kullanım:
  python conversation_viewer.py              # Son 48 saat
  python conversation_viewer.py 7            # Son 7 gün
  python conversation_viewer.py 30           # Son 30 gün
  python conversation_viewer.py --all        # Tüm geçmiş

Çıktı: logs/conversations.html → tarayıcıda aç
"""

import asyncio
import html
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

from db_pool import get_pool as _get_pool
OUTPUT = Path("logs/conversations.html")


async def get_conversations(days: int = 2):
    if days == 0:
        interval_clause = ""
        period_label = "Tüm Geçmiş"
    else:
        interval_clause = f"AND c.created_at >= NOW() - INTERVAL '{days} days'"
        period_label = f"Son {days} Gün"

    pool = await _get_pool()
    async with pool.acquire() as conn:
        # Tüm mesajları çek
        # 25.57 (Neo): ikincil sıra id ASC — aynı saniyedeki user+bot mesajları
        # eskiden non-deterministik sıralanıp "ters/boşluk" hissi yaratıyordu.
        # id = insertion order → user mesajı her zaman bot cevabından önce gelir.
        rows = await conn.fetch(f"""
            SELECT c.phone, c.message_role, c.content, c.created_at, c.tools_used
            FROM agent_conversations c
            WHERE c.content IS NOT NULL AND c.content != ''
            {interval_clause}
            ORDER BY c.created_at ASC, c.id ASC
        """)

        # Kullanıcı bilgilerini çek
        users = {}
        acl = await conn.fetch("SELECT phone, full_name, role FROM acl_users")
        for a in acl:
            p = (a['phone'] or '').replace('+', '')
            if p:
                users[p] = {"name": a['full_name'], "role": a['role']}

        students = await conn.fetch("SELECT phone, full_name, soz_no, class_name FROM students WHERE phone IS NOT NULL AND phone != ''")
        for s in students:
            p = (s['phone'] or '').replace('+', '')
            if p and p not in users:
                users[p] = {"name": s['full_name'], "role": "ogrenci", "soz_no": s['soz_no'], "class": s['class_name']}

    # Telefon bazlı grupla
    conversations = {}
    for r in rows:
        phone = (r['phone'] or '').replace('+', '')
        if not phone:
            phone = "bilinmeyen"
        if phone not in conversations:
            conversations[phone] = []
        conversations[phone].append({
            "role": r['message_role'],
            "content": r['content'] or '',
            "time": r['created_at'],
            "tools": r['tools_used'] if r['tools_used'] else None,
        })

    return conversations, users, period_label


def _role_badge(role: str) -> str:
    badges = {
        "admin": '<span class="badge admin">Admin</span>',
        "mudur": '<span class="badge mudur">Müdür</span>',
        "yonetim": '<span class="badge yonetim">Yönetim</span>',
        "ogretmen": '<span class="badge ogretmen">Öğretmen</span>',
        "ogrenci": '<span class="badge ogrenci">Öğrenci</span>',
        "rehber": '<span class="badge rehber">Rehber</span>',
    }
    return badges.get(role, f'<span class="badge">{role}</span>')


def _format_content(text: str) -> str:
    """WhatsApp markdown → HTML"""
    t = html.escape(text)
    # Bold: *text*
    import re
    t = re.sub(r'\*([^*]+)\*', r'<strong>\1</strong>', t)
    # Italic: _text_
    t = re.sub(r'_([^_]+)_', r'<em>\1</em>', t)
    # Strikethrough: ~text~
    t = re.sub(r'~([^~]+)~', r'<del>\1</del>', t)
    # Monospace: ```text```
    t = re.sub(r'```([^`]+)```', r'<code>\1</code>', t)
    # Emoji korunur (zaten HTML escape ile sorun yok)
    # Satır sonları
    t = t.replace('\n', '<br>')
    # --- ayırıcı
    t = t.replace('---', '<hr class="msg-hr">')
    return t


def _tr_title(name: str) -> str:
    """Türkçe title case"""
    _map = str.maketrans("İIĞŞÜÖÇ", "iığşüöç")
    lower = name.translate(_map).lower()
    parts = lower.split()
    result = []
    for p in parts:
        if p:
            first = p[0]
            up_map = str.maketrans("iığşüöç", "İIĞŞÜÖÇ")
            first_upper = first.translate(up_map).upper()
            result.append(first_upper + p[1:])
    return ' '.join(result)


def generate_html(conversations: dict, users: dict, period_label: str, days: int = 7) -> str:
    # Kullanıcıları son mesaj zamanına göre sırala
    sorted_phones = sorted(
        conversations.keys(),
        key=lambda p: conversations[p][-1]['time'] if conversations[p] else datetime.min,
        reverse=True
    )

    total_msgs = sum(len(msgs) for msgs in conversations.values())
    total_users = len(conversations)

    # Sol panel — kullanıcı listesi
    user_cards = []
    chat_panels = []
    page_size = 50

    for idx, phone in enumerate(sorted_phones):
        msgs = conversations[phone]
        user = users.get(phone, {})
        name = user.get('name', phone)
        if name and name == name.upper() and len(name) > 2:
            name = _tr_title(name)
        role = user.get('role', '?')
        cls = user.get('class', '')
        soz = user.get('soz_no', '')

        user_msgs = [m for m in msgs if m['role'] == 'user']
        bot_msgs = [m for m in msgs if m['role'] != 'user']
        first_time = msgs[0]['time'].strftime('%d.%m %H:%M') if msgs else ''
        last_time = msgs[-1]['time'].strftime('%d.%m %H:%M') if msgs else ''

        active_class = 'active' if idx == 0 else ''

        # 25.57 (Neo): son KULLANICI mesajı önizleme + bugün-aktif göstergesi
        # (bağlam taraması — kartlara bakınca kimin ne dediğini hızlı gör).
        _last_user_msg = next(
            (m['content'] for m in reversed(msgs) if m['role'] == 'user' and m['content']), ''
        )
        preview = ' '.join(_last_user_msg.split())[:70]
        _is_today = bool(msgs) and msgs[-1]['time'].date() == datetime.now().date()
        today_dot = '<span class="today-dot" title="Bugün aktif"></span>' if _is_today else ''

        # Kullanıcı kartı
        user_cards.append(f'''
        <div class="user-card {active_class}" onclick="showChat('{phone}', this)" data-phone="{phone}">
            <div class="user-avatar">{name[0] if name else '?'}</div>
            <div class="user-info">
                <div class="user-name">{today_dot}{html.escape(name)}</div>
                <div class="user-meta">{_role_badge(role)} {html.escape(str(cls))} {f'• #{soz}' if soz else ''}</div>
                <div class="user-stats">
                    {len(user_msgs)} mesaj • {first_time} — {last_time}
                </div>
                {f'<div class="user-preview">{html.escape(preview)}</div>' if preview else ''}
            </div>
        </div>
        ''')

        # Chat paneli — sayfalı
        total_pages = max(1, (len(msgs) + page_size - 1) // page_size)
        pages_html = []

        for page_num in range(total_pages):
            start = page_num * page_size
            end = min(start + page_size, len(msgs))
            page_msgs = msgs[start:end]

            bubbles = []
            prev_date = None
            for m in page_msgs:
                msg_date = m['time'].strftime('%d %B %Y')
                if msg_date != prev_date:
                    bubbles.append(f'<div class="date-separator">{msg_date}</div>')
                    prev_date = msg_date

                is_user = m['role'] == 'user'
                bubble_class = 'user-bubble' if is_user else 'bot-bubble'
                time_str = m['time'].strftime('%H:%M')
                content = m['content']

                # Tool calls gösterimi
                if content.startswith('[tool_calls:'):
                    tool_name = content.replace('[tool_calls:', '').replace(']', '').strip()
                    bubbles.append(f'''
                    <div class="tool-call">
                        🔧 <code>{html.escape(tool_name)}</code>
                    </div>
                    ''')
                    continue

                formatted = _format_content(content)

                bubbles.append(f'''
                <div class="bubble {bubble_class}">
                    <div class="bubble-content">{formatted}</div>
                    <div class="bubble-time">{time_str}</div>
                </div>
                ''')

            # 25.24-fix: SON sayfa default goster (en yeni mesajlar). Eskiden 0. sayfa
            # default acilirdi, kullanici 1-2 ay onceki mesajlari gorur, "asagiya inmiyor"
            # hissi yaratirdi. Artik default = en son mesajlar, isteyen ◀ Onceki ile geriye gider.
            page_display = 'block' if page_num == (total_pages - 1) else 'none'
            pages_html.append(f'''
            <div class="chat-page" id="page_{phone}_{page_num}" style="display:{page_display}">
                {''.join(bubbles)}
            </div>
            ''')

        # Pagination controls
        if total_pages > 1:
            # 25.24-fix: pag-info default = son sayfa
            # 25.25-fix: id yerine data-phone kullan — top+bot iki kez render ediliyor, duplicate id sorun yaratiyor
            pagination = f'''
            <div class="pagination" data-phone="{phone}">
                <button onclick="changePage('{phone}', -1)" class="pag-btn">◀ Önceki</button>
                <span class="pag-info" data-phone="{phone}">Sayfa {total_pages} / {total_pages}</span>
                <button onclick="changePage('{phone}', 1)" class="pag-btn">Sonraki ▶</button>
            </div>
            '''
        else:
            pagination = ''

        display = 'flex' if idx == 0 else 'none'
        chat_panels.append(f'''
        <div class="chat-panel" id="chat_{phone}" style="display:{display}">
            <div class="chat-header">
                <div class="chat-header-name">{html.escape(name)}</div>
                <div class="chat-header-info">
                    {_role_badge(role)} {html.escape(str(cls))} •
                    {len(user_msgs)} kullanıcı / {len(bot_msgs)} bot mesajı •
                    Tel: ...{phone[-4:] if len(phone) >= 4 else phone}
                </div>
            </div>
            {pagination}
            <div class="chat-messages">
                {''.join(pages_html)}
            </div>
            {pagination}
        </div>
        ''')

    now = datetime.now().strftime('%d.%m.%Y %H:%M')

    # 25.57 (Neo): UI gün seçici — URL elle değiştirmeden pencere değiştir, token korunur.
    _ranges = [(1, "Bugün"), (7, "7 Gün"), (30, "30 Gün"), (90, "90 Gün"), (0, "Tümü")]
    range_btns = ''.join(
        f'<button class="range-btn{" active" if d == days else ""}" onclick="setRange({d})">{lbl}</button>'
        for d, lbl in _ranges
    )

    return f'''<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>FermatAI Konuşmalar — {period_label}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;500;600&family=Fira+Sans:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
/* Oturum 25.14c — Conversation viewer premium revize (ui-ux-pro-max Cinema palette) */
:root {{
    --bg-deep:#020203; --bg-base:#050506; --bg-elevated:#0a0a0c;
    --surface-1:rgba(255,255,255,0.025);
    --surface-2:rgba(255,255,255,0.05);
    --surface-3:rgba(255,255,255,0.08);
    --brand-gold:#f59e0b; --brand-amber:#fbbf24;
    --brand-glow:rgba(245,158,11,0.3);
    --accent-indigo:#5E6AD2; --accent-purple:#8B5CF6;
    --success:#10b981;
    --fg:#ededef; --fg-muted:#a8aab2; --fg-tertiary:#6b6e78;
    --border:rgba(255,255,255,0.08);
    --border-strong:rgba(255,255,255,0.14);
    --easing:cubic-bezier(0.16,1,0.3,1);
    --gradient-gold:linear-gradient(135deg,#f59e0b 0%,#fbbf24 100%);
    --gradient-cinema:linear-gradient(180deg,#0a0a0f 0%,#020203 100%);
}}
* {{ margin:0; padding:0; box-sizing:border-box; -webkit-font-smoothing:antialiased; }}
html {{ background:var(--bg-deep); }}
body {{
    font-family:'Fira Sans',-apple-system,BlinkMacSystemFont,system-ui,sans-serif;
    background:var(--gradient-cinema);
    color:var(--fg); height:100vh; overflow:hidden;
    letter-spacing:-0.011em;
}}
.mono {{ font-family:'Fira Code',monospace; font-variant-numeric:tabular-nums; }}

/* Ambient blobs */
body::before, body::after {{
    content:''; position:fixed; border-radius:50%; filter:blur(80px);
    opacity:0.12; z-index:0; pointer-events:none;
}}
body::before {{
    width:500px; height:500px; top:-150px; left:-100px;
    background:radial-gradient(circle,var(--brand-gold),transparent 60%);
}}
body::after {{
    width:600px; height:600px; bottom:-200px; right:-150px;
    background:radial-gradient(circle,var(--accent-indigo),transparent 60%);
}}

/* Layout */
.container {{ display:flex; height:100vh; position:relative; z-index:10; }}
.sidebar {{
    width:360px;
    background:var(--surface-1);
    backdrop-filter:blur(24px) saturate(180%);
    -webkit-backdrop-filter:blur(24px) saturate(180%);
    border-right:1px solid var(--border);
    display:flex; flex-direction:column; overflow:hidden;
}}
.main {{
    flex:1; display:flex; flex-direction:column;
    background:var(--bg-deep); overflow:hidden;
}}

/* Sidebar header */
.sidebar-header {{
    padding:18px 20px;
    background:var(--surface-2);
    border-bottom:1px solid var(--border);
    position:relative;
}}
.sidebar-header::before {{
    content:''; position:absolute; top:0; left:0; right:0; height:1px;
    background:linear-gradient(90deg,transparent,rgba(255,255,255,0.18),transparent);
}}
.sidebar-header h2 {{
    font-size:16px; font-weight:700; letter-spacing:-0.02em;
    background:var(--gradient-gold);
    -webkit-background-clip:text; background-clip:text; color:transparent;
    margin-bottom:6px;
}}
.sidebar-header .stats {{
    font-size:11px; color:var(--fg-muted);
    font-family:'Fira Code',monospace;
    letter-spacing:0.02em;
}}

/* Search */
.search-box {{ padding:12px 14px; }}
.search-box input {{
    width:100%; padding:10px 14px;
    background:var(--bg-base);
    border:1px solid var(--border);
    border-radius:10px;
    color:var(--fg); font-size:14px; outline:none;
    font-family:inherit;
    transition:all 0.2s var(--easing);
}}
.search-box input:focus {{
    border-color:var(--brand-gold);
    box-shadow:0 0 0 3px var(--brand-glow);
}}
.search-box input::placeholder {{ color:var(--fg-tertiary); }}

/* 25.57 — Zaman aralığı seçici (1g/7g/30g/90g/Tümü) */
.range-selector {{
    display:flex; gap:6px; padding:0 14px 12px; flex-wrap:wrap;
}}
.range-btn {{
    flex:1; min-width:42px; padding:7px 6px;
    background:var(--bg-base); border:1px solid var(--border);
    border-radius:8px; color:var(--fg-muted);
    font-size:12px; font-weight:600; font-family:'Fira Code',monospace;
    cursor:pointer; transition:all 0.2s var(--easing);
}}
.range-btn:hover {{ border-color:var(--border-strong); color:var(--fg); }}
.range-btn.active {{
    background:var(--gradient-gold); color:#1a0d00; border-color:transparent;
    box-shadow:0 2px 10px var(--brand-glow);
}}

/* 25.57 — Bugün aktif noktası + son mesaj önizleme */
.today-dot {{
    display:inline-block; width:7px; height:7px; border-radius:50%;
    background:var(--success); margin-right:6px; vertical-align:middle;
    box-shadow:0 0 6px var(--success); animation:pulse 2s infinite;
}}
@keyframes pulse {{ 0%,100%{{opacity:1}} 50%{{opacity:0.4}} }}
.user-preview {{
    font-size:11.5px; color:var(--fg-tertiary); margin-top:4px;
    white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
    font-style:italic; opacity:0.85;
}}
.user-card.active .user-preview {{ color:var(--fg-muted); }}

/* User list */
.user-list {{ flex:1; overflow-y:auto; padding:6px 8px; }}
.user-card {{
    display:flex; align-items:center; padding:11px 13px; cursor:pointer;
    border:1px solid transparent; border-radius:12px; margin-bottom:4px;
    transition:all 0.25s var(--easing);
}}
.user-card:hover {{
    background:var(--surface-2);
    border-color:var(--border);
    transform:translateX(2px);
}}
.user-card.active {{
    background:var(--surface-3);
    border-color:var(--brand-gold);
    box-shadow:0 4px 16px rgba(245,158,11,0.12);
}}
.user-avatar {{
    width:42px; height:42px; border-radius:12px;
    background:var(--gradient-gold);
    display:flex; align-items:center; justify-content:center;
    font-size:17px; font-weight:700; color:#1a0d00;
    flex-shrink:0; margin-right:12px;
    box-shadow:0 4px 12px var(--brand-glow), inset 0 1px 0 rgba(255,255,255,0.4);
    letter-spacing:-0.05em;
}}
.user-info {{ flex:1; min-width:0; }}
.user-name {{
    font-size:14.5px; font-weight:600; color:var(--fg);
    white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
    letter-spacing:-0.01em;
}}
.user-meta {{
    font-size:11.5px; color:var(--fg-muted); margin-top:3px;
    display:flex; align-items:center; gap:6px; flex-wrap:wrap;
}}
.user-stats {{
    font-size:10.5px; color:var(--fg-tertiary); margin-top:2px;
    font-family:'Fira Code',monospace;
}}

/* Badges */
.badge {{
    display:inline-block; padding:2px 8px; border-radius:999px;
    font-size:9.5px; font-weight:700; text-transform:uppercase;
    letter-spacing:0.06em;
}}
.badge.admin {{ background:rgba(239,68,68,0.18); color:#fca5a5; }}
.badge.mudur {{ background:rgba(94,106,210,0.18); color:#a5b4fc; }}
.badge.yonetim {{ background:rgba(139,92,246,0.18); color:#c4b5fd; }}
.badge.ogretmen {{ background:rgba(245,158,11,0.18); color:var(--brand-amber); }}
.badge.ogrenci {{ background:rgba(16,185,129,0.18); color:#6ee7b7; }}
.badge.rehber {{ background:rgba(20,184,166,0.18); color:#5eead4; }}

/* Chat header */
.chat-header {{
    padding:18px 24px;
    background:var(--surface-1);
    backdrop-filter:blur(20px); -webkit-backdrop-filter:blur(20px);
    border-bottom:1px solid var(--border);
    position:relative;
}}
.chat-header::before {{
    content:''; position:absolute; top:0; left:0; right:0; height:1px;
    background:linear-gradient(90deg,transparent,rgba(255,255,255,0.18),transparent);
}}
.chat-header-name {{
    font-size:18px; font-weight:700; color:var(--fg);
    letter-spacing:-0.02em;
}}
.chat-header-info {{
    font-size:12px; color:var(--fg-muted); margin-top:4px;
    display:flex; align-items:center; gap:8px; flex-wrap:wrap;
    font-family:'Fira Code',monospace;
    font-variant-numeric:tabular-nums;
}}

/* Chat panel — flex column, full height (CRITICAL for chat-messages scroll) */
.chat-panel {{
    display:flex; flex-direction:column;
    height:100%; min-height:0;
}}

/* Chat messages */
.chat-messages {{
    flex:1 1 auto; overflow-y:auto; padding:24px 64px;
    background:transparent;
    min-height:0;  /* CRITICAL: nested flex+overflow needs this to scroll */
}}

/* Date separator */
.date-separator {{
    text-align:center; margin:24px auto 16px; font-size:11px;
    color:var(--fg-muted);
    background:var(--surface-2);
    border:1px solid var(--border);
    display:block; width:fit-content;
    padding:6px 14px; border-radius:999px;
    font-family:'Fira Code',monospace;
    letter-spacing:0.05em;
    text-transform:uppercase; font-weight:600;
}}

/* Bubbles */
.bubble {{
    max-width:72%; margin-bottom:6px; padding:11px 16px;
    position:relative; word-wrap:break-word; line-height:1.5; font-size:14px;
    clear:both; border-radius:14px;
    box-shadow:0 2px 8px rgba(0,0,0,0.3);
    transition:all 0.2s var(--easing);
}}
.bubble:hover {{ transform:translateY(-1px); box-shadow:0 4px 14px rgba(0,0,0,0.4); }}
.user-bubble {{
    background:linear-gradient(135deg,#92400e 0%,#b45309 100%);
    color:#fef3c7;
    float:right; border-top-right-radius:4px;
    margin-left:28%;
    border:1px solid rgba(245,158,11,0.3);
}}
.bot-bubble {{
    background:var(--surface-2);
    border:1px solid var(--border);
    float:left; border-top-left-radius:4px;
    margin-right:28%;
}}
.bubble::after {{ content:''; display:table; clear:both; }}
.bubble-content {{ color:var(--fg); }}
.user-bubble .bubble-content {{ color:#fef3c7; }}
.bubble-content strong {{ color:var(--brand-amber); font-weight:600; }}
.user-bubble .bubble-content strong {{ color:#fff; }}
.bubble-content em {{ color:var(--fg-muted); font-style:italic; }}
.bubble-content code {{
    background:var(--bg-deep); padding:2px 6px; border-radius:4px;
    font-size:12.5px; font-family:'Fira Code',monospace;
    color:var(--brand-amber);
}}
.bubble-content hr.msg-hr {{ border:none; border-top:1px solid var(--border); margin:8px 0; }}
.bubble-time {{
    font-size:10.5px; color:rgba(255,255,255,0.5); text-align:right;
    margin-top:4px; font-family:'Fira Code',monospace;
    font-variant-numeric:tabular-nums;
}}
.user-bubble .bubble-time {{ color:rgba(254,243,199,0.6); }}

/* Tool calls */
.tool-call {{
    text-align:center; margin:8px 0; font-size:11.5px;
    color:var(--fg-tertiary); clear:both;
    padding:6px 12px;
    background:var(--surface-1);
    border:1px dashed var(--border);
    border-radius:10px;
    width:fit-content; margin-left:auto; margin-right:auto;
}}
.tool-call code {{
    background:var(--surface-2); padding:2px 8px; border-radius:6px;
    font-family:'Fira Code',monospace;
    color:var(--accent-purple);
    font-weight:500;
}}

/* Pagination */
.pagination {{
    display:flex; align-items:center; justify-content:center; gap:14px;
    padding:12px 20px;
    background:var(--surface-1);
    border-bottom:1px solid var(--border);
    backdrop-filter:blur(12px); -webkit-backdrop-filter:blur(12px);
}}
.pag-btn {{
    background:var(--gradient-gold);
    color:#1a0d00; border:none;
    padding:7px 16px; border-radius:8px; cursor:pointer;
    font-size:12.5px; font-weight:600;
    font-family:inherit;
    transition:all 0.2s var(--easing);
    box-shadow:0 2px 8px var(--brand-glow);
}}
.pag-btn:hover {{
    transform:translateY(-1px);
    box-shadow:0 4px 14px var(--brand-glow);
}}
.pag-info {{
    font-size:12px; color:var(--fg-muted);
    font-family:'Fira Code',monospace;
    letter-spacing:0.02em;
}}

/* Empty state */
.empty-state {{
    display:flex; align-items:center; justify-content:center; flex:1;
    color:var(--fg-tertiary); font-size:15px;
}}

/* Scrollbar */
::-webkit-scrollbar {{ width:6px; height:6px; }}
::-webkit-scrollbar-track {{ background:transparent; }}
::-webkit-scrollbar-thumb {{
    background:var(--border-strong); border-radius:999px;
}}
::-webkit-scrollbar-thumb:hover {{ background:rgba(255,255,255,0.2); }}

/* Clear float fix */
.chat-page::after {{ content:''; display:table; clear:both; }}

/* Responsive */
@media (max-width: 768px) {{
    .sidebar {{ width:100%; position:fixed; z-index:50; }}
    .main {{ margin-left:0; }}
    .chat-messages {{ padding:14px 18px; }}
    .bubble {{ max-width:88%; padding:10px 14px; }}
    .chat-header-name {{ font-size:16px; }}
}}
</style>
</head>
<body>
<div class="container">
    <div class="sidebar">
        <div class="sidebar-header">
            <h2>🤖 FermatAI Konuşmalar</h2>
            <div class="stats">{total_users} kişi • {total_msgs} mesaj • {period_label} • {now}</div>
        </div>
        <div class="range-selector">
            {range_btns}
        </div>
        <div class="search-box">
            <input type="text" placeholder="Kişi veya mesaj içeriği ara..." oninput="filterUsers(this.value)">
        </div>
        <div class="user-list" id="userList">
            {''.join(user_cards)}
        </div>
    </div>
    <div class="main">
        {''.join(chat_panels)}
    </div>
</div>

<script>
// Sayfa state
const pageState = {{}};

function showChat(phone, el) {{
    // Tüm kartlardan active kaldır
    document.querySelectorAll('.user-card').forEach(c => c.classList.remove('active'));
    el.classList.add('active');
    // Tüm panelleri gizle
    document.querySelectorAll('.chat-panel').forEach(p => p.style.display = 'none');
    const panel = document.getElementById('chat_' + phone);
    if (panel) {{
        panel.style.display = 'flex';
        panel.style.flexDirection = 'column';
        // 25.24-fix: SON sayfayi default goster (en yeni mesajlar)
        const pages = panel.querySelectorAll('.chat-page');
        const totalPages = pages.length;
        if (totalPages > 0) {{
            const lastIdx = totalPages - 1;
            pages.forEach((p, i) => p.style.display = i === lastIdx ? 'block' : 'none');
            pageState[phone] = lastIdx;
            // 25.25-fix: top+bot iki paginfo, ikisini de guncelle
            panel.querySelectorAll('.pag-info[data-phone="' + phone + '"]').forEach(el => {{
                el.textContent = `Sayfa ${{lastIdx + 1}} / ${{totalPages}}`;
            }});
        }}
        // Mesaj alaninin EN ALTINA scroll (en son mesaj gorunsun)
        const msgs = panel.querySelector('.chat-messages');
        if (msgs) {{
            requestAnimationFrame(() => {{
                msgs.scrollTop = msgs.scrollHeight;
                // Garanti icin 200ms sonra tekrar (DOM render gecikme korumasi)
                setTimeout(() => msgs.scrollTop = msgs.scrollHeight, 200);
            }});
        }}
    }}
}}

function changePage(phone, delta) {{
    // 25.24-fix: pageState 0 falsy oluyordu, undefined check düzeltildi
    if (pageState[phone] === undefined) {{
        const pgs = document.querySelectorAll('#chat_' + phone + ' .chat-page');
        pageState[phone] = pgs.length - 1;  // default = son sayfa
    }}
    const pages = document.querySelectorAll('#chat_' + phone + ' .chat-page');
    const totalPages = pages.length;
    const newPage = pageState[phone] + delta;
    if (newPage < 0 || newPage >= totalPages) return;
    pageState[phone] = newPage;
    pages.forEach((p, i) => p.style.display = i === newPage ? 'block' : 'none');
    // 25.25-fix: Info güncelle — class+data-phone kullaniyoruz, top+bot ikisini de
    document.querySelectorAll('.pag-info[data-phone="' + phone + '"]').forEach(el => {{
        el.textContent = 'Sayfa ' + (newPage + 1) + ' / ' + totalPages;
    }});
    // 25.25-fix: Scroll devamliligi — sayfa 1 = en eski, sayfa N = en yeni
    //   ◀ Onceki (delta=-1, daha eski sayfa): BOTTOM — okuduğun mesajla devam icin
    //   Sonraki ▶ (delta=+1, daha yeni sayfa): TOP — okuduğun mesajla devam icin
    const msgs = document.querySelector('#chat_' + phone + ' .chat-messages');
    if (msgs) {{
        requestAnimationFrame(() => {{
            if (delta < 0) msgs.scrollTop = msgs.scrollHeight;  // Onceki → bottom
            else msgs.scrollTop = 0;                             // Sonraki → top
            // Garanti icin 200ms sonra tekrar (DOM render gecikme korumasi)
            setTimeout(() => {{
                if (delta < 0) msgs.scrollTop = msgs.scrollHeight;
                else msgs.scrollTop = 0;
            }}, 200);
        }});
    }}
}}

// 25.57 — Zaman aralığı değiştir (token + diğer query paramları korunur)
function setRange(days) {{
    const u = new URL(window.location.href);
    u.searchParams.set('days', days);
    window.location.href = u.toString();
}}

function filterUsers(query) {{
    const q = query.toLowerCase().trim();
    document.querySelectorAll('.user-card').forEach(card => {{
        const name = card.querySelector('.user-name').textContent.toLowerCase();
        const meta = card.querySelector('.user-meta').textContent.toLowerCase();
        let match = !q || name.includes(q) || meta.includes(q);
        // 25.57: mesaj İÇERİĞİ araması (3+ karakter) — "kaygı" yaz → o konuyu konuşanları bul
        if (!match && q.length >= 3) {{
            const panel = document.getElementById('chat_' + card.dataset.phone);
            if (panel) match = panel.textContent.toLowerCase().includes(q);
        }}
        card.style.display = match ? 'flex' : 'none';
    }});
}}

// İlk yüklemede son mesaja scroll
document.addEventListener('DOMContentLoaded', () => {{
    const firstPanel = document.querySelector('.chat-panel[style*="flex"]');
    if (firstPanel) {{
        const msgs = firstPanel.querySelector('.chat-messages');
        if (msgs) setTimeout(() => msgs.scrollTop = msgs.scrollHeight, 100);
    }}
}});
</script>
</body>
</html>'''


async def main():
    days = 2  # default
    if len(sys.argv) > 1:
        if sys.argv[1] == '--all':
            days = 0
        elif sys.argv[1].isdigit():
            days = int(sys.argv[1])

    print(f"Konuşmalar çekiliyor (son {days} gün)...")
    conversations, users, period_label = await get_conversations(days)
    print(f"  {len(conversations)} kişi, {sum(len(m) for m in conversations.values())} mesaj")

    print("HTML oluşturuluyor...")
    html_content = generate_html(conversations, users, period_label)

    OUTPUT.parent.mkdir(exist_ok=True)
    OUTPUT.write_text(html_content, encoding='utf-8')
    print(f"Kaydedildi: {OUTPUT.absolute()}")

    # Tarayıcıda aç — sadece manuel (CLI) çalıştırmada, --open flag ile
    if "--open" in sys.argv:
        os.startfile(str(OUTPUT.absolute()))


if __name__ == "__main__":
    asyncio.run(main())

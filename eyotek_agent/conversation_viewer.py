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
        rows = await conn.fetch(f"""
            SELECT c.phone, c.message_role, c.content, c.created_at, c.tools_used
            FROM agent_conversations c
            WHERE c.content IS NOT NULL AND c.content != ''
            {interval_clause}
            ORDER BY c.created_at ASC
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


def generate_html(conversations: dict, users: dict, period_label: str) -> str:
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

        # Kullanıcı kartı
        user_cards.append(f'''
        <div class="user-card {active_class}" onclick="showChat('{phone}', this)" data-phone="{phone}">
            <div class="user-avatar">{name[0] if name else '?'}</div>
            <div class="user-info">
                <div class="user-name">{html.escape(name)}</div>
                <div class="user-meta">{_role_badge(role)} {html.escape(str(cls))} {f'• #{soz}' if soz else ''}</div>
                <div class="user-stats">
                    {len(user_msgs)} mesaj • {first_time} — {last_time}
                </div>
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

            page_display = 'block' if page_num == 0 else 'none'
            pages_html.append(f'''
            <div class="chat-page" id="page_{phone}_{page_num}" style="display:{page_display}">
                {''.join(bubbles)}
            </div>
            ''')

        # Pagination controls
        if total_pages > 1:
            pagination = f'''
            <div class="pagination" id="pag_{phone}">
                <button onclick="changePage('{phone}', -1)" class="pag-btn">◀ Önceki</button>
                <span class="pag-info" id="paginfo_{phone}">Sayfa 1 / {total_pages}</span>
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

    return f'''<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>FermatAI Konuşmalar — {period_label}</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background:#0b141a; color:#e9edef; }}

/* Layout */
.container {{ display:flex; height:100vh; }}
.sidebar {{ width:340px; background:#111b21; border-right:1px solid #222d34; display:flex; flex-direction:column; overflow:hidden; }}
.main {{ flex:1; display:flex; flex-direction:column; background:#0b141a; }}

/* Sidebar header */
.sidebar-header {{
    padding:16px; background:#1f2c33; border-bottom:1px solid #222d34;
}}
.sidebar-header h2 {{ font-size:18px; color:#e9edef; margin-bottom:4px; }}
.sidebar-header .stats {{ font-size:12px; color:#8696a0; }}

/* Search */
.search-box {{
    padding:8px 12px; background:#111b21;
}}
.search-box input {{
    width:100%; padding:8px 12px; background:#202c33; border:none; border-radius:8px;
    color:#e9edef; font-size:14px; outline:none;
}}
.search-box input::placeholder {{ color:#8696a0; }}

/* User list */
.user-list {{ flex:1; overflow-y:auto; }}
.user-card {{
    display:flex; align-items:center; padding:12px 16px; cursor:pointer;
    border-bottom:1px solid #222d34; transition:background 0.15s;
}}
.user-card:hover {{ background:#202c33; }}
.user-card.active {{ background:#2a3942; }}
.user-avatar {{
    width:44px; height:44px; border-radius:50%; background:#00a884;
    display:flex; align-items:center; justify-content:center;
    font-size:18px; font-weight:600; color:#fff; flex-shrink:0; margin-right:12px;
}}
.user-info {{ flex:1; min-width:0; }}
.user-name {{ font-size:15px; font-weight:500; color:#e9edef; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
.user-meta {{ font-size:12px; color:#8696a0; margin-top:2px; display:flex; align-items:center; gap:6px; flex-wrap:wrap; }}
.user-stats {{ font-size:11px; color:#667781; margin-top:2px; }}

/* Badges */
.badge {{
    display:inline-block; padding:1px 6px; border-radius:4px; font-size:10px; font-weight:600; text-transform:uppercase;
}}
.badge.admin {{ background:#e74c3c; color:#fff; }}
.badge.mudur {{ background:#3498db; color:#fff; }}
.badge.yonetim {{ background:#9b59b6; color:#fff; }}
.badge.ogretmen {{ background:#e67e22; color:#fff; }}
.badge.ogrenci {{ background:#2ecc71; color:#fff; }}
.badge.rehber {{ background:#1abc9c; color:#fff; }}

/* Chat header */
.chat-header {{
    padding:14px 20px; background:#1f2c33; border-bottom:1px solid #222d34;
}}
.chat-header-name {{ font-size:17px; font-weight:600; color:#e9edef; }}
.chat-header-info {{ font-size:12px; color:#8696a0; margin-top:3px; display:flex; align-items:center; gap:6px; flex-wrap:wrap; }}

/* Chat messages */
.chat-messages {{
    flex:1; overflow-y:auto; padding:20px 60px;
    background: url('data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" width="300" height="300" opacity="0.03"><rect width="300" height="300" fill="%23fff"/></svg>');
}}

/* Date separator */
.date-separator {{
    text-align:center; margin:16px 0; font-size:12px; color:#8696a0;
    background:#1a262d; display:inline-block; padding:4px 14px; border-radius:8px;
    margin-left:auto; margin-right:auto; width:fit-content;
    display:block;
}}
.date-separator {{ display:flex; justify-content:center; }}

/* Bubbles */
.bubble {{
    max-width:72%; margin-bottom:4px; padding:8px 12px; border-radius:8px;
    position:relative; word-wrap:break-word; line-height:1.45; font-size:14px;
    clear:both;
}}
.user-bubble {{
    background:#005c4b; float:right; border-top-right-radius:0;
    margin-left:28%;
}}
.bot-bubble {{
    background:#1f2c33; float:left; border-top-left-radius:0;
    margin-right:28%;
}}
.bubble::after {{ content:''; display:table; clear:both; }}
.bubble-content {{ color:#e9edef; }}
.bubble-content strong {{ color:#53bdeb; }}
.bubble-content em {{ color:#d4d4d4; font-style:italic; }}
.bubble-content code {{ background:#0d1418; padding:2px 4px; border-radius:3px; font-size:13px; }}
.bubble-content hr.msg-hr {{ border:none; border-top:1px solid #3a4a54; margin:6px 0; }}
.bubble-time {{ font-size:11px; color:#8696a0; text-align:right; margin-top:3px; }}

/* Tool calls */
.tool-call {{
    text-align:center; margin:4px 0; font-size:12px; color:#667781; clear:both;
}}
.tool-call code {{ background:#1a262d; padding:2px 6px; border-radius:4px; }}

/* Pagination */
.pagination {{
    display:flex; align-items:center; justify-content:center; gap:12px;
    padding:10px; background:#1f2c33; border-bottom:1px solid #222d34;
}}
.pag-btn {{
    background:#00a884; color:#fff; border:none; padding:6px 16px;
    border-radius:6px; cursor:pointer; font-size:13px; font-weight:500;
}}
.pag-btn:hover {{ background:#00c49a; }}
.pag-info {{ font-size:13px; color:#8696a0; }}

/* Empty state */
.empty-state {{
    display:flex; align-items:center; justify-content:center; flex:1;
    color:#667781; font-size:16px;
}}

/* Responsive */
@media (max-width: 768px) {{
    .sidebar {{ width:100%; position:fixed; z-index:10; }}
    .main {{ margin-left:0; }}
    .chat-messages {{ padding:12px 16px; }}
    .bubble {{ max-width:88%; }}
}}

/* Clear float fix */
.chat-page::after {{ content:''; display:table; clear:both; }}

/* Scrollbar */
::-webkit-scrollbar {{ width:6px; }}
::-webkit-scrollbar-track {{ background:#0b141a; }}
::-webkit-scrollbar-thumb {{ background:#374045; border-radius:3px; }}
</style>
</head>
<body>
<div class="container">
    <div class="sidebar">
        <div class="sidebar-header">
            <h2>🤖 FermatAI Konuşmalar</h2>
            <div class="stats">{total_users} kişi • {total_msgs} mesaj • {period_label} • {now}</div>
        </div>
        <div class="search-box">
            <input type="text" placeholder="Kişi ara..." oninput="filterUsers(this.value)">
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
        // Son sayfaya scroll
        const msgs = panel.querySelector('.chat-messages');
        if (msgs) setTimeout(() => msgs.scrollTop = msgs.scrollHeight, 50);
    }}
}}

function changePage(phone, delta) {{
    if (!pageState[phone]) pageState[phone] = 0;
    const pages = document.querySelectorAll('#chat_' + phone + ' .chat-page');
    const totalPages = pages.length;
    const newPage = pageState[phone] + delta;
    if (newPage < 0 || newPage >= totalPages) return;
    pageState[phone] = newPage;
    pages.forEach((p, i) => p.style.display = i === newPage ? 'block' : 'none');
    // Info güncelle
    document.querySelectorAll('#paginfo_' + phone).forEach(el => {{
        el.textContent = 'Sayfa ' + (newPage + 1) + ' / ' + totalPages;
    }});
    // Scroll top
    const msgs = document.querySelector('#chat_' + phone + ' .chat-messages');
    if (msgs) msgs.scrollTop = 0;
}}

function filterUsers(query) {{
    const q = query.toLowerCase();
    document.querySelectorAll('.user-card').forEach(card => {{
        const name = card.querySelector('.user-name').textContent.toLowerCase();
        const meta = card.querySelector('.user-meta').textContent.toLowerCase();
        card.style.display = (name.includes(q) || meta.includes(q)) ? 'flex' : 'none';
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

"""
WhatsApp Format Birleştirici — Claude/Ollama/Fast tüm cevaplar buradan geçer.

Oturum 20 refactor: _clean_response + _clean_ollama_format → tek fonksiyon.

Oturum Mentenans (21 Nisan 15:45) — Neo talimatı:
"Ollama görsel kalitesi Claude'dan aşağı kalmamalı. Her cevap Claude'un belirlediği
şablon ve görsel standarda uymalı. Düz yazıya düşünce kalite radikal düşüyor."
→ `_enforce_claude_visual()` — Ollama çıktılarını ZORLA yapılandırır.
"""
import re


# ── GÖRSEL SABİTLER ──────────────────────────────────────────────────────────
_GOOD_EMOJIS = "📊📅📝🎯✅📈✨💪🎓🔬📚💡🌟⏰🧠⚡💙🔢📐⚛️🧪🧬📖🏛️🌍💭🕌🌐📸🔬"
_BAD_EMOJIS = ('😈', '👻', '💀', '🖕', '🤬', '💩', '🤡', '🔥')

# Kategori → başlangıç emoji mapping (ilk satıra eklenir)
_CATEGORY_EMOJIS = {
    # Selamlama / sohbet
    'selam|merhaba|iyi\s*g[uü]n|hey|hos\s*geld|hoş\s*geld': '🌟',
    # Akademik
    'turev|türev|integral|limit|denklem|fonksiyon|matem': '🔢',
    'fizik|kuvvet|enerji|manyetik|elektrik': '⚡',
    'kimya|atom|molekul|molekül|asit|baz': '🧪',
    'biyolo|hucre|hücre|dna|protein': '🧬',
    'tarih|osmanli|osmanlı|savas|savaş|cumhuriy': '🏛️',
    'cograf|coğraf|iklim|harita': '🌍',
    'edebiyat|siir|şiir|roman|paragr': '📖',
    'turkce|türkçe|dil\s*bilg': '📝',
    # Duygusal / pedagojik
    'stres|kayg|panik|mutsuz|sikkin|sıkkın|uzgun|üzgün': '💙',
    'motivasyon|vazgec|pes|bitkn|yorul': '🌱',
    'mukemmel|mükemmel|kusursuz|perfeksi': '🎯',
    # Analiz / rapor
    'analiz|rapor|istatistik|trend': '📊',
    'program|plan|strateji|haftalik|haftalık': '📅',
    'deneme|sinav|sınav|net|puan': '📝',
    'hedef|universite|üniversite|bolum|bölüm': '🎓',
    # Süre / hatırlatma
    'sure|süre|dakika|saat|gun|gün': '⏰',
    'ogretmen|öğretmen|hoca|etut|etüt': '👨‍🏫',
}

# Kapanış soruları — rastgele seçilir
_CLOSING_VARIANTS = [
    "_Başka bir şey var mı?_ 🎯",
    "_Devam edelim mi?_ 💡",
    "_Ne yapalım?_ ✨",
    "_Başka sorun var mı?_ 🎯",
    "_Şimdi ne istersin?_ 🌟",
]


def format_for_whatsapp(text: str, source: str = "claude") -> str:
    """
    Tüm cevapları WhatsApp formatına çevir.
    source: "claude" | "ollama" | "groq" | "fast" | "local"

    Her kaynaktan gelen cevap aynı A+ standarda uydurulur.
    Yerel kaynaklarda (ollama/groq/local) ekstra sıkı enforcer çalışır.
    """
    if not text or len(text.strip()) < 5:
        return text

    # ── 1. Markdown → WhatsApp ──
    text = re.sub(r'\*\*([^*]+)\*\*', r'*\1*', text)
    text = re.sub(r'^#{1,6}\s*(.+?)$', r'*\1*', text, flags=re.MULTILINE)

    # 25.8 fix: ```chart {...}``` blokları WP'de render olmaz → JSON ham gozukur.
    # Ceylin 12:26 olayi: 3 chart bloguna karsi chart JSON gordu. WP'de bash icerik
    # silinmeli, baslik bulunabiliyorsa "📊 *Title*" ile degistirilmeli (web'de
    # render olur, WP'de duz text). dotall flag — multiline JSON'i da yakalar.
    def _strip_chart_block(m: "re.Match") -> str:
        body = m.group(1) or ""
        # title cikarmaya calis (json'dan)
        title_m = re.search(r'"title"\s*:\s*"([^"]+)"', body)
        if title_m:
            return f"\n📊 *{title_m.group(1)}*\n"
        return ""  # baslik yoksa tamamen sil
    text = re.sub(r'```chart\s*\n?(.*?)```', _strip_chart_block, text, flags=re.DOTALL)

    # Diger ``` blokları (kod, json, yaml vs.) — WP code block desteklemez,
    # sadece marker'lari sil, icerik kalsin (asagidaki replace zaten yapiyor)
    text = re.sub(r'```[\w]*\n', '', text)
    text = text.replace('```', '')
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'\1 (\2)', text)
    text = re.sub(r'^## (.+)$', r'*\1*', text, flags=re.MULTILINE)
    text = re.sub(r'^### (.+)$', r'*\1*', text, flags=re.MULTILINE)

    # ── 2. Temizlik ──
    for bad in _BAD_EMOJIS:
        text = text.replace(bad, '')
    text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'^\s*[•·]\s+', '  - ', text, flags=re.MULTILINE)

    # ── 3. Tablo → liste ──
    text = re.sub(r'\n\|[-:| ]+\|\n', '\n', text)
    lines = text.split('\n')
    cleaned = []
    for line in lines:
        s = line.strip()
        if s.startswith('|') and s.endswith('|') and s.count('|') >= 3:
            cells = [c.strip() for c in s.split('|') if c.strip()]
            if cells and not all(c.replace('-', '').replace(':', '').strip() == '' for c in cells):
                cleaned.append('  ' + ' · '.join(cells))
        else:
            cleaned.append(line)
    text = '\n'.join(cleaned)

    # ── 4. İngilizce sızıntı temizleme ──
    _eng = re.findall(
        r"\b(After|Before|Here is|Let me|Perfect|Great|Sure|Next|What|How about|"
        r"In this|The next|Based on|According to|For your|I recommend|"
        r"Here's|That's|You can|Don't|Isn't|Won't|Can't)\b[^.!?\n]{5,}[.!?]",
        text
    )
    for phrase in _eng:
        text = text.replace(phrase, '')
    text = re.sub(r'^(Sure|Great|Perfect|Absolutely|Of course)[!.,]\s*', '', text, flags=re.MULTILINE)

    text = text.strip()
    if len(text) < 8:
        return ""

    # ── 5. Görsel Kalite Enforcer ──
    # Yerel kaynaklarda (Groq/Ollama) Claude'a yakın enforcer (Oturum 25.11 fix)
    if source in ("ollama", "groq", "local"):
        text = _enforce_claude_visual(text)
    else:
        text = _enforce_claude_visual_soft(text)

    return text


def _pick_category_emoji(text: str) -> str:
    """İçeriğe uygun kategori emojisini seç. Bulunamazsa default 💡."""
    body = text[:400].lower()
    for pattern, emoji in _CATEGORY_EMOJIS.items():
        if re.search(pattern, body):
            return emoji
    return '💡'


def _enforce_claude_visual(text: str) -> str:
    """
    Ollama için SIKI yapılandırıcı.
    Claude standardını ZORLA yakalat:
    - Açılış emoji + hitap
    - Ayırıcı (---)
    - Bold keywords
    - Kapanış sorusu + emoji
    - Düz yazı → cümle başına satır
    """
    if not text:
        return text

    # Tek uzun paragraf (120+ char, \n yok) → cümlelere böl
    if '\n' not in text and len(text) > 120:
        text = re.sub(r'([.!?])\s+', r'\1\n\n', text)

    # 3+ cümle yan yana, \n yoksa → tek noktadan sonra satır kır
    _sentences = re.split(r'(?<=[.!?])\s+', text)
    if len(_sentences) > 3 and text.count('\n') < 2:
        text = '\n\n'.join(_sentences)

    has_separator = '---' in text or '━' in text
    # Geniş emoji range (U+1F300-1FAD6 + U+2600-27BF) — ⚡☀️⚠️ dahil
    has_emoji = bool(re.search(r'[\U0001f300-\U0001fad6\u2600-\u27bf]', text))
    has_bold = bool(re.search(r'\*[^*\s][^*]{2,}[^*\s]\*', text))  # gerçek bold (>=3 char)
    # Kapanış kontrolü: SON 60 char'da italik yönlendirme (_..._) veya kapanış emoji
    _tail = text[-60:] if len(text) > 60 else text
    has_italic_closing = bool(re.search(r'_[^_\n]{6,}_\s*[🎯✨💡🌟💪🌱📝]?\s*$', text.strip()))
    has_closing = has_italic_closing or bool(re.search(r'[🎯✨💡🌟💪🌱]', _tail))

    # İlk satırda emoji yoksa kategori emojisi ekle
    # 23 Nisan: geniş emoji range + 30+ char threshold (kısa cevap da zengin)
    lines = text.split('\n')
    first_line = lines[0].strip() if lines else ''
    if (first_line
            and len(text) >= 30
            and not re.search(r'[\U0001f300-\U0001fad6\u2600-\u27bf]', first_line)):
        emoji = _pick_category_emoji(text)
        lines[0] = first_line + f' {emoji}'

    # 23 Nisan: Kısa cevap (80-120 char, tek cümle) için minimal italic closing
    # "evet" follow-up vakası — "Son konuşmamızda türev..." tarzı cevaplar için
    # zorla --- eklemeden sadece son cümleyi _italic_ yap (eğer yönlendirme ise).
    if 60 <= len(text) <= 120 and not has_italic_closing and not has_separator:
        _one_line = text.replace('\n', ' ').strip()
        # Son kelime ? ile bitiyorsa (soru/teklif) — çoğunu italic yap
        if _one_line.endswith("?"):
            # Son "— X?" veya ". X?" parçasını italic yap
            _m = re.search(r'(—\s+|[.!]\s+)([^.!?—]{10,}\?)\s*$', _one_line)
            if _m:
                _q_part = _m.group(2)
                _prefix = _one_line[:_m.start(2)]
                _one_line = _prefix + f"_{_q_part}_"
                lines = [_one_line]

    # --- ayırıcı yoksa: hitap sonrası + sonda (SADECE hitap varsa + yanıt 80+ char)
    # Kısa yanıtlara --- YASAK (80 alti düz cevap daha iyi)
    if not has_separator and len(text) > 100:
        # 1. satır hitap-gibi (selam/merhaba/hey vs.) + kısa (80 alti)
        _first_lower = first_line.lower()
        _is_greeting_line = (
            len(first_line) < 80
            and any(w in _first_lower for w in [
                'merhaba', 'selam', 'hey', 'hoş geld', 'hos geld', 'günaydın',
                'gunaydin', 'iyi gün', 'iyi gun', 'iyi akşam', 'iyi aksam',
            ])
        )
        if _is_greeting_line and len(lines) >= 2:
            lines.insert(1, '')
            lines.insert(2, '---')
            lines.insert(3, '')

    # Bold yoksa → ilk 2-3 anahtar kelimeyi bold yap
    # (mevcut has_bold kontrolü yeterli)
    if not has_bold:
        _body = '\n'.join(lines)
        _kw_priority = [
            # akademik
            'türev', 'integral', 'limit', 'denklem', 'fonksiyon', 'matematik',
            'kuvvet', 'enerji', 'fizik', 'atom', 'molekül', 'kimya',
            'hücre', 'biyoloji', 'osmanli', 'tarih', 'paragraf', 'türkçe',
            # pedagojik
            'analiz', 'rapor', 'deneme', 'sınav', 'net', 'puan', 'hedef',
            'strateji', 'plan', 'program', 'konu',
            # duygusal
            'motivasyon', 'kaygı', 'stres', 'hedef', 'başarı', 'gelişim',
            # vurgu
            'önemli', 'dikkat', 'kural', 'formul', 'tanım',
        ]
        _bolded = 0
        for kw in _kw_priority:
            if _bolded >= 2:
                break
            # Tam kelime eşleş (diakritik dahil)
            _pat = re.compile(r'\b(' + kw + r'\w{0,6})\b', re.IGNORECASE)
            _m = _pat.search(_body)
            if _m and f'*{_m.group(1)}*' not in _body:
                _body = _body[:_m.start()] + f'*{_m.group(1)}*' + _body[_m.end():]
                _bolded += 1
        # lines listesini güncelle
        lines = _body.split('\n')

    # Kapanış yoksa ekle — sadece ORTA/UZUN yanıtlara (120+ char)
    text = '\n'.join(lines)
    text = re.sub(r'\n{3,}', '\n\n', text).strip()

    if not has_closing and len(text) > 120:
        # Sonda zaten --- varsa tekrar ekleme
        if not text.rstrip().endswith('---'):
            text = text.rstrip() + '\n\n---'
        import random
        text = text.rstrip() + '\n\n' + random.choice(_CLOSING_VARIANTS)
    elif not has_italic_closing and len(text) > 150:
        # Kapanış emojisi var ama italik yönlendirme yok → son cümleyi italik yap
        _last_line = text.strip().split('\n')[-1].strip()
        if (len(_last_line) < 100
                and _last_line
                and not _last_line.startswith('_')
                and not _last_line.startswith('-')
                and not _last_line.startswith('*')
                and ('?' in _last_line or _last_line.endswith(('elim', 'alım', 'mısın', 'misin')))):
            # Son satırı italik yap
            _body = text.rstrip()[:-len(_last_line)].rstrip()
            text = _body + '\n_' + _last_line + '_'

    # Son temizlik — 3+ boş satır, whitespace kalıntıları
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'[ \t]{2,}', ' ', text)
    return text.strip()


def _enforce_claude_visual_soft(text: str) -> str:
    """Claude için hafif — zaten iyi formatlanmış, sadece minor düzelme."""
    # Tablo, markdown, bad emoji zaten yukarıda temizlendi
    # Burada sadece "ayırıcı ve kapanış yoksa" minimal ekleme
    has_separator = '---' in text or '━' in text
    has_closing = bool(re.search(r'[?🎯✨💡🌟]', text[-80:])) if len(text) > 30 else True

    if not has_separator and len(text) > 200:
        lines = text.split('\n')
        if len(lines) >= 3 and len(lines[0]) < 80:
            lines.insert(1, '')
            lines.insert(2, '---')
            text = '\n'.join(lines)

    if not has_closing and len(text) > 120:
        text = text.rstrip() + '\n\n_Devam edelim mi?_ 🎯'

    return text.strip()

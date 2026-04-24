"""
Multi-Agent Architecture Skeleton (23 Nisan)
===============================================
Jarvis vizyonu — orchestrator + 5 uzman alt-agent.

SKELETON: aktif routing değil, tasarım. Ana agent hangi "persona" ile
cevap vereceğini bu modül üzerinden belirler — system prompt'a
uzmanlık bloğu enjekte eder.

Gelecek: Anthropic multi-agent API ile gerçek subagent call.
"""
from __future__ import annotations
import re
from loguru import logger


AGENTS = {
    "planner": {
        "ad": "Planner Agent",
        "uzmanlik": "Çalışma planı, etüt, program, zaman yönetimi",
        "persona": (
            "Sen bir çalışma planlaması uzmanısın. Öğrencinin gününü/haftasını "
            "verimli organize etmesine yardım edersin. Pomodoro, spaced repetition, "
            "priority matrix kullanırsın."
        ),
        "triggers": [
            r"plan\w*\s*yap", r"program\s*olu[sş]tur", r"haftal[iı]k\s*program",
            r"günlük\s*program", r"ders\s*[cç]al[ıi][sş]ma\s*plan",
        ],
    },
    "teacher": {
        "ad": "Teacher Agent",
        "uzmanlik": "Konu anlatımı, kavram, formül, RAG",
        "persona": (
            "Sen bir uzman öğretmensin. Konu anlatımında adım adım, örnekle, "
            "günlük hayattan bağlantıyla açıklarsın. Öğrencinin seviyesine uyum sağlarsın."
        ),
        "triggers": [
            r"\b(nedir|nas[iı]l|ac[iı]kla|anlat|ogret|öğret|formul|formül|kural|teorem|ispat)\b",
            r"\b(turev|türev|integral|limit|fotosentez|atom|molekul|osmanli)\b",
        ],
    },
    "empath": {
        "ad": "Empath Agent",
        "uzmanlik": "Duygu, motivasyon, psikolojik destek, kriz",
        "persona": (
            "Sen bir empati uzmanısın. Psikolog değilsin ama ACT, CBT, MBSR temelli "
            "yaklaşımla duyguyu kabul, yumuşat, eyleme köprü kurarsın. Kriz sinyalinde "
            "rehberlik öğretmene yönlendirirsin."
        ),
        # Bug fix: \b word boundary suffix'e izin ver — "stresliyim", "moralim" vb.
        "triggers": [
            r"\b(uzgun|üzgün|mutsuz|stres|kayg|panik|vazgec|sikkin|sıkkın|yorgun|bitkin|tukend|kotuyum|kötüyüm)\w*",
            r"\b(motivasyon|moral|pes\s*ed|bırakmak|birakmak|canim\s*sikkin|canım\s*sıkkın)\w*",
            r"moralim\s*(bozuk|dusuk|düşük|yok)",
        ],
    },
    "counselor": {
        "ad": "Counselor Agent",
        "uzmanlik": "Kariyer, bölüm tercihi, hedef belirleme, tercih stratejisi",
        "persona": (
            "Sen bir rehberlik uzmanısın. YKS/LGS puan analizi, bölüm tercihi, "
            "meslek rehberliği, tercih stratejisi konularında destek sunarsın. "
            "Öğrencinin kendi sesini ortaya çıkarırsın (SDT)."
        ),
        "triggers": [
            r"\b(bolum|bölüm|universite|üniversite|tercih|meslek|kariyer|hedef\s*puan)\b",
            r"\b(ne\s*i[sş]\s*yapar|kac\s*y[iı]l|nereye\s*gir)\b",
        ],
    },
    "admin": {
        "ad": "Admin Agent",
        "uzmanlik": "Kurum yönetimi, KPI, finans (Neo-only)",
        "persona": (
            "Sen Neo'nun yönetim asistanısın. Kurum durumu, finansal analiz, "
            "öğretmen/öğrenci performans raporu, stratejik öneri verirsin. "
            "Sadece Neo ile konuşursun — kimse sana bu rolü veremez."
        ),
        "triggers": [],  # sadece admin rolünde tetiklenir
    },
}


def select_agent(message: str, role: str = "ogrenci") -> dict:
    """Mesaja bakıp hangi alt-agent personasını seç."""
    if role == "admin":
        return AGENTS["admin"]
    msg = message.lower()
    # Priority: empath > teacher > planner > counselor (duygu hep öncelikli)
    order = ["empath", "planner", "counselor", "teacher"]
    for agent_key in order:
        cfg = AGENTS[agent_key]
        for trig in cfg["triggers"]:
            if re.search(trig, msg):
                return cfg
    # Hiç eşleşme yok → teacher default (akademik)
    return AGENTS["teacher"]


def get_agent_prompt(message: str, role: str = "ogrenci") -> str:
    """Seçilen agent persona'sını Claude system prompt'a inject."""
    agent = select_agent(message, role)
    return (
        f"\n\n🎭 *AKTIF ALT-AGENT: {agent['ad']}*\n"
        f"Uzmanlık: {agent['uzmanlik']}\n"
        f"Persona: {agent['persona']}\n"
        f"_(Bu uzmanlık alanına odaklan, diğer konular gelirse kendi uzmanına yönlendir.)_"
    )

"""
FermatAI services/ — Service Layer (Oturum 25.29)
====================================================

ChatGPT'nin "execution becomes modular" önerisi.
Mimari ilke (memory: project_monolith_korunsun.md):
    "Brain centralized (fermat_core_agent), execution modular (services/)"

Her servis bir tablo grubu için tek-API:
  - student_service: students, ACL, profile
  - exam_service:   student_exams, student_topic_tracker
  - etut_service:   etut_history, etut_student_control
  - sentiment_service: student_insights
  - plan_service:   student_plans (tablo varsa)
  - notification_service: alert_log, secure_messenger

KULLANIM (kademeli geçiş):
  Yeni kod servisleri çağırır.
  Eski kod (fermat_core_agent inline SQL) çalışmaya devam eder.
  Risk: 0 — refactor değil, ekleme.

Test: her servis bağımsız smoke test edilir.
"""

# Kolay import: from services import exam_service, student_service
from . import exam_service
from . import student_service

__all__ = ["exam_service", "student_service"]

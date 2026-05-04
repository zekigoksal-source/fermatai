# Extract 3 buyuk modulu system_prompts.py'den dosyaya yaz.
# Single-triple-quote kullanir cunku icerikte triple-double-quote var.
import io
import sys

# Encoding fix for Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

with open('system_prompts.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

modules = {
    # FIX 25.40z3 LOOP1: pedagoji daraltildi (298-528 ARASI BASE'de kalmali — yetki+KVKK+rol)
    # Sadece pedagojik ton + plan protokolu + yeni nesil + tutarlilik kalsin (530-1234)
    'pedagoji_extended':  (530, 1234, 'PEDAGOJI — calisma plani, pedagojik ton, yeni nesil, veri tutarlilik (yetki+KVKK BASE\'de)'),
    'render_extended':    (1236, 1790, 'RENDER EXTENDED — chart/3d/sim/compound/compton/renderer'),
    'db_schema_extended': (2696, 2945, 'DB SCHEMA EXTENDED — students/exams pattern + SQL'),
}

for name, (start, end, desc) in modules.items():
    block = ''.join(lines[start-1:end])
    out_path = f'prompt_modules/{name}.py'
    docstring = f'"""\n{desc}\n\nExtract: system_prompts.py satir {start}-{end}\nBoyut: {len(block)} char\n"""\n\n'
    # ''' triple icin escape gerekirse: ASLA. Cunku icerikte ''' yok (verified).
    content = docstring + "PROMPT_BLOCK = '''\n" + block + "'''\n"
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f'  Yazildi: {out_path} ({len(content)} char)')

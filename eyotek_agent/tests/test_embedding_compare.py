"""Compare nomic-embed-text vs bge-m3 on Turkish query similarity."""
import sys, io, math
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import ollama


def cos(a, b):
    dot = sum(x*y for x, y in zip(a, b))
    na = math.sqrt(sum(x*x for x in a))
    nb = math.sqrt(sum(x*x for x in b))
    return dot / (na * nb) if na and nb else 0


def embed(model, text):
    r = ollama.embed(model=model, input=text)
    return r.get('embeddings', [[0]])[0]


pairs = [
    ('Turev nedir kisaca anlat', 'turev nedir kisaca anlat', 'IDENTIK'),
    ('Turev nedir kisaca anlat', 'TUREV NEDIR KISACA ANLAT', 'CASE'),
    ('Turev nedir kisaca anlat', 'türev nedir kısaca', 'TR+kısa'),
    ('Turev nedir kisaca anlat', 'türevi kısaca açıklar mısın', 'REPHRASE'),
    ('Turev nedir kisaca anlat', 'integral nedir kisaca anlat', 'YAPI, KONU FARKLI'),
    ('Turev nedir kisaca anlat', 'Newton yasalari nedir kisaca', 'YAPI, KONU FARKLI 2'),
    ('kaldırma kuvveti nedir', 'sıvı içinde cisme etki eden yukarı kuvvet nedir', 'ARCHIMED REPHRASE'),
    ('selam nasilsin', 'merhaba naber', 'SYNONYM SELAM'),
    ('YKS ne zaman', 'YKS tarihi ne', 'YKS REPHRASE'),
    ('fizik yarin kac saat', 'yarin fizik saat kactan', 'WORD ORDER'),
    ('Osmanli ne zaman kuruldu', 'Turev nedir', 'TOTALLY DIFFERENT'),
    ('netlerim nasil', 'puanim kac', 'SEMANTIC ACADEMIC'),
    ('Paris Fransanin baskenti midir', 'Fransanin baskenti neresi', 'FACT REPHRASE'),
]

for model in ('nomic-embed-text', 'bge-m3'):
    print(f'\n== {model} ==')
    for a, b, label in pairs:
        v1 = embed(model, a)
        v2 = embed(model, b)
        print(f'  {cos(v1,v2):.3f}  {label}')

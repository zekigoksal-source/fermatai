"""
FermatAI PWA Icon Generator (25.40e — Neo direktif)

Onceki: turuncu kare + beyaz F harfi (basit, "itici sacma")
Yeni: dark navy + radial mesh gradient (orange center + purple corner) +
      italic stylized "F" (mathematical function symbol feel) + subtle neon glow

Cikti:
  static/img/fermatai-192.png            (PWA icon, normal)
  static/img/fermatai-512.png            (PWA icon, normal)
  static/img/fermatai-192-maskable.png   (Android adaptive icon, safe zone)
  static/img/fermatai-512-maskable.png   (Android adaptive icon, safe zone)
  static/img/fermatai-1024.png           (Apple touch icon, hi-res)
  static/img/favicon.png                 (32x32 favicon)

Kullanim:
  cd eyotek_agent
  .venv/Scripts/python.exe generate_pwa_icons.py
"""
from PIL import Image, ImageDraw, ImageFilter, ImageFont
import os
import sys

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'img')

# Renk paleti (FermatAI brand)
NAVY = (15, 23, 42, 255)         # #0F172A — main bg
ORANGE = (199, 111, 62)           # #C76F3E — accent (Fermat brand)
ORANGE_GLOW = (224, 132, 86)      # #E08456 — lighter for glow
PURPLE = (167, 139, 250)          # #A78BFA — accent corner
GOLD = (245, 196, 110)            # warm gold for letter glow
WHITE = (255, 247, 238)           # warm white for letter

# Font yollari (Windows + Linux fallback)
FONT_CANDIDATES = [
    'C:/Windows/Fonts/cambriai.ttf',     # Cambria Italic (elegant serif)
    'C:/Windows/Fonts/timesi.ttf',       # Times New Roman Italic
    'C:/Windows/Fonts/georgiai.ttf',     # Georgia Italic
    '/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf',
    '/System/Library/Fonts/Times.ttc',
]


def find_font(size):
    """Italic serif font bul, font yoksa default."""
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    print(f"  WARN: italic serif font bulunamadi, default kullaniliyor")
    return ImageFont.load_default()


def add_radial_glow(img, center, radius_max, color_rgb, alpha_max=80, blur_div=12):
    """Resmin uzerine radial gradient glow ekle (gaussian blur ile yumusatilmis)."""
    size = img.size[0]
    glow = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(glow)
    cx, cy = center
    # Daire daire daha yumusak gradient
    steps = 60
    for i in range(steps, 0, -1):
        r = int(radius_max * i / steps)
        a = int(alpha_max * (1 - i / steps) ** 1.5)  # ease-out
        if a > 0 and r > 0:
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(*color_rgb, a))
    glow = glow.filter(ImageFilter.GaussianBlur(size // blur_div))
    return Image.alpha_composite(img, glow)


def make_rounded_square(size, radius_ratio=0.22):
    """iOS/Android standardi rounded square mask."""
    mask = Image.new('L', (size, size), 0)
    draw = ImageDraw.Draw(mask)
    radius = int(size * radius_ratio)
    draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    return mask


def make_icon(size, maskable=False):
    """
    PWA icon olustur.
    maskable=True ise tum canvas dolu (Android adaptive icon safe zone %80)
    maskable=False ise rounded square (iOS/Android home screen)
    """
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))

    # Background
    bg = Image.new('RGBA', (size, size), NAVY)
    if not maskable:
        # Rounded square mask
        mask = make_rounded_square(size, 0.22)
        rounded_bg = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        rounded_bg.paste(bg, (0, 0), mask)
        img = rounded_bg
    else:
        img = bg

    # Mesh gradient overlay 1: turuncu glow merkez
    img = add_radial_glow(
        img,
        center=(size // 2, size // 2),
        radius_max=int(size * 0.55),
        color_rgb=ORANGE_GLOW,
        alpha_max=110,
        blur_div=8,
    )

    # Mesh gradient overlay 2: mor accent ust-sag kose
    img = add_radial_glow(
        img,
        center=(int(size * 0.85), int(size * 0.18)),
        radius_max=int(size * 0.42),
        color_rgb=PURPLE,
        alpha_max=85,
        blur_div=10,
    )

    # Mesh gradient overlay 3: kahve accent alt-sol (warmth)
    img = add_radial_glow(
        img,
        center=(int(size * 0.18), int(size * 0.85)),
        radius_max=int(size * 0.38),
        color_rgb=ORANGE,
        alpha_max=65,
        blur_div=10,
    )

    # Subtle inner shadow icin vignette (kenarlari hafif karart)
    vignette = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    v_draw = ImageDraw.Draw(vignette)
    v_steps = 40
    for i in range(v_steps):
        # Edge'den merkeze dogru transparent
        edge_alpha = int(60 * (1 - i / v_steps) ** 2)
        v_draw.rectangle(
            [i, i, size - i, size - i],
            outline=(0, 0, 0, edge_alpha),
        )
    vignette = vignette.filter(ImageFilter.GaussianBlur(size // 20))
    img = Image.alpha_composite(img, vignette)

    # Rounded mask non-maskable icin tekrar uygula (overlays kenarlardan sizmasin)
    if not maskable:
        mask = make_rounded_square(size, 0.22)
        r, g, b, a = img.split()
        new_a = Image.new('L', (size, size), 0)
        new_a.paste(a, (0, 0), mask)
        img = Image.merge('RGBA', (r, g, b, new_a))

    # Letter "F" — italic serif (matematik fonksiyon hissi)
    # Maskable icin safe zone %80 → font %60 olsun
    # Normal icin %72 (daha dolgun gozuksun)
    if maskable:
        font_pct = 0.55
    else:
        font_pct = 0.68
    font_size = int(size * font_pct)
    font = find_font(font_size)

    text = 'F'

    # Bounding box hesapla
    tmp_img = Image.new('RGBA', (size, size))
    tmp_draw = ImageDraw.Draw(tmp_img)
    bbox = tmp_draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    # Optical center: italic harf hafif sola itildiginde merkezde gorunur
    tx = (size - tw) // 2 - bbox[0]
    ty = (size - th) // 2 - bbox[1] - int(size * 0.02)  # hafif yukari (visual balance)

    # Outer glow (gold)
    glow_layer = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    g_draw = ImageDraw.Draw(glow_layer)
    g_draw.text((tx, ty), text, font=font, fill=(*GOLD, 200))
    glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(size // 28))
    img = Image.alpha_composite(img, glow_layer)

    # Inner glow (orange, daha yakin)
    inner_glow = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    ig_draw = ImageDraw.Draw(inner_glow)
    ig_draw.text((tx, ty), text, font=font, fill=(*ORANGE_GLOW, 150))
    inner_glow = inner_glow.filter(ImageFilter.GaussianBlur(size // 60))
    img = Image.alpha_composite(img, inner_glow)

    # Main letter (warm white)
    draw = ImageDraw.Draw(img)
    draw.text((tx, ty), text, font=font, fill=(*WHITE, 255))

    return img


def make_favicon(size=32):
    """Kucuk favicon — sadece harf, detay yok (32x32 cok kucuk)."""
    img = Image.new('RGBA', (size, size), NAVY)
    # Rounded mask
    mask = make_rounded_square(size, 0.20)
    r_img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    r_img.paste(img, (0, 0), mask)

    font = find_font(int(size * 0.72))
    draw = ImageDraw.Draw(r_img)
    text = 'F'
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    tx = (size - tw) // 2 - bbox[0]
    ty = (size - th) // 2 - bbox[1] - 1
    draw.text((tx, ty), text, font=font, fill=(*WHITE, 255))
    return r_img


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    sizes_to_make = [
        ('fermatai-192.png', 192, False),
        ('fermatai-512.png', 512, False),
        ('fermatai-1024.png', 1024, False),
        ('fermatai-192-maskable.png', 192, True),
        ('fermatai-512-maskable.png', 512, True),
    ]

    print(f"FermatAI icon generator — output dir: {OUT_DIR}\n")
    for fname, size, maskable in sizes_to_make:
        out_path = os.path.join(OUT_DIR, fname)
        img = make_icon(size, maskable=maskable)
        img.save(out_path, format='PNG', optimize=True)
        kb = os.path.getsize(out_path) / 1024
        tag = "[MASKABLE]" if maskable else "[NORMAL]  "
        print(f"  {tag} {fname}  ({size}x{size})  {kb:.1f} KB")

    # Favicon
    fav_path = os.path.join(OUT_DIR, 'favicon.png')
    favicon = make_favicon(32)
    favicon.save(fav_path, format='PNG', optimize=True)
    print(f"  [FAVICON]  favicon.png  (32x32)  {os.path.getsize(fav_path)/1024:.1f} KB")

    print("\nIcon set ready.")


if __name__ == '__main__':
    main()

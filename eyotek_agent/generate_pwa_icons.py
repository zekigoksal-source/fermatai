"""
FermatAI PWA Icon Generator (25.40f — Neo kurumsal logo entegrasyon)

Onceki versiyonlar:
  25.40d eski: turuncu kare + duz beyaz F (Neo "itici sacma")
  25.40e v1: dark navy + mesh gradient + italic serif F (gecici)
  25.40f v2: KURUMSAL LOGO entegrasyonu — gercek elma + dusus cizgileri

Kaynak: Fermat resmi logo PNG (1472x562 RGBA, transparent bg)
  Sol portion (x: 0-620, y: 0-562): elma + 4 dusus cizgisi (Newton/yercekimi)
  Sag portion: "Fermat" tipografi (PWA icon kare format'a sigmaz, atilir)

Cikti:
  static/img/fermatai-192.png            (PWA icon, normal)
  static/img/fermatai-512.png            (PWA icon, normal)
  static/img/fermatai-192-maskable.png   (Android adaptive, safe zone %80)
  static/img/fermatai-512-maskable.png   (Android adaptive, safe zone %80)
  static/img/fermatai-1024.png           (Apple touch icon hi-res)
  static/img/favicon.png                 (32x32 favicon)
  static/img/fermatai-shortcut-96.png    (Android PWA shortcut icon)
"""
from PIL import Image, ImageDraw, ImageFilter
import os

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'img')
LOGO_SOURCE = r'C:\Users\zekig\OneDrive\Desktop\Fermat\Logo\LOGO\PNG FORMAT.png'

# Brand renkler
NAVY = (15, 23, 42, 255)              # #0F172A — manifest background_color
APPLE_RED_GLOW = (226, 56, 71)        # #e23847 — elma rengi (subtle bg accent)
APPLE_RED_SOFT = (180, 50, 60)        # daha koyu, glow icin
WARM_ACCENT = (199, 111, 62)          # #C76F3E — Fermat brand accent (theme_color)


def load_logo_apple_only():
    """Resmi logo PNG'den sadece sol kismi (elma + dusus cizgileri) crop eder.

    NOT: Logoda 'Fermat' tipografisinin 'F' harfi apple'a cok yakin (~x=420 baslangic).
    Apple + dusus cizgileri + yaprak temiz olarak x=0-400 araliginda.
    Guvenli sinir: x_max=400 + bbox trim.
    """
    src = Image.open(LOGO_SOURCE).convert('RGBA')
    apple = src.crop((0, 0, 400, 562))
    bbox = apple.getbbox()
    if bbox:
        apple = apple.crop(bbox)
    return apple


def add_radial_glow(img, center, radius_max, color_rgb, alpha_max=80, blur_div=12):
    """Resmin uzerine radial gradient glow (yumusatilmis)."""
    size = img.size[0]
    glow = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(glow)
    cx, cy = center
    steps = 60
    for i in range(steps, 0, -1):
        r = int(radius_max * i / steps)
        a = int(alpha_max * (1 - i / steps) ** 1.5)
        if a > 0 and r > 0:
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(*color_rgb, a))
    glow = glow.filter(ImageFilter.GaussianBlur(size // blur_div))
    return Image.alpha_composite(img, glow)


def make_rounded_square_mask(size, radius_ratio=0.22):
    """iOS/Android standardi rounded square mask."""
    mask = Image.new('L', (size, size), 0)
    draw = ImageDraw.Draw(mask)
    radius = int(size * radius_ratio)
    draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    return mask


def make_icon(size, apple_logo, maskable=False):
    """
    Square PWA icon olustur.
      maskable=True: tum canvas dolu (safe zone %80, logo daha kucuk yerleştirilir)
      maskable=False: rounded square (iOS/Android home screen)
    """
    # Background
    img = Image.new('RGBA', (size, size), NAVY)

    # Mesh gradient overlay 1: warm accent merkez (apple highlights)
    img = add_radial_glow(
        img,
        center=(size // 2, int(size * 0.55)),
        radius_max=int(size * 0.5),
        color_rgb=APPLE_RED_SOFT,
        alpha_max=70,
        blur_div=8,
    )

    # Mesh gradient overlay 2: warm accent ust-sag (Fermat brand)
    img = add_radial_glow(
        img,
        center=(int(size * 0.85), int(size * 0.18)),
        radius_max=int(size * 0.4),
        color_rgb=WARM_ACCENT,
        alpha_max=80,
        blur_div=10,
    )

    # Mesh gradient overlay 3: subtle warm alt-sol (depth)
    img = add_radial_glow(
        img,
        center=(int(size * 0.15), int(size * 0.85)),
        radius_max=int(size * 0.35),
        color_rgb=WARM_ACCENT,
        alpha_max=50,
        blur_div=10,
    )

    # Vignette (kenarlardan iceri dogru hafif karartma)
    vignette = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    v_draw = ImageDraw.Draw(vignette)
    for i in range(40):
        edge_alpha = int(60 * (1 - i / 40) ** 2)
        v_draw.rectangle([i, i, size - i, size - i], outline=(0, 0, 0, edge_alpha))
    vignette = vignette.filter(ImageFilter.GaussianBlur(size // 20))
    img = Image.alpha_composite(img, vignette)

    # Rounded mask (sadece non-maskable icin)
    if not maskable:
        mask = make_rounded_square_mask(size, 0.22)
        r, g, b, a = img.split()
        new_a = Image.new('L', (size, size), 0)
        new_a.paste(a, (0, 0), mask)
        img = Image.merge('RGBA', (r, g, b, new_a))

    # Logo'yu yerleştir
    # Maskable: %55 (safe zone içinde)
    # Normal: %72 (daha dolgun gözüksün)
    target_pct = 0.55 if maskable else 0.72
    target_size = int(size * target_pct)

    # Apple logo'nun aspect ratio'su koru
    lw, lh = apple_logo.size
    if lh > lw:
        new_h = target_size
        new_w = int(lw * (target_size / lh))
    else:
        new_w = target_size
        new_h = int(lh * (target_size / lw))

    apple_resized = apple_logo.resize((new_w, new_h), Image.LANCZOS)

    # Beyaz outline ekle elmaya (dark bg uzerinde net gozuksun)
    # Mevcut elma siyah outline'a sahip, dark bg'de kaybolabilir.
    # Solution: elmanin alpha mask'inden hafif daha buyuk bir warm-glow olustur arkasina koy.
    glow_layer = Image.new('RGBA', (new_w + 60, new_h + 60), (0, 0, 0, 0))
    # apple alpha'yi al, biraz buyut, glow ekle
    alpha = apple_resized.split()[-1]
    glow_mask = Image.new('RGBA', (new_w + 60, new_h + 60), (0, 0, 0, 0))
    # APPLE_RED_GLOW renkle alpha'yi mask olarak kullan
    glow_color = Image.new('RGBA', (new_w + 60, new_h + 60), (*APPLE_RED_GLOW, 0))
    glow_alpha_layer = Image.new('L', (new_w + 60, new_h + 60), 0)
    glow_alpha_layer.paste(alpha, (30, 30))
    # blur to create glow
    glow_alpha_blurred = glow_alpha_layer.filter(ImageFilter.GaussianBlur(15))
    glow_color.putalpha(Image.eval(glow_alpha_blurred, lambda x: min(int(x * 0.6), 130)))

    # Logo position (centered)
    px = (size - new_w) // 2
    py = (size - new_h) // 2

    # Glow'u önce yapıştır
    img.paste(glow_color, (px - 30, py - 30), glow_color)

    # Logo'yu üzerine koy
    img.paste(apple_resized, (px, py), apple_resized)

    return img


def make_favicon(apple_logo, size=32):
    """Kucuk favicon — sadece elma sembolu."""
    img = Image.new('RGBA', (size, size), NAVY)
    mask = make_rounded_square_mask(size, 0.20)
    r_img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    r_img.paste(img, (0, 0), mask)

    # Resize apple to fit
    target = int(size * 0.78)
    lw, lh = apple_logo.size
    if lh > lw:
        new_h = target
        new_w = int(lw * (target / lh))
    else:
        new_w = target
        new_h = int(lh * (target / lw))
    apple_small = apple_logo.resize((new_w, new_h), Image.LANCZOS)
    px = (size - new_w) // 2
    py = (size - new_h) // 2
    r_img.paste(apple_small, (px, py), apple_small)
    return r_img


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    print(f"FermatAI icon generator (25.40f — kurumsal logo)\nOutput: {OUT_DIR}\n")

    print("Loading source logo...")
    apple = load_logo_apple_only()
    print(f"  Apple+lines crop: {apple.size}\n")

    sizes = [
        ('fermatai-192.png', 192, False),
        ('fermatai-512.png', 512, False),
        ('fermatai-1024.png', 1024, False),
        ('fermatai-192-maskable.png', 192, True),
        ('fermatai-512-maskable.png', 512, True),
        ('fermatai-shortcut-96.png', 96, False),
    ]

    for fname, size, maskable in sizes:
        out_path = os.path.join(OUT_DIR, fname)
        img = make_icon(size, apple, maskable=maskable)
        img.save(out_path, format='PNG', optimize=True)
        kb = os.path.getsize(out_path) / 1024
        tag = "[MASKABLE]" if maskable else "[NORMAL]  "
        print(f"  {tag} {fname}  ({size}x{size})  {kb:.1f} KB")

    fav_path = os.path.join(OUT_DIR, 'favicon.png')
    favicon = make_favicon(apple, 32)
    favicon.save(fav_path, format='PNG', optimize=True)
    print(f"  [FAVICON]  favicon.png  (32x32)  {os.path.getsize(fav_path)/1024:.1f} KB")

    print("\nIcon set ready (kurumsal kimlik ile).")


if __name__ == '__main__':
    main()

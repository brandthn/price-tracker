"""Generateur de tickets de caisse synthetiques, avec leurs labels parfaits.

Rend des paires (image, Ticket) : des tickets plausibles dans plusieurs styles visuels
(thermique, compact, discount, delave...), avec du bruit d'encre et de mise en page
optionnel, puis des distorsions de prise de vue (rotation, perspective, flou, JPEG,
ombres, vignettage, cadrage de travers).
"""

from __future__ import annotations

import datetime
import io
import json
import random
import re
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

from receipt_vlm.data.schema import Product, Ticket, serialize_ticket

# Une ligne qui n'est que des separateurs (====, ----, ....) ne porte aucun texte.
_SEPARATOR_LINE = re.compile(r"^[\s\-=*#._]*$")


def _lines_to_transcription(lines: list[str]) -> str:
    """Le texte visible du ticket, mis bout a bout. C'est la cible de lecture."""
    kept = [ln.strip() for ln in lines if not _SEPARATOR_LINE.match(ln)]
    return "\n".join(ln for ln in kept if ln)

_WINDOWS_FONTS = ("consola.ttf", "cour.ttf", "lucon.ttf", "arial.ttf", "calibri.ttf")
_UNIX_FONTS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Menlo.ttc",
)

# Les palettes : (papier, encre, accent eventuel)
_PALETTES: list[tuple[tuple[int, int, int], tuple[int, int, int], Optional[tuple[int, int, int]]]] = [
    ((255, 255, 255), (0, 0, 0), None),
    ((252, 250, 245), (30, 30, 30), None),
    ((248, 246, 238), (50, 45, 40), None),
    ((255, 248, 240), (20, 20, 20), None),  # creme
    ((245, 242, 235), (35, 35, 35), None),  # thermique vieilli
    ((255, 240, 245), (40, 20, 30), (180, 40, 60)),  # thermique rose
    ((240, 248, 255), (25, 35, 55), None),  # delave bleute
    ((235, 235, 230), (15, 15, 15), None),  # papier gris
    ((255, 255, 250), (60, 60, 60), (0, 100, 0)),  # encre legerement verte
    ((250, 245, 230), (80, 60, 40), None),  # sepia, brule par le soleil
]

_LAYOUT_STYLES = (
    "thermal_classic",
    "thermal_narrow",
    "thermal_wide",
    "compact",
    "retail_dashed",
    "discount",
    "minimal",
    "dense",
)


def generate_ticket(seed: Optional[int] = None, locale: Optional[str] = None) -> Ticket:
    """Fabrique un Ticket au hasard, avec ses labels parfaits.

    La locale choisit le pack d'enseignes et de produits, donc le meme moteur de
    rendu sort des tickets dans n'importe quelle langue a ecriture latine.
    """
    from receipt_vlm.data.locales import get_locale

    pack = get_locale(locale)
    rng = random.Random(seed)
    store_name, store_addr = rng.choice(pack.stores)
    n_items = rng.randint(3, 14)

    produits: list[Product] = []
    for _ in range(n_items):
        name, base_price = rng.choice(pack.products)
        price = round(base_price * rng.uniform(0.9, 1.12), 2)
        qty = rng.choice([1, 1, 1, 1, 2, 2, 3, 4])
        produits.append(Product(name, price, qty))

    moment = datetime.datetime.now() - datetime.timedelta(
        days=rng.randint(0, 365), hours=rng.randint(0, 12), minutes=rng.randint(0, 59)
    )
    moment = moment.replace(hour=rng.randint(8, 20))

    include_date = rng.random() > 0.05
    include_address = rng.random() > 0.10

    return Ticket(
        date=moment.strftime("%Y%m%d %H:%M") if include_date else "",
        chaine_supermarche=store_name,
        adresse=store_addr if include_address else "",
        produits=produits,
    )


# Pool de polices optionnel : deposer des .ttf/.otf dans receipt_vlm/data/fonts/ elargit
# la diversite de glyphes, et c'est de loin le levier le plus efficace pour que le modele
# apprenne a lire autre chose qu'une seule typo. Pool vide : on retombe sur les polices
# systeme listees plus bas.
_FONT_DIR = Path(__file__).resolve().parent / "fonts"
_FONT_EXTS = (".ttf", ".otf", ".ttc")
_FONT_POOL: list[str] = []


def add_fonts_from_dir(directory: str | Path) -> int:
    """Ajoute toutes les polices du dossier au pool de rendu."""
    d = Path(directory)
    if not d.is_dir():
        return 0
    added = 0
    for p in sorted(d.rglob("*")):
        if p.suffix.lower() in _FONT_EXTS and str(p) not in _FONT_POOL:
            _FONT_POOL.append(str(p))
            added += 1
    return added


add_fonts_from_dir(_FONT_DIR)  # charge les polices embarquees si le dossier existe


def _pick_font_path(rng: random.Random, mono: bool) -> Optional[str]:
    return rng.choice(_FONT_POOL) if _FONT_POOL else None


def _load_font(size: int, mono: bool = True, path: Optional[str] = None) -> ImageFont.ImageFont:
    if path:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    candidates = (_WINDOWS_FONTS + _UNIX_FONTS) if mono else (
        "arial.ttf", "calibri.ttf", "segoeui.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ) + _WINDOWS_FONTS + _UNIX_FONTS
    for name in candidates:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _format_price(value: float, style: str, symbol: str = "€", code: str = "EUR") -> str:
    if style == "suffix":
        return f"{value:.2f} {code}"
    if style == "space":
        return f"{value:.2f} {symbol}"
    return f"{value:.2f}"


def _build_lines(
    ticket: Ticket, rng: random.Random, style: str, loc: "LocalePack | None" = None
) -> tuple[list[str], dict]:
    """Rend les lignes de texte et la mise en page, pour un style et une locale.

    Le pack de locale fournit tous les mots imprimes sur le ticket, ce qui permet a
    la logique de mise en page de rester neutre linguistiquement.
    """
    from receipt_vlm.data.locales import get_locale

    L = loc or get_locale(None)

    if style == "thermal_narrow":
        cols = rng.choice([30, 32, 34])
    elif style == "thermal_wide":
        cols = rng.choice([44, 46, 48])
    elif style == "compact":
        cols = rng.choice([36, 38])
    elif style == "dense":
        cols = rng.choice([40, 42])
    else:
        cols = rng.choice([36, 38, 40, 42])

    money_style = rng.choice(["plain", "space", "suffix"])
    meta = {"cols": cols, "style": style, "euro_style": money_style, "locale": L.code}

    def fmt(v: float) -> str:
        return _format_price(v, money_style, L.currency_symbol, L.currency_code)

    lines: list[str] = []

    if style == "retail_dashed":
        sep_heavy = ("-" * cols)
        sep_light = ("." * cols)
    elif style == "discount":
        sep_heavy = ("*" * cols)
        sep_light = ("-" * cols)
    elif style == "minimal":
        sep_heavy = ""
        sep_light = ""
    else:
        sep_heavy = rng.choice(["=", "*", "#"]) * cols
        sep_light = "-" * cols

    if sep_heavy:
        lines.append(sep_heavy)
    if style == "discount":
        lines.append(("*** " + ticket.chaine_supermarche.upper() + " ***").center(cols))
    elif style == "retail_dashed":
        lines.append(ticket.chaine_supermarche.upper())
        lines.append(L.subtitle)
    else:
        lines.append(ticket.chaine_supermarche.upper().center(cols))

    if ticket.adresse:
        addr = ticket.adresse
        if len(addr) > cols:
            cut = addr.rfind(" ", 0, cols)
            cut = cut if cut > 0 else cols
            if style in ("retail_dashed", "minimal"):
                lines.append(addr[:cut].strip())
                if addr[cut:].strip():
                    lines.append(addr[cut:].strip())
            else:
                lines.append(addr[:cut].strip().center(cols))
                if addr[cut:].strip():
                    lines.append(addr[cut:].strip().center(cols))
        else:
            align = (lambda s: s) if style in ("retail_dashed", "minimal") else (lambda s: s.center(cols))
            lines.append(align(addr))

    if style != "minimal" and rng.random() < 0.45:
        tel = (f"{L.tel_prefix} 0{rng.randint(1, 5)}.{rng.randint(10, 99)}."
               f"{rng.randint(10, 99)}.{rng.randint(10, 99)}.{rng.randint(10, 99)}")
        lines.append(tel.center(cols) if style not in ("retail_dashed",) else tel)

    if sep_heavy and style != "minimal":
        lines.append(sep_heavy)

    if ticket.date:
        day, time_part = ticket.date.split(" ")
        yyyy, mm, dd = day[0:4], day[4:6], day[6:8]
        dstr = f"{mm}/{dd}/{yyyy}" if L.date_order == "mdy" else f"{dd}/{mm}/{yyyy}"
        if style == "retail_dashed":
            lines.append(L.date_retail.format(d=dstr, t=time_part))
        elif style == "compact":
            lines.append(f"{dstr} {time_part}")
        else:
            lines.append(L.date_default.format(d=dstr, t=time_part))

    if style == "discount":
        lines.append(L.register_discount.format(nn=f"{rng.randint(1, 12):02d}", num=rng.randint(100000, 999999)))
    else:
        lines.append(L.register_default.format(n=rng.randint(1, 9), num=rng.randint(1000, 99999)))

    if sep_light and style != "minimal":
        lines.append(sep_light)

    total = 0.0
    for product in ticket.produits:
        line_total = round(product.prix_unitaire_ou_kg * product.unites, 2)
        total = round(total + line_total, 2)
        name = product.nom_produit[: cols - 12]
        price_txt = fmt(line_total)

        if style == "compact":
            if product.unites > 1:
                lines.append(f"{product.unites}x {name[:cols-14]} {price_txt}".strip()[:cols])
            else:
                lines.append(f"{name} {price_txt}"[:cols])
        elif style == "dense":
            unit = fmt(product.prix_unitaire_ou_kg)
            lines.append(name[:cols])
            if product.unites > 1:
                lines.append(f"  {product.unites} @ {unit}".ljust(cols - len(price_txt)) + price_txt)
            else:
                lines.append((" " * (cols - len(price_txt))) + price_txt)
        elif product.unites > 1:
            lines.append(name)
            qty_part = f"  {product.unites} x {fmt(product.prix_unitaire_ou_kg)}"
            pad = cols - max(8, len(price_txt))
            lines.append(qty_part.ljust(pad) + price_txt.rjust(len(price_txt)))
        else:
            pad = cols - len(price_txt)
            lines.append(name.ljust(pad) + price_txt.rjust(len(price_txt)))

    if sep_light and style != "minimal":
        lines.append(sep_light)

    total_txt = fmt(total)
    if style == "discount":
        lines.append((L.total_pay + " " + total_txt).center(cols))
    elif style == "retail_dashed":
        lines.append(L.total_retail.ljust(cols - len(total_txt)) + total_txt)
    else:
        lines.append(L.total_default.ljust(cols - len(total_txt)) + total_txt)

    n_articles = sum(p.unites for p in ticket.produits)
    lines.append(L.articles_compact.format(n=n_articles) if style == "compact"
                 else L.articles_default.format(n=n_articles))

    if rng.random() < 0.75:
        rate = L.tax_rate
        tva = round(total * rate / (1 + rate), 2)
        tva_txt = fmt(tva)
        tax_lbl = L.tax_label.format(pct=f"{rate * 100:g}%")
        lines.append(tax_lbl.ljust(cols - len(tva_txt)) + tva_txt)

    if style == "discount" and rng.random() < 0.4:
        lines.append(L.loyalty_label + str(rng.randint(1000, 9999)))

    payment = rng.choice(L.payment_methods)
    if style == "retail_dashed":
        lines.append(L.payment_retail.format(m=payment))
    else:
        lines.append(L.payment_default.format(m=payment))

    if payment != L.cash_word and rng.random() < 0.65:
        lines.append(f"**** **** **** {rng.randint(1000, 9999)}")

    if sep_heavy and style != "minimal":
        lines.append(sep_heavy)
    lines.append(rng.choice(L.thankyou).center(cols)
                 if style not in ("retail_dashed", "minimal")
                 else rng.choice(L.thankyou_short))

    # Le style minimal produit des lignes vides accidentelles.
    lines = [ln for ln in lines if ln != "" or style == "minimal"]
    return lines, meta


def _pick_style(rng: random.Random, diverse: bool) -> str:
    if not diverse:
        return "thermal_classic"
    weights = {
        "thermal_classic": 14,
        "thermal_narrow": 12,
        "thermal_wide": 10,
        "compact": 14,
        "retail_dashed": 12,
        "discount": 10,
        "minimal": 8,
        "dense": 10,
    }
    styles = list(weights.keys())
    w = [weights[s] for s in styles]
    return rng.choices(styles, weights=w, k=1)[0]


def _draw_receipt(
    lines: list[str],
    rng: random.Random,
    meta: dict,
    diverse: bool,
) -> Image.Image:
    style = meta["style"]
    cols = meta["cols"]

    if style == "thermal_narrow":
        width = rng.choice([300, 320, 340])
    elif style == "thermal_wide":
        width = rng.choice([480, 500, 520])
    else:
        width = rng.choice([360, 380, 400, 420, 440])

    if diverse:
        font_size = rng.choice([10, 11, 12, 13, 14, 15, 16])
        mono = rng.random() < 0.75
    else:
        font_size = rng.choice([12, 13, 14])
        mono = True

    font = _load_font(font_size, mono=mono, path=_pick_font_path(rng, mono))
    line_height = font_size + rng.randint(3, 7)
    margin_x = rng.randint(4, 24)
    margin_y = rng.randint(10, 32)
    height = len(lines) * line_height + 2 * margin_y + rng.randint(0, 20)

    paper, ink, accent = rng.choice(_PALETTES)
    if diverse and rng.random() < 0.25:
        # Un peu de variation de couleur sur le papier
        paper = tuple(max(0, min(255, c + rng.randint(-12, 12))) for c in paper)

    img = Image.new("RGB", (width, height), paper)
    draw = ImageDraw.Draw(img)

    # Avant rendu : degrade vertical (le haut du rouleau thermique est souvent plus pale)
    if diverse and rng.random() < 0.35:
        fade = Image.new("L", (width, height), 255)
        fade_draw = ImageDraw.Draw(fade)
        for y in range(height):
            factor = 0.85 + 0.15 * (y / max(1, height - 1))
            if rng.random() < 0.5:
                factor = 1.1 - 0.2 * (y / max(1, height - 1))
            fade_draw.line([(0, y), (width, y)], fill=int(255 * factor))
        img = Image.composite(img, Image.new("RGB", img.size, paper), fade)

    draw = ImageDraw.Draw(img)

    for i, line in enumerate(lines):
        y = margin_y + i * line_height
        # Avant rendu : interlignes irreguliers
        if diverse:
            y += rng.randint(-1, 2)
        # Avant rendu : tremblement horizontal, comme une imprimante usee
        x = margin_x + (rng.randint(-2, 3) if diverse else 0)

        line_ink = ink
        if diverse and rng.random() < 0.08:
            # Ligne delavee ou imprimee deux fois
            line_ink = tuple(min(255, c + rng.randint(40, 90)) for c in ink)
        if accent and i == 0 and style == "discount":
            line_ink = accent

        draw.text((x, y), line, fill=line_ink, font=font)

        # Avant rendu : ligne fantome, bavee
        if diverse and rng.random() < 0.04:
            draw.text((x + 1, y), line, fill=tuple(min(255, c + 60) for c in line_ink), font=font)

    return img


def _jpeg_recompress(img: Image.Image, quality: int) -> Image.Image:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    buf.seek(0)
    return Image.open(buf).convert("RGB")


def _add_gaussian_noise(arr: np.ndarray, sigma: float) -> np.ndarray:
    noise = np.random.normal(0, sigma, arr.shape)
    return np.clip(arr + noise, 0, 255).astype(np.uint8)


def _perspective_warp(img: Image.Image, rng: random.Random) -> Image.Image:
    w, h = img.size
    max_shift = int(min(w, h) * rng.uniform(0.02, 0.09))
    src = [(0, 0), (w, 0), (w, h), (0, h)]
    dst = [
        (rng.randint(0, max_shift), rng.randint(0, max_shift)),
        (w - rng.randint(0, max_shift), rng.randint(0, max_shift)),
        (w - rng.randint(0, max_shift), h - rng.randint(0, max_shift)),
        (rng.randint(0, max_shift), h - rng.randint(0, max_shift)),
    ]
    coeffs = _find_perspective_coeffs(dst, src)
    return img.transform((w, h), Image.Transform.PERSPECTIVE, coeffs, Image.Resampling.BICUBIC)


def _find_perspective_coeffs(
    dst: list[tuple[int, int]], src: list[tuple[int, int]]
) -> tuple[float, ...]:
    """Coefficients de la transformation de perspective attendus par PIL."""
    matrix = []
    for (x, y), (u, v) in zip(dst, src):
        matrix.extend([x, y, 1, 0, 0, 0, -u * x, -u * y])
        matrix.extend([0, 0, 0, x, y, 1, -v * x, -v * y])
    a = np.array(matrix, dtype=np.float64).reshape(8, 8)
    b = np.array(src, dtype=np.float64).reshape(8)
    res = np.linalg.solve(a, b)
    return tuple(res.tolist())


def _vignette(img: Image.Image, strength: float) -> Image.Image:
    w, h = img.size
    y, x = np.ogrid[:h, :w]
    cy, cx = h / 2, w / 2
    dist = np.sqrt((x - cx) ** 2 + (y - cy) ** 2)
    max_dist = np.sqrt(cx ** 2 + cy ** 2)
    mask = 1.0 - strength * (dist / max_dist)
    mask = np.clip(mask, 0.55, 1.0)
    arr = np.asarray(img).astype(np.float32)
    arr *= mask[..., np.newaxis]
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def _frame_on_background(img: Image.Image, rng: random.Random) -> Image.Image:
    """Simule une photo au telephone : le ticket sur une table, avec une ombre."""
    bg_color = rng.choice([
        (45, 42, 38), (60, 58, 55), (28, 32, 40), (75, 70, 65),
        (90, 85, 80), (35, 45, 35), (50, 50, 60),
    ])
    pad_x = rng.randint(24, 80)
    pad_y = rng.randint(30, 100)
    canvas_w = img.width + 2 * pad_x
    canvas_h = img.height + 2 * pad_y
    canvas = Image.new("RGB", (canvas_w, canvas_h), bg_color)

    shadow = Image.new("RGBA", img.size, (0, 0, 0, 90))
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=rng.randint(2, 5)))
    canvas.paste(shadow, (pad_x + rng.randint(4, 10), pad_y + rng.randint(4, 10)), shadow)
    canvas.paste(img, (pad_x + rng.randint(-6, 6), pad_y + rng.randint(-6, 6)))
    return canvas


def _chromatic_aberration(img: Image.Image, rng: random.Random) -> Image.Image:
    """Decale les canaux R et B de quelques pixels : le frangeage d'un objectif bas de gamme."""
    arr = np.asarray(img)
    shift = rng.randint(1, 3)
    out = arr.copy()
    out[:, :, 0] = np.roll(arr[:, :, 0], shift, axis=1)
    out[:, :, 2] = np.roll(arr[:, :, 2], -shift, axis=1)
    return Image.fromarray(out)


def _texture_overlay(img: Image.Image, rng: random.Random) -> Image.Image:
    """Melange une couche de bruit doux : le grain du papier, la texture de la table."""
    w, h = img.size
    noise = np.random.randint(0, 256, (h, w, 3), dtype=np.uint8)
    tex = Image.fromarray(noise).filter(ImageFilter.GaussianBlur(rng.uniform(2, 6)))
    return Image.blend(img, tex.convert("RGB"), rng.uniform(0.04, 0.14))


def _stamp_overlay(img: Image.Image, rng: random.Random) -> Image.Image:
    """Colle un tampon semi-transparent, comme un cachet de magasin."""
    base = img.convert("RGBA")
    sw, sh = rng.randint(80, 160), rng.randint(48, 90)
    stamp = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
    draw = ImageDraw.Draw(stamp)
    colour = rng.choice([(180, 30, 30, 150), (30, 60, 150, 150), (40, 120, 40, 150)])
    if rng.random() < 0.5:
        draw.ellipse([2, 2, sw - 2, sh - 2], outline=colour, width=3)
    else:
        draw.rectangle([2, 2, sw - 2, sh - 2], outline=colour, width=3)
    text = rng.choice(["PAID", "COPY", "VOID", "OK", "MERCI", "*"])
    draw.text((sw // 2 - 4 * len(text), sh // 2 - 7), text, fill=colour, font=_load_font(16))
    stamp = stamp.rotate(rng.uniform(-25, 25), expand=True)
    x = rng.randint(0, max(1, base.width - stamp.width))
    y = rng.randint(0, max(1, base.height - stamp.height))
    base.alpha_composite(stamp, (x, y))
    return base.convert("RGB")


# Tous les effets activables. L'ordre ici est l'ordre d'application.
ALL_VARIATIONS: tuple[str, ...] = (
    "rotate", "warp", "chroma", "brightness", "contrast", "blur", "noise",
    "overlay", "stamp", "jpeg", "vignette", "frame", "crop", "autocontrast",
)


def distort_receipt_image(
    image: Image.Image,
    seed: Optional[int] = None,
    *,
    intensity: str = "medium",
    variations: "set[str] | None" = None,
) -> Image.Image:
    """Le bruit de prise de vue, applique apres le rendu. Chaque effet est activable."""
    rng = random.Random(seed)
    img = image.convert("RGB")

    enabled = ALL_VARIATIONS if variations is None else tuple(v for v in ALL_VARIATIONS if v in variations)
    probs = {"light": 0.35, "medium": 0.65, "heavy": 0.85}[intensity]

    def on(name: str, p_scale: float = 1.0) -> bool:
        return name in enabled and rng.random() < min(1.0, probs * p_scale)

    if on("rotate", 0.7):
        angle = rng.uniform(-9, 9) if intensity == "heavy" else rng.uniform(-6, 6)
        img = img.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=img.getpixel((0, 0)))

    if on("warp", 0.8):
        img = _perspective_warp(img, rng)

    if on("chroma", 0.4):
        img = _chromatic_aberration(img, rng)

    if on("brightness", 0.5):
        img = ImageEnhance.Brightness(img).enhance(rng.uniform(0.75, 1.25))

    if on("contrast", 0.5):
        img = ImageEnhance.Contrast(img).enhance(rng.uniform(0.7, 1.35))

    if on("blur", 0.4):
        radius = rng.uniform(0.4, 1.8) if intensity != "heavy" else rng.uniform(0.6, 2.5)
        img = img.filter(ImageFilter.GaussianBlur(radius=radius))

    if on("noise", 0.35):
        arr = _add_gaussian_noise(np.asarray(img), sigma=rng.uniform(3, 14))
        img = Image.fromarray(arr)

    if on("overlay", 0.35):
        img = _texture_overlay(img, rng)

    if on("stamp", 0.3):
        img = _stamp_overlay(img, rng)

    if on("jpeg", 0.55):
        quality = rng.randint(35, 88) if intensity == "heavy" else rng.randint(45, 92)
        img = _jpeg_recompress(img, quality)

    if on("vignette", 0.45):
        img = _vignette(img, strength=rng.uniform(0.15, 0.45))

    if on("frame", 0.4):
        img = _frame_on_background(img, rng)

    if on("crop", 0.25) and intensity in ("medium", "heavy"):
        # Recadrage partiel, comme une photo prise trop pres
        w, h = img.size
        crop_pct = rng.uniform(0.02, 0.12)
        left = int(w * crop_pct * rng.random())
        top = int(h * crop_pct * rng.random())
        right = w - int(w * crop_pct * rng.random())
        bottom = h - int(h * crop_pct * rng.random())
        if right - left > w * 0.5 and bottom - top > h * 0.5:
            img = img.crop((left, top, right, bottom))

    if on("autocontrast", 0.2):
        img = ImageOps.autocontrast(img, cutoff=rng.randint(0, 2))

    return img


def render_receipt_image(
    ticket: Ticket,
    seed: Optional[int] = None,
    width: int = 420,
    *,
    diverse: bool = False,
    distort: bool = False,
    distort_intensity: str = "medium",
    locale: Optional[str] = None,
    distort_variations: "set[str] | None" = None,
    return_text: bool = False,
):
    """Dessine un Ticket sous forme d'image de ticket de caisse."""
    from receipt_vlm.data.locales import get_locale

    pack = get_locale(locale)
    rng = random.Random(seed)
    style = _pick_style(rng, diverse=diverse)
    lines, meta = _build_lines(ticket, rng, style, loc=pack)

    if diverse:
        img = _draw_receipt(lines, rng, meta, diverse=True)
    else:
        # L'ancien chemin, garde pour ne pas casser les datasets deja generes.
        meta = {"cols": rng.choice([38, 40, 42]), "style": "thermal_classic", "euro_style": "plain"}
        lines, _ = _build_lines(ticket, rng, "thermal_classic", loc=pack)
        img = Image.new("RGB", (width, 1), (255, 255, 255))
        font_size = rng.choice([12, 13, 14])
        font = _load_font(font_size, path=_pick_font_path(rng, True))
        line_height = font_size + 5
        margin_x, margin_y = rng.randint(8, 20), rng.randint(14, 28)
        height = len(lines) * line_height + 2 * margin_y
        background = rng.choice([(255, 255, 255), (252, 250, 245), (248, 246, 238)])
        ink = rng.choice([(0, 0, 0), (40, 40, 40), (60, 55, 50)])
        img = Image.new("RGB", (width, height), background)
        draw = ImageDraw.Draw(img)
        for i, line in enumerate(lines):
            draw.text((margin_x, margin_y + i * line_height), line, fill=ink, font=font)

    if distort:
        img = distort_receipt_image(
            img,
            seed=None if seed is None else seed + 7919,
            intensity=distort_intensity,
            variations=distort_variations,
        )

    if return_text:
        return img, _lines_to_transcription(lines)
    return img


def save_dataset(
    n: int,
    output_dir: str | Path,
    seed: int = 0,
    *,
    diverse: bool = False,
    distort: bool = False,
    distort_intensity: str = "medium",
    start_index: int = 0,
    locale: Optional[str] = None,
    distort_variations: "set[str] | None" = None,
) -> list[Path]:
    """Genere n paires (image, label) dans output_dir.

    Writes ``receipt_{i:05d}.png`` and matching ``.json`` labels. ``locale`` and
    ``distort_variations`` are forwarded to the renderer.
    """
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for i in range(n):
        idx = start_index + i
        ticket = generate_ticket(seed=seed + i, locale=locale)
        image = render_receipt_image(
            ticket,
            seed=seed + i,
            diverse=diverse,
            distort=distort,
            distort_intensity=distort_intensity,
            locale=locale,
            distort_variations=distort_variations,
        )
        image_path = output / f"receipt_{idx:05d}.png"
        label_path = output / f"receipt_{idx:05d}.json"
        image.save(image_path)
        label_path.write_text(serialize_ticket(ticket), encoding="utf-8")
        paths.append(image_path)
    return paths


def load_dataset(directory: str | Path) -> list[tuple[Path, Ticket]]:
    """Recharge les paires (chemin d'image, Ticket) ecrites par save_dataset."""
    from receipt_vlm.data.schema import ticket_from_dict

    directory = Path(directory)
    samples: list[tuple[Path, Ticket]] = []
    for image_path in sorted(directory.glob("*.png")):
        label_path = image_path.with_suffix(".json")
        if not label_path.exists():
            continue
        payload = json.loads(label_path.read_text(encoding="utf-8"))
        samples.append((image_path, ticket_from_dict(payload)))
    return samples

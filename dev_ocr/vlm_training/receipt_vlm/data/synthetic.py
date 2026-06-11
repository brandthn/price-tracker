"""Synthetic French receipt generator — perfect canonical labels.

Generates (image, Ticket) pairs: plausible French supermarket receipts in
several visual styles (thermal, compact, discount, faded, …) plus optional
pre-render ink/layout noise and post-render capture distortions (rotation,
perspective, blur, JPEG, shadows, vignette, off-centre framing).
"""

from __future__ import annotations

import datetime
import io
import json
import random
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

from receipt_vlm.data.schema import Product, Ticket, serialize_ticket

FRENCH_STORES = [
    {"name": "Carrefour Market", "address": "12 rue de la République, 69002 Lyon"},
    {"name": "Carrefour City", "address": "8 avenue Jean Jaurès, 75019 Paris"},
    {"name": "Monoprix", "address": "21 boulevard Haussmann, 75009 Paris"},
    {"name": "Lidl", "address": "45 route de Vannes, 44100 Nantes"},
    {"name": "Franprix", "address": "3 rue de la Paix, 75002 Paris"},
    {"name": "Super U", "address": "10 place du Marché, 35000 Rennes"},
    {"name": "Intermarché", "address": "ZAC des Vergers, 13100 Aix-en-Provence"},
    {"name": "E.Leclerc", "address": "120 avenue de la Liberté, 59000 Lille"},
    {"name": "Auchan", "address": "Centre Commercial Englos, 59320 Englos"},
    {"name": "Casino", "address": "5 cours Gambetta, 34000 Montpellier"},
    {"name": "Picard", "address": "18 rue des Halles, 37000 Tours"},
    {"name": "Aldi", "address": "27 rue Nationale, 67000 Strasbourg"},
    {"name": "GIFI", "address": "14 avenue Charles de Gaulle, 33600 Pessac"},
    {"name": "Action", "address": "ZAC du Port, 44200 Nantes"},
]

PRODUCTS_BY_CATEGORY: dict[str, list[tuple[str, float]]] = {
    "produits_laitiers": [
        ("LAIT DEMI-ECREME 1L", 1.09),
        ("YAOURT NATURE X8", 2.45),
        ("FROMAGE RAPE 200G", 2.89),
        ("BEURRE DOUX 250G", 2.65),
        ("CREME FRAICHE 30CL", 1.75),
        ("CAMEMBERT 250G", 2.39),
        ("YAOURT FRUITS X4", 2.10),
        ("MOZZARELLA 125G", 1.15),
    ],
    "epicerie": [
        ("PATES SPAGHETTI 500G", 0.99),
        ("RIZ BASMATI 1KG", 2.19),
        ("HUILE TOURNESOL 1L", 1.89),
        ("FARINE T55 1KG", 0.95),
        ("SUCRE EN POUDRE 1KG", 1.35),
        ("CONFITURE FRAISE 370G", 2.25),
        ("CEREALES CHOCO 375G", 2.79),
        ("CAFE MOULU 250G", 3.49),
        ("THE VERT X25", 2.15),
        ("CHOCOLAT NOIR 100G", 1.59),
        ("BISCUITS PETIT DEJ 400G", 2.05),
        ("MIEL FLEURS 250G", 3.85),
    ],
    "boissons": [
        ("EAU MINERALE 6X1.5L", 2.99),
        ("JUS D'ORANGE 1L", 2.49),
        ("SODA COLA 1.5L", 1.85),
        ("SIROP GRENADINE 75CL", 2.55),
        ("BIERE BLONDE 6X25CL", 4.95),
        ("VIN ROUGE 75CL", 4.50),
    ],
    "fruits_legumes": [
        ("BANANES VRAC", 1.99),
        ("POMMES GALA 1KG", 2.49),
        ("TOMATES GRAPPE 500G", 2.15),
        ("CAROTTES 1KG", 1.29),
        ("SALADE BATAVIA", 1.05),
        ("CITRONS X3", 1.65),
        ("AVOCAT PIECE", 1.25),
        ("COURGETTES 1KG", 2.35),
    ],
    "viandes_poissons": [
        ("FILET POULET 400G", 5.49),
        ("STEAK HACHE X2", 4.25),
        ("JAMBON BLANC X4", 2.95),
        ("SAUMON FUME 120G", 4.85),
        ("LARDONS FUMES 200G", 2.45),
    ],
    "hygiene": [
        ("SAVON LIQUIDE 300ML", 2.15),
        ("DENTIFRICE 75ML", 1.89),
        ("SHAMPOOING 250ML", 3.25),
        ("GEL DOUCHE 250ML", 2.49),
        ("PAPIER TOILETTE X6", 3.95),
        ("MOUCHOIRS X10", 1.45),
    ],
    "entretien": [
        ("LIQUIDE VAISSELLE 500ML", 1.79),
        ("LESSIVE LIQUIDE 1.5L", 6.95),
        ("EPONGES X3", 1.55),
        ("SACS POUBELLE 30L X20", 2.25),
    ],
    "boulangerie": [
        ("BAGUETTE TRADITION", 1.15),
        ("PAIN DE MIE 500G", 1.65),
        ("CROISSANTS X4", 2.45),
        ("BRIOCHE TRANCHEE 500G", 2.19),
    ],
}

_WINDOWS_FONTS = ("consola.ttf", "cour.ttf", "lucon.ttf", "arial.ttf", "calibri.ttf")
_UNIX_FONTS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Menlo.ttc",
)

# Visual palettes: (paper_rgb, ink_rgb, accent_rgb or None)
_PALETTES: list[tuple[tuple[int, int, int], tuple[int, int, int], Optional[tuple[int, int, int]]]] = [
    ((255, 255, 255), (0, 0, 0), None),
    ((252, 250, 245), (30, 30, 30), None),
    ((248, 246, 238), (50, 45, 40), None),
    ((255, 248, 240), (20, 20, 20), None),  # warm cream
    ((245, 242, 235), (35, 35, 35), None),  # aged thermal
    ((255, 240, 245), (40, 20, 30), (180, 40, 60)),  # pink thermal
    ((240, 248, 255), (25, 35, 55), None),  # bluish fade
    ((235, 235, 230), (15, 15, 15), None),  # grey paper
    ((255, 255, 250), (60, 60, 60), (0, 100, 0)),  # faint green tint ink
    ((250, 245, 230), (80, 60, 40), None),  # sepia / sun-bleached
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


def generate_ticket(seed: Optional[int] = None) -> Ticket:
    """Generate a random :class:`Ticket` with perfect canonical labels."""
    rng = random.Random(seed)
    store = rng.choice(FRENCH_STORES)
    n_items = rng.randint(3, 14)

    produits: list[Product] = []
    for _ in range(n_items):
        category = rng.choice(list(PRODUCTS_BY_CATEGORY))
        name, base_price = rng.choice(PRODUCTS_BY_CATEGORY[category])
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
        chaine_supermarche=store["name"],
        adresse=store["address"] if include_address else "",
        produits=produits,
    )


def _load_font(size: int, mono: bool = True) -> ImageFont.ImageFont:
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


def _format_price(value: float, euro_style: str) -> str:
    if euro_style == "suffix":
        return f"{value:.2f} EUR"
    if euro_style == "space":
        return f"{value:.2f} €"
    return f"{value:.2f}"


def _build_lines(ticket: Ticket, rng: random.Random, style: str) -> tuple[list[str], dict]:
    """Return text lines and layout metadata for a given style."""
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

    meta = {"cols": cols, "style": style, "euro_style": rng.choice(["plain", "space", "suffix"])}
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
        lines.append("TICKET DE CAISSE")
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
        tel = (f"Tel 0{rng.randint(1, 5)}.{rng.randint(10, 99)}."
               f"{rng.randint(10, 99)}.{rng.randint(10, 99)}.{rng.randint(10, 99)}")
        lines.append(tel.center(cols) if style not in ("retail_dashed",) else tel)

    if sep_heavy and style != "minimal":
        lines.append(sep_heavy)

    if ticket.date:
        day, time_part = ticket.date.split(" ")
        if style == "retail_dashed":
            lines.append(f"DATE {day[6:8]}/{day[4:6]}/{day[0:4]}  HEURE {time_part}")
        elif style == "compact":
            lines.append(f"{day[6:8]}/{day[4:6]}/{day[0:4]} {time_part}")
        else:
            lines.append(f"Le {day[6:8]}/{day[4:6]}/{day[0:4]} a {time_part}")

    if style == "discount":
        lines.append(f"CAISSE {rng.randint(1, 12):02d}  N° {rng.randint(100000, 999999)}")
    else:
        lines.append(f"Caisse {rng.randint(1, 9)}  Ticket {rng.randint(1000, 99999)}")

    if sep_light and style != "minimal":
        lines.append(sep_light)

    total = 0.0
    euro = meta["euro_style"]
    for product in ticket.produits:
        line_total = round(product.prix_unitaire_ou_kg * product.unites, 2)
        total = round(total + line_total, 2)
        name = product.nom_produit[: cols - 12]
        price_txt = _format_price(line_total, euro)

        if style == "compact":
            if product.unites > 1:
                lines.append(f"{product.unites}x {name[:cols-14]} {price_txt}".strip()[:cols])
            else:
                lines.append(f"{name} {price_txt}"[:cols])
        elif style == "dense":
            unit = _format_price(product.prix_unitaire_ou_kg, euro)
            lines.append(name[:cols])
            if product.unites > 1:
                lines.append(f"  {product.unites} @ {unit}".ljust(cols - len(price_txt)) + price_txt)
            else:
                lines.append((" " * (cols - len(price_txt))) + price_txt)
        elif product.unites > 1:
            lines.append(name)
            qty_part = f"  {product.unites} x {_format_price(product.prix_unitaire_ou_kg, euro)}"
            pad = cols - max(8, len(price_txt))
            lines.append(qty_part.ljust(pad) + price_txt.rjust(len(price_txt)))
        else:
            pad = cols - len(price_txt)
            lines.append(name.ljust(pad) + price_txt.rjust(len(price_txt)))

    if sep_light and style != "minimal":
        lines.append(sep_light)

    total_txt = _format_price(total, euro)
    if style == "discount":
        lines.append(("A PAYER " + total_txt).center(cols))
    elif style == "retail_dashed":
        lines.append("MONTANT TTC".ljust(cols - len(total_txt)) + total_txt)
    else:
        lines.append("TOTAL TTC".ljust(cols - len(total_txt)) + total_txt)

    n_articles = sum(p.unites for p in ticket.produits)
    lines.append(f"{n_articles} article(s)" if style != "compact" else f"Articles: {n_articles}")

    if rng.random() < 0.75:
        tva = round(total * 0.055 / 1.055, 2)
        tva_txt = _format_price(tva, euro)
        lines.append(f"TVA 5.5%".ljust(cols - len(tva_txt)) + tva_txt)

    if style == "discount" and rng.random() < 0.4:
        lines.append("CARTE FIDELITE: ****" + str(rng.randint(1000, 9999)))

    payment = rng.choice(["CB", "CARTE BANCAIRE", "ESPECES", "SANS CONTACT", "TICKET RESTO"])
    if style == "retail_dashed":
        lines.append(f"PAIEMENT : {payment}")
    else:
        lines.append(f"Reglement: {payment}")

    if payment != "ESPECES" and rng.random() < 0.65:
        lines.append(f"CB **** **** **** {rng.randint(1000, 9999)}")

    if sep_heavy and style != "minimal":
        lines.append(sep_heavy)
    lines.append(rng.choice([
        "Merci de votre visite !",
        "A bientot !",
        "Merci et a bientot",
        "Bonnes fetes !",
        "A tres bientot",
    ]).center(cols) if style not in ("retail_dashed", "minimal") else rng.choice([
        "Merci", "A bientot", "Merci de votre visite",
    ]))

    # Drop accidental empty lines from minimal style
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

    font = _load_font(font_size, mono=mono)
    line_height = font_size + rng.randint(3, 7)
    margin_x = rng.randint(4, 24)
    margin_y = rng.randint(10, 32)
    height = len(lines) * line_height + 2 * margin_y + rng.randint(0, 20)

    paper, ink, accent = rng.choice(_PALETTES)
    if diverse and rng.random() < 0.25:
        # Extra colour jitter on paper
        paper = tuple(max(0, min(255, c + rng.randint(-12, 12))) for c in paper)

    img = Image.new("RGB", (width, height), paper)
    draw = ImageDraw.Draw(img)

    # Pre-render: vertical fade (top of thermal roll often lighter/darker)
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
        # Pre-render: uneven line spacing
        if diverse:
            y += rng.randint(-1, 2)
        # Pre-render: horizontal jitter (worn printer)
        x = margin_x + (rng.randint(-2, 3) if diverse else 0)

        line_ink = ink
        if diverse and rng.random() < 0.08:
            # Faded / double-print line
            line_ink = tuple(min(255, c + rng.randint(40, 90)) for c in ink)
        if accent and i == 0 and style == "discount":
            line_ink = accent

        draw.text((x, y), line, fill=line_ink, font=font)

        # Pre-render: ghost/smear line
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
    """Return PIL perspective transform coefficients (dst → src mapping)."""
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
    """Simulate a phone photo: receipt on table + margin + shadow."""
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


def distort_receipt_image(
    image: Image.Image,
    seed: Optional[int] = None,
    *,
    intensity: str = "medium",
) -> Image.Image:
    """Post-render capture noise: rotation, perspective, blur, JPEG, etc.

    Args:
        image: clean rendered receipt.
        seed: RNG seed for reproducibility.
        intensity: ``light`` | ``medium`` | ``heavy`` — probability/strength scale.
    """
    rng = random.Random(seed)
    img = image.convert("RGB")

    probs = {"light": 0.35, "medium": 0.65, "heavy": 0.85}[intensity]
    def maybe(p_scale: float = 1.0) -> bool:
        return rng.random() < min(1.0, probs * p_scale)

    if maybe(0.7):
        angle = rng.uniform(-9, 9) if intensity == "heavy" else rng.uniform(-6, 6)
        img = img.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=img.getpixel((0, 0)))

    if maybe(0.8):
        img = _perspective_warp(img, rng)

    if maybe(0.5):
        img = ImageEnhance.Brightness(img).enhance(rng.uniform(0.75, 1.25))

    if maybe(0.5):
        img = ImageEnhance.Contrast(img).enhance(rng.uniform(0.7, 1.35))

    if maybe(0.4):
        radius = rng.uniform(0.4, 1.8) if intensity != "heavy" else rng.uniform(0.6, 2.5)
        img = img.filter(ImageFilter.GaussianBlur(radius=radius))

    if maybe(0.35):
        arr = _add_gaussian_noise(np.asarray(img), sigma=rng.uniform(3, 14))
        img = Image.fromarray(arr)

    if maybe(0.55):
        quality = rng.randint(35, 88) if intensity == "heavy" else rng.randint(45, 92)
        img = _jpeg_recompress(img, quality)

    if maybe(0.45):
        img = _vignette(img, strength=rng.uniform(0.15, 0.45))

    if maybe(0.4):
        img = _frame_on_background(img, rng)

    if maybe(0.25) and intensity in ("medium", "heavy"):
        # Partial crop (photo zoomed in)
        w, h = img.size
        crop_pct = rng.uniform(0.02, 0.12)
        left = int(w * crop_pct * rng.random())
        top = int(h * crop_pct * rng.random())
        right = w - int(w * crop_pct * rng.random())
        bottom = h - int(h * crop_pct * rng.random())
        if right - left > w * 0.5 and bottom - top > h * 0.5:
            img = img.crop((left, top, right, bottom))

    if maybe(0.2):
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
) -> Image.Image:
    """Render a :class:`Ticket` as a PIL receipt image.

    Args:
        ticket: canonical ground truth.
        seed: drives layout, colours, and distortions.
        width: used only when ``diverse=False`` (legacy fixed width).
        diverse: enable multi-style layouts, palettes, and pre-render noise.
        distort: apply post-render capture distortions.
        distort_intensity: ``light`` | ``medium`` | ``heavy`` when ``distort=True``.
    """
    rng = random.Random(seed)
    style = _pick_style(rng, diverse=diverse)
    lines, meta = _build_lines(ticket, rng, style)

    if diverse:
        img = _draw_receipt(lines, rng, meta, diverse=True)
    else:
        # Legacy path: keep original behaviour for existing datasets/tests.
        meta = {"cols": rng.choice([38, 40, 42]), "style": "thermal_classic", "euro_style": "plain"}
        lines, _ = _build_lines(ticket, rng, "thermal_classic")
        img = Image.new("RGB", (width, 1), (255, 255, 255))
        font_size = rng.choice([12, 13, 14])
        font = _load_font(font_size)
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
        img = distort_receipt_image(img, seed=None if seed is None else seed + 7919, intensity=distort_intensity)

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
) -> list[Path]:
    """Generate ``n`` (image, label) pairs under ``output_dir``.

    Writes ``receipt_{i:05d}.png`` and matching ``.json`` labels.
    """
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for i in range(n):
        idx = start_index + i
        ticket = generate_ticket(seed=seed + i)
        image = render_receipt_image(
            ticket,
            seed=seed + i,
            diverse=diverse,
            distort=distort,
            distort_intensity=distort_intensity,
        )
        image_path = output / f"receipt_{idx:05d}.png"
        label_path = output / f"receipt_{idx:05d}.json"
        image.save(image_path)
        label_path.write_text(serialize_ticket(ticket), encoding="utf-8")
        paths.append(image_path)
    return paths


def load_dataset(directory: str | Path) -> list[tuple[Path, Ticket]]:
    """Load (image_path, Ticket) pairs produced by :func:`save_dataset`."""
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

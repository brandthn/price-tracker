"""Synthetic French receipt generator — perfect canonical labels.

Generates (image, Ticket) pairs: a plausible French supermarket receipt
rendered in thermal-printer style, plus its ground truth in the canonical
schema. Totals / TVA / payment lines are *printed on the image but absent
from the labels*, teaching the model to ignore them (matching the canonical
schema, which only keeps store, date, address and product lines).
"""

from __future__ import annotations

import datetime
import json
import random
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

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
]

# (label printed on the receipt, base unit price)
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

_WINDOWS_FONTS = ("consola.ttf", "cour.ttf", "lucon.ttf")
_UNIX_FONTS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    "/System/Library/Fonts/Menlo.ttc",
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
        # Small price jitter so the model reads prices instead of memorizing.
        price = round(base_price * rng.uniform(0.9, 1.12), 2)
        qty = rng.choice([1, 1, 1, 1, 2, 2, 3, 4])
        produits.append(Product(name, price, qty))

    moment = datetime.datetime.now() - datetime.timedelta(
        days=rng.randint(0, 365), hours=rng.randint(0, 12), minutes=rng.randint(0, 59)
    )
    # Shops are open 08:00-21:00.
    moment = moment.replace(hour=rng.randint(8, 20))

    include_date = rng.random() > 0.05
    include_address = rng.random() > 0.10

    return Ticket(
        date=moment.strftime("%Y%m%d %H:%M") if include_date else "",
        chaine_supermarche=store["name"],
        adresse=store["address"] if include_address else "",
        produits=produits,
    )


def _load_font(size: int) -> ImageFont.ImageFont:
    for name in _WINDOWS_FONTS + _UNIX_FONTS:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def render_receipt_image(
    ticket: Ticket,
    seed: Optional[int] = None,
    width: int = 420,
) -> Image.Image:
    """Render a :class:`Ticket` as a thermal-printer style PIL image.

    Layout details (column width, separators, totals/TVA/payment footer) are
    randomized; the footer content is intentionally NOT in the labels.
    """
    rng = random.Random(seed)
    cols = rng.choice([38, 40, 42])
    lines: list[str] = []

    sep_heavy = rng.choice(["=", "*"]) * cols
    sep_light = "-" * cols

    lines.append(sep_heavy)
    lines.append(ticket.chaine_supermarche.upper().center(cols))
    if ticket.adresse:
        # Address may wrap over two printed lines.
        addr = ticket.adresse
        if len(addr) > cols:
            cut = addr.rfind(" ", 0, cols)
            cut = cut if cut > 0 else cols
            lines.append(addr[:cut].strip().center(cols))
            lines.append(addr[cut:].strip().center(cols))
        else:
            lines.append(addr.center(cols))
    if rng.random() < 0.5:
        lines.append(f"Tel: 0{rng.randint(1, 5)} {rng.randint(10, 99)} "
                     f"{rng.randint(10, 99)} {rng.randint(10, 99)} "
                     f"{rng.randint(10, 99)}".center(cols))
    lines.append(sep_heavy)

    if ticket.date:
        day, time_part = ticket.date.split(" ")
        pretty = f"{day[6:8]}/{day[4:6]}/{day[0:4]}"
        lines.append(f"Le {pretty} a {time_part}")
    lines.append(f"Caisse {rng.randint(1, 9)}  Ticket {rng.randint(1000, 99999)}")
    lines.append(sep_light)

    total = 0.0
    for product in ticket.produits:
        line_total = round(product.prix_unitaire_ou_kg * product.unites, 2)
        total = round(total + line_total, 2)
        name = product.nom_produit[: cols - 10]
        if product.unites > 1:
            lines.append(name)
            qty_part = f"  {product.unites} x {product.prix_unitaire_ou_kg:.2f}"
            lines.append(qty_part.ljust(cols - 8) + f"{line_total:.2f}".rjust(8))
        else:
            lines.append(name.ljust(cols - 8) + f"{line_total:.2f}".rjust(8))

    lines.append(sep_light)
    lines.append("TOTAL TTC".ljust(cols - 8) + f"{total:.2f}".rjust(8))
    n_articles = sum(p.unites for p in ticket.produits)
    lines.append(f"{n_articles} article(s)")

    # Footer noise: TVA breakdown + payment (absent from labels on purpose).
    if rng.random() < 0.8:
        tva = round(total * 0.055 / 1.055, 2)
        lines.append(f"TVA 5.5%".ljust(cols - 8) + f"{tva:.2f}".rjust(8))
    payment = rng.choice(["CB", "CARTE BANCAIRE", "ESPECES", "SANS CONTACT"])
    lines.append(f"Reglement: {payment}")
    if payment != "ESPECES" and rng.random() < 0.7:
        lines.append(f"CB **** **** **** {rng.randint(1000, 9999)}")
    lines.append(sep_heavy)
    lines.append(rng.choice([
        "Merci de votre visite !",
        "A bientot !",
        "Merci et a bientot",
    ]).center(cols))

    font_size = rng.choice([12, 13, 14])
    font = _load_font(font_size)
    line_height = font_size + 5
    margin_x, margin_y = rng.randint(8, 20), rng.randint(14, 28)
    height = len(lines) * line_height + 2 * margin_y

    background = rng.choice([(255, 255, 255), (252, 250, 245), (248, 246, 238)])
    img = Image.new("RGB", (width, height), background)
    draw = ImageDraw.Draw(img)
    ink = rng.choice([(0, 0, 0), (40, 40, 40), (60, 55, 50)])
    for i, line in enumerate(lines):
        draw.text((margin_x, margin_y + i * line_height), line, fill=ink, font=font)
    return img


def save_dataset(
    n: int,
    output_dir: str | Path,
    seed: int = 0,
) -> list[Path]:
    """Generate ``n`` (image, label) pairs under ``output_dir``.

    Writes ``receipt_{i:05d}.png`` and ``receipt_{i:05d}.json`` (canonical
    serialization). Returns the list of image paths.
    """
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for i in range(n):
        ticket = generate_ticket(seed=seed + i)
        image = render_receipt_image(ticket, seed=seed + i)
        image_path = output / f"receipt_{i:05d}.png"
        label_path = output / f"receipt_{i:05d}.json"
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

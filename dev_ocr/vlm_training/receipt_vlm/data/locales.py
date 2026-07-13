"""Packs de locale pour le generateur de tickets synthetiques.

Le rendu et les distorsions sont neutres linguistiquement. Seuls varient le contenu
(enseignes, lexique produit) et les mots imprimes sur le ticket (TOTAL, TVA, merci,
moyen de paiement...). Ajouter une locale, c'est copier un pack et traduire la
quinzaine de champs.

Ecritures non latines exclues (arabe, CJK, cyrillique, grec, hebreu, thai) : le
modele ne les voit jamais a l'entrainement.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class LocalePack:
    code: str
    stores: tuple[tuple[str, str], ...]              # (name, address)
    products: tuple[tuple[str, float], ...]          # (name, base_price)
    currency_symbol: str = "€"
    currency_code: str = "EUR"
    date_order: str = "dmy"                          # "dmy" or "mdy"
    date_default: str = "Le {d} a {t}"               # {d}=formatted date, {t}=time
    date_retail: str = "DATE {d}  HEURE {t}"
    subtitle: str = "TICKET DE CAISSE"
    register_default: str = "Caisse {n}  Ticket {num}"
    register_discount: str = "CAISSE {nn}  No {num}"
    total_default: str = "TOTAL"
    total_retail: str = "MONTANT TOTAL"
    total_pay: str = "A PAYER"
    articles_default: str = "{n} article(s)"
    articles_compact: str = "Articles: {n}"
    tax_label: str = "TVA {pct}"
    tax_rate: float = 0.055
    loyalty_label: str = "CARTE FIDELITE: ****"
    tel_prefix: str = "Tel"
    payment_methods: tuple[str, ...] = ("CB", "CARTE BANCAIRE", "ESPECES", "SANS CONTACT")
    payment_default: str = "Reglement: {m}"
    payment_retail: str = "PAIEMENT : {m}"
    cash_word: str = "ESPECES"
    thankyou: tuple[str, ...] = ("Merci de votre visite !", "A bientot !", "Merci et a bientot")
    thankyou_short: tuple[str, ...] = ("Merci", "A bientot")


_FR = LocalePack(
    code="fr",
    stores=(
        ("Carrefour Market", "12 rue de la Republique, 69002 Lyon"),
        ("Carrefour City", "8 avenue Jean Jaures, 75019 Paris"),
        ("Monoprix", "21 boulevard Haussmann, 75009 Paris"),
        ("Lidl", "45 route de Vannes, 44100 Nantes"),
        ("Franprix", "3 rue de la Paix, 75002 Paris"),
        ("Super U", "10 place du Marche, 35000 Rennes"),
        ("Intermarche", "ZAC des Vergers, 13100 Aix-en-Provence"),
        ("E.Leclerc", "120 avenue de la Liberte, 59000 Lille"),
        ("Auchan", "Centre Commercial Englos, 59320 Englos"),
        ("Casino", "5 cours Gambetta, 34000 Montpellier"),
        ("Picard", "18 rue des Halles, 37000 Tours"),
        ("Aldi", "27 rue Nationale, 67000 Strasbourg"),
        ("GIFI", "14 avenue Charles de Gaulle, 33600 Pessac"),
        ("Action", "ZAC du Port, 44200 Nantes"),
    ),
    products=(
        ("LAIT DEMI-ECREME 1L", 1.09), ("YAOURT NATURE X8", 2.45), ("FROMAGE RAPE 200G", 2.89),
        ("BEURRE DOUX 250G", 2.65), ("CREME FRAICHE 30CL", 1.75), ("CAMEMBERT 250G", 2.39),
        ("YAOURT FRUITS X4", 2.10), ("MOZZARELLA 125G", 1.15), ("PATES SPAGHETTI 500G", 0.99),
        ("RIZ BASMATI 1KG", 2.19), ("HUILE TOURNESOL 1L", 1.89), ("FARINE T55 1KG", 0.95),
        ("SUCRE EN POUDRE 1KG", 1.35), ("CONFITURE FRAISE 370G", 2.25), ("CEREALES CHOCO 375G", 2.79),
        ("CAFE MOULU 250G", 3.49), ("THE VERT X25", 2.15), ("CHOCOLAT NOIR 100G", 1.59),
        ("BISCUITS PETIT DEJ 400G", 2.05), ("MIEL FLEURS 250G", 3.85), ("EAU MINERALE 6X1.5L", 2.99),
        ("JUS D'ORANGE 1L", 2.49), ("SODA COLA 1.5L", 1.85), ("SIROP GRENADINE 75CL", 2.55),
        ("BIERE BLONDE 6X25CL", 4.95), ("VIN ROUGE 75CL", 4.50), ("BANANES VRAC", 1.99),
        ("POMMES GALA 1KG", 2.49), ("TOMATES GRAPPE 500G", 2.15), ("CAROTTES 1KG", 1.29),
        ("SALADE BATAVIA", 1.05), ("CITRONS X3", 1.65), ("AVOCAT PIECE", 1.25),
        ("COURGETTES 1KG", 2.35), ("FILET POULET 400G", 5.49), ("STEAK HACHE X2", 4.25),
        ("JAMBON BLANC X4", 2.95), ("SAUMON FUME 120G", 4.85), ("LARDONS FUMES 200G", 2.45),
        ("SAVON LIQUIDE 300ML", 2.15), ("DENTIFRICE 75ML", 1.89), ("SHAMPOOING 250ML", 3.25),
        ("GEL DOUCHE 250ML", 2.49), ("PAPIER TOILETTE X6", 3.95), ("MOUCHOIRS X10", 1.45),
        ("LIQUIDE VAISSELLE 500ML", 1.79), ("LESSIVE LIQUIDE 1.5L", 6.95), ("EPONGES X3", 1.55),
        ("SACS POUBELLE 30L X20", 2.25), ("BAGUETTE TRADITION", 1.15), ("PAIN DE MIE 500G", 1.65),
        ("CROISSANTS X4", 2.45), ("BRIOCHE TRANCHEE 500G", 2.19),
    ),
)

_EN = LocalePack(
    code="en",
    stores=(
        ("Tesco Express", "45 High Street, Manchester M1 2AB"),
        ("Sainsbury's Local", "12 Market Square, Leeds LS1 6DT"),
        ("Walmart Supercenter", "3200 Cerrillos Rd, Santa Fe, NM 87507"),
        ("Target", "1 Mall Drive, Columbus, OH 43219"),
        ("Whole Foods Market", "500 Wailea Ave, Austin, TX 78701"),
        ("Costco Wholesale", "2900 Richmond Ave, Houston, TX 77098"),
        ("Aldi", "88 Queen Street, Cardiff CF10 2GP"),
        ("Trader Joe's", "610 Boston Ave, Medford, MA 02155"),
    ),
    products=(
        ("WHOLE MILK 1GAL", 3.49), ("GREEK YOGURT 32OZ", 4.29), ("BUTTER UNSALTED 1LB", 3.99),
        ("SPAGHETTI 16OZ", 1.19), ("JASMINE RICE 5LB", 6.49), ("GROUND COFFEE 12OZ", 7.99),
        ("SPRING WATER 24PK", 3.99), ("ORANGE JUICE 64OZ", 3.79), ("RED WINE 750ML", 11.99),
        ("BANANAS", 0.59), ("GALA APPLES 3LB", 4.49), ("ROMA TOMATOES", 1.99),
        ("CHICKEN BREAST 2LB", 8.99), ("SLICED HAM 8OZ", 4.29), ("SOURDOUGH LOAF", 3.49),
        ("HAND SOAP 12OZ", 2.99), ("PAPER TOWELS 6PK", 8.99), ("CROISSANTS 4CT", 4.49),
    ),
    currency_symbol="$", currency_code="USD", date_order="mdy",
    date_default="Date {d}  {t}", date_retail="DATE {d}  TIME {t}",
    subtitle="SALES RECEIPT",
    register_default="Reg {n}  Trans {num}", register_discount="REG {nn}  No {num}",
    total_default="TOTAL", total_retail="AMOUNT DUE", total_pay="BALANCE DUE",
    articles_default="{n} item(s)", articles_compact="Items: {n}",
    tax_label="TAX {pct}", tax_rate=0.0725, loyalty_label="REWARDS: ****", tel_prefix="Tel",
    payment_methods=("VISA", "MASTERCARD", "CASH", "DEBIT", "CONTACTLESS"),
    payment_default="Payment: {m}", payment_retail="PAYMENT : {m}", cash_word="CASH",
    thankyou=("Thank you for shopping!", "See you soon!", "Have a great day"),
    thankyou_short=("Thank you", "Thanks"),
)

_ES = LocalePack(
    code="es",
    stores=(
        ("Mercadona", "Calle Mayor 34, 28013 Madrid"),
        ("Carrefour Express", "Av. Diagonal 210, 08018 Barcelona"),
        ("Dia", "Calle Sierpes 12, 41004 Sevilla"),
        ("El Corte Ingles", "Plaza del Duque 8, 41002 Sevilla"),
        ("Consum", "Carrer de Colon 45, 46004 Valencia"),
        ("Alcampo", "Poligono Centrovia, 50198 Zaragoza"),
    ),
    products=(
        ("LECHE ENTERA 1L", 0.95), ("YOGUR NATURAL X8", 1.85), ("MANTEQUILLA 250G", 2.35),
        ("ESPAGUETIS 500G", 0.89), ("ARROZ REDONDO 1KG", 1.49), ("CAFE MOLIDO 250G", 3.25),
        ("AGUA MINERAL 6X1.5L", 2.40), ("ZUMO NARANJA 1L", 1.95), ("VINO TINTO 75CL", 3.95),
        ("PLATANOS", 1.49), ("MANZANAS 1KG", 1.99), ("TOMATE RAMA 500G", 1.85),
        ("PECHUGA POLLO 500G", 4.25), ("JAMON YORK X4", 2.65), ("PAN RUSTICO", 1.05),
        ("JABON MANOS 300ML", 1.95), ("PAPEL HIGIENICO X6", 3.45), ("CROISSANTS X4", 1.95),
    ),
    date_default="Fecha {d}  {t}", date_retail="FECHA {d}  HORA {t}",
    subtitle="TICKET DE COMPRA",
    register_default="Caja {n}  Ticket {num}", register_discount="CAJA {nn}  No {num}",
    total_default="TOTAL", total_retail="IMPORTE TOTAL", total_pay="A PAGAR",
    articles_default="{n} articulo(s)", articles_compact="Articulos: {n}",
    tax_label="IVA {pct}", tax_rate=0.21, loyalty_label="TARJETA CLIENTE: ****", tel_prefix="Tel",
    payment_methods=("TARJETA", "EFECTIVO", "CONTACTLESS", "VISA"),
    payment_default="Pago: {m}", payment_retail="PAGO : {m}", cash_word="EFECTIVO",
    thankyou=("Gracias por su compra!", "Hasta pronto!", "Vuelva pronto"),
    thankyou_short=("Gracias", "Hasta pronto"),
)

_DE = LocalePack(
    code="de",
    stores=(
        ("REWE", "Hauptstrasse 45, 10827 Berlin"),
        ("EDEKA", "Marktplatz 3, 80331 Munchen"),
        ("Lidl", "Bahnhofstrasse 12, 20095 Hamburg"),
        ("ALDI SUD", "Industriestrasse 8, 50667 Koln"),
        ("Kaufland", "Am Einkaufszentrum 1, 70173 Stuttgart"),
        ("dm-drogerie markt", "Konigstrasse 22, 01097 Dresden"),
    ),
    products=(
        ("VOLLMILCH 1L", 1.09), ("NATURJOGHURT 500G", 0.79), ("BUTTER 250G", 2.29),
        ("SPAGHETTI 500G", 0.89), ("BASMATIREIS 1KG", 2.49), ("KAFFEE GEMAHLEN 500G", 5.99),
        ("MINERALWASSER 6X1.5L", 2.94), ("ORANGENSAFT 1L", 1.79), ("ROTWEIN 0.75L", 4.99),
        ("BANANEN", 1.49), ("APFEL 1KG", 2.29), ("TOMATEN 500G", 1.99),
        ("HAHNCHENBRUST 400G", 4.99), ("KOCHSCHINKEN 200G", 2.49), ("BROTCHEN X6", 1.20),
        ("HANDSEIFE 300ML", 1.45), ("TOILETTENPAPIER X8", 4.49), ("CROISSANTS X4", 1.99),
    ),
    date_default="Datum {d}  {t}", date_retail="DATUM {d}  ZEIT {t}",
    subtitle="KASSENBON",
    register_default="Kasse {n}  Beleg {num}", register_discount="KASSE {nn}  Nr {num}",
    total_default="SUMME", total_retail="GESAMTBETRAG", total_pay="ZU ZAHLEN",
    articles_default="{n} Artikel", articles_compact="Artikel: {n}",
    tax_label="MwSt {pct}", tax_rate=0.19, loyalty_label="KUNDENKARTE: ****", tel_prefix="Tel",
    payment_methods=("EC-KARTE", "BAR", "KONTAKTLOS", "VISA"),
    payment_default="Zahlung: {m}", payment_retail="ZAHLUNG : {m}", cash_word="BAR",
    thankyou=("Vielen Dank fur Ihren Einkauf!", "Bis bald!", "Auf Wiedersehen"),
    thankyou_short=("Danke", "Bis bald"),
)

_IT = LocalePack(
    code="it",
    stores=(
        ("Esselunga", "Via Roma 45, 20121 Milano"),
        ("Conad", "Corso Italia 12, 00198 Roma"),
        ("Coop", "Piazza Garibaldi 3, 40121 Bologna"),
        ("Carrefour Market", "Via Torino 88, 10121 Torino"),
        ("Lidl", "Viale Europa 5, 80143 Napoli"),
        ("Eurospin", "Via del Commercio 21, 35100 Padova"),
    ),
    products=(
        ("LATTE INTERO 1L", 1.15), ("YOGURT BIANCO X8", 2.29), ("BURRO 250G", 2.49),
        ("SPAGHETTI 500G", 0.95), ("RISO ARBORIO 1KG", 2.39), ("CAFFE MACINATO 250G", 3.15),
        ("ACQUA MINERALE 6X1.5L", 2.34), ("SUCCO ARANCIA 1L", 1.89), ("VINO ROSSO 75CL", 4.25),
        ("BANANE", 1.69), ("MELE 1KG", 2.19), ("POMODORI 500G", 1.95),
        ("PETTO POLLO 500G", 4.49), ("PROSCIUTTO COTTO X4", 2.75), ("PANE CASERECCIO", 1.35),
        ("SAPONE MANI 300ML", 1.85), ("CARTA IGIENICA X6", 3.65), ("CORNETTI X4", 2.15),
    ),
    date_default="Data {d}  {t}", date_retail="DATA {d}  ORA {t}",
    subtitle="SCONTRINO",
    register_default="Cassa {n}  Scontrino {num}", register_discount="CASSA {nn}  N {num}",
    total_default="TOTALE", total_retail="IMPORTO TOTALE", total_pay="DA PAGARE",
    articles_default="{n} articolo(i)", articles_compact="Articoli: {n}",
    tax_label="IVA {pct}", tax_rate=0.22, loyalty_label="CARTA FEDELTA: ****", tel_prefix="Tel",
    payment_methods=("CARTA", "CONTANTI", "CONTACTLESS", "VISA"),
    payment_default="Pagamento: {m}", payment_retail="PAGAMENTO : {m}", cash_word="CONTANTI",
    thankyou=("Grazie e arrivederci!", "A presto!", "Grazie per la visita"),
    thankyou_short=("Grazie", "A presto"),
)

LOCALES: dict[str, LocalePack] = {p.code: p for p in (_FR, _EN, _ES, _DE, _IT)}
DEFAULT_LOCALE = "fr"


def get_locale(code: str | None) -> LocalePack:
    """Rend le pack de la locale demandee. Un code inconnu leve KeyError."""
    if not code:
        return LOCALES[DEFAULT_LOCALE]
    return LOCALES[code.strip().lower()]


def available_locales() -> list[str]:
    return sorted(LOCALES)

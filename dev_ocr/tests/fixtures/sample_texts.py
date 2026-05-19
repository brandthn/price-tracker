"""In-memory OCR text fixtures used by the unit tests.

Keeping fixtures in Python (rather than image files) lets the unit
tests run with no third-party dependency, no network and no real
photo, while still exercising every parsing edge case described in
``project_guidelines.md``.
"""

from __future__ import annotations


HAPPY_PATH = """\
CARREFOUR MARKET
12 rue de la République
75001 Paris
Tel 01 23 45 67 89
SIRET 123 456 789

15/03/2024 14:30

BANANES BIO              2,15 €
PAIN COMPLET             1,20 €
COCA COLA 1.5L           2,49 €
CAMEMBERT                3,75 €

SOUS TOTAL               9,59
TVA 5.5%                 0,52
TOTAL TTC                9,59 €
CARTE BANCAIRE           9,59
MERCI DE VOTRE VISITE
"""

WITH_QUANTITY = """\
INTERMARCHE
5 avenue des Lilas
69003 Lyon

02/04/2024 09:05

YAOURT NATURE            3,87 €
3 x 1,29
EAU MINERALE             1,50 €

TOTAL                    5,37
"""

WITH_WEIGHT = """\
LECLERC
ZAC du Pré Long
44000 Nantes

12/12/2023 18:45

POMMES GALA              2,70 €
0,452 kg x 5,98 €/kg
TOMATES GRAPPE           3,20 €

TOTAL                    5,90
"""

EMPTY_TEXT = ""

MISSING_DATE = """\
MONOPRIX
3 boulevard Haussmann
75009 Paris

PAIN AUX CEREALES       1,50 €
LAIT DEMI ECREME        0,95 €

TOTAL                   2,45
"""

ONLY_HEADER_NOISE = """\
www.example.fr
@boutique
Tel 01 02 03 04 05
SIRET 999 999 999
"""

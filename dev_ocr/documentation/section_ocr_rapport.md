# III. OCR & Vision

> Contenu destiné à la section III du rapport annuel PriceTracker.
> Toutes les mesures citées sont tracées : elles proviennent du journal de développement
> (`dev_ocr/documentation.md`, entrées 1 à 19), des fichiers d'évaluation
> (`vlm_training/checkpoints/eval_epoch0*.json`) et du banc d'essai comparatif
> (`vlm_training/checkpoints/evaluate-all-backends-kaggle.log`). Aucun chiffre n'est estimé.

---

## 3.1 Le problème

Lire un ticket de caisse est la brique la plus difficile du projet. Il ne s'agit pas de reconnaître
du texte propre, mais de convertir une **photo prise au téléphone** — cadrage de travers, éclairage
inégal, papier thermique froissé, mise en page différente à chaque enseigne — en **lignes
structurées** : une enseigne, une date, et pour chaque article un libellé, un prix et une quantité.

La difficulté n'est pas seulement optique. Un ticket réel n'écrit presque jamais un article sur une
seule ligne : le nom, le prix unitaire, le total et la quantité (`2 x`) sont éclatés sur des lignes
séparées ; la date et l'heure atterrissent à deux endroits différents (`15/10/24` puis `12:40`) ; le
poids se lit sur deux lignes (`0,972 kg` puis `2,79 €/kg`). Le moteur de lecture ne fait que la
moitié du travail — il faut ensuite **réassembler** ce que la mise en page a séparé.

Nous avons traversé quatre approches successives avant d'en retenir une, et nous en avons entraîné
deux nous-mêmes. Ce chapitre raconte ce parcours, y compris — et surtout — ce qui n'a pas marché.

## 3.2 Une architecture faite pour pivoter

La toute première décision, prise avant d'écrire la moindre ligne de reconnaissance, a été de
séparer **le moteur de lecture** du **code qui interprète le texte lu**. Le paquet `receipt_ocr`
applique un **patron Strategy** : une interface `OcrBackend` avec une seule méthode
(`extract_text(image) -> str`), un analyseur (`ReceiptParser`) totalement indépendant du moteur, et
un point d'entrée unique :

```python
from receipt_ocr import extract_receipt
data = extract_receipt("ticket.jpg")     # → {"ticket": {"date", "chaine_supermarche", "produits": [...]}}
```

Ce choix, anodin au premier jour, s'est révélé être **la décision structurante du projet**. Chacun
des cinq moteurs que nous avons ensuite essayés — PP-OCRv4, Moondream, Groq, notre modèle hybride,
notre modèle *from scratch* — s'est ajouté sous la forme d'**un fichier et d'une ligne de registre**,
sans jamais modifier l'API publique ni l'analyseur. C'est ce qui a rendu possible, à la fin, de
**comparer tous les moteurs sur les mêmes images** : ils sont interchangeables par construction. Dès
l'entrée 1 du journal, un backend `vlm` figurait d'ailleurs comme stub — la place du modèle de
vision-langage était réservée avant même que nous sachions lequel ce serait.

## 3.3 L'OCR classique : ça marche, mais…

### PaddleOCR, et la machine qui gèle

Le premier moteur réellement implémenté est **PaddleOCR**. Sur un ticket Super U, la chaîne complète
fonctionne de bout en bout : date `20241015 12:40`, adresse, et cinq produits correctement extraits.
Le résultat est là. Le coût, lui, est prohibitif :

| | Initialisation | OCR + analyse par image |
|---|---|---|
| PaddleOCR (réglages initiaux) | ~35 s | **~104 s** |

Pire, lancer la suite de tests a rendu le poste **apparemment figé : 100 % de CPU, plusieurs minutes
sans réponse**. Le diagnostic est instructif, car ce n'était *pas* une boucle infinie dans notre
code, mais **sept causes cumulées** : des modèles lourds et un multi-threading agressif ; une API
PaddleOCR 3.x qui avait changé ; un moteur `paddle_static` qui échoue sur certaines *builds* Windows ;
des photos pleine résolution (2,3 Mo) envoyées telles quelles ; un modèle **rechargé à chaque appel**
faute de cache ; et surtout des tests d'intégration qui, en découvrant récursivement le cache Kaggle,
tournaient sur **~395 images** — soit des heures à pleine charge.

Les correctifs sont autant de décisions d'ingénierie assumées, résumées par un principe explicite,
**« la stabilité avant la vitesse brute sur Windows »** : forcer le moteur dynamique, plafonner à
**2 threads CPU**, redimensionner à **1 280 px** avant lecture, désactiver MKL-DNN, **mettre le
backend en cache** (singleton), et borner les tests d'intégration à **3 images par défaut**.

C'est aussi à ce moment que l'analyseur a appris à recoller les lignes éclatées décrites en 3.1 — la
logique la plus subtile du paquet, et celle qui a survécu à tous les changements de moteur ensuite.

### PP-OCRv4 mobile : l'optimisation qui déçoit

Cent secondes par image restant inutilisables, nous avons ajouté un moteur **PP-OCRv4 mobile**, plus
léger, avec une image réduite à 640 px.

| | Initialisation | OCR + analyse |
|---|---|---|
| `paddle` | ~35 s | ~104 s |
| `ppocrv4` | ~29 s | **~54 s** |

Deux fois plus rapide — mais la sortie structurée **se dégrade** : là où la version pleine résolution
extrayait cinq produits, celle-ci n'en retrouve que deux. La réduction à 640 px fait tout simplement
**disparaître des lignes** de la détection. Le gain de vitesse est payé en rappel : *pas de repas
gratuit*. Nous avons également exploré une piste **ONNX** pour un déploiement mobile réel — impasse :
le moteur `onnxruntime` n'est pas accepté par le constructeur de pipeline de PaddleOCR 3.5.

Le verdict de cette phase est structurel, et il motive tout le reste : même à 54 secondes par image,
l'OCR classique reste trop lent, et son plafond de qualité — enseigne lue `SUPER(U`, heuristiques de
recollement fragiles — ne dépend pas de nos réglages.

## 3.4 Le VLM local : un échec instructif

Nous avons alors parié sur un **modèle de vision-langage** local, **Moondream 0.5B** en poids int8,
qui lit l'image et produit directement la structure — supprimant, en théorie, l'étape fragile de
recollement.

Le résultat, sur de vraies photos, est un **échec net** : liste de produits **vide**, enseigne
hallucinée, et surtout un modèle qui traite la tâche comme une **conversation** au lieu d'une
extraction — il répond `"Note: The image shows…"` là où on attend du JSON. Après trois tentatives, il
finit par rendre `[Text is illegible]`. Le tout pour **15 à 60 secondes par image** sur CPU : ni plus
rapide, ni utilisable.

Les causes sont identifiées sans complaisance : **0,5 milliard de paramètres, c'est trop peu** pour
une extraction complète en une passe sur une photo longue et penchée ; le ticket n'occupe qu'une
fraction du cadre, et le modèle lit la table, les mains, le sol.

La réponse d'ingénierie est, elle, réutilisable, et c'est ce qui rend cet échec intéressant. Nous
avons construit **trois modes d'extraction**, en partant du constat qu'*un petit modèle réussit mieux
des tâches étroites* :

| Mode | Principe |
|---|---|
| `transcribe` *(défaut)* | Le VLM ne fait que **transcrire** le ticket ligne à ligne — puis on **réutilise l'analyseur de l'ère OCR**. |
| `json` | Une seule requête, JSON complet en une passe. |
| `multipass` | La tâche est **décomposée en trois requêtes** (en-tête / date / produits), fusionnées ensuite. |

À cela s'ajoutent un prétraitement d'image (recadrage automatique sur le ticket, 1 536 px, qualité
95), un nettoyage des réponses bavardes, une **validation de sortie** et une politique de reprise :
en cas d'échec, on rejoue avec un prompt strict et un recadrage centré. Et si tout échoue, le
pipeline **lève une erreur** au lieu de renvoyer du JSON plausible. Cette doctrine — **« échouer
bruyamment plutôt que fabriquer silencieusement »** — est restée une règle du projet.

Moondream 0.5B n'a jamais atteint les critères de succès que nous lui avions fixés. Mais le mode
`transcribe`, qui recycle l'analyseur OCR, et la validation de sortie ont servi à tous les moteurs
suivants.

## 3.5 Le basculement cloud : Groq

Nous avons donc branché un **VLM hébergé**, `llama-4-scout` (17 Md de paramètres) chez **Groq**, en
tant que simple fournisseur supplémentaire — une variable d'environnement suffit à basculer de
Moondream à Groq, l'architecture n'ayant pas bougé.

Le contraste est brutal : **~5 secondes par image**, contre 54 à 104 s pour l'OCR local et 15 à 60 s
pour un Moondream qui ne produisait rien. Détail savoureux, le mode `json` — celui qui **échouait**
sur le modèle 0,5B — est ici le **seul autorisé** : le fournisseur refuse de démarrer dans un autre
mode. Les modes `transcribe` et `multipass` n'étaient que des béquilles pour compenser un manque de
capacité.

Groq n'a pas pour autant été magique, et le nettoyage qu'il a fallu écrire en dit long sur la
réalité des sorties de LLM :

- **le même produit répété trois ou quatre fois** → déduplication stricte (nom normalisé *et* prix
  arrondi *et* quantité identiques) ;
- **deux blocs JSON concaténés**, ou un tableau tronqué → on collecte tous les candidats et on
  **garde le plus riche qui soit valide** ; budget de tokens porté de 1 024 à 4 096 ;
- **dates au format français** (`15/10/24`) → normalisation vers le schéma canonique ;
- **quantités fractionnaires** (`0.972` pour un article au poids) → arrondi à au moins 1 ;
- **plafond de 4 Mo** sur la charge base64 → contrôle de taille avant envoi.

Groq est devenu le **moteur par défaut en production**. Il l'est resté.

*Note de sécurité :* le fichier `.env` n'était initialement pas ignoré par Git. Il a été ajouté au
`.gitignore`, un `.env.example` sans secret a été versionné, et la consigne de **rotation de la clé**
a été inscrite au journal.

## 3.6 Entraîner nos propres modèles

Utiliser une API est un choix d'ingénieur ; **en comprendre le fonctionnement suppose d'en construire
une**. Nous avons donc entraîné deux modèles, avec deux ambitions différentes. Groq change alors de
rôle : de moteur de production, il devient **l'annotateur** qui pré-étiquette nos photos réelles.

### a) `receipt-vlm-500m` — un modèle hybride de type LLaVA (~457 M paramètres)

L'architecture assemble deux réseaux pré-entraînés **gelés** autour de composants que nous avons
écrits :

```
Image (224×224) → CLIP ViT-B/16  [GELÉ, ~86 M]
                → Projecteur multimodal  [ÉCRIT PAR NOUS, ~6,8 M]
                → SmolLM2-360M  [GELÉ] + LoRA rang 16  [ÉCRIT PAR NOUS, ~4 M]
                → Décodage sous contrainte grammaticale  [ÉCRIT PAR NOUS, 0 paramètre]
```

Trois pièces sont de nous. Le **projecteur** est un « Q-Former allégé » : 32 vecteurs de requête
apprenables qui interrogent, par attention croisée, les 197 vecteurs d'image de CLIP, et produisent
32 « tokens visuels » directement lisibles par le modèle de langage. La **LoRA** est implémentée à la
main, sans la bibliothèque `peft` : on n'entraîne pas les poids `W`, mais un produit de deux petites
matrices `B·A` ajouté à la sortie, `B` initialisé à zéro pour que l'adaptateur soit l'identité au
départ. Enfin, le **décodeur sous contrainte** est un automate à états qui, à chaque caractère,
masque les tokens interdits par la grammaire du schéma — ce qui **garantit un JSON valide par
construction**, et non « le plus souvent ».

Au total, la surface entraînable est de **~10,8 M paramètres sur 457 M, soit 2,4 %**. C'est
précisément l'intérêt de l'approche : obtenir un modèle spécialisé sans jamais réentraîner CLIP ni le
modèle de langage.

Trois écarts à notre spécification initiale méritent d'être assumés, car ce sont des décisions, pas
des renoncements : SmolLM2-**360M** au lieu de 1,7 Md (sans quoi le « ~500 M total » du cahier des
charges ne tenait pas) ; **aucune tête JSON entraînée**, remplacée par l'automate — *une tête
entraînée ne peut pas garantir un JSON valide, un automate si* ; et une entrée en **224×224** et non
448, car 448 sur un ViT-B/16 produirait 785 patches et **casserait les embeddings positionnels
gelés** du modèle figé.

**Le verdict est sévère, et nous le publions tel quel : ce modèle n'a jamais été évalué contre ses
propres critères d'acceptation.** Sa meilleure trace mesurée est un ANLS de ~0,62 sur 16 échantillons
de validation, avec une **précision de date de 0,000**. L'artefact d'inférence de 1,82 Go a été
exporté depuis un point de contrôle de **phase 2, epoch 4** — la phase 3 prévue n'a jamais tourné. Et
lors du banc d'essai final, il a **planté** au chargement (incompatibilité `huggingface_hub`) : il
**n'a aucune colonne dans le tableau comparatif** de la section 3.7. Un modèle architecturalement
complet, testé et déployable, mais jamais mesuré : c'est un résultat, et il est négatif.

### b) `OcrVLM` — le modèle *from scratch* (8,73 M paramètres)

Le second modèle pousse la logique à son terme : **aucun poids pré-entraîné**, ni CLIP, ni modèle de
langage. Un encodeur convolutif suivi d'attention, un décodeur autorégressif, tous deux écrits à la
main. Il est **52 fois plus petit** que le précédent.

Les choix de conception répondent tous à la nature des tickets. L'entrée est en **384×256, en mode
portrait** — un ticket est haut et étroit — et l'image est **letterboxée** sur fond blanc pour ne pas
écraser le texte. Le tokenizer est **au caractère** (vocabulaire de 190 symboles) : c'est ce qui rend
le modèle **ouvert par construction** — n'importe quel nom de produit, n'importe quel accent, se
décode sans mot inconnu. Enfin, la cible n'est pas du JSON mais un **schéma linéarisé** compact
(inspiré de Donut), reconverti ensuite en JSON par une fonction de récupération **volontairement
tolérante**, capable de reconstruire une sortie partielle.

L'entraînement s'est fait en trois temps, et c'est le meilleur matériau de ce rapport.

**Temps 1 — apprendre à lire (synthétique).** Faute de données annotées, nous avons écrit un
**générateur de tickets synthétiques** : plusieurs enseignes, mises en page de ticket thermique
variées, palettes de couleurs, et surtout des **dégradations réalistes** (rotation, perspective,
flou, bruit, recompression JPEG, vignettage, fond de table). Subtilité d'annotation : les totaux, la
TVA et les lignes de paiement sont **imprimés sur l'image mais absents des étiquettes**, ce qui
apprend au modèle à les ignorer. Les tickets sont générés **à la volée à chaque epoch** — variété
infinie, coût d'annotation nul, et aucun stockage disque. Après 40 epochs sur un T4 gratuit :

| Sur données synthétiques | epoch 1 | epoch 40 |
|---|---|---|
| ANLS | 0,32 | **0,904** |
| Rappel produits | 0,02 | **0,558** |
| JSON valide | 1,00 | **1,00** |

Le modèle apprend. Sur du synthétique, il lit.

**Temps 2 — la découverte du gouffre.** Confronté pour la première fois à **533 tickets réels**, il
s'effondre : ANLS **0,170**, rappel produits **0,001**. Mais le mode de défaillance est
extraordinairement instructif — **le modèle n'est pas cassé**. Il produit des tickets *parfaitement
valides et cohérents*… entièrement inventés à partir des enseignes synthétiques qu'il a mémorisées :

```
Vérité : 'TRADERJOE'S'   →  Prédiction : 'Eurospin'
Vérité : 'CVS/pharmacy'  →  Prédiction : 'Lidl'
```

Il **génère depuis son a priori synthétique sans réellement regarder les pixels**. C'est le fossé
*sim-to-real*, dans sa forme la plus pure. Et le diagnostic est sans appel : **ajouter des epochs
synthétiques ne servirait à rien** — cela ne ferait qu'affûter l'a priori. Le modèle doit *voir* des
tickets réels.

**Temps 3 — le mélange, et une métrique à inventer.** Nous avons donc réentraîné en mélangeant
**3 500 tickets réels (875 distincts, répétés 4 fois) à 4 000 synthétiques**. Le comportement change
qualitativement :

```
epoch 40 : 'TRADERJOE'S' → 'Eurospin'                        (hallucination pure)
epoch 50 : 'TRADERJOE'S' → 'WAL[UNK]MART' , 1er article 'BANANAS' @0.59   (il lit)
```

Il lit vraiment. Mais **nos métriques ne le voyaient pas** : ANLS et F1 restaient à zéro, car elles
comparent en correspondance exacte et pénalisent une lecture *presque* juste autant qu'une
hallucination. Nous avons donc **conçu une métrique adaptée** : une *précision de lecture* définie
comme `1 − CER` sur le texte lisible concaténé et normalisé (minuscules, sans espaces ni
ponctuation). Validée sur des cas connus : texte correct mais prix faux → 1,0 ; lecture approchée →
0,93 ; enseigne hallucinée → 0,0.

| Tickets réels (WildReceipt) | epoch 40 (synthétique seul) | epoch 50 (mélange) |
|---|---|---|
| **Précision de lecture (1−CER)** | **0,033** | **0,122** (×3,7) |
| ANLS | 0,170 | 0,184 |
| Rappel produits | 0,001 | 0,002 |

**La direction est prouvée ; la magnitude reste faible.** Le `[UNK]` dans `WAL[UNK]MART` est
d'ailleurs notre tokenizer caractère qui rencontre un glyphe hors de son vocabulaire de 190 symboles.

### Ce que l'entraînement nous a coûté

Ces résultats se sont payés en incidents, et les taire donnerait une image fausse du travail réel :

- **Un shell tué en pleine epoch** a interrompu le premier entraînement ; la trace tronquée nous a
  d'abord fait accuser à tort la bibliothèque d'augmentation — un test de résistance de 800 appels
  n'a révélé aucune défaillance.
- **Le disque plein** (`SQLITE_FULL`) a rendu l'entraînement local impossible et forcé la migration
  vers Colab, puis Kaggle.
- **Des points de contrôle perdus** : les disques éphémères sont effacés à l'arrêt, et seul le
  meilleur checkpoint était sauvegardé *aux frontières de phase* — un arrêt en milieu de phase
  effaçait toutes les epochs depuis la dernière frontière. Correctif : **une sauvegarde par epoch** et
  une reprise ordonnée.
- **Un conflit de dépendances** (la version de `tokenizers` exigée par Moondream est incompatible
  avec celle de `transformers`) a imposé un environnement virtuel séparé pour l'entraînement.
- **Le poste de travail figé** de nouveau, cette fois par la génération autorégressive sur 424
  tickets : l'évaluation a été **définitivement déportée sur Kaggle (T4)**, où elle prend 8 à 10
  minutes par point de contrôle. C'est devenu une règle permanente du projet.
- **Le quota de l'annotateur** : l'offre gratuite de Groq plafonne à 500 000 tokens par jour, soit
  ~128 tickets. Ce mur a **dicté le choix des jeux de données** : nous avons privilégié ceux qui
  fournissent *déjà* le texte transcrit plutôt que ceux qui auraient exigé une annotation par Groq.

## 3.7 Évaluation comparative

Tous les moteurs ont finalement été évalués **sur la même base de 18 photos de tickets réels**, avec
les mêmes métriques. C'est l'aboutissement du choix d'architecture de la section 3.2.

| Métrique | paddle | ppocrv4 | groq | **ocrvlm** *(le nôtre, from scratch)* |
|---|---|---|---|---|
| Précision de lecture (1−CER) | 0,111 | 0,074 | **0,790** | **0,113** |
| Sortie valide (non vide) | 0,833 | 0,722 | **1,000** | **1,000** |
| Rappel produits | 0,106 | 0,071 | **0,682** | 0,000 |
| Field F1 | 0,109 | 0,025 | **0,746** | 0,000 |
| ANLS | 0,186 | 0,147 | **0,986** | 0,166 |
| Date (correspondance exacte) | 0,000 | 0,000 | **0,944** | 0,000 |

Trois lectures s'imposent.

**1. Groq écrase tout.** ANLS 0,986, Field F1 0,746, date lue dans 94 % des cas. Un VLM *frontier*
hébergé reste hors de portée de ce que nous pouvons entraîner ou faire tourner localement. C'est la
raison, factuelle et non idéologique, pour laquelle il est le moteur de production.

**2. Notre modèle de 8,7 M paramètres, entraîné de zéro sur un GPU gratuit, égale PaddleOCR en
lecture pure** (0,113 contre 0,111), **dépasse PP-OCRv4** (0,074), et il est le **seul moteur local à
produire 100 % de sorties exploitables** (PaddleOCR : 83 %, PP-OCRv4 : 72 %) — grâce à la
récupération tolérante décrite en 3.6.b. Face à des moteurs OCR industriels, développés par des
équipes dédiées et entraînés sur des corpus considérables, c'est le résultat que nous défendons.

**3. Mais il obtient 0,000 en rappel produits et en Field F1.** Il **lit des caractères ; il n'extrait
pas encore des champs**. Son erreur de prix de 0,000 n'est d'ailleurs pas une victoire — elle signifie
qu'il n'a jamais apparié un produit permettant de comparer un prix. À noter enfin qu'**aucun moteur
local ne lit une date** : 0,000 partout, y compris pour notre modèle hybride. Seul Groq y parvient.

## 3.8 Mise en production

Puisque les moteurs sont interchangeables, chacun est déployé comme **son propre service Cloud Run**
— six au total : `ocr-paddle`, `ocr-ppocrv4`, `ocr-vlm-moondream`, `ocr-vlm-groq`, `ocr-vlm-receipt`
et `ocr-vlm-scratch`. Le code commun (analyseur, schéma, orchestration) est factorisé dans une
bibliothèque partagée ; chaque service n'embarque **que son moteur**, de sorte que l'image Groq ne
transporte pas PaddlePaddle et que l'image Paddle ne transporte pas PyTorch.

L'intérêt n'est pas seulement l'isolation : en publiant le **même ticket sur deux files**, on obtient
deux lectures du même ticket, écrites dans les mêmes tables — la comparaison des moteurs devient
possible **sur du trafic réel**, et non plus seulement sur un jeu de test figé.

## 3.9 Limites et perspectives

Nous refermons ce chapitre sur ce qui ne marche pas, car c'est ce qui oriente la suite.

- **La date n'est lue par aucun modèle local** — 0,000 partout, y compris sur données *synthétiques*,
  là où le modèle dispose pourtant d'étiquettes parfaites et de données illimitées. Il produit des
  dates plausibles mais fausses. L'anomalie est trop nette pour être une fatalité : c'est
  vraisemblablement un correctif ciblé, à fort rendement.
- **Passer de la lecture à l'extraction.** Le modèle *from scratch* lit environ 12 % des caractères
  d'un ticket réel ; il faut monter ce chiffre avant que le rappel produits puisse décoller. Les
  leviers identifiés sont plus de données réelles, une augmentation synthétique plus agressive, et
  davantage d'epochs — la courbe **montait encore** quand nous avons atteint le plafond d'epochs.
- **Un levier gardé en réserve** : initialiser le décodeur depuis un petit modèle de langage
  pré-entraîné multilingue (ce que fait Donut). C'est le gain de qualité le plus important encore
  disponible — mais il **romprait la pureté du « entièrement from scratch »**, qui est l'objet même de
  l'exercice. Nous l'avons délibérément laissé de côté.
- **Le modèle hybride doit être évalué**, ou abandonné. Il est complet, testé, exporté — et sans
  mesure. C'est une dette, pas un résultat.

En l'état, PriceTracker lit ses tickets avec Groq, et sait exactement **de combien** ses propres
modèles en sont éloignés. C'est, nous semble-t-il, la conclusion la plus utile d'un travail
d'ingénierie : non pas un modèle qui gagne, mais une chaîne de décisions traçable, et une mesure
honnête de ce qu'elle vaut.

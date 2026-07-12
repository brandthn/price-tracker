# III. OCR & Vision

Lire un ticket est la brique la plus difficile du projet : convertir une **photo prise au téléphone**
— cadrage de travers, papier froissé, mise en page différente à chaque enseigne — en lignes
structurées (enseigne, date, produit, prix, quantité). Un ticket réel n'écrit presque jamais un
article sur une seule ligne : nom, prix et quantité sont éclatés, la date et l'heure atterrissent à
deux endroits. Le moteur de lecture ne fait que la moitié du travail ; il faut ensuite **réassembler**.

Nous avons traversé quatre approches avant d'en retenir une, et nous en avons **entraîné deux
nous-mêmes**.

## 3.1 Données et métriques

### Sources de données

| Source | Rôle |
|---|---|
| **Tickets synthétiques** — générés par nous (`receipt_vlm/data/synthetic.py`) | **Source principale d'entraînement.** 4 000/epoch, générés **à la volée** (jamais stockés), 5 langues latines, mises en page et dégradations aléatoires. Volume annoté illimité à coût nul. |
| **WildReceipt** — `download.openmmlab.com/mmocr/data/wildreceipt.tar` | Entraînement (804 tickets ×4) **et principal jeu de test réel** (424). Retenu car il fournit déjà le texte transcrit. |
| **ExpressExpense SRD** — `expressexpense.com/large-receipt-image-dataset-SRD.zip` | Entraînement (71) + test (38). |
| **CORD-v2** — `huggingface.co/datasets/naver-clova-ix/cord-v2` | Entraînement du modèle hybride, puis **écarté** de l'évaluation : tickets indonésiens (roupies, dates vides), ANLS 0,000. |
| **TrainingDataPro** — `huggingface.co/datasets/TrainingDataPro/ocr-receipts-text-detection` | Validation (10) + test (9). Repère plus lisible que WildReceipt. |
| **Photos françaises** — 19 photos prises par nous | Pseudo-annotées par Groq (18/19). Base du **benchmark comparatif final**. |

Au total **1 875 tickets réels annotés**. Le choix des jeux a été **dicté par une contrainte** : l'offre
gratuite de Groq, notre annotateur, plafonne à ~128 tickets/jour. Nous avons donc privilégié les jeux
livrant *déjà* le texte transcrit plutôt que ceux exigeant une annotation.

### Métriques

| Métrique | Ce qu'elle mesure |
|---|---|
| **ANLS** | Ressemblance entre texte prédit et texte attendu (distance de Levenshtein normalisée), de 0 à 1. Tolérante aux petites fautes, contrairement à une correspondance exacte. |
| **Rappel produits** | Part des articles du ticket effectivement retrouvés. |
| **Field F1** | Exactitude des champs structurés (enseigne, date, prix) en correspondance **exacte**. |
| **Précision de lecture (1−CER)** | **Métrique que nous avons conçue** (voir 3.4) : lecture pure du texte, indépendamment de la structure. |
| **Sortie valide** | Part des tickets pour lesquels le moteur produit une structure exploitable. |

## 3.2 Une architecture faite pour pivoter

Première décision, prise avant toute ligne de reconnaissance : séparer **le moteur de lecture** du
code qui **interprète** le texte lu (patron *Strategy*). Une interface `OcrBackend`, un analyseur
indépendant du moteur, un point d'entrée unique.

Ce choix s'est révélé structurant. Chacun des cinq moteurs essayés ensuite s'est ajouté sous la forme
d'**un fichier et d'une ligne de registre**, sans jamais modifier l'API. C'est ce qui rend possible,
en 3.5, de **comparer tous les moteurs sur les mêmes images** : ils sont interchangeables par
construction.

## 3.3 Trois approches, trois enseignements

**L'OCR classique (PaddleOCR).** Fonctionne de bout en bout — cinq produits extraits sur un ticket
Super U — mais à **~104 s par image**, et le poste s'est retrouvé **figé à 100 % de CPU** (modèles
rechargés à chaque appel, tests lancés sur ~395 images). Correctifs : cache du moteur, 2 threads,
image réduite à 1 280 px. Une variante mobile (PP-OCRv4) descend à **~54 s**, mais **perd des
produits** — la réduction à 640 px fait disparaître des lignes de la détection. *Pas de repas
gratuit.* Le plafond de qualité (enseigne lue `SUPER(U`) est structurel, pas un problème de réglage.

**Le VLM local (Moondream 0,5 Md).** Échec net : liste de produits **vide**, enseigne hallucinée, et
un modèle qui traite la tâche comme une **conversation** (`"Note: The image shows…"`) au lieu d'une
extraction. 0,5 milliard de paramètres, c'est trop peu. Nous en tirons deux acquis réutilisés
partout ensuite : un mode où le VLM se contente de **transcrire**, l'analyseur OCR reprenant la main ;
et une doctrine — **« échouer bruyamment plutôt que fabriquer silencieusement »** : si la validation
échoue, on lève une erreur, on ne renvoie pas du JSON plausible.

**Le cloud (Groq, `llama-4-scout`).** **~5 s par image**, contre 54 à 104 s en local. Devient le
**moteur de production**, sans changer une ligne de l'architecture. Il a fallu néanmoins nettoyer ses
sorties : produits dupliqués, blocs JSON concaténés, dates au format français, quantités
fractionnaires.

## 3.4 Entraîner nos propres modèles

Utiliser une API est un choix d'ingénieur ; **en comprendre le fonctionnement suppose d'en construire
une**. Groq change alors de rôle : de moteur de production, il devient **l'annotateur** de nos photos.

### a) Modèle hybride, ~457 M paramètres

CLIP ViT-B/16 **gelé** → un **projecteur écrit par nous** (32 vecteurs de requête qui interrogent
l'image par attention croisée) → SmolLM2-360M **gelé** + une **LoRA implémentée à la main**, sans
bibliothèque → un **décodeur sous contrainte grammaticale** qui *garantit* un JSON valide par
construction. Surface entraînable : **10,8 M sur 457 M, soit 2,4 %** — tout l'intérêt de l'approche.

**Verdict honnête : ce modèle n'a jamais été évalué contre ses propres critères.** L'export de 1,82 Go
provient d'un point de contrôle intermédiaire (la phase finale n'a jamais tourné), et il a **planté au
banc d'essai**. Il n'a **aucune colonne** dans le tableau de la section 3.5. Un modèle complet, testé,
déployable — mais sans mesure. C'est une dette, pas un résultat.

### b) Modèle *from scratch*, 8,73 M paramètres (52× plus petit)

**Aucun poids pré-entraîné** : encodeur convolutif + attention, décodeur autorégressif, tous deux
écrits à la main. Entrée **384×256 en portrait** (un ticket est haut et étroit), tokenizer **au
caractère** — donc ouvert par construction : n'importe quel nom de produit se décode.

**Temps 1 — il apprend (synthétique, 40 epochs).** ANLS **0,904**, rappel produits **0,558**, JSON
valide 1,00. Sur du synthétique, il lit.

**Temps 2 — le gouffre.** Confronté à 533 tickets réels, il s'effondre : ANLS **0,170**, rappel
**0,001**. Mais le mode de défaillance est instructif : **le modèle n'est pas cassé**. Il produit des
tickets *valides et cohérents*… entièrement inventés depuis les enseignes synthétiques mémorisées.

```
Vérité : 'TRADERJOE'S'   →  Prédiction : 'Eurospin'
Vérité : 'CVS/pharmacy'  →  Prédiction : 'Lidl'
```

Il **génère depuis son a priori sans regarder les pixels** : c'est le fossé *sim-to-real*. Diagnostic
sans appel — **ajouter des epochs synthétiques ne servirait à rien**, cela ne ferait qu'affûter l'a
priori. Le modèle doit *voir* du réel.

**Temps 3 — le mélange, et une métrique à inventer.** Réentraînement en mélangeant **3 500 tickets
réels à 4 000 synthétiques**. Le comportement change :

```
epoch 40 : 'TRADERJOE'S' → 'Eurospin'                                    (hallucination)
epoch 50 : 'TRADERJOE'S' → 'WAL[UNK]MART' , 1er article 'BANANAS' @0.59   (il lit)
```

Mais **nos métriques ne le voyaient pas** : ANLS et F1 restaient à zéro, car elles pénalisent une
lecture *presque* juste autant qu'une hallucination. Nous avons donc **conçu une métrique adaptée** —
la précision de lecture (`1 − CER`) sur le texte concaténé normalisé, qui mesure la lecture
indépendamment de la structure. Elle, elle voit le progrès : **0,033 → 0,122 (×3,7)**. *La direction
est prouvée ; la magnitude reste faible.*

Ce parcours s'est payé en incidents — poste figé, disque plein, points de contrôle perdus sur disques
éphémères — qui ont conduit à déporter définitivement l'entraînement et l'évaluation sur GPU distant
(Kaggle T4).

## 3.5 Évaluation comparative

Tous les moteurs, évalués **sur les mêmes 18 photos réelles**, avec les mêmes métriques —
l'aboutissement du choix d'architecture de la section 3.2.

| Métrique | paddle | ppocrv4 | groq | **ocrvlm** *(le nôtre)* |
|---|---|---|---|---|
| Précision de lecture (1−CER) | 0,111 | 0,074 | **0,790** | **0,113** |
| Sortie valide | 0,833 | 0,722 | **1,000** | **1,000** |
| Rappel produits | 0,106 | 0,071 | **0,682** | 0,000 |
| Field F1 | 0,109 | 0,025 | **0,746** | 0,000 |
| ANLS | 0,186 | 0,147 | **0,986** | 0,166 |
| Date (exacte) | 0,000 | 0,000 | **0,944** | 0,000 |

**1. Groq écrase tout** (ANLS 0,986, date lue dans 94 % des cas). Un VLM *frontier* hébergé reste hors
de portée de ce que nous pouvons entraîner localement : c'est la raison, factuelle, pour laquelle il
est en production.

**2. Notre modèle de 8,7 M paramètres, entraîné de zéro sur un GPU gratuit, égale PaddleOCR en lecture
pure** (0,113 vs 0,111), **dépasse PP-OCRv4**, et est le **seul moteur local à 100 % de sorties
exploitables** (PaddleOCR : 83 %). Face à des moteurs OCR industriels, c'est le résultat que nous
défendons.

**3. Mais il obtient 0,000 en rappel produits et en Field F1** : il **lit des caractères, il n'extrait
pas encore des champs**. Son erreur de prix de 0,000 n'est pas une victoire — il n'a jamais apparié un
produit permettant de comparer un prix. Et **aucun moteur local ne lit une date**.

## 3.6 Mise en production et limites

Les moteurs étant interchangeables, chacun est déployé comme **son propre service Cloud Run** (six au
total). En publiant le **même ticket sur deux files**, on obtient deux lectures comparables : le
banc d'essai devient possible **sur du trafic réel**.

Restent trois chantiers ouverts. **La date n'est lue par aucun modèle local** — 0,000 y compris sur
données *synthétiques*, là où les étiquettes sont parfaites : l'anomalie est trop nette pour être une
fatalité, c'est vraisemblablement un correctif ciblé à fort rendement. **Passer de la lecture à
l'extraction** suppose de faire monter les ~12 % de caractères lus ; la courbe **montait encore**
quand nous avons atteint le plafond d'epochs. Enfin, un **levier est gardé en réserve** : initialiser
le décodeur depuis un petit modèle de langage pré-entraîné — le gain le plus important encore
disponible, mais il romprait la pureté du « entièrement *from scratch* », qui est l'objet même de
l'exercice.

En l'état, PriceTracker lit ses tickets avec Groq, et sait **exactement de combien** ses propres
modèles en sont éloignés. C'est la conclusion la plus utile d'un travail d'ingénierie : non pas un
modèle qui gagne, mais une chaîne de décisions traçable et une mesure honnête de ce qu'elle vaut.

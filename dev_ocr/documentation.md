# Notes de dev OCR

Trace de ce qu'on a fait et des trucs intéressants tombés en route.
Le journal court, au fil de l'eau, est dans journal_dev_ocr.md.


## 2026-05-19 première version

Package qui sort un dict structuré depuis une photo de ticket. Le découpage : un
backend OCR rend du texte brut, ReceiptParser en fait le dict. Les deux ne se
connaissent pas, donc on change de moteur sans toucher au parsing. C'est tout
l'intérêt, et ça n'a pas bougé depuis.

Deux choix qui ont tenu : aucune enseigne en dur (on la déduit des premières
lignes), et les imports des libs OCR faits à l'instanciation du backend, pas au
chargement du module sinon on ne peut plus lancer un seul test sans avoir
installé PaddleOCR.


## 2026-05-23 le PC qui freeze

Lancer PaddleOCR bloquait la machine. Pas une boucle infinie : gros modèles qui
prennent tous les cœurs, photos envoyées en pleine résolution, backend recréé
(donc poids rechargés) à chaque appel, et des tests d'intégration qui ramassaient
environ 395 images. Plus paddle_static qui casse sur Windows (oneDNN).

Sur Windows on privilégie donc la stabilité à la vitesse : paddle_dynamic, 2
threads, resize 1280 px, MKL-DNN coupé, modèles chargés une fois.

Le parser a aussi dû apprendre les vrais tickets : sur une photo, l'OCR éclate
nom / prix / total / quantité sur des lignes séparées, et la date et l'heure
aussi. Rien à voir avec un ticket propre.

Résultat : environ 35 s d'init puis environ 100 s par grosse image. Lent mais correct.


## 2026-05-23 ppocrv4

Backend plus rapide (poids mobile, entrée 640 px), environ 2x moins de temps. ONNX n'est
pas branchable ici, PaddleOCR 3.5 ne l'accepte pas dans son constructeur.


## 2026-05-23 Moondream 0.5B en local

Sur de vraies photos, le JSON sortait inutilisable : produits vide, et le modèle
qui commente l'image ("Note: The image shows...") au lieu de la lire.

Ce qui a débloqué : arrêter de lui demander le JSON complet d'un coup. Un 0.5B est
bien meilleur sur une tâche étroite ("transcris") que sur une tâche large
("extrais-moi ce JSON"). Donc mode transcribe par défaut, et on réutilise les
heuristiques du parser qui marchent déjà.

Décision assumée : quand la validation échoue au bout des retries, on lève une
erreur. On échoue franchement plutôt que de rendre du JSON inventé.

Bilan honnête quand même : le 0.5B en local ne suffit pas sur les photos
difficiles. C'est ce qui amène Groq.


## 2026-05-25 Groq (cloud)

Même architecture, on change juste de provider par variable d'env donc on peut
comparer local et cloud sans rien réécrire, ce qui est exactement ce qu'on
voulait. Le provider force le mode JSON.

Au passage : .env n'était pas gitignoré. Si la clé Groq a traîné dans un commit,
il faut la faire tourner.

Groq répétait parfois le même produit 3-4 fois, sortait deux blocs JSON
concaténés, ou des unités fractionnaires (0.972 pour du poids au kilo). Le schéma
n'était jamais cassé, mais les doublons polluent directement le total. D'où une
normalisation + dédoublonnage après n'importe quel VLM. Subtilité : deux produits
ne fusionnent que si nom, prix ET quantité sont identiques. Même nom à prix
différent, ça arrive vraiment sur un ticket.


## 2026-05-25 worker Cloud Run

Coquille événementielle autour du package : Pub/Sub → GCS → OCR → Cloud SQL. Le
package n'a pas été réécrit.

Le point à retenir, c'est la sémantique HTTP : une image illisible renvoie 204 (on
marque le ticket en échec et on ACK, parce qu'il est inutile de faire rejouer
Pub/Sub : ça échouera pareil). Seules les pannes d'infra renvoient 5xx, là où un
retry a du sens.

Les tests pg tournent sur un vrai Postgres (testcontainers). Trois sur quatre
plantaient : conteneur partagé mais la fixture rejouait tout le DDL à chaque test,
donc "type ticket_status already exists". DDL de test rendu idempotent. Problème
de fixture, pas de code.


## 2026-06-11 le VLM maison (hybride)

Livrable académique : un VLM environ 457M monté à la main. CLIP gelé + un projecteur
multimodal écrit from scratch + SmolLM2 gelé avec des LoRA faits main + un
décodage JSON contraint par machine à états.

Le décodage contraint est la vraie bonne idée : une tête entraînée ne peut pas
*garantir* du JSON valide, un masque de tokens si. Le modèle sort le schéma
canonique directement, donc tout le pipeline existant marche sans changement.

Entraîné en 3 phases (projecteur seul, puis LoRA, puis alignement JSON). Données
majoritairement synthétiques : on génère des faux tickets français, parce qu'on n'a
pas de jeu labellisé et qu'en labelliser des centaines à la main n'était pas tenable.


## 2026-06-18 apprendre à ne pas perdre son training

Les GPU gratuits (Colab, Kaggle) coupent la session et effacent le disque. On ne
sauvegardait qu'en fin de phase : une coupure au milieu perdait toutes les epochs
depuis la dernière frontière. Corrigé : checkpoint à chaque epoch, reprise
automatique en milieu de phase, et écriture directe sur un stockage durable.

Rien de glorieux, mais c'est le genre de truc qui coûte des jours si on l'ignore.


## 2026-07-05 il fallait de vraies données

On validait sur 5 tickets de test. Trop peu et trop français pour croire le
moindre chiffre. Passé à environ 1875 tickets labellisés (CORD, WildReceipt,
TrainingDataPro, SRD).

Leçon au passage : le pseudo-labelling est le goulot d'étranglement (le quota Groq
gratuit s'épuise vers environ 128 tickets/jour). Donc on a privilégié les datasets qui
livrent déjà le texte transcrit : un adaptateur, et zéro appel LLM. C'est ce qui
a permis de passer le millier sans rien payer.

Attention quand même : ces sources ne se valent pas. CORD est indonésien en
roupies, WildReceipt a un texte de référence sans espaces. Bon pour mesurer la
lecture, mauvais pour mesurer les prix.


## 2026-07-06 le modèle from-scratch hallucine

Nouvelle direction : un VLM entièrement from scratch (plus de CLIP, plus de
SmolLM2), beaucoup plus petit. Entraîné sur du synthétique uniquement.

Sur son synthétique il apprend bien. Sur de vraies photos il s'effondre et pas
en bafouillant : il sort un ticket valide et cohérent, tiré d'une poignée
d'enseignes mémorisées pendant l'entraînement. Un vrai "Trader Joe's" devient Lidl,
un "CVS/pharmacy" devient Lidl aussi, "Jungle Jamboree" devient Carrefour Express.

Il ne lit pas l'image, il génère depuis son a priori synthétique. C'est le risque
n°1 qu'on avait identifié, et il s'est réalisé en grand. Conclusion immédiate :
rajouter des epochs synthétiques ne servirait qu'à renforcer l'hallucination. Il
faut lui montrer du réel.


## 2026-07-07 mélanger du réel, et inventer la bonne métrique

On mélange 875 vrais tickets dans le flux synthétique (sur-échantillonnés). Le
synthétique ne régresse pas, donc pas de sur-adaptation.

Problème : les métriques (F1, ANLS) restaient à 0 alors qu'on *voyait* le modèle
commencer à lire. Elles pénalisent les quasi-lectures et s'étranglent sur le texte
de référence mal formaté de WildReceipt. Donc nouvelle métrique : on concatène le
texte lisible, on normalise en alphanumérique minuscule, et on score 1 − CER. Ça
répond juste à "est-ce que les caractères ont été lus".

Verdict : la lecture réelle passe de 0.033 à 0.122, presque x4. L'epoch 40
hallucinait des enseignes, l'epoch 50 tente de vraies lectures (WAL[UNK]MART,
BANANAS). Direction validée, magnitude encore faible 12% des caractères, pas de
quoi matcher un champ exact.

Leçon opérationnelle : ne jamais évaluer ce modèle en local. Générer sur 424
tickets a quasi-figé la workstation. L'éval tourne sur Kaggle, point.


## 2026-07-10 un worker par backend

Les backends étaient interchangeables en théorie mais un seul service tournait, et
comparer deux moteurs voulait dire basculer une variable d'env en prod. Donc : un
Cloud Run par backend, et le pipeline commun extrait dans une lib partagée.

Chaque worker copie seulement le backend qu'il utilise : paddlepaddle ne part
pas dans l'image Groq, torch ne part pas dans l'image Paddle.

Le modèle from-scratch, lui, n'avait aucun provider : il court-circuite toute la
machinerie VLM (prompts, retries, escalade de crop) parce qu'il n'en a pas besoin :
il ne prend pas de prompt et décode le ticket directement. C'est aussi le seul qui
a besoin de deux fichiers de poids (checkpoint + tokenizer caractère) : sans le
tokenizer avec lequel il a été entraîné, le checkpoint ne vaut rien.


## 2026-07-12 le gros modèle perd

L'hybride (457M) a enfin des chiffres, après avoir root-causé un crash qui l'avait
tenu hors de toutes les comparaisons. Le crash venait de son propre correctif : un
`pip -U transformers` ajouté pour réparer un import avait tiré transformers 5,
qu'un autre backend cassait ensuite en downgradant tokenizers. La notebook
installait tous les backends d'un coup. Maintenant elle n'installe que ce que le
backend sélectionné demande.

Le résultat, sur les mêmes 18 photos :

| Métrique | hybride (457M) | from-scratch (8.7M) | Groq |
|---|---|---|---|
| Lecture (1−CER) | 0.064 | 0.113 | 0.790 |
| Product recall | 0.000 | 0.000 | 0.682 |
| Field F1 | 0.000 | 0.000 | 0.746 |
| Date exacte | 0.000 | 0.000 | 0.944 |

L'hybride lit deux fois moins bien que le modèle from-scratch 52 fois plus
petit, alors qu'il est bâti sur deux backbones pré-entraînés. Son ANLS est
pourtant meilleur, et ce n'est pas contradictoire : ANLS récompense une structure
plausible, la lecture compte les caractères réellement lus. L'hybride produit des
tickets bien formés dont le contenu est plus faux. Le décodeur contraint garantit
la forme, pas la vérité.

La cause probable est bête : le checkpoint exporté vient de la phase 2, la phase 3
(alignement JSON) n'a jamais tourné. Des backbones pré-entraînés ne rachètent pas
un entraînement inachevé.

Ce qui reste ouvert :

- Personne ne lit une date. 0.000 pour les trois modèles locaux, y compris sur
  du synthétique où les labels sont parfaits. Échec transversal, et le correctif le
  plus rentable qui reste.
- Lire ≠ extraire. Les trois modèles locaux sont à 0 en product recall et F1.
- Groq écrase tout (0.79 de lecture contre 0.11). En prod, ça reste lui.

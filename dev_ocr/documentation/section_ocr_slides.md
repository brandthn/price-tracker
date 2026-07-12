# OCR & Vision — 2 slides

> Support de présentation. Texte calibré pour être lu à distance : peu de mots, gros chiffres.
> Les notes de l'orateur portent le détail — elles ne vont pas sur la diapo.

---

## SLIDE 1 — Le parcours

**Titre :** Lire un ticket : de l'OCR classique à nos propres modèles

**Ce qu'on a essayé — et pourquoi on a continué à chercher**

| | Approche | Verdict |
|---|---|---|
| 1 | **OCR classique** — PaddleOCR | Ça marche… en **104 s/image**, et le poste gèle |
| 2 | **OCR mobile** — PP-OCRv4 | 2× plus rapide (**54 s**) — mais **perd des produits** |
| 3 | **VLM local** — Moondream 0,5 Md | **0 produit.** Le modèle *bavarde* au lieu d'extraire |
| 4 | **VLM cloud** — Groq | **5 s/image**, très bons résultats → **la référence à atteindre** |
| **5** | **Notre modèle hybride** — 457 M<br>*CLIP + SmolLM2 gelés, projecteur & LoRA écrits par nous* | Le pré-entraîné **ne suffit pas** : il lit **2× moins bien** que le modèle 52× plus petit |
| **6** | **Notre modèle *from scratch*** — 8,7 M<br>*aucun poids pré-entraîné, tout écrit à la main* | **Le cœur du travail.** Résultats → slide 2 |

**⚠️ Groq n'est pas notre solution : c'est notre étalon.**
Nous l'utilisons en production **faute de mieux, pour l'instant** — nos modèles ne sont pas encore au
niveau. L'objectif reste de **les y amener**.

**Le choix qui a tout permis :** dès le premier jour, moteur de lecture **séparé** de l'analyseur.
→ Chaque nouveau moteur = **1 fichier + 1 ligne**. Zéro réécriture.
→ C'est ce qui rend possible le **benchmark de la slide 2** : tous comparables sur les mêmes images.

**Données d'entraînement :** tickets **synthétiques générés à la volée** (4 000/epoch) +
**1 875 tickets réels** (WildReceipt, CORD-v2, ExpressExpense, TrainingDataPro).

> **Notes orateur.** Le gel du poste n'était pas un bug : modèles rechargés à chaque appel + tests
> sur 395 images. Moondream a laissé deux acquis réutilisés partout : le mode « transcription » et la
> doctrine *échouer bruyamment plutôt que fabriquer du JSON plausible*. Groq change ensuite de rôle :
> de moteur de production, il devient **notre annotateur** — c'est lui qui étiquette nos photos pour
> entraîner nos propres modèles. Le hybride (5) a longtemps été notre dette — il plantait au banc
> d'essai. Nous l'avons corrigé et enfin mesuré : il est **moins bon** que notre petit modèle. C'est
> un résultat négatif, nous le présentons comme tel.

---

## SLIDE 2 — Nos modèles face à la référence

**Titre :** 8,7 M paramètres entraînés de zéro = PaddleOCR

| | paddle | ppocrv4 | **groq** *(étalon)* | *hybride* **457 M** | **le nôtre** *8,7 M* |
|---|---|---|---|---|---|
| **Lecture** (1−CER) | 0,111 | 0,074 | **0,790** | 0,064 | **0,113** |
| **Sortie valide** | 0,833 | 0,722 | **1,000** | **1,000** | **1,000** |
| **Rappel produits** | 0,106 | 0,071 | **0,682** | 0,000 | 0,000 |
| **ANLS** | 0,186 | 0,147 | **0,986** | 0,258 | 0,166 |

*18 photos réelles, mêmes métriques pour tous.*

**① L'écart avec l'étalon est net.** Groq reste très au-dessus → nous le gardons en production
**en attendant**.

**② Notre modèle égale PaddleOCR en lecture** (0,113 vs 0,111) et il est le **seul moteur local à
100 % de sorties exploitables**. **8,7 M paramètres, entraînés de zéro, sur un GPU gratuit.**

**③ Le plus gros n'est pas le meilleur.** Le hybride — **52× plus lourd**, bâti sur CLIP + SmolLM2
pré-entraînés — **lit 2× moins bien** (0,064). Son meilleur ANLS trahit des tickets **bien structurés
au contenu faux**.

**④ Ils lisent — ils n'extraient pas encore.** 0,000 en rappel produits pour les trois modèles locaux.
C'est **la prochaine marche**, pas un échec.

**La découverte qui a débloqué le projet — entraîné sur du synthétique, il *récitait* :**

*Sur un ticket américain, il prédisait des produits italiens — ceux de son générateur.*

```
epoch 40 :  'Lidl'  ·  'POMODORI 500G'                    → propre, valide… et inventé
epoch 50 :  'GO BA JANDINEPONE'  ·  'ChowatterMas(Sw/Strie'  → abîmé… mais il déchiffre
```

→ **Halluciner = du texte impeccable et faux.  Lire mal = du texte cassé.** Le second est un progrès.
→ Correctif : mélanger du **réel** → lecture **×3,7** (0,033 → 0,122).
→ Nos métriques ne voyaient pas ce progrès → **nous avons conçu la nôtre** (1−CER).

> **Notes orateur.** Message à faire passer : nous ne présentons pas un modèle qui gagne, mais une
> **trajectoire mesurée**. Nous savons exactement de combien nous sommes loin de l'étalon, et
> pourquoi. Sur le point ③ — si on demande *pourquoi* le gros modèle est moins bon : son entraînement
> **n'a jamais été mené à terme** (phase finale d'alignement jamais lancée, export depuis un point de
> contrôle intermédiaire). Le pré-entraînement ne rachète pas un entraînement inachevé. La courbe du
> petit modèle, elle, **montait encore** quand nous avons atteint le plafond d'epochs — le levier
> suivant (initialiser le décodeur depuis un petit modèle de langage pré-entraîné) est identifié,
> mais il romprait la pureté du « entièrement *from scratch* », qui est l'objet de l'exercice.

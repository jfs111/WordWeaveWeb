# 📊 Benchmark — Corpus NovaTech Solutions (Documentation Entreprise)

## Protocole de test

| Paramètre | Valeur |
|-----------|--------|
| **Corpus** | 274 PDFs — Statuts, RI, CDI, avenants, contrats clients/fournisseurs, PV CSE, politiques, notes de service, incidents, audits, fiches de poste |
| **Chunks** | 395 |
| **Clusters** | 32 |
| **Relations** | 2 406 |
| **LLM** | openai/gpt-oss-20b |
| **Embedding model** | paraphrase-multilingual-MiniLM-L12-v2 (384d) |
| **Auto-Hop budget** | 1.0 |
| **Auto-Hop max_hops** | 10 |
| **n_context** | 10 (sans graphe) / 7-8 vector + 17-20 graph (avec graphe) |
| **Chunk size** | 200 mots |
| **Chunk overlap** | 50 mots |
| **Seuil similarite** | 0.6 |
| **Date du test** | 07/03/2026 |

### Objectif
Ce corpus de documentation contractuelle d'entreprise teste la capacite du Graph-RAG a suivre les chaines de references croisees (CDI → RI → Charte IT → PSSI → PPDP), les chaines d'avenants (TEL-2021 → AV-TEL-2023 → AV-CDI-2024) et les liens transversaux entre domaines (securite, RH, juridique, IT).

### Methode
Chaque question est posee avec et sans enrichissement graphe. Les resultats sont compares sur le nombre de chunks, la couverture thematique, les documents cites, les scores de similarite et la qualite de la reponse.

---

## Question 1 — Quelles sont les obligations de confidentialite pour un nouveau salarie chez NovaTech ?

> _Question transversale testant la chaine CDI → RI → Charte IT → PSSI → PPDP (5 documents lies)._

### Reponse SANS enrichissement graphe (RAG classique)

| Metrique | Valeur |
|----------|--------|
| Chunks contexte | 10 vector + 0 graph = 10 total |
| Documents cites | RI (62%), avenant RI (56%), PSSI (56%), CDI modele (56%), Livret accueil (55%) |

**Reponse :**
> 6 obligations identifiees sous forme de tableau :
>
> 1. **Secret professionnel general** — Confidentialite de toutes les informations (RI article 6, CI, PPDP).
> 2. **Clause de confidentialite renforcee** — Renforcee par la Charte Informatique et la PPDP.
> 3. **Duree de l'engagement** — 2 ans apres la fin du contrat.
> 4. **Confidentialite vis-a-vis des outils IA** — Pas de partage avec IA non approuvee (NS-IA-2024).
> 5. **Engagement ecrit obligatoire** — Signature Charte IT, engagement confidentialite, RI avant remise du materiel.
> 6. **Conformite aux politiques internes** — Violation = manquement disciplinaire.

### Reponse AVEC enrichissement graphe (Auto-Hop)

| Metrique | Valeur |
|----------|--------|
| Chunks contexte | 7 vector + 20 graph = 27 total |
| Documents cites | RI (62%), CDI modele (74%), Contrat client (63%), CCT (82%), avenant RI (56%) |
| Hops detail | 7 traversees : 3 + 3 + 3 + 8 + 3 + 5 + 6 hops (31 hops total) |
| Budget moyen consomme | 0.87 |
| Types de relations | SIMILAIRE, COMPLEMENTAIRE, TRANSVERSAL, SUITE_LOGIQUE |

**Reponse :**
> 5 niveaux d'obligations hierarchises avec durees differenciees :
>
> 1. **Secret professionnel general** — RI art. 6, CI art. 2, PPDP. Duree : 5 ans apres fin contrat.
> 2. **Confidentialite specifique outils IA** — NS-IA-2024, PCD. Duree : 2 ans apres fin contrat.
> 3. **Confidentialite donnees personnelles** — PPDP section 4, PGIS. Duree : 5 ans apres fin contrat.
> 4. **Confidentialite propriete intellectuelle** — Code PI (art. L113-9, L611-7), RI art. 8. Duree : 5 ans.
> 5. **Obligation de signalement** — PGIS : signalement immediat au RSSI.
>
> Points cles : signature obligatoire (Charte IT, engagement confidentialite, RI), limitation outils IA (DSI), sanctions disciplinaires (art. 3 RI).

### Analyse comparative

| Critere | RAG classique | Graph-RAG Auto-Hop |
|---------|--------------|-------------------|
| **Chunks contexte** | 10 | 27 (+170%) |
| **Obligations listees** | 6 (liste plate) | 5 niveaux hierarchises avec durees |
| **Durees de confidentialite** | 2 ans uniquement | 2 ans ET 5 ans selon le type |
| **Signalement incidents (PGIS)** | Non mentionne | Oui |
| **Propriete intellectuelle** | Non mentionnee | Oui (art. L113-9, L611-7) |
| **Classification par niveau** | Non | Oui (5 niveaux) |
| **Scores sources max** | 62% | 82% |

**Conclusion Q1 :** Le Graph-RAG apporte une structuration en niveaux avec des durees differenciees (2 ans vs 5 ans selon le type d'obligation), et decouvre des obligations non trouvees par le RAG classique (PI, signalement incidents). La traversee de 8 hops via des relations SIMILAIRE a haute similarite (0.83-0.96) a permis de parcourir la serie des contrats CDI pour extraire les clauses communes.

---

## Question 2 — Comment les regles de teletravail ont-elles evolue chez NovaTech ?

> _Question testant la chaine d'avenants : TEL-2021 → AV-TEL-2023 → AV-CDI-2024._

### Reponse SANS enrichissement graphe (RAG classique)

| Metrique | Valeur |
|----------|--------|
| Chunks contexte | 10 vector + 0 graph = 10 total |
| Documents cites | Accord teletravail (64%), Livret accueil (57%), Fiche poste PO (57%), Charte IT (56%), Avenant CDI teletravail (55%) |

**Reponse :**
> Evolution chronologique en 5 etapes :
>
> 1. **2021** — Accord TEL-2021 : 2 jours max, 3 jours sur site, allocation 50 euros/mois.
> 2. **2023** — Avenant AV-TEL-2023 : passage a 3 jours, mardis/jeudis obligatoires.
> 3. **Guide Pratique** — Declaration SIRH, joignabilite 10-12h/14-16h, ergonomie.
> 4. **Charte IT** — Materiel pro, MFA obligatoire, pas de donnees C2/C3 sur supports perso.
> 5. **RI** — Reference a l'accord teletravail pour modalites de presence.

### Reponse AVEC enrichissement graphe (Auto-Hop)

| Metrique | Valeur |
|----------|--------|
| Chunks contexte | 6 vector + 20 graph = 26 total |
| Documents cites | Accord teletravail (64%), RI (86%), RI v2 (90%), CDI modele (87%), Accord amenagement temps (83%) |
| Hops detail | 6 traversees : 5 + 10 + 10 + 6 + 4 + 10 hops (45 hops total) |
| Budget moyen consomme | 0.73 |
| Types de relations | COMPLEMENTAIRE, SUITE_LOGIQUE, APPLICATION, SIMILAIRE, TRANSVERSAL, AUTRE |

**Reponse :**
> Evolution chronologique enrichie en 4 etapes avec integration contractuelle :
>
> 1. **15 juin 2021** — Accord TEL-2021 : 2 jours max, planning mensuel.
> 2. **2023** — Avenant AV-TEL-2023 : 3 jours, mardis/jeudis, allocation 50 euros nets/mois.
> 3. **1er janvier 2024** — Avenant CDI n2 (AV-CDI-2024) : article 9 "Teletravail regulier", integration contractuelle, VPN + MFA obligatoire.
> 4. **2024** — Guide Pratique Teletravail : procedures SIRH, joignabilite, ergonomie.
>
> 6 points cles recapitulatifs : augmentation jours, jours obligatoires, allocation, integration contractuelle, support materiel/securite, guide pratique.

### Analyse comparative

| Critere | RAG classique | Graph-RAG Auto-Hop |
|---------|--------------|-------------------|
| **Chunks contexte** | 10 | 26 (+160%) |
| **Integration contractuelle (AV-CDI-2024 art. 9)** | Non mentionnee | Oui — force juridique renforcee |
| **VPN + MFA (PSSI)** | Mentionnes | Detailles avec reference PSSI 2020 |
| **Scores sources max** | 64% | 90% |
| **Traversees max_hops** | — | 3 traversees a 10 hops (max atteint) |
| **Types de relations** | — | 6 types differents (diversite maximale) |

**Conclusion Q2 :** Le Graph-RAG reconstruit la chaine complete d'avenants via les relations SUITE_LOGIQUE et APPLICATION. L'integration contractuelle (AV-CDI-2024) est un element critique que le RAG classique manque. 3 traversees ont atteint le max de 10 hops avec des similarites de 0.99 — les series de contrats CDI et PV CSE.

---

## Question 3 — Quelle est la procedure en cas d'incident de securite impliquant des donnees personnelles ?

> _Question testant la chaine securite : PSSI → PGIS → PPDP → PTR → PCA/PRA._

### Reponse SANS enrichissement graphe (RAG classique)

| Metrique | Valeur |
|----------|--------|
| Chunks contexte | 10 vector + 0 graph = 10 total |
| Documents cites | Charte IT (68%), PSSI (61%), Procedure gestion incidents (59%), Politique transfert international (54%), PPDP (54%) |

**Reponse :**
> Procedure en 9 etapes detaillees :
>
> 1. Detection & classification (PGIS). 2. Signalement immediat (DPO, RSSI, President si P1). 3. Containment & isolation (PGIS). 4. Analyse forensique. 5. Notification DPO & CNIL 72h (art. 33 RGPD). 6. Information personnes concernees (art. 34 RGPD). 7. Communication interne/externe. 8. REX dans les 10 jours (PTR). 9. Suivi & audit.

### Reponse AVEC enrichissement graphe (Auto-Hop)

| Metrique | Valeur |
|----------|--------|
| Chunks contexte | 4 vector + 18 graph = 22 total |
| Documents cites | Charte IT (68%), Procedure gestion incidents (75%), Plan traitement risques (74%), PPDP (75%), PSSI (80%) |
| Hops detail | 4 traversees : 4 + 3 + 4 + 10 hops (21 hops total) |
| Budget moyen consomme | 0.87 |
| Types de relations | COMPLEMENTAIRE (dominant), SIMILAIRE, TRANSVERSAL |

**Reponse :**
> Procedure en 7 etapes avec archivage :
>
> 1. Detection & classification (PGIS). 2. Containment (PSSI §3). 3. Analyse forensique. 4. Notification interne (DPO, section 5 PGIS). 5. Notification externe (CNIL 72h, personnes si risque eleve). 6. REX 10 jours ouvres (PTR). 7. **Archivage 5 ans (RCD)**.
>
> Ajout par rapport a la version sans graphe : archivage conforme au Referentiel de Conservation des Donnees (REF-RCD-2021) pendant 5 ans.

### Analyse comparative

| Critere | RAG classique | Graph-RAG Auto-Hop |
|---------|--------------|-------------------|
| **Chunks contexte** | 10 | 22 (+120%) |
| **Archivage (RCD)** | Non mentionne | Oui — 5 ans |
| **Scores sources max** | 68% | 80% |
| **Chaine securite couverte** | PSSI, PGIS, PPDP | PSSI, PGIS, PPDP, PTR, RCD (+2 docs) |
| **Une traversee 10 hops** | — | Oui (serie rapports incidents, sim 0.97-0.99) |

**Conclusion Q3 :** Le RAG classique s'en sort bien sur cette question securite (9 etapes detaillees). Le Graph-RAG ajoute l'etape d'archivage (RCD) et atteint des scores de sources plus eleves (80% vs 68%), indiquant un contexte plus pertinent. La chaine COMPLEMENTAIRE a permis de suivre la procedure PGIS → PTR → RCD.

---

## Question 4 — Quelles sont les regles d'utilisation de l'IA generative chez NovaTech ?

> _Question testant la chaine NS-IA-2024 → Charte IT → PSSI → Classification → PI → AV-RI-2023._

### Reponse SANS enrichissement graphe (RAG classique)

| Metrique | Valeur |
|----------|--------|
| Chunks contexte | 10 vector + 0 graph = 10 total |
| Documents cites | NS IA generative (73%), avenant RI (67%), Politique PI (66%), Contrat client modele (66%), CDI modele (64%) |

**Reponse :**
> 4 categories de regles :
>
> 1. **Utilisation generale** — Redaction, dev logiciel, recherche, brainstorming. Interdit : donnees C2/C3, donnees perso, code source proprietaire.
> 2. **Confidentialite** — Memes obligations que tout autre systeme informatique.
> 3. **Outils approuves** — GitHub Copilot (licence entreprise). Tout autre outil valide par DSI.
> 4. **Protection donnees** — Respect PPDP et RGPD.
>
> References : NS-IA-2024, AV-RI-2023, CI, PCD, PPDP.

### Reponse AVEC enrichissement graphe (Auto-Hop)

| Metrique | Valeur |
|----------|--------|
| Chunks contexte | 3 vector + 17 graph = 20 total |
| Documents cites | NS IA generative (73%), avenant RI (85%), RI v1 (83%), RI v2 (90%), Accord teletravail (86%) |
| Hops detail | 3 traversees : 5 + 4 + 8 hops (17 hops total) |
| Budget moyen consomme | 0.87 |
| Types de relations | APPLICATION, SUITE_LOGIQUE, COMPLEMENTAIRE, SIMILAIRE, TRANSVERSAL, AUTRE |

**Reponse :**
> 3 categories de regles avec les memes elements que sans graphe, mais :
>
> - Scores de sources nettement superieurs (90% vs 64%)
> - Relation APPLICATION entre NS-IA-2024 et Charte IT
> - Relation SUITE_LOGIQUE entre AV-RI-2023 et RI original

### Analyse comparative

| Critere | RAG classique | Graph-RAG Auto-Hop |
|---------|--------------|-------------------|
| **Chunks contexte** | 10 | 20 (+100%) |
| **Couverture thematique** | 4 categories | 3 categories (equivalent) |
| **Scores sources max** | 73% | 90% |
| **Diversite relations** | — | 6 types (diversite maximale) |

**Conclusion Q4 :** Sur cette question, le gain est essentiellement qualitatif — les deux versions couvrent les memes points. Mais les scores de sources sont significativement plus eleves avec le graphe (90% vs 64%), indiquant que le LLM recoit un contexte plus pertinent. La relation APPLICATION entre la NS-IA-2024 et la Charte IT est semantiquement exacte.

---

## Question 5 — Comment un salarie peut-il exercer son droit a l'effacement de ses donnees personnelles ?

> _Question testant la chaine PED → PPDP → RCD → CDI._

### Reponse SANS enrichissement graphe (RAG classique)

| Metrique | Valeur |
|----------|--------|
| Chunks contexte | 10 vector + 0 graph = 10 total |
| Documents cites | RI (57%), Charte ethique (51%), Accord amenagement temps (50%), CCT (49%), Politique transfert international (49%) |

**Reponse :**
> Procedure generique en 6 etapes :
>
> 1. Formuler la demande (email/courrier au DPO ou RH). 2. Preciser les types de donnees. 3. Delai 30 jours. 4. Verification faisabilite (contrat en cours, obligations legales). 5. Mise en oeuvre (suppression, revocation acces). 6. Confirmation ecrite.
>
> **Probleme majeur :** La Procedure d'Exercice des Droits (PED) n'est PAS dans les sources — les scores sont tres bas (49-57%) et les documents cites ne sont pas les plus pertinents (RI, charte ethique, accord amenagement temps).

### Reponse AVEC enrichissement graphe (Auto-Hop)

| Metrique | Valeur |
|----------|--------|
| Chunks contexte | 8 vector + 18 graph = 26 total |
| Documents cites | RI (57%), CDI modele (74%), Contrat client modele (63%), CCT (82%), Charte ethique (51%) |
| Hops detail | 8 traversees : 3 + 3 + 3 + 4 + 3 + 4 + 3 + 4 hops (27 hops total) |
| Budget moyen consomme | 0.88 |
| Types de relations | SIMILAIRE, COMPLEMENTAIRE, TRANSVERSAL |

**Reponse :**
> Procedure precise en 7 etapes avec references aux paragraphes :
>
> 1. **Demande de retrait** — Email dpo@novatech-solutions.fr ou formulaire interne (PED §1).
> 2. **Accuse de reception 48h** (PED §2).
> 3. **Verification identite** — Copie document identite, recommandations CNIL (PED §3).
> 4. **Analyse de la requete** — Obligations legales/contractuelles, Referentiel Conservation (RCD) (PED §4).
> 5. **Mise en oeuvre** — Suppression ou restitution, article 28 RGPD, CCT (PED §5).
> 6. **Notification** — Decision finale sous 30 jours, prolongation possible 2 mois (PED §4).
> 7. **Suivi** — Registre des traitements, Plan Traitement Risques (PTR) (PGIS §6).

### Analyse comparative

| Critere | RAG classique | Graph-RAG Auto-Hop |
|---------|--------------|-------------------|
| **Chunks contexte** | 10 | 26 (+160%) |
| **PED (Procedure Exercice Droits)** | Non trouvee | Trouvee via graphe — 7 etapes avec §§ |
| **Accuse reception 48h** | Non mentionne | Oui |
| **Verification identite** | Non mentionnee | Oui (CNIL) |
| **CCT (clauses sous-traitants)** | Non mentionnees | Oui — suppression art. 28 RGPD |
| **PTR (suivi post-effacement)** | Non mentionne | Oui |
| **Scores sources max** | 57% | 82% |

**Conclusion Q5 :** Cas le plus demonstratif du benchmark. La recherche vectorielle ne trouve pas la PED (scores 49-57%, documents non pertinents). Le Graph-RAG l'atteint via les chaines COMPLEMENTAIRE et TRANSVERSAL, produisant une procedure precise avec references aux paragraphes. Le gain est massif : la reponse passe d'une procedure generique a une procedure specifique avec email du DPO, delai 48h, verification identite CNIL, et references CCT/PTR.

---

## Synthese

| # | Question (type) | RAG classique | Graph-RAG Auto-Hop | Apport du graphe |
|---|----------|--------------|-------------------|-----------------|
| Q1 | Confidentialite salarie *(transversale)* | 10 chunks, 6 obligations, max 62% | 27 chunks, 5 niveaux hierarchises, max 82% | **+PI, +signalement, +durees differenciees (2 vs 5 ans)** |
| Q2 | Evolution teletravail *(chaine avenants)* | 10 chunks, 5 etapes, max 64% | 26 chunks, 4 etapes enrichies, max 90% | **+Integration contractuelle AV-CDI-2024, scores +26%** |
| Q3 | Incident securite *(chaine securite)* | 10 chunks, 9 etapes, max 68% | 22 chunks, 7 etapes + archivage, max 80% | **+Archivage RCD 5 ans, scores +12%** |
| Q4 | IA generative *(reglementaire)* | 10 chunks, 4 categories, max 73% | 20 chunks, 3 categories, max 90% | **Gain qualitatif : scores +17%, contexte plus pertinent** |
| Q5 | Droit effacement *(procedure)* | 10 chunks, 6 etapes generiques, max 57% | 26 chunks, 7 etapes precises, max 82% | **PED trouvee via graphe, +48h accuse, +verification CNIL, +CCT, +PTR** |

### Observations generales

1. **Le Graph-RAG apporte une valeur ajoutee sur les 5 questions**, meme sur un corpus d'entreprise tres structure — le gain varie de qualitatif (Q4 : +17% scores) a massif (Q5 : procedure introuvable sans graphe).

2. **Le gain est proportionnel a la transversalite de la question :**
   - Questions transversales (Q1, Q5) : gain majeur — nouveaux documents decouverts, nouvelles informations
   - Questions chaine d'avenants (Q2) : gain sur l'integration contractuelle et les scores
   - Questions chaine securite (Q3) : gain sur l'archivage et les scores
   - Questions reglementaires (Q4) : gain qualitatif sur la pertinence du contexte

3. **Les types de relations varient selon la nature de la question :**
   - Q1 (confidentialite) : SIMILAIRE domine (chaine CDI)
   - Q2 (teletravail) : SUITE_LOGIQUE + APPLICATION (chaine avenants)
   - Q3 (incidents) : COMPLEMENTAIRE domine (chaine securite)
   - Q4 (IA) : APPLICATION + SUITE_LOGIQUE (lien reglementaire)
   - Q5 (droits) : COMPLEMENTAIRE + TRANSVERSAL (liens cross-documents)

4. **Les traversees longues (8-10 hops) apparaissent sur les series de documents similaires** (contrats CDI, PV CSE, rapports incidents) avec des similarites de 0.97-0.999. Le max_hops=10 est atteint 5 fois sur l'ensemble des tests, toujours sur des series SIMILAIRE.

5. **Les scores de sources sont systematiquement superieurs avec le graphe** (+12% a +26%), indiquant que l'Auto-Hop fournit un contexte plus pertinent au LLM meme quand la couverture thematique est equivalente.

6. **Budget de 1.0 bien calibre :** Consommation moyenne de 0.73-0.88 selon les questions. Le budget n'est jamais le facteur limitant principal — c'est l'absence de voisins viables qui stoppe la majorite des traversees.

### Conclusion

Le benchmark NovaTech confirme et amplifie les resultats du benchmark RGPD :

**Quantitativement :**
- +100% a +170% de chunks contexte
- +12% a +26% de scores de similarite des sources
- Jusqu'a 10 hops de traversee sur les chaines documentaires

**Qualitativement :**
- Decouverte de documents inaccessibles par recherche vectorielle (Q5 : PED)
- Reconstitution des chaines d'avenants (Q2 : integration contractuelle)
- Ajout d'informations critiques (Q1 : PI et signalement, Q3 : archivage RCD)
- Structuration hierarchique des reponses (Q1 : 5 niveaux avec durees)

**Specificite du corpus entreprise :**
Le corpus NovaTech met en evidence un comportement de l'Auto-Hop absent du corpus RGPD : les **traversees longues sur series de documents similaires** (CDI, PV CSE, incidents). Les similarites de 0.97-0.999 entre ces documents permettent des traversees de 10 hops avec un cout budgetaire tres faible (0.30-0.39), exploitant efficacement le budget restant pour explorer en profondeur une famille de documents.

La **relation SUITE_LOGIQUE**, specifique au corpus NovaTech (absente du RGPD), capture les chaines d'avenants contractuels — un cas d'usage critique pour la documentation d'entreprise que le RAG classique ne peut pas reconstituer.

Le benchmark demontre que le Graph-RAG Auto-Hop est particulierement adapte a la documentation contractuelle d'entreprise, ou les references croisees, les chaines d'avenants et les liens transversaux entre domaines (RH, IT, juridique, securite) sont la norme.
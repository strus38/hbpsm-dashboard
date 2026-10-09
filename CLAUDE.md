# Tableau de bord HBPSM — reprise du projet

Ce fichier donne à Claude Code le contexte d'une conversation de conception menée dans
claude.ai le 04/10/2026. Le README décrit le fonctionnement ; ici, l'état, les règles et la suite.

## But

Suivre chaque semaine les seniors garçons du HB Pays de Saint-Marcellin (HBPSM), 2e division
masculine P16 AURA, poules 71 et 72 : classements, feuilles de match, équipe proposée pour le
match suivant, matchs clés pour finir 1er, axes de travail à l'entraînement. Le tableau de bord
alimente l'application indépendante `strus38/HANDBALL-training` par un fichier `.hbt.json`.

## Règles à ne jamais enfreindre

Le dépôt `strus38/hbpsm-dashboard` est PUBLIC et ne sert qu'à poser le code.

- Aucun nom de joueur en clair : ni dans un fichier versionné, ni dans un test, ni dans un
  commentaire, ni dans une Release, ni dans un artefact, ni dans le journal des Actions.
- Ne jamais versionner `data/`, `raw/`, `docs/`, `roster.csv` (voir `.gitignore`).
- Les résultats ne sortent que chiffrés (`publie/*.enc`, AES-256-GCM, `pipeline/vault.py`),
  sauf deux fichiers d'équipe sans nom (`seance-prochaine.hbt.json`, `tableau-public.json`),
  relus par `publish.check_public` contre tous les noms connus avant d'être écrits.
- GitHub Pages ne sert que la page sans donnée (décision de l'auteur, 04/10/2026).
- Les tests n'utilisent que des joueurs et des clubs inventés.
- Avant tout commit : chercher les noms de l'effectif dans le diff.

Secrets GitHub attendus : `HBPSM_CLE` (phrase secrète, 16 caractères au moins) et
`HBPSM_EFFECTIF` (un joueur par ligne, « Prénom Nom »). En local, les passer en variables
d'environnement ; ne jamais les écrire dans un fichier du dépôt.

## État

Testé (14 tests, `python -m pytest -q`, une vingtaine de secondes) sur un faux site et de fausses
feuilles qui reprennent la forme du vrai site : collecte, lecture des feuilles, analyse,
chiffrement, reprise d'état, page publiée ouverte en fichier local. Les tests qui ouvrent un
navigateur prennent le Chrome installé sur le PC (`HBPSM_NAVIGATEUR=chromium` sinon).

Vérifié sur le vrai site le 04/10/2026 (collecte et lecture lancées depuis le PC) :
- les deux poules sont trouvées depuis la page de la compétition et inscrites dans
  `config.yml` (poule 71 = `poule-196332`, poule 72 = `poule-196334`) ; 42 rencontres par poule ;
- les 6 feuilles des matchs joués sont lues sans écart : score final, mi-temps, total des buts
  individuels et dernier événement du déroulé concordent ; chaque événement a son joueur ;
- l'aperçu `docs/index.html` s'ouvre dans Chrome sans erreur, en clair comme en sombre ;
- le fichier `.hbt.json` produit est accepté par l'importeur réel de HANDBALL-training 1.14.2
  (vérifié dans claude.ai, avant la reprise).

Ce que le vrai site a appris (les hypothèses de claude.ai étaient fausses) :
- les données sont en JSON dans le HTML servi (`<smartfire-component name=… attributes=…>`) :
  plus de Playwright pour la collecte ; l'API `wp-json/…/computeBlockAttributes` renvoie des
  données brouillées, on ne s'en sert pas ;
- poules désignées par un identifiant interne, pas par leur numéro ; liste dans le bloc
  `competitions---poule-selector` de la page de la compétition ;
- feuille à `https://fdm.fdme.ffhandball.fr/<c1>/<c2>/<c3>/<c4>/<code>.pdf` (code = `fdmCode`
  de la rencontre) ; 404 avant le match ;
- feuille : un seul tableau, une ligne d'en-tête par équipe, « X » pour Av. et Dis ; déroulé
  sur deux colonnes, sans numéro ni équipe (rapprochement par le nom), heure en `01:00:00`
  à la 60e minute, événements « Commotion » (jamais conservés) ;
- pages en cache CloudFront d'une à deux heures : un score peut manquer sur la page alors que
  la feuille existe ; la collecte tente alors la feuille.

Le dépôt GitHub est vide au 04/10/2026 : rien n'a encore été poussé.

## Prochaine tâche

1. Chercher les noms de l'effectif (et ceux vus sur les feuilles) dans tout ce qui sera versionné.
2. Pousser le code, créer les deux secrets, lancer le workflow « Collecte quotidienne » et
   vérifier le premier passage sur GitHub (le site répond-il aux adresses de GitHub ?).
3. Après la journée 2 (10-11/10), relancer et vérifier qu'une journée close n'est plus relue.

En local : `python -m venv .venv`, `.venv/Scripts/python -m pip install -r requirements-dev.txt`.
Rester léger avec le site de la fédération : deux poules, un passage par jour du dimanche au
vendredi (demande de l'auteur, 04/10/2026, car les feuilles arrivent dans le désordre), une
seconde entre deux pages, ne pas relire une journée dont toutes les feuilles sont lues.

## Points ouverts

- Règlement AURA 2026-2027 (Règlements particuliers, aura-handball.fr/wp-content/uploads/2026/08/
  Reglements_Particuliers_26-27.pdf) : 2e division en 8 secteurs ; « les 2 meilleures équipes
  éligibles de chaque secteur » montent en 1re division ; pas de descente. Poules 71 et 72 = un
  secteur (déduit de la numérotation). Deuxième phase au calendrier (avril à juin 2027), formule
  publiée vers février-mars ; aucun play-off 71/72 écrit. Précédent 2025-2026 : poule haute avec les
  4 premiers de chaque poule. Objectif réglé à 2, finir 1er ou 2e (choix de l'auteur, 06/10/2026 ; 3 avant ;
  `objectif.rang`), simulé sur la première phase ;
  l'onglet Saison montre aussi les chances de chaque rang final. À revoir quand la formule paraîtra.
- Départage (RG FFHB 3.3, repris par l'AURA) : points, puis points et différence de buts des
  confrontations directes (répétés), différence générale, buts marqués (`rank_teams`). Non
  modélisés : buts à l'extérieur des confrontations directes, nombre de licenciés.
- L'effectif fourni compte 20 noms ; il en manque au moins un.
- Les postes ne sont pas dans l'effectif : l'entraîneur les saisit dans la page.
- Le temps de jeu n'existe pas sur la feuille de match : matchs disputés, temps passé à
  2 minutes et indice de présence seulement.
- Cartons jaunes, 2 minutes et cartons rouges sont distingués partout (demande de l'auteur,
  04/10/2026 ; champs `jaunes`, `deux_min`, `rouges`). Aucun carton rouge n'a encore été vu sur
  une vraie feuille : la colonne « Dis » du tableau fait foi ; le libellé du déroulé est supposé
  « Disqualification » ou « Carton rouge ». Un libellé inconnu apparaît dans
  `rapport_extraction.json` (`actions_inconnues`, premier mot seulement) et dans le journal.
- Avec très peu de matchs joués, notes, matchs clés et axes de travail sont presque vides : la
  saison 2025-2026 (`pipeline/history.py`, demande de l'auteur) sert de point de départ. HBPSM y
  était en poule 5A puis 5 haute ; Bièvre, Tain 2, Pilat 2, St Donat dans les mêmes poules ;
  Domène, Pontois, Usvizille en poule 7 ; Meylan 2, Drac Isère, Sablons, Nord Drôme sans
  historique à ce niveau. Feuilles 2025-2026 : ancien format (mots collés, « ButJRN°51NOMprénom »,
  équipe et numéro donnés), lu par `parse_fdme`.
- Le serveur des feuilles (fdm.fdme.ffhandball.fr) répond 429 après une trentaine de feuilles à
  1 s d'intervalle (04/10/2026) : `collect.Ralenti` ; une feuille toutes les 4 s pour
  l'historique, attente du Retry-After, budget de 15 min par passage, reprise au suivant.
- Horaire pas encore fixé : la date est celle du début du week-end de la journée, marquée
  « à confirmer » (`date_provisoire`).
- Heures : toujours celles de Paris (`common.paris_now`, paquet `tzdata` pour Windows), y compris
  sur le runner GitHub en UTC : `meta.genere`, la date du jour, la comparaison avec l'heure des
  matchs. Seuls `maj` du manifeste et `exporteLe` de la séance restent en UTC, avec leur « Z ».
- HANDBALL-training ne demande jamais la phrase (décision de l'auteur, 04/10/2026) : son
  écran « Tableau de bord HBPSM » lit `publie/tableau-public.json` et
  `publie/seance-prochaine.hbt.json`, et ouvre la page complète sur GitHub Pages
  (https://strus38.github.io/hbpsm-dashboard/), qui demande la phrase une fois par poste.
  Contrat à ne pas rompre : ces deux chemins sur `main`, `format` « hbpsm-public » `v` 1,
  `.hbt.json` v3, l'adresse Pages suivie de `#entraineur`.
- Modes (demande de l'auteur, 05/10/2026) : seul l'entraîneur modifie Planification, Semaine,
  Convocation et les réglages des fiches, et seulement depuis HANDBALL-training (`COACH` : marqueur
  `#entraineur` dans l'adresse, posé par le profil HBPSM de l'application, 1.16.1). Ouverte
  autrement : consultation (`body.lecture`, classes `.coach` / `.lecture-only`, saisies ignorées).
  Pas un verrou : les choix restent dans chaque navigateur ; viser seulement à ne pas tromper un
  joueur.
- Feuille validée (demande de l'auteur, 05/10/2026) : « Valider la feuille » en mode entraîneur
  chiffre les feuilles validées dans le navigateur (`sealVault`, même coffre que `vault.py`) et
  lance `choix.yml` par l'API GitHub avec un jeton à grain fin (Actions : lecture et écriture,
  ce dépôt seulement), collé une fois par l'entraîneur (`localStorage` « hbpsm:jeton », jamais
  dans un fichier ni dans l'export du planning). `pipeline/choix.py` vérifie (phrase du club,
  forme, taille) et écrit `publie/choix.enc` ; les pages le relisent (`fetchChoices`). Visiteur :
  « Choix de l'entraîneur » ou « Suggestion » (pointillés). Une feuille validée est figée et sort
  de la rotation ; la retoucher la repasse « modifiée » (`S.valide[id] = null`). États :
  suggestion, choix, publiee, attente, modifiee, a_revoir, retrait. « Retirer la validation »
  (`withdraw`, `S.retire` jusqu'à ce que le retrait soit en ligne) republie sans ce match.
- Coupes (demande de l'auteur, 05/10/2026) : `coupes` dans config.yml (Coupe de France
  départementale masculine 2026-2027, competition 33244 ; 1er tour le 17/10 à Saint-Rambert-d'Albon).
  `collect.crawl_cup` ne garde que les matchs du club (poule « coupe », champs `coupe`, `tour`,
  `tour_id`) ; un tour clos ou passé sans le club n'est plus relu. `analyze` : classement,
  profils, simulation sur le championnat seul ; `club_players` sur tous les matchs ; `cup_ahead`
  ajoute les matchs de coupe à `saison.matchs` (enjeu nul, jamais clé) ; `coupes` = parcours.
  Page : `roundOf` / `roundShort`, rotation d'abord sur la coupe, 2 gardiens changés possibles.
  Résumé public : champs `coupe`, `tour` (HANDBALL-training 1.16.2 les affiche).
- Adversaires de coupe venus d'ailleurs (demande de l'auteur, 05/10/2026) : `voisines` dans
  config.yml (1re division P16 AURA 30499, 2e division 30501) ; `collect.crawl_rivals` retrouve
  leur poule (liste `calendar-button` des équipes) et lit leurs seuls matchs (`crawl_poule(only=)`),
  marqués `externe` (poule « ext-<id> », classement officiel sous la même clé). `analyze` : fiche
  avec `poule_libelle` et `coupe`, sans toucher nos poules. 1er tour 2026-2027 : 1re division, poule 6.
- Caisse noire (demande de l'auteur, 05/10/2026) : onglet « Caisse noire ». Règlement 2026-2027
  repris dans `pipeline/caisse.py` (REGLEMENT : partie, titre, montant, unité, texte ; noms des
  trésoriers jamais dans le dépôt, ils sont dans l'effectif, 4e colonne « trésorier »). Registre
  en journal d'opérations chiffré (`publie/caisse.enc` : amende, refus, annule, paiement), écrit
  par `caisse.yml` + `caisse.main` (dédoublonnage par id). Saisie réservée aux détenteurs du jeton
  (trésoriers, entraîneur : choix de l'auteur) ; boîte d'envoi locale `hbpsm:caisse-envoi`
  jusqu'à publication. Propositions : `caisse.proposals` (feuilles) + « Bon point ! » calculé dans
  la page ; une proposition validée a l'id « v:<proposition> », refusée « r:<proposition> ».
  Penalties manqués (introuvables sur la feuille : colonne « 7m » = buts sur 7 m, aucun libellé
  d'échec) : une proposition « m_penalty:<match>:check » par match (tireurs, joueurs de la
  feuille), traitée dans la carte « Gérard Penaldo » (`penaltyOps`). Cotisations : carte à part,
  « Payé » = amende + paiement ; hors podium et hors compte des amendes.
  Le jeton étant partagé, `collect.set_urls` n'accepte que des adresses ffhandball.fr.
  Propositions de tous (demande de l'auteur, 06/10/2026) : n'importe qui ayant la phrase propose une
  amende depuis la page (« Vous êtes », puis « Proposer l'amende ») ; elle part au dépôt public à part
  strus38/hbpsm-cn (workflow « Proposition d'amende », `propositions.py`, journal chiffré
  `propositions.enc`), avec un jeton limité à ce seul dépôt (droit Actions) : secret `HBPSM_JETON_CN`
  du tableau de bord, rangé par la collecte dans les données chiffrées (`caisse.jeton_cn`, jamais dans
  la page publique ni le journal). S'il fuit : ajouter des propositions, rien d'autre. Les pages relisent
  le journal (`fetchCN`, `CFG.cn`) ; les propositions rejoignent « À valider » (`cnProposals`) ; seuls les
  trésoriers valident (« v:<id> ») ou refusent (« r:<id> ») dans le registre. Code du dépôt à part tenu et
  testé dans `cn/` (son `vault.py` = celui du pipeline) ; secret `HBPSM_CLE` dans les deux dépôts.
  Cotisation d'abord (demande de l'auteur, 08/10/2026) : seuls les joueurs à jour de leur cotisation mettent
  (trésoriers, entraîneur : `whoAmI`, « Vous êtes » du mode trésorier) ou dénoncent (proposition, copie, partage :
  « Vous êtes » du formulaire) une amende ; les autres peuvent toujours la régler (« Payé »). `blocage(c, L, w)` dit
  pourquoi, `auteurOK` garde chaque action (mettre, valider, penalties, proposer, copier, partager) ; payer,
  encaisser, refuser, annuler restent libres. Proposition de tous d'un joueur pas à jour : `irrecevable` (seulement
  « Refuser »). Hors caisse : rôle « hors caisse » de l'effectif (`hors_caisse`, `caisse.hors`, pas de cotisation
  proposée ; un joueur de l'effectif l'est au 08/10/2026, choix de l'auteur) ou « ne participe pas » d'un trésorier
  (refus de la cotisation, `L.sortis`, « réintégrer » l'annule) ; `L.out` : ni amende, ni bon point, ni penalty, ni
  dénonciation (`participants`). Pas vérifié côté workflow : seuls les détenteurs du jeton y écrivent.
  Les comptes (demande de l'auteur, 08/10/2026) : `balancesBlock` montre le total encaissé sur le total dû, une
  barre par joueur (payé / reste, à l'échelle du plus gros compte), la cotisation en pastille, « À régler » (reste
  décroissant) puis « À jour », puis « Sans amende » et « Cotisation à régler ». Pas de détail payé / à payer par
  amende (choix de l'auteur) : les paiements ne visent pas une amende précise.
  Téléphone : bouton « 📤 Partager » à côté de la dénonciation (menu de partage du téléphone, `navigator.share`,
  `canShare`), sous 560 px et si le navigateur le permet ; sinon le copier-coller.
  Anniversaires (demande de l'auteur, 05/10/2026) : 6e colonne `naissance` de l'effectif (MM-JJ, jamais
  l'année ; roster.csv et le secret, jamais le dépôt) ; une ligne de rôle « coach » donne celui de
  l'entraîneur sans en faire un joueur (`is_staff`). `birthdays` -> `caisse.anniversaires` ; carte
  « 🎂 Anniversaires » de l'onglet (celui du jour, puis les 30 jours suivants, sinon le prochain).
  Reprise d'un état tenu ailleurs (tableau des trésoriers, 05/10/2026) : `python -m pipeline.caisse import`
  lit le secret temporaire `HBPSM_CAISSE_IMPORT` (opérations en clair : jamais une entrée visible du
  workflow), les vérifie (`validate`) et les ajoute au registre (`add`, sans doublon) ; étape du
  workflow « Caisse noire », sans effet sans le secret, qu'on efface après usage. Reprise du 05/10 :
  cotisations « * » = payées (amende + paiement, comme le bouton « Payé »), 5 amendes (8 €) dues.
- Division du dessus (demande de l'auteur, 05/10/2026 : « une division au-dessus » = 1re division
  masculine P16 AURA, 27884 en 2025-2026, 30499 en 2026-2027) : entrée `historique` avec `niveau: 1`
  (fichier `<saison>-niveau1.json`, seules nos équipes et nos adversaires de coupe), `voisines` en
  {url, niveau}, `ecart_division` (0,12, hypothèse). `history_profiles(above)` : bilan d'en haut
  relevé de l'écart, pondéré par la continuité ; `passe.niveau`, `passe.division`, `dessus` quand
  le club était dans les deux. `cup_chance` : victoire estimée d'un match de coupe contre une
  équipe d'une autre poule ou division (forces de `outlook`). `same_team` exige le même numéro
  d'équipe (`team_number`). Constat au 05/10/2026 : seule Hand Bièvre Terres Froides (poule 72)
  jouait en 1re division en 2025-2026 (12e sur 12) ; Meylan 2, Drac Isère 2, Sablons, Nord Drôme 2,
  Chirens-Coublevie et Nord Drôme (coupe, en 1re division cette saison) n'étaient ni en 1re ni en
  2e division ; le club Drac Isère avait son équipe 1 en 1re division, pas son équipe 2.
- Origine des joueurs (demande de l'auteur, 05/10/2026 : notre division est la plus basse, une
  équipe absente la saison passée est une nouvelle équipe ou entente, ses joueurs viennent d'autres
  clubs) : `history_profiles` cherche chaque joueur de cette saison (feuilles de championnat, de
  coupe et des poules des adversaires de coupe, `rosters`) dans toutes les feuilles de la saison
  passée lues, tous clubs et divisions ; force de départ = celle des équipes d'où ils viennent
  (écart de division compris), continuité = part retrouvée ; `origines` (vus, retrouves, equipes),
  aussi dans le résumé public (noms d'équipes et nombres seulement). Limite : seules les poules où
  jouaient nos équipes d'aujourd'hui sont lues.
- Saison 2024-2025 (demande de l'auteur, 05/10/2026) : le club jouait en 1re division P16 AURA (confirmé
  par l'auteur ; 25096, poule 6, 10e sur 12). Entrée `historique` avec
  `club_seul: true` (seuls nos matchs et leurs feuilles) ; `club_players(older=)` la compte pour HIST2
  (un quart de match) : `merged`, `season_line`, `avant` sur chaque joueur, `reliability(m, passée,
  avant)`. Elle n'entre pas dans la force des adversaires (seule la saison la plus récente y sert).
- Saison 2023-2024 (demande de l'auteur, 06/10/2026, pour un gardien revenu au club, aux seniors de 2020 à
  2024) : le club jouait en Honneur masculin AURA (22315, poule 127119, adresse donnée par l'auteur ; ni en
  1re ni en 2e division P16 cette saison-là, 33 poules lues). Entrée `historique` avec `niveau: 2` (supposé)
  et `club_seul: true`, fichier `2023-2024-niveau2.json`. `club_players(ancient=)` : comme les -18, un quart
  de match et seulement pour un joueur sans aucun match plus récent (cette saison, la passée, celle d'avant) ;
  ligne `ancienne` sur sa fiche. La saison d'avant (`older`) n'est plus que la plus récente des saisons
  antérieures (2024-2025) : avant, toute saison plus ancienne s'y serait mêlée sous son nom.
- Moins de 18 ans du club (demande de l'auteur, 05/10/2026) : entrée `historique` avec `categorie: "M18"`
  (M18 masculin division 2 AURA 2025-2026, 30005, 2e phase poule 12 ; la 1re phase n'est pas dans la
  M18 Excellence 27887, sans doute départementale : non trouvée). Fichier `<saison>-m18.json`, jamais
  pour les adversaires ; `club_players(youth=)` : un quart de match, seulement pour un joueur sans aucun
  match senior (cette saison, la passée, celle d'avant), ligne `jeunes` sur sa fiche (« -18 2025-2026 »).
- Propositions stables et communes (demande de l'auteur, 05/10/2026) : en consultation, la
  planification ignore tout ce qui est rangé dans le navigateur (`SP()` renvoie `NEUTRE` hors mode
  entraîneur) ; `analyze.freeze_plan` fige les entrées de la rotation (`scores_plan`, `p_plan`, `cle`)
  dans `data/planif.json` (repris de etat.enc) tant que les feuilles lues du club, l'effectif, les
  forfaits et l'historique (saisons et jeunes, feuilles lues) ne changent pas ; `meta.planif_depuis`. « proposé » tant que l'entraîneur n'a pas décidé
  (`DECIDE`), « retenu » ensuite.
- Jamais deux fois de suite la même équipe (demande de l'auteur, 05/10/2026) : `MIN_CHANGES` = 2
  joueurs (gardiens compris) changent d'un match au suivant, à partir du dernier match joué, même sur
  un match clé ; l'échange le moins coûteux, poste pour poste, sans découvrir un poste clef, jamais
  avec un joueur en dépannage (`forced` ; « N changement(s) seulement » sinon).
- Planification : les deux derniers matchs terminés du club dont la feuille est lue (`derniers`,
  `last_matches` : joueurs de la feuille par clé, buts et arrêts), en colonnes grisées avant les 4 à
  venir (6 colonnes au plus) ; ceux de la saison seulement, jamais la saison passée (demande de
  l'auteur, 05/10/2026 ; `derniers` en garde pourtant la fin, pour les séries des gardiens). Un match
  de la saison passée ne compte pas pour la règle des 2 changements.
- Saison qui avance (demande de l'auteur, 05/10/2026) : les saisons passées (et les -18) pèsent
  HIST × `fade(n)` = HIST × FONDU / (FONDU + n), n = feuilles du club lues cette saison (FONDU = 6) :
  0,5 au départ, 0,43 après 1 match, 0,25 après 6, 0,11 en fin de saison ; `reliability` porte
  `poids_passee` / `poids_avant`. Côté adversaires, c'était déjà progressif : départ sur la saison
  passée (3 à 5 matchs de poids selon la continuité), incertitude réduite par les matchs joués.
- Poste pour poste (demande de l'auteur, 05/10/2026) : le 2e poste ARD de tous les droitiers faisait
  passer presque tout échange pour « même poste ». `compat(entrant, sortant)` : 3 même poste principal,
  2 l'entrant tient le poste principal du sortant, 1 un poste en commun, 0 aucun ; `fit` = min(compat,
  2) : 3 et 2 aussi bons pour choisir. Rotation : sur l'ensemble des matchs abordables, d'abord un
  échange de fit 2, le plus abordable ; sinon le moins mauvais. Règle des 2 changements : fit avant
  l'âge, puis celui qui a le plus joué. Infobulle : « même poste », « il tient son poste », « poste
  différent, faute de mieux ».
- Domicile / extérieur (demande de l'auteur, 05/10/2026) : que personne, gardiens compris, ne joue que
  d'un côté. `journal.dom` ; `atVenue`, `excess` (matchs joués de la saison et proposés) ; `lastSide` :
  ne pas reposer quelqu'un sur son dernier match d'un côté s'il y a mieux (avant l'âge) ; puis l'entrant
  va du côté où il a le moins joué, le sortant est celui qui en a le plus de ce côté.
- Gardiens (demande de l'auteur, 05/10/2026) : pas plus de `GB_SUITE` = 3 matchs de suite sans sortir,
  matchs joués de la saison compris (`derniers` en garde 3, la planification en montre 2). Après la
  rotation, avant la règle des 2 changements : il se repose sur le match le plus abordable de la
  série (coupe d'abord, jamais un match clé s'il y a mieux, jamais une feuille validée), remplacé par
  le gardien disponible qui a le moins joué et qui ne dépasse pas lui-même la limite (`runWith`) ;
  sinon « gardien : 3 matchs de suite dépassés » sous le match (`gbSuite`).
- Début de saison (demande de l'auteur, 05/10/2026) : tant que moins de `PARTAGE_GB` = 6 feuilles du club
  sont lues, les jeunes gardiens (classe d'âge, jamais affichée) jouent autant l'un que l'autre, à un
  match près (matchs joués de la saison compris) : le plus utilisé cède un match, pas un match clé si
  possible, en laissant un gardien solide à côté (`partner`), sans dépasser 3 de suite ; ensuite, les
  résultats départagent. Après la limite des 3 matchs de suite, avant la règle des 2 changements.
- Blessé, absent (demandes de l'auteur, 05/10/2026) : seul l'entraîneur les déclare, d'un clic sur
  une case (… incertain → absent → blessé → disponible). Absent : pour ce match (`dm` « a »). Blessé :
  à partir de ce match jusqu'à son retour (`S.blesse[cle]` = {de, a}, dates de match ; un clic sur un
  match suivant le dit rétabli). Les deux partent avec la publication des choix (`choix.enc` :
  `blesses`, `absents` {match: [joueurs]}, vérifiés par `choix.check`) : les propositions changent
  pour tout le monde avant même que la feuille soit validée ; bandeau « pas encore publiés » et
  bouton Publier (`statusPending`). Ce qu'il a saisi ici prime sur le publié (« d » efface).
- Classe d'âge (demande de l'auteur, 05/10/2026 : miser sur l'avenir, une équipe solide et jeune en
  cas de montée) : 5e colonne `age` de l'effectif, dans roster.csv et le secret, jamais dans le dépôt.
  Depuis le 06/10/2026 (demande de l'auteur), tranches de 5 ans à partir de 18 ans : « 18-22 », « 23-27 »,
  « 28-32 »… (`analyze.age_class`, `bandRank` dans la page), d'après l'âge atteint dans l'année où la saison
  commence, les moins de 18 ans dans la première ; calculées depuis les dates de naissance du fichier de la
  caisse noire de l'auteur, lues en mémoire : seule la tranche est gardée, JAMAIS l'année ; à refaire chaque
  saison (juillet) avec son fichier. Les anciens mots restent compris (jeune = tranche 1, intermediaire = 3,
  experimente = 5) : au 06/10/2026, trois joueurs sans date les gardent. Jeunes gardiens (partage du temps de
  jeu en début de saison) : 27 ans au plus (`youngGK`). Paramètre seulement, JAMAIS affiché (choix de
  l'auteur) : à besoin égal, la rotation fait entrer le plus jeune et reposer le plus âgé (poste pour poste
  d'abord) ; la règle des 2 changements préfère faire entrer un plus jeune (`ageRank`).
- Expérience (demande de l'auteur, 06/10/2026 : avoir joué plus haut donne de l'expérience, de la maturité, la
  capacité à tirer l'équipe vers le haut) : `analyze.experience_of`, matchs joués au club (feuilles lues),
  cette saison et toutes les saisons passées lues sauf les -18, un match comptant 1 + 0,5 × niveau (niveau =
  divisions au-dessus de la nôtre : 1re div. 1, Honneur 2, Excellence 3, Prénationale 4) ; composante `exp`
  = min(1, total / 100) ; 10 % de la note (`EXP_POIDS`), gardiens compris. JAMAIS affichée (choix de
  l'auteur) : absente de `COMP_NOM`. Les chiffres affichés des saisons passées restent bruts.
  Saisons lues pour cela (nos matchs seulement, `club_seul` ; adresses retrouvées par l'auteur) : Excellence
  régionale 2015-2016 (1012) et 2016-2017 (4541), Prénationale Est 2017-2018 (7656, niveau 4), Excellence AURA
  2018-2019 (10485), 2019-2020 (13164), 2021-2022 (17618), 2022-2023 (19735) (niveau 3), Honneur 2020-2021 (15582)
  et 2023-2024 (niveau 2), 1re division 2024-2025 (niveau 1). L'équipe réserve (départemental 2015-2017) et la
  coupe de l'Isère n'y sont pas. Avant 2018-2019, le serveur n'a plus les feuilles (404) : la page « statistiques »
  de la poule du club (bloc `competitions---stats-joueurs` : matchs, buts, arrêts de chaque joueur) en tient lieu,
  lue une fois par saison (`history.club_stats` -> `joueurs_club`) ; l'expérience prend, saison par saison, le plus
  grand des deux décomptes. Liste des compétitions de la ligue pour une saison : …/regional/o-ligue-
  auvergne-rhone-alpes-4/. Plusieurs saisons anciennes sur une fiche : « 2015-2024 » (`saison_ancienne`).
- Avis de l'auteur (demande de l'auteur, 06/10/2026 : un demi-centre que l'auteur juge clairement le meilleur
  joueur devrait être au-dessus de 65 ; son jeu ne se lit pas sur la feuille) : 8e colonne `avis` de l'effectif,
  1 à 5 étoiles (`analyze.opinion`), un quart de la note (`AVIS_POIDS`), roster.csv et le secret seulement, JAMAIS
  affiché ; sans avis, la note ne change pas. Au 06/10/2026, un seul joueur en a un (5 étoiles).
- En buts plutôt qu'en pourcentages (demande de l'auteur, 06/10/2026, visibles de tous) : buts évités par un
  gardien face au gardien moyen des poules lues (`league_save_rate` sur les tirs cadrés dont on sait qui a pris
  les buts ; `goals_saved`, dès 60 tirs ; `evites` cette saison, `evites_passe` la saison passée ; affichés :
  `evites_cumul` = cette saison et la passée cumulées, la passée comptant HIST × fade comme pour les notes, avec
  leur marge à 95 % (`goals_saved_mix` ; demande de l'auteur, 06/10/2026 : avec 5 gardiens, une saison seule ne
  départage personne avant les matchs clés ; les saisons de nos seuls matchs restent hors du calcul, leur
  gardien moyen étant biaisé ; « dans la marge d'erreur » quand l'écart ne dépasse pas la marge) sur sa fiche,
  et pour la paire proposée dans la Semaine face à la plus sûre disponible (`gkPairLine`) ; écart attendu de
  chaque match (`ecart`, `buts_pour` : buts attendus des forces centrales d'`outlook`, `cup_chance(goals=)` en
  coupe), ajusté à la feuille (`goalsAdj` = écart − (1 − force) × buts attendus du club) dans la Semaine, le
  risque, la causerie et les barres de la Saison ; coût d'une exclusion (`exclusion_cost` : écart de buts des
  2 minutes qui suivent, moins le rythme du match, sur tous nos déroulés depuis 2018 ; `meta.exclusion`, environ
  −0,44 but sur 376 au 06/10/2026) dans « À travailler », la fiche (exclusions en buts) et la causerie.
- Fins de match (`clutch`, 06/10/2026) : neutres (0,5) tant que personne n'a d'action décisive dans la saison,
  puis ramenées vers 0,5 avec peu de matchs (`CLUTCH_PRUDENCE` = 3) ; avant, un seul match joué sans but
  décisif donnait 0, contre 0,5 à ceux qui n'avaient pas joué.
- Disponible jusqu'à une date (demande de l'auteur, 06/10/2026 : un gardien revenu, intermédiaire, disponible
  jusqu'en avril 2027, présence en 2027-2028 pas confirmée ; 5 gardiens depuis) : 7e colonne `jusqu_au` de
  l'effectif (« AAAA-MM » = fin du mois, ou « AAAA-MM-JJ » ; roster.csv et le secret, jamais le dépôt),
  `analyze.until`. Page : indisponible après (`gone` ; case « indispo. », « disponible jusqu'au … » ; fiche),
  compté à la rotation ; à besoin égal il passe après tous les autres en championnat (`leaving`, `ageRank` 3)
  et devant tous en coupe (« typiquement sur les coupes de France », demande de l'auteur : `lateAt` -1,
  `cupFirst`, la coupe avant le côté domicile / extérieur). La raison n'est jamais affichée.
- Feuille de coupe à 14 (demande de l'auteur, 06/10/2026) : règlement FFHandball de la Coupe de France
  régionale et départementale, art. 15 (2024-2025 et 2025-2026 ; version 2026-2027 pas trouvée au 06/10/2026) :
  « 14 joueurs de 17 ans et plus ». `effectif_feuille` sous l'entrée de `coupes`, `cup_ahead` -> `effectif` du
  match, `sizeOf(m)` dans la page ; toujours 2 gardiens. Règle des 2 changements en entrants ou sortants
  (de 14 en coupe à 12, deux sortent déjà).
- Noms courts : deux joueurs de même nom et même initiale : `playerShort` allonge
  le prénom (« Isi. Exemple »).
- Forfait général (demande de l'auteur, 05/10/2026 : Nord Drôme 2, poule 71) : `forfaits` dans
  config.yml, le site ne le dit pas. L'équipe reste au classement, en gris, en bas et sans rang
  (`poule_view(gone)`, `forfait` sur la ligne, aussi dans le résumé public) ; ses matchs sortent du
  classement, de la simulation (6 équipes), des matchs à préparer et de la planification ; « À
  venir » les montre grisés, « ne sera pas joué ».
- Noms courts : le numéro d'équipe est gardé (« Nord Drome 2 » ≠ « Nord Drome »).
- Cartons dessinés (jaune, rouge) à la place de « CJ » et « CR » (`carton()` dans la page).
- Anciennes feuilles : ENTREEGARDIEN / SORTIEGARDIEN donnent le gardien en place (buts pris
  exacts) ; PROTOCOLECOMMOTION, COMMOTION et TEMPSDEREGULATIONCOMPORTEMENTAL sont ignorés
  (donnée de santé, sans intérêt). Feuille en 404 : `pdf_absent`, plus redemandée.
- Simulation de saison : forces tirées à chaque saison simulée, `analyze.UNSURE` (8 %) réduit
  par les matchs joués ; sans cela, 99 % de chances dès la 1re journée.

## Choix déjà arrêtés

- Un fichier HTML unique gardé sur le PC (ou la même page sur GitHub Pages), qui se met à jour
  à chaque ouverture ; une Release à chaque changement de données. Elle s'adapte au téléphone
  (demande de l'auteur, 05/10/2026, sous 560 px) : menu d'onglets fixé en bas, icône au-dessus
  du libellé court, noms courts d'équipes et de joueurs (`.tl`/`.ts`), colonnes secondaires des
  tableaux masquées (`.opt`), planification un match à la fois (pastilles du haut, `S.pm`) à
  colonne des noms fixe, mode « explique » (`S.tap`) qui montre la raison d'une case au doigt,
  faute de survol. Le test Chrome vérifie l'absence de débordement à 360 px.
- Mode clair sur téléphone (demande de l'auteur, 05/10/2026) : bouton ☀️ dans le bandeau, visible sous
  560 px seulement ; par défaut la page suit le réglage du téléphone (comme avant) ; « clair » force
  `data-theme="light"` (rangé dans `localStorage` « hbpsm:theme », ce téléphone seulement) ; le PC ne
  change pas (`applyTheme` ne force rien au-delà de 560 px).
- Rendu plus graphique (demande de l'auteur, 05/10/2026) : logos des clubs pris sur le site de la
  fédération (`structureNLogo` de la rencontre, quand `equipeNShowLogo` vaut 1 ; `D.logos`,
  `analyze.team_logos`, adresse `media-logos-clubs.ffhandball.fr/128/<fichier>.webp`), initiales
  à défaut ou si l'image ne charge pas (`logo()` dans la page) ; Semaine ouverte sur une carte du
  match (logos, VS, date, lieu) et une jauge de victoire (`gauge()`). Résumé public : `logos`
  (équipe -> image `data:` de 64 px, `publish.embed_logos`, ajoutée après `check_public`) et
  `logos_sources` (adresse d'origine : un logo n'est retéléchargé que si elle change). Le serveur
  des logos n'envoie pas d'en-tête CORS et HANDBALL-training doit marcher hors connexion : d'où
  les images intégrées ; l'application (1.16.3) ne garde que des images `data:`.
- Carte du match de la Semaine (demandes de l'auteur, 05/10/2026) : gymnase -> Google Maps
  (`mapsUrl`, adresse complète lue sur la page de la rencontre) ; date -> menu `details.agenda` :
  Google Agenda (lien) ou fichier .ics fabriqué au clic (`matchEvent`, `icsText`, VTIMEZONE
  Europe/Paris, 90 min, rendez-vous de l'entraîneur dans la description) ; rien tant que
  l'horaire est provisoire. Terrain : sept de départ (`startSeven`) et les 5 autres sous le
  titulaire de leur premier poste (`benchOf`), le 2e gardien sous le gardien ; libellés au prénom
  (`firstName`, initiale du nom si deux prénoms identiques), « titulaire / remplaçant ».
- L'empreinte du manifeste comprend le code du calcul (`publish.code_version` : pipeline/*.py et
  config.yml) : un changement de code republie, même sans nouvelle feuille.
- La page lit `publie/hbpsm.enc` par `raw.githubusercontent.com`, car les fichiers de Release
  n'ont pas d'en-tête CORS (vérifié).
- Les deux projets restent indépendants : seul le format de fichier les relie.
- Couleurs : celles du profil HBPSM de HANDBALL-training (`clubs/hbpsm/profil.json`), recopiées
  dans `dashboard/template.html` avec les mêmes rôles (bleu marine = ossature, jaune = actif ou
  mis en avant, toujours avec un texte foncé). Si le club change sa palette, changer les deux.
- Organisation de la page (demande de l'auteur, 04/10/2026, pour l'entraîneur qui convoque les
  12 joueurs après l'entraînement du vendredi) : Planification (4 prochains matchs, onglet
  ouvert à chaque ouverture de la page), Semaine,
  Convocation, Joueurs, Adversaires, Saison. Feuille : 12 joueurs dont 2 gardiens
  (`effectif_feuille`, `gardiens_feuille`). Rotation (refaite le 05/10/2026, l'ancienne,
  match par match, tombait sur les matchs difficiles et ne reposait jamais le 1er gardien) :
  chacun joue au moins 1 des 4 matchs par défaut (`S.regle` = 1, 2 ou 0 = libre), d'abord sur
  les matchs les plus abordables, jamais sur un match clé, 3 joueurs de champ et 1 gardien au
  plus par match, 2 gardiens si le minimum l'exige sur un match à 65 % ou plus (`ROT_GB2`) ;
  sort celui qui a le plus joué sur la période, poste pour poste si possible, sans découvrir un
  poste clef (`postes_clefs` dans config.yml, choix de l'auteur : 2 pivots, 4 arrières ARG/DC/ARD ;
  ARD en 2e poste pour tous les joueurs de champ droitiers, dans l'effectif et le secret, au
  05/10/2026 ; 2e poste facultatif dans la fiche joueur). « dépannage » dans la colonne
  disponible de l'effectif (`depannage`, case dans la fiche, `S.depannage`) : retenu en dernier,
  besoin de rotation nul ; un joueur de l'effectif y est (demande de l'auteur, 05/10/2026).
- Anciennes feuilles : le nom est souvent répété après le prénom (« DUPONTjean-DUPONT ») et le
  prénom est en minuscules ; `parse_fdme.split_name` corrige, et `analyze.load_history` le
  réapplique aux saisons déjà lues (sans les retélécharger). Adversaires : `passe.joueurs`
  (`analyze.past_players`), gardien = plus d'arrêts que de buts ; `avant` sur les buteurs et
  gardiens de cette saison. Fiabilité de chaque note (`analyze.reliability`,
  `FIABLE`) affichée en points ; avec 1 feuille au 05/10/2026, les choix restent des tendances.
  Notes ramenées vers la moyenne du groupe (`analyze.shrink_notes`, `PRUDENCE` = 2 matchs moyens,
  demande de l'auteur) ; `scores_bruts` garde la note d'avant. Conséquence assumée : un joueur
  peu vu remonte vers la moyenne, devant un joueur souvent vu mais en dessous ; les joueurs
  jamais alignés restent sans note (NON_NOTE dans la page). Gymnase des 4 prochains
  matchs du club lu sur la page de la rencontre ; heure de rendez-vous saisie par l'entraîneur.
  Disponibilités, choix et rendez-vous restent dans le navigateur de l'entraîneur (`S` dans
  `localStorage`), avec export / import en fichier ; jamais publiés.
- Risque d'une feuille (précisé à la demande de l'auteur, 05/10/2026) : ce qu'elle coûte en chances
  d'atteindre l'objectif par rapport à la meilleure équipe (tout le monde présent) = (victoire au
  complet − victoire avec cette feuille) × enjeu ; faible < 1 point, modéré 1 à 3, élevé > 3 ou feuille
  incomplète ou poste clef découvert ; coupe : faible. L'étiquette montre le coût (`riskCost`), un
  toucher ou le survol donne le calcul du match (`riskWhy`, `data-why-text`).
- Nouvelle version de la page (demande de l'auteur, 05/10/2026) : en ligne, plus de lien « La télécharger »
  mais « elle s'affichera d'elle-même d'ici quelques minutes » ; `waitNewPage` relit la page chaque minute
  (une demi-heure au plus) et recharge dès qu'elle porte la nouvelle empreinte, en gardant l'onglet
  (`sessionStorage` « hbpsm:onglet »). Un fichier gardé sur l'ordinateur garde le lien vers la Release.
- Santé du tableau de bord (proposée et validée par l'auteur, 06/10/2026) : `pipeline/sante.py` après chaque
  publication : rencontres lues pour chaque poule, prochain match du club trouvé, feuilles du club en
  retard (> 3 jours) ou illisibles, libellés inconnus, jetons qui expirent (< 30 jours, lu dans l'en-tête de
  l'API ; `HBPSM_JETON_CN`, et `HBPSM_JETON_PUBLICATION` facultatif) ; `publie/sante.json` (public, sans nom,
  relu par `check_public`, réécrit seulement s'il change) et issue « Tableau de bord : alerte » (ouverte,
  mise à jour, fermée d'elle-même ; `issues: write`) ; `--echec` quand la collecte échoue. Page : bandeau
  (`santeBanner`), les jetons pour l'entraîneur et les trésoriers seulement.
- Bilan du dernier match (06/10/2026) : en tête de Semaine (`bilanBlock`, ouvert 4 jours) : buteurs, gardiens,
  discipline, écart entre le choix publié de l'entraîneur et la feuille (les choix des derniers matchs
  restent publiés), chances d'atteindre l'objectif avant et après (`data/chances.json`, `record_chances`,
  repris de etat.enc), axes de la semaine.
- « Ma semaine » (06/10/2026) : 8e onglet « Moi » (`viewMoi`), le joueur choisi une fois sur l'appareil (même
  choix que pour proposer une amende, « hbpsm:moi ») : prochain match (statut proposé / retenu / repos /
  absent / blessé, rendez-vous, agenda, Maps), les 4 matchs, sa caisse (reste à payer, dernières amendes,
  cotisation, anniversaire), ses chiffres. Le rendez-vous de l'entraîneur part avec ses choix (`rdv`, vérifié
  par `choix.check`) ; `rdvOf` le lit pour tous.
- Onglet Saison (demande de l'auteur, 06/10/2026 : « Matchs à gagner » trop long, surtout sur téléphone) :
  une barre par match de championnat, haute des points de chance en jeu, match clé en jaune, journée, lieu
  et victoire estimée dessous, le calcul au toucher (`stakesChart`, `stakeWhy`) ; le détail match par match
  dans un tiroir fermé. En fin d'onglet, « Parcours de l'équipe » (`viewParcours`) : courbe des divisions
  depuis 2015 (R1 Prénationale à R5 2e division P16), point coloré selon la suite (montée, descente,
  maintien, en cours), place finale au-dessus, détail saison par saison dans un tiroir. Données : `parcours`
  dans config.yml (fourni par l'auteur, 2023-2024 à 2025-2026 recoupés avec les classements officiels) ; la
  saison en cours se complète d'après le classement de notre poule (`parcoursList`).
- Calendrier, application, image, causerie (demandes de l'auteur, 06/10/2026) :
  `pipeline/agenda.py` écrit `publie/matchs.ics` (public, relu par `check_public`, réécrit seulement si un
  match change, DTSTAMP mis à part) : matchs du club, championnat et coupe, heure de Paris, « horaire à
  confirmer » en journée entière (STATUS:TENTATIVE), score des matchs joués, sans les matchs contre un
  forfait ; noms courts comme la page (`short_team`). Page : `subscribeMenu` (Google `?cid=webcal…`, webcal,
  copier l'adresse ; `CFG.ics`). Application : `dashboard/manifest.webmanifest`, `sw.js` (réseau d'abord pour
  la page, jamais la page en cache hors navigation : `waitNewPage` doit voir la nouvelle version), icônes
  `dashboard/icons/` ; copiés dans `_site` par le workflow ; `installCard` dans Ma semaine (Android :
  `beforeinstallprompt` ; iPhone : explication ; « hbpsm:installe-vu »). Image du bilan : `bilanFacts`,
  `bilanImage` (canvas 1080 × 1350, prénoms, logos `data:` du résumé public), `shareBilan` (partage du
  téléphone, sinon téléchargement). Mode causerie : `talkSlides` (le match, l'adversaire, à surveiller, notre
  plan, notre équipe), `drawTalk` hors du rendu, clavier, glisser, plein écran. Rappel de 2e phase : santé,
  code « rappel-phase2 » du 1er février au 30 avril, coupé par `objectif.phase2` ; bandeau réservé à
  l'entraîneur et aux trésoriers (comme les jetons).
- Envois rapprochés (échec de « Caisse noire » le 07/10/2026 : deux envois à 4 s d'écart, le second, mis
  en attente, repartait du commit de son lancement et butait sur un conflit au push d'un fichier chiffré) :
  `caisse.yml`, `choix.yml`, `cn/…/proposer.yml` partent du dernier état de la branche (`ref: github.ref`)
  et, si le push est refusé, reprennent ce dernier état et y réappliquent l'entrée (5 essais ; sans doublon
  pour les journaux, l'envoi le plus récent gagne pour les choix). La collecte part aussi du dernier état.
- Navigation et statistiques (demande de l'auteur, 08/10/2026, tout en un) : sur téléphone, 4 onglets selon le mode
  (`PRIMARY` : entraîneur planif, semaine, convoc, joueurs ; joueur moi, semaine, saison, caisse), les autres sous
  « Plus » (`plusMenu`, classe `sec`, ordre `--o`). Ouverture : planification pour l'entraîneur, « Ma semaine » pour un
  joueur dont « hbpsm:moi » est rangé ; un onglet dans l'adresse l'emporte (`TAB_IDS`, `TAB_ALIAS`, `HASH_TAB` :
  `#caisse`, `#entraineur&convoc`…), puis le retour après mise à jour. L'adresse n'est jamais réécrite au changement
  d'onglet (la page doit rouvrir sur la planification). Raccourcis des longs onglets : `sec(id, libellé)` sur les h2,
  `withJumps` (3 au moins). Tiroirs gardés d'un rendu à l'autre : `keep()` / `KEEP` (`data-keep`). Joueurs : tri `JTRI`
  (`TRIS`, `triKey`, `pcKey`), ligne courte sur téléphone (CSS). Saison : `courseBlock` (`trajectoire` =
  `analyze.trajectory` : rang, points, `marge` sur le premier dehors ou le dernier dedans, `dedans` ; `chances` en
  courbe), `notreEquipe` (moyennes, `periods`, domicile / extérieur depuis `equipes[club].matches`, part des 3 meilleurs
  buteurs), résultats et à venir de notre poule limités à nos matchs (`TOUTE`, bouton). Adversaires : `versus` (projection,
  jamais présentée comme un face-à-face : chacun sur ses propres matchs, demande de l'auteur ; tranches à surveiller et à
  exploiter), « buts / match ». Bilan : `courseChart` (`derniers[].courbe` =
  `analyze.score_curve`, écart but après but depuis le déroulé). Semaine sur grand écran : `.solo` sans terrain,
  `.sem-bas` (matchs suivants et saison côte à côte). Planification : légende et calcul en tiroirs. Caisse : « Mon
  compte » (`monCompte`) en tête, formulaire en tiroir sur téléphone (`#cpicker`).
- Pronostics gardés et apprentissage (demande de l'auteur, 09/10/2026 : garder la Projection, voir la prédiction
  face à la réalité après le match, et s'en servir pour mieux estimer selon les résultats et les présents) :
  `pipeline/pronostic.py`. `record` garde le pronostic de chaque match du club à venir (`snapshot` : moyennes
  des deux équipes, score attendu `pour`/`contre`/`ecart`, `p`, tranches `surveiller`/`exploiter`) et le réécrit
  à chaque collecte jusqu'au coup d'envoi (`kickoff` ; horaire provisoire : le début du jour) ; `data/pronostics.json`
  (`STATE_FILES`, repris de etat.enc). Match joué : `reality` (score, mi-temps, tranches, discipline, arrêts, et
  `presents` des deux côtés d'après leurs feuilles d'avant le match, saison passée à HIST × fade), `corrige`
  (pronostic avec ces présents), `retenue` (feuille publiée de l'entraîneur, `published_choices` déchiffre
  choix.enc) ; figé une fois la feuille lue (`V` pour tout refaire). `calibrate` sur toutes les saisons lues +
  celle-ci, chaque match prévu avec ce qu'on savait avant lui : `dom`/`ext` (terrain, ramenés vers 1,04/0,96 par
  200 matchs fictifs ; passés à `outlook` et `cup_chance`, `terrain=`), β (force de frappe : taux de buts des
  six meilleurs joueurs de champ alignés, `frappe`, face aux autres feuilles de l'équipe ; « tous les joueurs »
  donnait une présence gonflée par les feuilles longues et les nouveaux venus) et γ (% d'arrêts des gardiens
  alignés moins celui de l'équipe), régression ramenée vers l'a priori (0,5 ± 0,25 ; 1,4 ± 0,5). Au 09/10/2026 :
  1 180 matchs, 383 feuilles, dom 1,063, ext 0,975, β 0,33 ± 0,08, γ 1,32 ± 0,29, vainqueur trouvé 76 %, écart
  à 5,2 buts près. Page : `D.pronostics` (matchs, suivi, modele, equipe) ; `taux`, `sr`, `part_gb` sur les
  joueurs ; `lineupAdj` donne `goalsAdj` et `costGoals` de la planification (la victoire estimée et le risque
  restent ceux de la force alignée, choix de l'auteur sur les notes) ; `pronoLive` dans la Projection,
  `pronoCompare` / `pronoPast` (Adversaires), bilan de la Semaine, `pronoSaison` (onglet Saison : matchs joués
  et prochain seulement, biais annoncé à partir de 3 matchs).
- Tout le calcul lourd se fait dans la collecte sur GitHub ; la page ne fait que la feuille
  proposée, la force alignée et le risque (formules dans le README). Ouverte, elle relit `publie/manifeste.json`
  toutes les dix minutes (`VERIF` dans `pipeline/publish.py`), au retour au premier plan et au
  retour de la connexion, et ne retélécharge `hbpsm.enc` que si `maj` a changé.
- Barème du classement : victoire 3, nul 2, défaite 1.
- Interface, commentaires et documentation en français.

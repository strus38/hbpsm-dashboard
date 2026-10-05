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
  4 premiers de chaque poule. Objectif de 1re phase réglé à 3 (choix de l'auteur, `objectif.rang`) ;
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
  (demande de l'auteur, 05/10/2026, sous 560 px) : menu sur une ligne aux libellés courts, noms
  courts d'équipes et de joueurs (`.tl`/`.ts`), colonnes secondaires des tableaux masquées
  (`.opt`), planification à colonne des noms fixe, mode « explique » (`S.tap`) qui montre la
  raison d'une case au doigt, faute de survol. Le test Chrome vérifie l'absence de débordement à
  360 px.
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
- Tout le calcul lourd se fait dans la collecte sur GitHub ; la page ne fait que la feuille
  proposée, la force alignée et le risque (formules dans le README). Ouverte, elle relit `publie/manifeste.json`
  toutes les dix minutes (`VERIF` dans `pipeline/publish.py`), au retour au premier plan et au
  retour de la connexion, et ne retélécharge `hbpsm.enc` que si `maj` a changé.
- Barème du classement : victoire 3, nul 2, défaite 1.
- Interface, commentaires et documentation en français.

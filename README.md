# Tableau de bord HBPSM

Suivi des poules 71 et 72 de la 2e division masculine P16 AURA : classements,
feuilles de match, équipe proposée pour le match suivant, matchs clés de la saison et axes de
travail pour l'entraînement.

## Principe : dépôt public, résultats chiffrés

Ce dépôt ne sert qu'à poser le code et à faire tourner la collecte. Tout ce qui porte un nom de
joueur est chiffré avant d'y entrer (AES-256-GCM, clé dérivée d'une phrase secrète) :

| Fichier | Contenu | Lisible par |
|---|---|---|
| `publie/HBPSM-tableau-de-bord.html` | la page, sans aucune donnée | tout le monde |
| `publie/hbpsm.enc` | données du tableau de bord et séance à importer | qui connaît la phrase |
| `publie/etat.enc` | état de la collecte (rencontres, feuilles lues) | qui connaît la phrase |
| `publie/historique.enc` | saisons passées collectées (rencontres, feuilles lues) | qui connaît la phrase |
| `publie/manifeste.json` | date et empreinte de la dernière mise à jour | tout le monde |
| `publie/seance-prochaine.hbt.json` | séance du prochain entraînement, sans nom de joueur | tout le monde |
| `publie/tableau-public.json` | résumé d'équipe sans nom de joueur (prochain match, classements, chances, repérage par numéro) | tout le monde |
| `publie/matchs.ics` | calendrier des matchs du club (équipes, dates, gymnases, scores), sans nom de joueur, auquel on s'abonne | tout le monde |

Les deux fichiers publics en clair sont relus avant d'être écrits : si un nom de l'effectif ou
d'une feuille de match (saison passée comprise) y apparaît, la publication est refusée.

La même page sans donnée est aussi servie par GitHub Pages, à une adresse fixe
(https://strus38.github.io/hbpsm-dashboard/) : elle demande la phrase une fois par poste, comme
le fichier gardé sur le PC. Les captures brutes d'un lancement partent dans une archive
7z chiffrée avec la même phrase. La phrase n'existe que dans le secret `HBPSM_CLE` et chez les
entraîneurs : choisir au moins cinq mots tirés au hasard, car le fichier chiffré est public et
une phrase courte se devine par essais successifs.

## Mise en route

1. **Settings > Secrets and variables > Actions** : créer `HBPSM_CLE` (la phrase secrète) et,
   si souhaité, `HBPSM_EFFECTIF` (un joueur par ligne, « Prénom Nom,POSTE,disponibilité » :
   poste facultatif, « ARG/ARD » pour deux postes ; disponibilité « non » pour un joueur absent
   longtemps, « dépannage » pour un joueur qui ne joue que s'il manque du monde ; puis
   « trésorier » en 4e colonne pour ceux qui tiennent la caisse noire (« hors caisse » pour un joueur
   qui n'y participe pas), la tranche d'âge en 5e (5 ans
   à partir de 18 ans : « 18-22 », « 23-27 »… ; jamais l'année de naissance),
   l'anniversaire « MM-JJ » en 6e et, pour un joueur qui ne reste pas toute la saison, le dernier
   mois « AAAA-MM » ou jour « AAAA-MM-JJ » où il est disponible en 7e).
2. **Settings > Pages** : source « GitHub Actions » (une fois).
3. **Actions > Collecte quotidienne > Run workflow**. Les adresses des poules 71 et 72 sont
   dans `config.yml` ; vides, la collecte les retrouve sur la page de la compétition.

Ensuite la collecte tourne seule chaque jour du dimanche au vendredi à 05:00 UTC (7 h à
Paris l'été, 6 h l'hiver) : les feuilles arrivent dans le désordre, et une journée n'est close
que lorsque toutes ses feuilles sont lues. Dates et heures sont celles de Paris. Quand les données changent,
une Release « Données du … » est créée.

## Pour les entraîneurs

Télécharger une fois `HBPSM-tableau-de-bord.html` depuis la dernière Release et le garder sur
son ordinateur. À chaque ouverture, la page récupère les dernières données, demande la phrase
secrète la première fois, puis s'en souvient. Tant qu'elle reste ouverte, elle revient voir le
dépôt toutes les dix minutes, et dès que la fenêtre revient au premier plan ou que la connexion
revient : elle ne lit que `manifeste.json` (quelques octets) et ne télécharge les données que si
elles ont changé, puis se redessine sans perdre l'onglet ni les réglages. Le bandeau du haut dit
« à jour » avec l'heure de la dernière vérification, ou « hors connexion ». Sans connexion, elle
affiche la dernière copie reçue. Quand la page elle-même évolue, un bandeau propose de
télécharger la nouvelle version.

La page suit la semaine de l'entraîneur :

| Onglet | Ce qu'il donne |
|---|---|
| Planification | les 4 prochains matchs : disponibilités (disponible, incertain, absent) et choix saisis par l'entraîneur, 12 joueurs dont 2 gardiens proposés par match, rotation guidée, force alignée et risque recalculés à chaque clic |
| Semaine | le prochain match : rang de l'adversaire, victoire estimée avec l'équipe retenue, enjeu pour la saison, recommandation de prise de risque, les 12 retenus, le sept possible |
| Convocation | après l'entraînement du vendredi : les 12, la date, le gymnase (lu sur ffhandball.fr), l'heure du rendez-vous, un message à copier pour le groupe et une version imprimable |
| Joueurs | fiches graphiques : note, buts ou arrêts par match, réussite au tir ou pourcentage d'arrêts face à la référence, sanctions, sélections à venir ; triées par note, buts, réussite, matchs ou sanctions |
| Adversaires | toutes les équipes des deux poules, HBPSM compris : buts (par match), mi-temps, discipline, gardiens, joueurs à surveiller (avec leurs chiffres de la saison passée s'ils étaient déjà là), une projection du match, pas un face-à-face (nos moyennes à côté des leurs, chacun sur ses propres matchs, nos buts par tranche de 10 minutes à côté des leurs, la tranche à surveiller et celle à exploiter), repères communs, et les joueurs de la saison passée, ceux revus cette saison en tête |
| Saison | chances de finir premier, la course (rang après chaque journée et marge sur la place visée, chances au fil des mises à jour), matchs à gagner (une barre par match : ce qu'il met en jeu ; le détail au toucher), notre équipe (moyennes, buts par tranche de 10 minutes, domicile et extérieur, part des 3 meilleurs buteurs), axes de travail, séance à importer, classements (nos matchs d'abord, toute la poule d'un bouton), parcours de l'équipe depuis 2015 (division et place de chaque saison, `parcours` dans `config.yml`) |

La proposition retient les 2 meilleurs gardiens et les 10 meilleurs joueurs de champ disponibles
(notes pondérées selon l'adversaire), en respectant les choix de l'entraîneur et les postes clefs
de `config.yml` : au moins 2 pivots et 4 arrières (ARG, DC ou ARD) sur chaque feuille ; un joueur
à deux postes (« 2e poste » dans sa fiche) compte pour l'un ou l'autre. Un joueur « en dépannage »
(effectif, ou case de sa fiche) n'est retenu que s'il manque des joueurs ou un poste clef, et
reste hors rotation. Puis la rotation,
sur les 4 matchs à la fois : chacun joue au moins 1 des 4 matchs (ou 2, ou rotation libre, au
choix de l'entraîneur). Elle se fait d'abord sur les matchs les plus abordables (victoire
estimée la plus haute), jamais sur un match clé, avec au plus 3 joueurs de champ et 1 gardien
changés par match (les 2 gardiens si le minimum l'exige, sur un match à la victoire estimée
d'au moins 65 %) ; laisse sa place celui qui a le plus joué sur la période (à égalité, le moins
bien noté), si bien que le repos tourne aussi chez les titulaires et les gardiens ; le
remplacement se fait poste pour poste quand c'est possible, et jamais au point de découvrir un
poste clef. Chaque note
dit sur combien de matchs elle repose (saison passée comptée pour moitié) : fragile sous 3,
indicative sous 6, solide au-delà ; tant que le club a moins de 5 feuilles lues ou des notes
fragiles, la planification le rappelle. Chaque note est ramenée vers la moyenne de l'effectif
(gardiens et joueurs de champ à part), comme si le joueur avait aussi joué 2 matchs moyens :
une note sur un ou deux matchs reste près de la moyenne, une note sur huit matchs bouge de
1 à 3 points ; la fiche garde la note brute. Chaque case
dit pourquoi au survol ; un minimum impossible à tenir est signalé en rouge. La force
alignée rapporte la valeur des 12 retenus à celle de l'équipe type ; la victoire estimée part
de celle calculée sur GitHub (équipe au complet) et baisse avec la force ; le risque multiplie
cette baisse par l'enjeu du match pour la saison.

Tout le calcul lourd (classements, notes, chances de victoire et de finir premier, matchs clés,
axes de travail) est fait par la collecte sur GitHub. La page ne fait que ces calculs légers,
parce que les disponibilités, les choix et les postes se saisissent sur l'ordinateur de
l'entraîneur et n'en sortent pas (un fichier « Sauvegarder mon planning » les emporte ailleurs).

Deux modes. Ouverte depuis HANDBALL-training, dont le lien se termine par `#entraineur`, la
page est en mode entraîneur : disponibilités, choix, rotation, rendez-vous, convocation et
postes se modifient. Ouverte directement (GitHub Pages ou fichier), elle se consulte seulement :
aucun contrôle de modification, une note rappelle qu'une feuille non validée par l'entraîneur
n'est qu'une suggestion, et toucher une case en donne la raison. Ce n'est pas un verrou : rien
de ce qu'on modifie ne quitte le navigateur, sauf la feuille que l'entraîneur valide (ci-dessous).

Les propositions sont les mêmes pour tous et d'une ouverture à l'autre : en consultation, rien de
ce qui a pu être saisi dans le navigateur n'y entre, et les notes et chances de victoire qui
guident la rotation restent figées entre deux matchs du club (elles repartent à chaque nouvelle
feuille lue, ou si l'effectif change). D'un match au suivant, au moins deux joueurs changent,
gardiens compris, à partir du dernier match joué. Un gardien ne fait pas plus de trois matchs de
suite sans sortir, matchs déjà joués compris. Les échanges se font poste pour poste
(même poste principal, ou un entrant qui tient le poste du sortant) et équilibrent, autant que
possible, matchs à domicile et à l'extérieur pour chacun. Une case dit « proposé » tant que l'entraîneur
n'a pas validé la feuille, « retenu » ensuite. Le tableau montre aussi les deux derniers matchs terminés
de la saison : qui était sur la feuille. Une
tranche d'âge de 5 ans, dans l'effectif (secret), oriente les changements vers les plus jeunes à valeur
proche ; elle n'est affichée nulle part. De même, l'expérience au club (les matchs joués depuis 2015, comptés
davantage dans les divisions plus hautes) entre pour 10 % dans la note, sans être affichée ; et l'avis de
l'auteur sur un joueur (1 à 5 étoiles, dans l'effectif), pour ce que la feuille de match ne dit pas, en
compte pour un quart.

L'entraîneur seul déclare un joueur absent (pour un match) ou blessé (à partir d'un match, jusqu'à
ce qu'il le dise rétabli), d'un clic sur une case. Le joueur sort des propositions concernées, et
la rotation des matchs suivants s'en accommode. Publiés avec ses choix (chiffrés), ces statuts
valent pour tout le monde : les propositions changent avant même qu'il valide la feuille.

Sur téléphone, la page prend l'allure d'une application : onglets en bas avec icônes, noms
courts, tableaux sans les colonnes secondaires, planification un match à la fois (choisi par
les pastilles du haut) avec la colonne des noms fixe et de grandes cases. Le survol n'existant
pas au doigt, « Toucher une case : explique » affiche la raison d'une case au lieu de la
modifier. En bas, quatre onglets selon qui regarde (l'entraîneur : Planification, Semaine,
Convocation, Joueurs ; un joueur : Ma semaine, Semaine, Saison, Caisse), les autres sous « Plus ».
Les fiches des joueurs tiennent sur une ligne tant qu'on ne les ouvre pas ; la légende et le
calcul de la planification se replient ; le formulaire de la caisse s'ouvre d'un bouton.

Navigation. La page s'ouvre sur la planification pour l'entraîneur, sur « Ma semaine » pour un joueur
qui a dit qui il est sur cet appareil. Un lien vers un onglet l'ouvre directement : l'adresse de la
page suivie de `#caisse`, `#saison`, `#moi`, `#semaine`, `#joueurs`, `#adversaires`, `#planification`
ou `#convocation` (avec l'entraîneur : `#entraineur&convocation`). Les longs onglets (Joueurs, Saison,
Caisse noire) commencent par une rangée de raccourcis vers leurs parties. Le bilan du dernier match
montre l'écart au score minute par minute (plus grosse avance, plus gros retard).

Les équipes sont montrées avec le logo de leur club, pris sur le site de la fédération (ses
initiales s'il n'y en a pas). L'onglet Semaine s'ouvre sur une carte du match : les deux
équipes face à face, la date, le gymnase et une jauge de la victoire estimée. Toucher le
gymnase l'ouvre dans Maps ; toucher la date propose d'ajouter le match à son agenda (Google
Agenda, ou un fichier .ics pour l'agenda du téléphone et Outlook), avec l'heure de rendez-vous
si l'entraîneur l'a fixée. Tant que la fédération n'a pas fixé l'horaire, la date ne propose
rien. Le terrain montre les 12 de la feuille : le sept de départ et, sous chaque poste, les
remplaçants qui le jouent d'abord.

Couleurs : celles du club, reprises du profil HBPSM de HANDBALL-training
(`clubs/hbpsm/profil.json`), avec les mêmes rôles : le bleu marine pour l'ossature, le jaune
pour ce qui est actif ou mis en avant, toujours avec un texte foncé.

La page lit `publie/hbpsm.enc` par `raw.githubusercontent.com` : les fichiers attachés à une
Release ne sont pas lisibles par une page web (GitHub n'y met pas d'en-tête CORS).

## Coupes

`coupes` dans `config.yml` désigne les coupes où joue le club (la Coupe de France
départementale en 2026-2027). La collecte y lit chaque tour, une poule d'une journée de
plusieurs centaines de rencontres, et n'en garde que les matchs du club, avec leur feuille.
Ces matchs comptent dans les statistiques et les notes des joueurs, et dans la planification :
ils s'y placent à leur date, marqués « Coupe », sans enjeu pour le classement, jamais match clé,
et la rotation y passe en premier (les gagner compte moins qu'en championnat). Ils ne comptent
ni dans le classement ni dans les chances de la saison ; l'onglet Saison montre le parcours du
club en coupe.

Un adversaire de coupe qui ne joue pas dans nos poules a lui aussi sa fiche dans Adversaires,
marquée « (coupe) » : la collecte le retrouve dans les compétitions de `voisines` (la 1re et la
2e division P16 AURA) et ne lit que ses matchs de championnat, avec leurs feuilles. Ils servent
à sa fiche seulement, jamais au classement de nos poules.

## Feuille validée par l'entraîneur

Tant que l'entraîneur n'a pas validé un match, tout le monde voit sur la page une
**suggestion** du tableau de bord (cases en pointillés chez les visiteurs). En mode entraîneur,
« Valider la feuille » (planification, semaine ou convocation) fige la feuille de ce match et
la publie : chacun voit alors « Choix de l'entraîneur, validé le… », et cette feuille sort de la
rotation automatique. Retoucher une feuille validée la repasse à valider ; les joueurs voient
la version publiée jusqu'à la nouvelle validation. « Retirer la validation » la retire aussi de
ce qui est publié : chacun revoit une suggestion pour ce match.

La page de l'entraîneur chiffre les feuilles validées avec la phrase du club et lance le
workflow « Choix de l'entraîneur » (`.github/workflows/choix.yml`). Il vérifie qu'elles sont
chiffrées avec la phrase du club, de la forme attendue, puis les écrit dans
`publie/choix.enc`, que toutes les pages relisent. Rien n'est déchiffré dans le journal.

Pour cela, la page a besoin d'un jeton GitHub, créé une fois par le propriétaire du dépôt :
1. GitHub > Settings > Developer settings > Personal access tokens > **Fine-grained tokens** >
   Generate new token ;
2. Repository access : **Only select repositories**, `hbpsm-dashboard` ;
3. Permissions > Repository permissions : **Actions : Read and write** (rien d'autre ; il peut
   lancer ce workflow, pas modifier le code) ;
4. une date d'expiration (la fin de la saison, par exemple), puis Generate token.

L'entraîneur colle ce jeton une fois, quand la page le lui demande à sa première validation ;
il reste dans son navigateur, jamais dans un fichier. « Oublier le jeton de publication », en
bas de la planification, l'efface.

## Caisse noire

L'onglet « Caisse noire » reprend le règlement du groupe (`pipeline/caisse.py`), point par
point. Il montre ce qu'il y a dans la caisse, le podium des amendes, les comptes de chacun et
les derniers mouvements. Les comptes se lisent d'un coup d'œil : le total encaissé sur le total
dû, une barre par joueur (vert payé, rouge reste à payer), la cotisation en pastille (payée ou à
régler), les joueurs « À régler » (du plus gros reste au plus petit) puis « À jour » ; sur
téléphone, le nom, la barre et le reste seulement.

- Les trésoriers (et l'entraîneur), qui ont le jeton de publication, mettent une amende en
  trois touches (qui, quoi, combien), valident ou refusent les propositions, encaissent les
  paiements et annulent une amende. Chaque saisie part chiffrée au workflow « Caisse noire »
  (`.github/workflows/caisse.yml`), qui l'ajoute au registre `publie/caisse.enc` ; une saisie
  renvoyée n'est comptée qu'une fois. Tout le monde la voit en une minute ou deux.
- Les autres consultent. Ils peuvent préparer une dénonciation, copiée pour le groupe
  (une fausse dénonciation coûte 1 €, comme le dit le règlement).
- Seuls les joueurs à jour de leur cotisation mettent (trésoriers, entraîneur) ou dénoncent une
  amende (proposition, dénonciation copiée ou partagée) ; ceux qui ne l'ont pas encore réglée
  peuvent toujours le faire. Chacun dit d'abord qui il est (« Vous êtes ») ; sinon, ou sans
  cotisation, les boutons restent grisés et la page dit pourquoi. Une proposition d'un joueur pas à
  jour est marquée irrecevable : le trésorier ne peut que la refuser.
- Propositions, à valider par un trésorier, chacune avec son point du règlement : d'après les
  feuilles de match, la 2e exclusion de 2 minutes, les 3 × 2 minutes, l'expulsion directe, une
  réussite au tir sous 40 %, le dernier but du match, la victoire de +20 (tournée du coach) ;
  et aussi le « Bon point ! » d'un mois sans amende.
- Penalties manqués (« Gérard Penaldo ») : la feuille ne dit pas qu'un 7 m est manqué. Après
  chaque match, une carte propose les tireurs (ceux qui ont marqué un 7 m, plus un autre au
  choix) ; le trésorier indique les manqués et les hors cadre, la page compte l'amende comme le
  règlement (1 € à partir du 2e échec du match, 2 € tout de suite pour un hors cadre).
- Cotisations : une carte où le trésorier marque qui a payé (la cotisation et son paiement sont
  enregistrés ensemble) ou qui ne participe pas à la caisse (« réintégrer » l'annule) ; elle
  disparaît quand tout le monde est fixé. La cotisation compte dans la caisse, pas comme une
  amende (ni podium, ni compte des amendes).
- Hors caisse (« ne participe pas », ou « hors caisse » dans l'effectif) : ni cotisation, ni
  amende, ni bon point, ni penalty à vérifier, ni dénonciation.

Pour qu'un trésorier puisse saisir, donnez-lui le jeton de publication (celui de la feuille
validée) : il le colle une fois via « Je suis trésorier ». Les trésoriers sont marqués dans
l'effectif (colonne « trésorier »), jamais dans un fichier du dépôt.

## Chaîne de traitement

| Étape | Commande | Produit |
|---|---|---|
| Reprise | `python -m pipeline.publish restore` | `data/` depuis `publie/etat.enc` |
| Effectif | `python -m pipeline.publish roster` | `roster.csv` depuis le secret |
| Collecte | `python -m pipeline.collect` | `data/fixtures.json`, `raw/fdme/*.pdf` |
| Feuilles | `python -m pipeline.parse_fdme` | `data/matches/<id>.json` |
| Publication | `python -m pipeline.publish seal` | `publie/` |

`data/`, `raw/`, `docs/` et `roster.csv` ne sont jamais versionnés. Pour un aperçu en clair sur
sa propre machine : `python -m pipeline.build_dashboard` écrit `docs/index.html`.

La collecte n'a pas besoin de navigateur : chaque page de ffhandball.fr porte ses données en
JSON dans le HTML servi (`<smartfire-component name="competitions---rencontre-list"
attributes="…">`). Elle lit la page de la poule, puis chaque journée pas encore close (une
journée est close quand toutes ses feuilles sont lues), soit une quinzaine de pages par poule
en début de saison et de moins en moins ensuite, avec une pause d'une seconde entre deux.
La feuille se télécharge à l'adresse tirée de son code (`fdm.fdme.ffhandball.fr/W/A/G/W/WAGWUHC.pdf`),
sans ouvrir la page de la rencontre. Les pages passent par un cache d'une à deux heures : un
score absent de la page est pris sur la feuille, et un classement fédéral qui compte moins de
matchs joués est signalé « pas encore à jour » plutôt que comme une pénalité.

## Réglages

- `config.yml` : URL des poules, motifs de reconnaissance du club, taille de la feuille, rang
  visé, équipe et jours d'entraînement.
- Effectif : le nom s'écrit « Prénom Nom » ; il est rapproché de celui de la feuille de match
  sans tenir compte de l'ordre, des accents ni de la casse. On peut ajouter `,POSTE`
  (GB, ALG, ARG, DC, ARD, ALD, PIV). Un joueur jamais aligné apparaît dans « Pas encore alignés ».
  Postes et absences se saisissent aussi dans la page, où ils restent sur l'ordinateur.

## Comment la note est calculée

Note sur 100 par joueur, à partir des feuilles du club : buts récents (les derniers matchs
pèsent plus), efficacité si les tirs sont saisis, discipline, écart de l'équipe avec et sans le
joueur, buts en fin de match serré, assiduité. Trois pondérations (équilibré, attaque, rigueur) ;
celle conseillée dépend du profil de l'adversaire. Gardiens : d'abord le pourcentage d'arrêts
(arrêts sur tirs cadrés subis, c'est-à-dire arrêts + buts pris), puis les arrêts par match,
l'impact et l'assiduité. Joueurs de champ : les buts face aux tirs (réussite au tir).

La feuille donne les arrêts de chaque gardien, pas ses buts pris. Quand un seul gardien a fait
des arrêts, il prend tous les buts du match. Quand deux gardiens se partagent le match, chaque but
encaissé va au gardien du dernier arrêt de la même mi-temps (à défaut, du prochain) : c'est une
estimation, marquée comme telle dans la page. Le même calcul donne le pourcentage d'arrêts des
gardiens adverses dans le repérage.

L'équipe proposée compte 12 joueurs dont 2 gardiens (`effectif_feuille` et `gardiens_feuille`
dans `config.yml`), 14 en Coupe de France (`effectif_feuille` de la coupe : « le club peut aligner
14 joueurs de 17 ans et plus », règlement de la Coupe de France régionale et départementale,
art. 15), les mieux notés parmi les disponibles ; s'il manque du monde, un joueur de l'effectif pas
encore aligné complète la feuille. Un joueur disponible jusqu'à une date (effectif, 7e colonne)
n'est plus proposé ensuite ; à besoin égal, il passe après les autres en championnat et devant
eux en coupe, qui ne compte pas pour le classement.

Discipline : les trois sanctions de la feuille restent distinctes partout (joueurs, journal des
matchs, repérage de l'adversaire) : l'avertissement (carton jaune, un au plus par joueur et par
match), l'exclusion de 2 minutes, et la disqualification (carton rouge, que le carton bleu
complète d'un rapport). Dans la note, un 2 minutes compte 1, un carton rouge 3, un carton jaune 0,3.

Limites : la feuille ne dit ni le temps de jeu, ni les postes, ni qui était sur le terrain en
même temps. Le tableau de bord donne les matchs disputés, le temps passé sur le banc à 2 minutes
et un indice de présence (tranches de dix minutes avec une action relevée). Avec peu de matchs,
les notes sont des tendances.

## Objectif de saison et matchs clés

L'onglet Saison estime les chances d'atteindre le rang visé (`objectif.rang`, 2 : finir 1er ou 2e,
les places de montée) en simulant les matchs restants de la poule, montre les chances de chaque
rang final, et donne pour chaque match du club l'écart de chances entre une victoire et un autre
résultat : les trois plus gros écarts sont les matchs clés. La force de chaque équipe reste
incertaine : chaque saison simulée la tire autour de son estimation (±8 % de buts au départ),
d'autant moins large que l'équipe a joué de matchs. Égalités départagées comme le
règlement (confrontations directes, puis différence de buts). Règlement AURA 2026-2027 : 2
montées par secteur (poules 71 et 72), au terme d'une deuxième phase dont la formule sera
publiée vers février ; le modèle ignore les pénalités.

## Saison passée

`historique` dans `config.yml` désigne les saisons passées au même niveau (2025-2026).
`python -m pipeline.history` les collecte une fois : les poules où jouaient le club et ses
adversaires d'aujourd'hui, puis les feuilles de leurs matchs. Le serveur des feuilles limite le
débit (HTTP 429) : elles arrivent par reprises successives, une toutes les 4 secondes, en
respectant le délai demandé, dans un budget de 15 minutes par passage (la collecte quotidienne
la relance jusqu'à ce qu'elle soit complète ; une feuille jamais déposée, HTTP 404, n'est plus
redemandée). Le résultat est publié chiffré dans `publie/historique.enc`, réécrit seulement
s'il change. Les anciennes feuilles disent qui entre et sort des buts : les buts pris y sont
attribués exactement au gardien en place, et à aucun quand il était sorti (jeu à 7). Les
mentions de commotion ne sont jamais conservées.

Ce qu'elle apporte :
- les notes des joueurs partent de la saison passée : un match de l'an dernier compte pour la
  moitié d'un match de cette saison au départ, puis de moins en moins à mesure que la saison avance
  (0,43 après un match, 0,25 après six) : les matchs joués aident de plus en plus à choisir ; un joueur de l'effectif pas encore aligné reçoit une note
  provisoire ; un joueur parti n'est pas repris ; la saison d'avant (2024-2025, nos matchs seulement)
  compte pour un quart de match ; nos moins de 18 ans et les saisons plus anciennes (2023-2024, nos
  matchs seulement) servent, pour un quart de match aussi, au seul joueur sans aucun match plus récent
  (un jeune qui monte, un joueur revenu au club) ;
- pour chaque adversaire déjà vu : bilan et classement, confrontations avec le club, joueurs de
  cette saison déjà là l'an dernier, devenir de ses meilleurs buteurs ;
- dans la simulation, la force de départ d'une équipe connue est celle de la saison passée,
  d'autant plus que son effectif est resté, au lieu de la moyenne de la poule.

La division du dessus (1re division P16 AURA) est aussi lue pour la saison passée (entrée
`niveau: 1` de `historique`), mais seulement pour les équipes de nos poules et nos adversaires
de coupe qui y jouaient. Une équipe qui en descend compte plus forte : son bilan d'alors est
relevé de l'écart entre deux divisions (`ecart_division`, 12 % de buts marqués en plus et
encaissés en moins, hypothèse à revoir avec les résultats de coupe), d'autant plus qu'elle a
gardé ses joueurs. Un club présent dans les deux divisions voit ses deux bilans pesés selon la
part de son effectif de cette saison qui jouait dans chacune. L'équipe 2 d'un club n'est jamais
confondue avec son équipe 1. De même, un adversaire de coupe qui joue cette saison dans la
division du dessus (`voisines`, `niveau: 1`) reçoit une victoire estimée qui tient compte de
l'écart. Adversaires le signale : « niveau potentiellement supérieur au nôtre ».

Notre division est la plus basse : une équipe absente la saison passée est une nouvelle équipe
ou une nouvelle entente. Ses joueurs sont donc cherchés un par un sur toutes les feuilles de la
saison passée déjà lues, quel que soit leur club : sa force de départ est celle des équipes d'où
ils viennent, à proportion des joueurs retrouvés (Adversaires : « Leurs joueurs en 2025-2026 :
6 de leurs 11 joueurs retrouvés, 6 avec … »). Cela vaut pour toutes les équipes : un club qui a
gardé ses joueurs retrouve son propre bilan.

## Ma semaine, bilan du match, santé

- **Ma semaine** (onglet « Moi ») : chaque joueur choisit une fois qui il est sur son appareil et voit
  son prochain match (proposé, retenu par l'entraîneur, au repos, absent ou blessé), le rendez-vous,
  l'ajout à l'agenda et le gymnase, ses quatre prochains matchs, sa caisse noire et ses chiffres.
- **Bilan du match** : dès que la feuille du dernier match est lue, l'onglet Semaine s'ouvre sur son
  bilan : buteurs, gardiens, discipline, écart avec le choix de l'entraîneur, chances d'atteindre
  l'objectif avant et après, axes de travail de la semaine.
- **Santé** : à chaque collecte, `pipeline/sante.py` vérifie que le site de la fédération est bien lu,
  que les feuilles du club arrivent et se lisent, et que les jetons n'approchent pas de leur échéance.
  En cas de souci, la page affiche un bandeau et une issue « Tableau de bord : alerte » s'ouvre (son
  auteur est prévenu par mail) ; elle se ferme d'elle-même quand tout va bien. De février à avril, elle
  rappelle aussi de prendre en compte la formule de la deuxième phase (« phase2: vue » sous `objectif`
  dans `config.yml` une fois fait) ; ce rappel ne s'affiche qu'à l'entraîneur et aux trésoriers.

## En buts plutôt qu'en pourcentages

- **Buts évités par un gardien** : ses arrêts, moins ce qu'aurait arrêté le gardien moyen des poules sur les
  mêmes tirs cadrés (dès 60 tirs) ; sur sa fiche, et pour la paire proposée dans la Semaine.
- **Écart attendu** de chaque match, en buts, à côté de la victoire estimée, et ajusté à l'équipe retenue
  d'après ce que les feuilles ont appris des présents (voir « Pronostics et réalité »).
- **Coût d'une exclusion de 2 minutes**, mesuré sur nos feuilles : l'écart de buts des deux minutes qui
  suivent, comparé au rythme du match (environ −0,4 but) ; dans « À travailler », sur les fiches et en causerie.

## Pronostics et réalité

Le pronostic de chaque match du club (celui de la Projection, onglet Adversaires : nos moyennes face aux
leurs, score attendu, victoire estimée, tranches à surveiller et à exploiter) est gardé tel qu'il était à
la dernière collecte avant le coup d'envoi (`pipeline/pronostic.py`, `data/pronostics.json` repris de
`etat.enc`). Le match joué, la feuille dit ce qu'il en a été : score, mi-temps, discipline, gardiens, buts
dans les deux tranches, qui jouait de chaque côté et ce que les présents expliquent de l'écart au pronostic
(« avec ces présents, le modèle aurait dit… »), et, si l'entraîneur l'avait publiée, l'écart attendu de
l'équipe retenue. Comparaison dans l'onglet Adversaires, le bilan de la Semaine et l'onglet Saison, qui
tient aussi le compte (vainqueur trouvé, erreur moyenne sur l'écart, biais à partir de 3 matchs).

À chaque collecte, toutes les saisons lues (un millier de matchs, plusieurs centaines de feuilles) apprennent
au modèle, chaque match étant prévu avec ce qu'on savait avant lui :

- **le terrain** : buts attendus à domicile et à l'extérieur, au lieu des ±4 % posés au départ (environ
  +6 % et −2,5 % au 09/10/2026) ; ils servent à la simulation de la saison et aux matchs de coupe ;
- **les buteurs absents** : la force de frappe d'une feuille, ce sont les buts par match de ses six meilleurs
  buteurs de champ (les six joueurs de champ sur le terrain : une feuille plus longue ne marque pas plus). Une
  équipe dont la force de frappe alignée vaut une part p de l'habitude marque environ 1 + β (p − 1) fois ses
  buts attendus ; β ≈ 0,33 : les autres compensent une bonne part ;
- **les gardiens** : chaque point d'arrêts de plus que le gardien habituel de l'équipe retire environ γ % des
  buts de l'adversaire (γ ≈ 1,3).

β et γ partent d'une valeur a priori (0,5 et 1,4) et suivent les feuilles. La page s'en sert pour l'écart
attendu de la feuille proposée : écart du modèle + β (p − 1) × nos buts attendus + γ × (arrêts des gardiens
alignés − arrêts habituels) × leurs buts attendus. La victoire estimée et le risque restent ceux de la force
alignée (les notes).

## Calendrier, application, image du bilan, causerie

- **Tous les matchs dans son agenda** : le menu « 🔔 Tous les matchs » (Semaine, Ma semaine) abonne
  Google Agenda, l'iPhone ou Outlook à `publie/matchs.ics` (`pipeline/agenda.py`). Les horaires « à
  confirmer » et les gymnases s'y mettent à jour d'eux-mêmes ; les matchs joués y prennent leur score.
- **Application sur l'écran d'accueil** : la page de GitHub Pages s'installe (manifeste, icônes et
  service worker dans `dashboard/`, copiés par le workflow) ; Ma semaine propose l'installation sur
  Android et l'explique sur iPhone. Installée, elle s'ouvre en plein écran et sans connexion.
- **Image du bilan** : « Partager le bilan en image » fabrique dans l'appareil une image (score, logos,
  buteurs, gardiens, discipline, chances) pour le groupe de l'équipe ; rien n'est publié.
- **Mode causerie** : depuis la Semaine, cinq écrans à montrer au vestiaire (le match, l'adversaire,
  à surveiller, notre plan, notre équipe) ; flèches, glisser ou pastilles pour avancer, Échap pour fermer.

## Caisse noire : propositions de tous

N'importe quel joueur qui a la phrase du club et qui est à jour de sa cotisation propose une amende
depuis l'onglet Caisse noire : il a dit qui il est (« Qui êtes-vous ? »), choisit le joueur et la règle, puis touche « Proposer
l'amende ». La proposition part,
chiffrée, au dépôt public à part `strus38/hbpsm-cn` (code tenu dans `cn/`), avec un jeton limité à
ce seul dépôt : la collecte le range dans les données chiffrées, personne n'a rien à coller. Tout le
monde la voit d'ici une à deux minutes ; seuls les trésoriers la valident ou la refusent. Même extrait
de la page, ce jeton ne permet que d'ajouter une proposition, jamais de valider une amende ni de
toucher au tableau de bord. Secrets : `HBPSM_JETON_CN` ici, `HBPSM_CLE` dans les deux dépôts.

## Présences et homme du match

Onglet « Présences » (et « Mes présences » dans Ma semaine : les deux semaines qui viennent, répondues ou non). À sa première ouverture, la page demande
« Qui êtes-vous ? » : chacun choisit son nom une fois sur son appareil. Ce choix part au dépôt
`strus38/hbpsm-cn` ; un nom déjà choisi sur un autre appareil est signalé (« C'est bien moi » ou
« Choisir un autre nom »), et l'appareil d'origine voit qu'un autre s'est déclaré comme lui. On peut
toujours se redéclarer (« changer ») : l'équipe règle les doublons entre elle. Le premier appareil d'un
joueur reçoit un **code personnel** (Ma semaine, « 🔑 Votre code personnel ») : sur un autre téléphone ou
ordinateur, le joueur choisit son nom puis donne ce code, et il est reconnu sans doublon signalé. Seule
une empreinte du code (PBKDF2) part au journal, jamais le code ; aucun secret GitHub n'est nécessaire.

- Chacun répond pour chaque entraînement (jours de `entrainement.jours`) et chaque match du club,
  au plus tard 4 jours avant, 21 h (`presences` dans `config.yml`) : « Présent », ou « Absent » avec
  un motif (malade, blessé, vacances, autre ; « autre » demande un mot). Les présences commencent le
  12/10/2026 (`debut`) ; tout le calendrier de la saison est ouvert (`fin`), mois par mois, pour répondre
  à l'avance, avec « Présent à tout ce qui reste sans réponse » pour un mois. « Absent plusieurs jours »
  couvre d'un coup les séances et les matchs d'une période.
- Seul l'entraîneur voit les réponses des autres ; un joueur ne voit que les siennes, ni les réponses
  ni le nombre de présents des autres (demande de l'auteur, 09/10/2026). Le journal est chiffré avec
  la phrase du club : comme le mode entraîneur, c'est un usage, pas un verrou.
- Feuille proposée (entraîneur) : un joueur qui a dit ne pas venir sort ; si assez de joueurs ont dit
  venir (10 joueurs de champ et 2 gardiens, 12 et 2 en coupe), la feuille se fait parmi eux ; sinon,
  comme avant, parmi tous les disponibles. Un clic de l'entraîneur prime sur la réponse. En
  consultation, la suggestion ne tient compte que de la réponse de celui qui regarde.
- L'entraîneur voit, match par match, la feuille, ceux qui ont dit venir, ceux qui n'ont pas répondu
  et les absents avec leur motif, et retient ou retire d'un bouton ; puis il valide la feuille. Pour
  chaque entraînement : joueurs de champ et gardiens annoncés, absents, sans réponse.
- L'entraîneur annule (ou rétablit) n'importe quel entraînement ou match de la saison (« Le calendrier de
  la saison », ou « Annuler ce match »). Publié avec ses choix, c'est vu de tous (Présences, Ma semaine,
  Semaine, calendrier des matchs marqué annulé). Plus de réponse attendue, ni amende, ni vote, ni
  planification ; les réponses déjà données sont gardées : rétabli, tout revient. Une séance annulée
  n'est pas exportée vers HANDBALL-training (la suivante l'est). La séance exportée vers HANDBALL-training porte le
  nombre de joueurs de champ et de gardiens annoncés (`effectifJoueurs`, `effectifGardiens`).
- Sans réponse à temps : « absent – sans justification » et l'amende du règlement (1 € entraînement,
  2 € match) proposée aux trésoriers, pour les séances et les matchs à partir de `amendes_depuis`.
- Homme du match : les joueurs de la feuille (lue, sinon celle publiée par l'entraîneur) votent
  pendant 48 h après le match, pas pour eux-mêmes ; le résultat est visible de tous (Présences, bilan
  de la Semaine) et l'amende « MVP » (2 €) proposée aux trésoriers.

Tout part par le même jeton et le même workflow que les propositions d'amendes, dans un journal à part,
`presences.enc`.

## Lien avec l'application de préparation des entraînements

Le fichier chiffré contient une séance au format d'échange `.hbt.json` de HANDBALL-training :
datée du prochain entraînement, avec les axes de travail et le repérage de l'adversaire dans
l'objectif, sans exercice. Elle se télécharge depuis l'onglet Saison et s'importe par la
fonction Importer de l'application (vérifié avec l'importeur de la version 1.14.2).

L'exemplaire HBPSM de l'application a un écran « Tableau de bord HBPSM », sans phrase
secrète : il lit `publie/tableau-public.json` (prochain match, objectif et chances de chaque
rang, classements des deux poules, repérage de l'adversaire par numéro, axes de travail), crée
la séance de la semaine depuis `publie/seance-prochaine.hbt.json`, et ouvre d'un bouton le
tableau de bord complet sur GitHub Pages (planification, convocation, fiches des joueurs), qui
lui demande la phrase. C'est la seule partie de l'application qui passe par internet, et
seulement quand l'entraîneur ouvre cet écran.

Les deux projets restent indépendants, sans code partagé. Le seul lien est ce contrat, à ne
pas rompre d'un côté sans l'autre : les chemins `publie/tableau-public.json` (`format`
« hbpsm-public », `v` 1) et `publie/seance-prochaine.hbt.json` (`.hbt.json` v3) sur la branche
`main`, et l'adresse GitHub Pages. Ces adresses sont déclarées dans `clubs/hbpsm/profil.json`
de HANDBALL-training.

## Tests

`pip install -r requirements-dev.txt` puis `python -m pytest -q`. Les tests utilisent un faux
site local, de fausses feuilles et des joueurs inventés, construits sur la forme relevée sur le
vrai site ; ils couvrent la collecte, la lecture des feuilles, l'analyse, le chiffrement, la
reprise d'état et la page publiée ouverte en fichier local. Ce dernier test ouvre le Chrome
installé sur le poste (`HBPSM_NAVIGATEUR=chromium` pour le Chromium de Playwright, après
`playwright install chromium`). `python -m pipeline.demo_data` crée des données fictives pour un aperçu.

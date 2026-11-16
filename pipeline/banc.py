"""Le banc d'essai des pronostics (demande de l'auteur, 16/11/2026 : mesurer avant d'améliorer).

Les matchs : chaque match des poules lues en entier (notre division la saison passée, nos deux poules cette saison)
est rejoué avec ce qu'on savait la veille : les matchs déjà joués de sa poule et, cette saison, le point de départ
des équipes (saison passée, origine des joueurs). Même calcul que la page pour nos matchs : forces (analyze.forces),
incertitude sur ces forces (analyze.uncertainty), hasard du match (analyze.play_match), dont match_law donne la loi
sans tirage. Le pronostic (victoire de l'équipe qui reçoit, nul, écart) est mis en face du score et de deux repères
simples : « l'équipe qui reçoit gagne » (la part des victoires à domicile jusque-là, l'écart moyen) et un classement
Elo (K = 30, 40 points pour l'équipe qui reçoit, la saison passée reprise à moitié).

Les chances de l'objectif : sur chaque poule terminée (tous ses matchs aller et retour joués), après chaque journée,
les chances de chaque équipe de finir dans les `cible` premiers, simulées comme analyze.outlook, face à son rang
final ; repère : le classement du moment.

Scores : Brier (écart au carré entre la probabilité annoncée et ce qui est arrivé : 0 parfait, 0,25 pour un pile ou
face), log-loss (punit les certitudes démenties), vainqueur trouvé, erreur moyenne sur l'écart, dispersion (l'écart
type annoncé du score face à celui observé), nuls annoncés et observés, tranches (quand on annonce 60 à 80 %,
combien de fois c'est arrivé).

Les variantes (demande de l'auteur, 16/11/2026, après la première lecture du banc : le modèle est trop sûr de lui) :
les mêmes matchs rejoués avec d'autres réglages de l'incertitude sur la force des équipes (au départ, et sa forme :
analyze.uncertainty) et du hasard du match (analyze.play_match, BRUIT), face au réglage en service. L'écart de log-loss
de chaque variante vient avec sa marge à 95 % (match par match, sur les mêmes matchs) : un réglage ne change que si une
variante fait mieux au-delà de la marge, sans dégrader cette saison ni les chances de l'objectif.

Rien que des chiffres d'ensemble, ni nom de joueur ni nom d'équipe : D.banc, que l'entraîneur voit dans l'onglet
Saison. Limites : l'avantage du terrain vient de pronostic.calibrate, appris sur toutes les saisons lues (deux
nombres sur plus de 1 000 matchs) ; le point de départ de cette saison suit les joueurs vus sur toutes ses feuilles
déjà lues, même après le match rejoué.
"""
import math
import random
import statistics
from collections import Counter, defaultdict
from statistics import NormalDist

from . import analyze as an

V = 2
ELO_DEPART, ELO_K, ELO_DOM, ELO_REPRISE = 1500, 30, 40, 0.5
NUL_DEPART = 0.04          # part des nuls avant d'en avoir vu (handball : rares)
SIMS = 300                 # saisons simulées par journée rejouée (chances de l'objectif)
SEED = 38160
TRANCHES = (0.2, 0.4, 0.6, 0.8)
PAR_MATCHS = ((0, 2, "0 à 2"), (3, 5, "3 à 5"), (6, 99, "6 et plus"))   # matchs déjà joués par la moins vue des deux
PHI = NormalDist().cdf
# les variantes : incertitude de départ et sa forme (« actuelle » : la même au départ quel que soit le point de départ ;
# « racine » : plus étroite quand on en sait plus), puis le hasard du match
BASES = ((0.08, "actuelle"), (0.12, "actuelle"), (0.16, "actuelle"), (0.20, "racine"), (0.30, "racine"))
BRUITS = (1.0, 1.15, 1.3)
CHANCES_VARIANTES = 3      # les chances de l'objectif : rejouées pour le réglage en service et les 3 meilleures variantes


def variantes():
    """Le réglage en service d'abord, puis la grille des autres (sans le répéter)."""
    cur = (an.UNSURE, an.INCERTITUDE, an.BRUIT)
    out = [dict(nom="en service", base=cur[0], forme=cur[1], bruit=cur[2])]
    for base, forme in BASES:
        for b in BRUITS:
            if (base, forme, b) != cur:
                out.append(dict(nom=f"{forme} {base:g} · hasard ×{b:g}", base=base, forme=forme, bruit=b))
    return out


def match_law(avg, att, dfn, unsure, home, away, dom_f, ext_f, bruit=None):
    """La loi de l'écart (domicile − extérieur) que donne la simulation : forces tirées autour de leur valeur
    (analyze.draw_strengths : l'attaque de l'un et la défense de l'autre, l'une sans l'autre), buts de chaque équipe
    selon une loi normale d'écart type BRUIT × √(moyenne), arrondis (analyze.play_match). Approchée par une loi
    normale : (écart des forces centrales, écart moyen, écart type, P(victoire de l'équipe qui reçoit), P(nul))."""
    b2 = (an.BRUIT if bruit is None else bruit) ** 2
    mh = avg * att[home] * dfn[away] * dom_f
    ma = avg * att[away] * dfn[home] * ext_f
    s2 = unsure[home] ** 2 + unsure[away] ** 2
    grow, spread = math.exp(s2 / 2), math.exp(2 * s2) - math.exp(s2)
    mu = (mh - ma) * grow
    sd = math.sqrt(b2 * (mh + ma) * grow + (mh * mh + ma * ma) * spread + 2 / 12)
    lo, hi = PHI((-0.5 - mu) / sd), PHI((0.5 - mu) / sd)
    return mh - ma, mu, sd, 1 - hi, hi - lo


def groups_of(matches):
    """{(saison, poule): matchs dans l'ordre} ; seuls les matchs joués, aux deux noms connus."""
    out = defaultdict(list)
    for m in matches:
        if m["home"].get("score") is None or m["away"].get("score") is None:
            continue
        out[(m.get("saison") or "", str(m.get("poule")))].append(m)
    for ms in out.values():
        ms.sort(key=lambda m: (m.get("date") or "", str(m.get("id"))))
    return out


def names(m):
    return m["home"]["name"], m["away"]["name"], m["home"]["score"], m["away"]["score"]


def replay(groups, priors_of, terrain, elo_start=None, seen=None, variants=None):
    """Rejoue chaque match de chaque poule avec ce qu'on savait la veille. groups : [(clé, matchs)], dans l'ordre des
    saisons ; priors_of(clé) : point de départ des équipes (None : la moyenne de la poule). seen : ce que les repères
    ont déjà vu (victoires à domicile, nuls, écarts), cumulé d'une saison à l'autre ; variants : les réglages essayés
    (le premier fait le pronostic de la ligne ; chacun dans v : P(victoire), P(nul), écart moyen, écart type).
    Renvoie (lignes, Elo final)."""
    dom_f, ext_f = terrain
    variants = variants or variantes()[:1]
    seen = seen if seen is not None else Counter()
    rows, elo_end = [], {}
    for key, ms in groups:
        teams = sorted({m["home"]["name"] for m in ms} | {m["away"]["name"] for m in ms})
        start = elo_start or {}
        elo = {t: ELO_DEPART + ELO_REPRISE * (start[t] - ELO_DEPART) if t in start else ELO_DEPART for t in teams}
        days = defaultdict(list)
        for m in ms:
            days[(m.get("date") or "")[:10]].append(m)
        before, priors = [], priors_of(key)
        for day in sorted(days):
            if before:   # la première journée : aucun match de la poule encore, pas de pronostic
                table = {r["equipe"]: r for r in an.standings(before, teams)}
                avg, att, dfn, k_of = an.forces(table, priors)
                unsures = [an.uncertainty(table, k_of, x["base"], x["forme"]) for x in variants]
                p_dom = seen["dom"] / seen["n"] if seen["n"] else 0.5
                nul = seen["nul"] / seen["n"] if seen["n"] else NUL_DEPART
                marge_dom = seen["marge"] / seen["n"] if seen["n"] else 0.0
                for m in days[day]:
                    h, a, gh, ga = names(m)
                    laws = [match_law(avg, att, dfn, u, h, a, dom_f, ext_f, x["bruit"]) for u, x in zip(unsures, variants)]
                    ecart, mu, sd, pw, pd = laws[0]
                    e = 1 / (1 + 10 ** (-(elo[h] + ELO_DOM - elo[a]) / 400))
                    rows.append(dict(cle=key, y=gh > ga, nul=gh == ga, marge=gh - ga, p=pw, pnul=pd, ecart=ecart, mu=mu,
                                     sd=sd, elo=min(0.99, max(0.01, e - nul / 2)), dom=p_dom, marge_dom=marge_dom,
                                     vus=min(table[h]["j"], table[a]["j"]),
                                     v=[(law[3], law[4], law[1], law[2]) for law in laws]))
            for m in days[day]:
                h, a, gh, ga = names(m)
                e = 1 / (1 + 10 ** (-(elo[h] + ELO_DOM - elo[a]) / 400))
                s = 1.0 if gh > ga else 0.5 if gh == ga else 0.0
                elo[h] += ELO_K * (s - e)
                elo[a] -= ELO_K * (s - e)
                seen.update(n=1, dom=int(gh > ga), nul=int(gh == ga))
                seen["marge"] += gh - ga
            before += days[day]
        elo_end.update(elo)
    return rows, elo_end


def season_replay(groups, terrain, target, sims=SIMS, seed=SEED, variant=None):
    """Les chances de l'objectif rejouées sur les poules terminées : après chaque journée (sauf la dernière), la part
    des saisons simulées où chaque équipe finit dans les target premiers, face à son rang final (analyze.rank_teams).
    variant : le réglage essayé (celui en service sans)."""
    dom_f, ext_f = terrain
    x = variant or variantes()[0]
    rng, rows = random.Random(seed), []
    for key, ms in groups:
        teams = sorted({m["home"]["name"] for m in ms} | {m["away"]["name"] for m in ms})
        played_by = Counter(t for m in ms for t in (m["home"]["name"], m["away"]["name"]))
        # poule finie : chacun a joué autant que les autres, au moins une fois contre chacun (aller seul ou aller-retour)
        if len(teams) <= target + 1 or len(set(played_by.values())) != 1 or min(played_by.values()) < len(teams) - 1:
            continue
        final = an.rank_teams(teams, [names(m) for m in ms])
        top = set(final[:target])
        rounds = sorted({(m.get("date") or "")[:10] for m in ms})
        journees = sorted({m.get("journee") for m in ms if m.get("journee") is not None})
        if len(journees) >= 2 and all(m.get("journee") is not None for m in ms):
            steps = [(j, lambda m, j=j: m["journee"] <= j) for j in journees[:-1]]
        else:   # sans numéro de journée : jour par jour
            steps = [(d, lambda m, d=d: (m.get("date") or "")[:10] <= d) for d in rounds[:-1]]
        for i, (_, done) in enumerate(steps):
            played = [m for m in ms if done(m)]
            rest = [m for m in ms if not done(m)]
            if not played or not rest:
                continue
            table = {r["equipe"]: r for r in an.standings(played, teams)}
            avg, att0, dfn0, k_of = an.forces(table, None)
            unsure = an.uncertainty(table, k_of, x["base"], x["forme"])
            att, dfn, count = dict(att0), dict(dfn0), Counter()
            already = [names(m) for m in played]
            for _ in range(sims):
                an.draw_strengths(rng, att0, dfn0, unsure, att, dfn)
                sim = list(already)
                for m in rest:
                    h, a = m["home"]["name"], m["away"]["name"]
                    sim.append((h, a) + an.play_match(rng, avg, att, dfn, h, a, dom_f, ext_f, x["bruit"]))
                draw = {t: rng.random() for t in teams}
                for t in an.rank_teams(teams, sim, draw.get)[:target]:
                    count[t] += 1
            moment = (i + 1) / (len(steps) + 1)   # part de la saison jouée
            for t in teams:
                rows.append(dict(p=count[t] / sims, y=t in top, ici=table[t]["rang"] <= target, moment=moment))
    return rows


def _mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else None


def _r(x, n=3):
    return None if x is None else round(x, n)


def brier(rows, key):
    return _r(_mean((r[key] - r["y"]) ** 2 for r in rows))


def logloss(rows, key):
    clip = lambda p: min(0.99, max(0.01, p))
    return _r(_mean(-math.log(clip(r[key])) if r["y"] else -math.log(1 - clip(r[key])) for r in rows))


def found(rows, key):
    """Vainqueur trouvé, en % des matchs sans nul : le favori annoncé a gagné."""
    decided = [r for r in rows if not r["nul"]]
    return round(100 * _mean((r[key] > 0.5) == r["y"] for r in decided)) if decided else None


def tranches(rows, key="p"):
    out, edges = [], (0.0,) + TRANCHES + (1.01,)
    for lo, hi in zip(edges, edges[1:]):
        part = [r for r in rows if lo <= r[key] < hi]
        if part:
            out.append(dict(de=round(100 * lo), a=min(100, round(100 * hi)), n=len(part),
                            annonce=round(100 * _mean(r[key] for r in part)), observe=round(100 * _mean(r["y"] for r in part))))
    return out


def match_scores(rows):
    """Les chiffres d'ensemble d'une série de matchs rejoués ; None sans match."""
    if not rows:
        return None
    z = [(r["marge"] - r["mu"]) / r["sd"] for r in rows]
    return dict(
        n=len(rows), nuls=sum(r["nul"] for r in rows), nuls_annonces=round(sum(r["pnul"] for r in rows), 1),
        modele=dict(brier=brier(rows, "p"), logloss=logloss(rows, "p"), vainqueur=found(rows, "p"),
                    erreur=round(_mean(abs(r["marge"] - r["ecart"]) for r in rows), 1)),
        elo=dict(brier=brier(rows, "elo"), logloss=logloss(rows, "elo"), vainqueur=found(rows, "elo")),
        domicile=dict(brier=brier(rows, "dom"), logloss=logloss(rows, "dom"), vainqueur=found(rows, "dom"),
                      erreur=round(_mean(abs(r["marge"] - r["marge_dom"]) for r in rows), 1)),
        dispersion=dict(annoncee=round(_mean(r["sd"] for r in rows), 1),
                        observee=round(math.sqrt(_mean((r["marge"] - r["mu"]) ** 2 for r in rows)), 1),
                        z2=round(_mean(x * x for x in z), 2)),
        tranches=tranches(rows),
        par_matchs=[dict(matchs=label, n=len(part), modele=brier(part, "p"), elo=brier(part, "elo"),
                         z2=round(_mean(((r["marge"] - r["mu"]) / r["sd"]) ** 2 for r in part), 2))
                    for lo, hi, label in PAR_MATCHS for part in [[r for r in rows if lo <= r["vus"] <= hi]] if part])


def season_scores(rows):
    if not rows:
        return None
    third = lambda lo, hi: [r for r in rows if lo <= r["moment"] < hi]
    return dict(n=len(rows), brier=brier(rows, "p"), logloss=logloss(rows, "p"),
                moment=_r(_mean((float(r["ici"]) - r["y"]) ** 2 for r in rows)),
                par_moment=[dict(moment=label, n=len(part), brier=brier(part, "p"),
                                 classement=_r(_mean((float(r["ici"]) - r["y"]) ** 2 for r in part)))
                            for lo, hi, label in ((0, 1 / 3, "début"), (1 / 3, 2 / 3, "milieu"), (2 / 3, 1.01, "fin"))
                            for part in [third(lo, hi)] if part],
                tranches=tranches(rows))


def variant_scores(rows, i):
    """Les scores de la variante i sur des matchs rejoués (log-loss, Brier, dispersion z², nuls annoncés) ; pour une
    autre que celle en service, son écart de log-loss match par match (négatif : mieux) et la marge à 95 % de cet
    écart."""
    if not rows:
        return None
    clip = lambda p: min(0.99, max(0.01, p))
    ll = lambda r, j: -math.log(clip(r["v"][j][0])) if r["y"] else -math.log(1 - clip(r["v"][j][0]))
    out = dict(n=len(rows), logloss=_r(_mean(ll(r, i) for r in rows)), brier=_r(_mean((r["v"][i][0] - r["y"]) ** 2 for r in rows)),
               z2=round(_mean(((r["marge"] - r["v"][i][2]) / r["v"][i][3]) ** 2 for r in rows), 2),
               nuls_annonces=round(sum(r["v"][i][1] for r in rows), 1))
    if i:
        d = [ll(r, i) - ll(r, 0) for r in rows]
        sd = statistics.stdev(d) if len(d) > 1 else 0.0
        out.update(ecart=_r(_mean(d)), marge=_r(1.96 * sd / math.sqrt(len(d))))
    return out


def evaluate(seasons, current, priors, terrain, target):
    """seasons : les saisons passées de notre division lues en entier (load_history, sans niveau ni catégorie) ;
    current : les matchs de championnat de cette saison (nos poules) ; priors : leur point de départ
    (analyze.history_profiles) ; terrain : (dom, ext) ; target : le rang visé. Renvoie D.banc, ou None sans match
    à rejouer."""
    past = [(k, ms) for x in seasons for k, ms in sorted(groups_of(x.get("matches") or []).items())]
    now = sorted(groups_of(current).items())
    seen, vs = Counter(), variantes()
    rows_past, elo = replay(past, lambda k: None, terrain, seen=seen, variants=vs)
    rows_now, _ = replay(now, lambda k: priors, terrain, elo_start=elo, seen=seen, variants=vs)
    if not rows_past and not rows_now:
        return None
    # les variantes, la meilleure d'abord (log-loss sur tous les matchs rejoués) ; les chances de l'objectif pour le
    # réglage en service et les meilleures
    table = [dict(x, passees=variant_scores(rows_past, i), saison=variant_scores(rows_now, i),
                  toutes=variant_scores(rows_past + rows_now, i), chances=None) for i, x in enumerate(vs)]
    order = sorted(range(len(vs)), key=lambda i: (table[i]["toutes"]["logloss"], i))
    chances = None
    for i in [0] + [j for j in order if j][:CHANCES_VARIANTES]:
        sc = season_scores(season_replay(past, terrain, target, variant=vs[i]))
        if i == 0:
            chances = sc
        table[i]["chances"] = sc and dict(n=sc["n"], brier=sc["brier"], logloss=sc["logloss"])
    return dict(v=V, cible=target, terrain=[round(terrain[0], 3), round(terrain[1], 3)], incertitude=an.UNSURE,
                reglage=dict(base=an.UNSURE, forme=an.INCERTITUDE, bruit=an.BRUIT),
                saisons=sorted({k[0] for k, _ in past if k[0]}), poules=len(past),
                passees=match_scores(rows_past), saison=match_scores(rows_now),
                toutes=match_scores(rows_past + rows_now), chances=chances,
                variantes=[table[i] for i in order], meilleure=table[order[0]]["nom"])

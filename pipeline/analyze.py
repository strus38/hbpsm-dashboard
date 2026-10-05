"""Calcule classements, profils d'équipes, notes des joueurs et associations.

Entrées : data/matches/*.json, data/fixtures.json, roster.csv, config.yml
Sortie  : dictionnaire prêt pour le tableau de bord (docs/data.json).
"""
import csv
import hashlib
import json
import itertools
import math
import random
import re
import statistics
from collections import Counter, defaultdict

from .common import (DATA, ROOT, is_club, load_config, load_matches, match_name, name_key,
                     norm, paris_now, read_json, same_team, write_json)
from . import caisse
from .parse_fdme import split_name

POINTS = {"V": 3, "N": 2, "D": 1}  # barème FFHB
PLANS = {
    "equilibre": dict(att=.30, eff=.15, disc=.15, imp=.20, clutch=.10, assid=.10),
    "attaque": dict(att=.40, eff=.20, disc=.05, imp=.15, clutch=.10, assid=.10),
    "rigueur": dict(att=.20, eff=.10, disc=.30, imp=.25, clutch=.05, assid=.10),
}
DECAY = 0.7  # poids d'un match par rapport au suivant, pour la forme récente


def outcome(gf, ga):
    return "V" if gf > ga else "D" if gf < ga else "N"


def sides(match):
    """Renvoie [(côté, équipe, adversaire, bp, bc)] pour un match joué."""
    h, a = match["home"], match["away"]
    return [("home", h["name"], a["name"], h["score"], a["score"]),
            ("away", a["name"], h["name"], a["score"], h["score"])]


def keepers_conceded(match, side):
    """Buts pris par chaque gardien d'une équipe sur un match : ({numéro: buts}, estimé ?).

    La feuille donne les arrêts de chaque gardien, pas ses buts pris. L'ancienne feuille (2025-2026)
    dit qui entre et sort des buts : le but est pour le gardien en place (exact), pour aucun si le
    gardien était sorti (jeu à 7). Sinon, un seul
    gardien a fait des arrêts : il prend tous les buts ; plusieurs : un but est
    pour le gardien du dernier arrêt de la même mi-temps, à défaut du prochain arrêt de cette
    mi-temps, sinon de l'arrêt le plus proche. Sans déroulé, plusieurs gardiens : inconnu ({})."""
    other = "away" if side == "home" else "home"
    keepers = [p for p in (match.get("players") or {}).get(side, []) if p.get("saves")]
    against = match[other].get("score")
    if not keepers or against is None:
        return {}, False
    if len(keepers) == 1:
        return {keepers[0]["num"]: against}, False
    events = match.get("events") or []
    saves = [e for e in events if e["type"] == "save" and e["side"] == side and e.get("num") is not None]
    goals = [e for e in events if e["type"] in ("goal", "pen_goal") and e["side"] == other]
    changes = [e for e in events if e["type"] in ("gk_in", "gk_out") and e["side"] == side and e.get("num") is not None]
    if not goals or not (saves or changes):
        return {}, True
    half = lambda t: t > 1800
    out = {p["num"]: 0 for p in keepers}
    exact = bool(changes)
    for g in goals:
        if changes:  # l'ancienne feuille dit qui entre et sort des buts : le gardien en place
            on, known = None, False
            for e in changes:
                if e["t"] > g["t"]:
                    break
                known = True
                on = e["num"] if e["type"] == "gk_in" else (None if on == e["num"] else on)
            if on is not None:
                out[on] = out.get(on, 0) + 1
                continue
            if known:  # gardien sorti (jeu à 7) : but dans le but vide, pour aucun gardien
                continue
            exact = False
        if not saves:
            continue
        same = [s for s in saves if half(s["t"]) == half(g["t"])]
        before = [s for s in same if s["t"] <= g["t"]]
        after = [s for s in same if s["t"] > g["t"]]
        pick = before[-1] if before else after[0] if after else min(saves, key=lambda s: abs(s["t"] - g["t"]))
        out[pick["num"]] = out.get(pick["num"], 0) + 1
    return out, not exact


def save_pct(saves, conceded):
    """Pourcentage d'arrêts sur les tirs cadrés subis (arrêts + buts pris), arrondi."""
    return round(100 * saves / (saves + conceded)) if saves + conceded else None


def official_table(official, column=("PTS", "POINTS", "PT")):
    """Lit le classement affiché par la fédération : {équipe: valeur de la colonne}, au mieux."""
    if not official or not official.get("lignes"):
        return {}
    head = [norm(c) for c in official.get("entetes") or []]
    col = next((i for i, h in enumerate(head) if h in column), None)
    out = {}
    for row in official["lignes"]:
        cells = [str(c).strip() for c in row]
        names = [c for c in cells if len(re.findall(r"[A-Za-zÀ-ÿ]", c)) >= 3]
        if not names:
            continue
        name = re.sub(r"^\d+\s+", "", max(names, key=len))
        pts = None
        if col is not None and col < len(cells) and re.fullmatch(r"-?\d+", cells[col]):
            pts = int(cells[col])
        out[name] = pts
    return out


def known_teams(fixtures, officials):
    """Équipes de chaque poule, d'après le calendrier et le classement officiel."""
    teams = defaultdict(set)
    for f in fixtures:
        for side in ("home", "away"):
            if f.get(side):
                teams[str(f.get("poule"))].add(f[side])
    for poule, official in (officials or {}).items():
        seen = {norm(t) for t in teams[str(poule)]}
        for name in official_table(official):
            if norm(name) not in seen:
                teams[str(poule)].add(name)
    return teams


def rank_teams(teams, results, last=None):
    """Ordre de classement selon le règlement (Ligue AURA 2026-2027, règlements généraux FFHB 3.3) :
    points ; entre équipes à égalité, points puis différence de buts des confrontations directes,
    répétés tant qu'il reste des égalités ; puis différence de buts générale, buts marqués.
    results : [(domicile, extérieur, buts domicile, buts extérieur)] ; last : départage final
    (le nom, ou un tirage dans les simulations). Non pris en compte : buts à l'extérieur dans les
    confrontations directes, nombre de licenciés."""
    pts, diff, bp = defaultdict(int), defaultdict(int), defaultdict(int)
    for h, a, gh, ga in results:
        pts[h] += POINTS[outcome(gh, ga)]
        pts[a] += POINTS[outcome(ga, gh)]
        diff[h] += gh - ga
        diff[a] += ga - gh
        bp[h] += gh
        bp[a] += ga
    last = last or (lambda t: t)

    def split(group):
        if len(group) < 2:
            return list(group)
        inside = set(group)
        hp, hd = defaultdict(int), defaultdict(int)
        for h, a, gh, ga in results:
            if h in inside and a in inside:
                hp[h] += POINTS[outcome(gh, ga)]
                hp[a] += POINTS[outcome(ga, gh)]
                hd[h] += gh - ga
                hd[a] += ga - gh
        out = []
        for _, sub in itertools.groupby(sorted(group, key=lambda t: (-hp[t], -hd[t])), key=lambda t: (hp[t], hd[t])):
            sub = list(sub)
            if 1 < len(sub) < len(group):
                out += split(sub)  # la règle reprend entre les seules équipes encore à égalité
            else:
                out += sorted(sub, key=lambda t: (-diff[t], -bp[t], last(t)))
        return out

    order = []
    for _, group in itertools.groupby(sorted(teams, key=lambda t: -pts[t]), key=lambda t: pts[t]):
        order += split(list(group))
    return order


def standings(matches, teams=()):
    table = {t: dict(equipe=t, pts=0, j=0, v=0, n=0, d=0, bp=0, bc=0, forme=[]) for t in teams}
    for m in sorted(matches, key=lambda x: x.get("date") or ""):
        for _, team, _, gf, ga in sides(m):
            row = table.setdefault(team, dict(equipe=team, pts=0, j=0, v=0, n=0,
                                              d=0, bp=0, bc=0, forme=[]))
            res = outcome(gf, ga)
            row["pts"] += POINTS[res]
            row["j"] += 1
            row[res.lower()] += 1
            row["bp"] += gf
            row["bc"] += ga
            row["forme"].append(res)
    for r in table.values():
        r["diff"] = r["bp"] - r["bc"]
        r["forme"] = r["forme"][-5:]
    results = [(m["home"]["name"], m["away"]["name"], m["home"]["score"], m["away"]["score"]) for m in matches]
    rows = [table[t] for t in rank_teams(list(table), results)]
    for i, r in enumerate(rows, 1):
        r["rang"] = i
    return rows


def team_profiles(matches, teams_by_poule=None):
    """Profil de chaque équipe des deux poules (repérage des adversaires)."""
    acc = defaultdict(lambda: dict(matches=[], scorers=defaultdict(
        lambda: dict(buts=0, pen=0, m=0, num=None, tirs=0, tirs_buts=0)), jaunes=0, deux_min=0, rouges=0,
        keepers=defaultdict(lambda: dict(arrets=0, pris=0, cadres=0, m=0, estime=False)),
        arrets=0, pris=0, periods_for=[0] * 6, periods_against=[0] * 6, has_events=0))
    for m in sorted(matches, key=lambda x: x.get("date") or ""):
        for side, team, opp, gf, ga in sides(m):
            a = acc[team]
            ht_f = m[side].get("ht")
            other = "away" if side == "home" else "home"
            ht_a = m[other].get("ht")
            a["poule"] = m.get("poule")
            a["sheets"] = a.get("sheets", 0) + (1 if m.get("players", {}).get(side) else 0)
            a["matches"].append(dict(id=m["id"], date=m.get("date"), adv=opp,
                                     dom=side == "home", bp=gf, bc=ga,
                                     res=outcome(gf, ga), mt_bp=ht_f, mt_bc=ht_a))
            conceded, estimated = keepers_conceded(m, side)
            for p in m.get("players", {}).get(side, []):
                key = norm(p.get("name")) or f"N{p.get('num')}"
                s = a["scorers"][key]
                s["nom"] = p.get("name") or f"n° {p.get('num')}"
                s["num"] = p.get("num")
                s["buts"] += p.get("goals") or 0
                s["pen"] += p.get("pen_goals") or 0
                s["m"] += 1
                if p.get("shots"):
                    s["tirs"] += p["shots"]
                    s["tirs_buts"] += p.get("goals") or 0
                a["jaunes"] += p.get("yellow") or 0
                a["deux_min"] += p.get("two_min") or 0
                a["rouges"] += p.get("red") or 0
                if p.get("saves"):
                    k = a["keepers"][key]
                    k["nom"], k["num"] = s["nom"], p.get("num")
                    k["arrets"] += p["saves"]
                    k["m"] += 1
                    if p.get("num") in conceded:
                        k["pris"] += conceded[p["num"]]
                        k["cadres"] += p["saves"] + conceded[p["num"]]
                        k["estime"] = k["estime"] or estimated
            if conceded:  # pourcentage de l'équipe : seulement les matchs où les buts pris sont répartis
                a["arrets"] += sum(p.get("saves") or 0 for p in m["players"][side])
                a["pris"] += sum(conceded.values())
            if m.get("events"):
                a["has_events"] += 1
                for e in m["events"]:
                    if e["type"] in ("goal", "pen_goal"):
                        k = min(5, int(e["t"] // 600))
                        if e["side"] == side:
                            a["periods_for"][k] += 1
                        else:
                            a["periods_against"][k] += 1
    out = {}
    for team, a in acc.items():
        n = len(a["matches"])
        gf = sum(x["bp"] for x in a["matches"])
        ga = sum(x["bc"] for x in a["matches"])
        halves = [x for x in a["matches"] if x["mt_bp"] is not None]
        scorers = sorted(a["scorers"].values(), key=lambda s: -s["buts"])[:5]
        out[team] = dict(
            equipe=team, poule=a.get("poule"), j=n,
            bp_moy=round(gf / n, 1), bc_moy=round(ga / n, 1),
            forme=[x["res"] for x in a["matches"]][-5:],
            matches=a["matches"],
            mt1_bp=round(sum(x["mt_bp"] for x in halves) / len(halves), 1) if halves else None,
            mt2_bp=round(sum(x["bp"] - x["mt_bp"] for x in halves) / len(halves), 1) if halves else None,
            mt1_bc=round(sum(x["mt_bc"] for x in halves) / len(halves), 1) if halves else None,
            mt2_bc=round(sum(x["bc"] - x["mt_bc"] for x in halves) / len(halves), 1) if halves else None,
            # trois sanctions distinctes : avertissement (jaune), 2 minutes, disqualification (rouge)
            jaunes_moy=round(a["jaunes"] / a["sheets"], 1) if a.get("sheets") else None,
            deux_min_moy=round(a["deux_min"] / a["sheets"], 1) if a.get("sheets") else None,
            rouges=a["rouges"] if a.get("sheets") else None,
            buteurs=[dict(nom=s["nom"], num=s["num"], buts=s["buts"], pen=s["pen"],
                          moy=round(s["buts"] / max(1, s["m"]), 1), m=s["m"], tirs=s["tirs"] or None,
                          reussite=round(100 * s["tirs_buts"] / s["tirs"]) if s["tirs"] else None)
                     for s in scorers if s["buts"] > 0],
            arrets_pct=save_pct(a["arrets"], a["pris"]),
            gardiens=sorted((dict(nom=k["nom"], num=k["num"], m=k["m"], arrets=k["arrets"],
                                  pris=k["pris"] if k["cadres"] else None,
                                  pct=save_pct(k["cadres"] - k["pris"], k["pris"]) if k["cadres"] else None,
                                  estime=k["estime"])
                             for k in a["keepers"].values()), key=lambda k: (-k["m"], -k["arrets"])),
            periodes_bp=[round(x / a["has_events"], 1) for x in a["periods_for"]] if a["has_events"] else None,
            periodes_bc=[round(x / a["has_events"], 1) for x in a["periods_against"]] if a["has_events"] else None,
        )
    for poule, teams in (teams_by_poule or {}).items():
        for team in teams:
            out.setdefault(team, dict(
                equipe=team, poule=poule, j=0, bp_moy=None, bc_moy=None, forme=[], matches=[],
                mt1_bp=None, mt2_bp=None, mt1_bc=None, mt2_bc=None, jaunes_moy=None, deux_min_moy=None,
                rouges=None, buteurs=[], arrets_pct=None, gardiens=[], passe=None,
                periodes_bp=None, periodes_bc=None))
    return out


def load_history():
    """Saisons passées collectées par pipeline.history, de la plus ancienne à la plus récente ; seuls
    les matchs joués, avec leurs deux équipes et leur score, sont gardés."""
    ok = lambda m: all((m.get(side) or {}).get("name") and (m.get(side) or {}).get("score") is not None
                       for side in ("home", "away"))
    seasons = []
    for path in sorted((DATA / "historique").glob("*.json")):
        season = read_json(path)
        season["matches"] = [m for m in season.get("matches") or [] if ok(m)]
        for m in season["matches"]:  # noms lus avant la correction du découpage : remis d'aplomb ici
            for pl in (m.get("players") or {}).get("home", []) + (m.get("players") or {}).get("away", []):
                pl["name"] = split_name(pl.get("name"))
        seasons.append(season)
    return seasons


def past_players(mine, now, matches, team):
    """Les joueurs d'une équipe la saison passée, d'après ses feuilles : matchs, buts, tirs, arrêts
    et buts pris des gardiens, sanctions ; present dit s'il figure sur une feuille de cette saison
    (None tant qu'aucune n'est lue), num_now son numéro d'aujourd'hui. Gardien : plus d'arrêts que
    de buts (un joueur de champ crédité d'un arrêt reste joueur de champ). Revus d'abord, puis
    les meilleurs."""
    num_now = {name_key(pl["name"]): pl.get("num") for m in matches for side in ("home", "away")
               if m[side]["name"] == team for pl in (m.get("players") or {}).get(side, [])}
    acc = {}
    for m, side in mine:
        plist = (m.get("players") or {}).get(side, [])
        conceded, estimated = keepers_conceded(m, side) if plist else ({}, False)
        for pl in plist:
            s = acc.setdefault(name_key(pl["name"]), dict(
                nom=pl["name"], nums=Counter(), m=0, buts=0, pen=0, tirs=0, tirs_buts=0, arrets=0,
                pris=0, cadres=0, estime=False, deux_min=0, jaunes=0, rouges=0))
            s["m"] += 1
            if pl.get("num") is not None:
                s["nums"][pl["num"]] += 1
            s["buts"] += pl.get("goals") or 0
            s["pen"] += pl.get("pen_goals") or 0
            if pl.get("shots"):
                s["tirs"] += pl["shots"]
                s["tirs_buts"] += pl.get("goals") or 0
            s["arrets"] += pl.get("saves") or 0
            if pl.get("saves") and pl.get("num") in conceded:
                s["pris"] += conceded[pl["num"]]
                s["cadres"] += pl["saves"] + conceded[pl["num"]]
                s["estime"] = s["estime"] or estimated
            s["deux_min"] += pl.get("two_min") or 0
            s["jaunes"] += pl.get("yellow") or 0
            s["rouges"] += pl.get("red") or 0
    out = []
    for k, s in acc.items():
        out.append(dict(
            nom=s["nom"], num=s["nums"].most_common(1)[0][0] if s["nums"] else None, m=s["m"],
            gardien=s["arrets"] > s["buts"], buts=s["buts"], pen=s["pen"], moy=round(s["buts"] / s["m"], 1),
            tirs=s["tirs"] or None, reussite=round(100 * s["tirs_buts"] / s["tirs"]) if s["tirs"] else None,
            arrets=s["arrets"], pris=s["pris"] if s["cadres"] else None,
            pct=save_pct(s["cadres"] - s["pris"], s["pris"]) if s["cadres"] else None, estime=s["estime"],
            deux_min=s["deux_min"], jaunes=s["jaunes"], rouges=s["rouges"],
            present=(k in now) if now else None, num_now=num_now.get(k)))
    out.sort(key=lambda j: (j["present"] is not True, -(j["arrets"] if j["gardien"] else j["buts"]), -j["m"]))
    return out


ECART = 0.12  # écart de force entre deux divisions voisines, si config.yml ne le donne pas


def division_label(competition):
    """« …/1ere-division-masculine-… » -> « 1re division »."""
    m = re.search(r"/(\d+)(?:ere|eme)-division", competition or "")
    return f"{m.group(1)}{'re' if m.group(1) == '1' else 'e'} division" if m else None


def history_profiles(seasons, profiles, matches, config, above=(), rosters=None):
    """Ce que la saison passée dit des équipes d'aujourd'hui : bilan et classement, confrontations
    avec le club, part de l'effectif de cette saison déjà là, devenir des meilleurs buteurs, et
    chaque joueur de la saison passée avec ses chiffres et s'il est revu cette saison.
    above : la même saison dans la division du dessus (niveau 1) ; une équipe qui y jouait compte
    plus forte de l'écart de division, d'autant plus qu'elle a gardé ses joueurs.
    rosters : les matchs de cette saison dont les feuilles disent qui joue où (championnat, coupe,
    poules des adversaires de coupe) ; matches par défaut.
    Renvoie aussi, pour la simulation, la force relative de chaque équipe et sa continuité : d'après
    l'équipe où chacun de ses joueurs d'aujourd'hui jouait la saison passée, tous clubs et toutes
    divisions confondus (une nouvelle équipe, une nouvelle entente réunit des joueurs d'autres
    clubs : notre division est la plus basse, personne n'en monte), sinon d'après son nom."""
    rosters = matches if rosters is None else rosters
    priors = {}
    same = lambda a, b: same_team(a, b) or (is_club(a, config) and is_club(b, config))
    gap = 1 + float(config.get("ecart_division", ECART))
    for prof in profiles.values():
        prof.setdefault("passe", None)
        prof.setdefault("dessus", None)
    latest = seasons[-1:]  # la saison la plus récente
    year = latest[0].get("saison") if latest else None
    levels = [(s, 0) for s in latest] + [(s, int(s.get("niveau") or 1)) for s in above
                                         if year is None or s.get("saison") == year]
    found = defaultdict(list)  # équipe -> [(niveau, bilan, force, joueurs)]
    for season, level in levels:
        played = season.get("matches") or []
        if not played:
            continue
        avg = sum(m["home"]["score"] + m["away"]["score"] for m in played) / (2 * len(played))
        for team, prof in profiles.items():
            mine = [(m, side) for m in played for side in ("home", "away") if same(m[side]["name"], team)]
            if not mine:
                continue
            other = lambda side: "away" if side == "home" else "home"
            res = [outcome(m[side]["score"], m[other(side)]["score"]) for m, side in mine]
            bp = sum(m[side]["score"] for m, side in mine)
            bc = sum(m[other(side)]["score"] for m, side in mine)
            rangs = []
            for label, poule in (season.get("poules") or {}).items():
                for row in ((poule.get("classement") or {}).get("lignes") or []):
                    if same(row[1], team):
                        rangs.append(dict(poule=label, rang=int(row[0]) if str(row[0]).isdigit() else None,
                                          equipes=len(poule["classement"]["lignes"])))
            face = [dict(date=m.get("date"), phase=m.get("phase"), dom=side == "home",
                         score=f"{m[side]['score']}-{m[other(side)]['score']}",
                         res=outcome(m[side]["score"], m[other(side)]["score"]))
                    for m, side in mine if is_club(m[other(side)]["name"], config) and not is_club(team, config)]
            last = {name_key(pl["name"]) for m, side in mine for pl in (m.get("players") or {}).get(side, [])}
            now = {name_key(pl["name"]) for m in rosters for side in ("home", "away") if m[side]["name"] == team
                   for pl in (m.get("players") or {}).get(side, [])}
            scorers = Counter()
            names = {}
            for m, side in mine:
                for pl in (m.get("players") or {}).get(side, []):
                    scorers[name_key(pl["name"])] += pl.get("goals") or 0
                    names[name_key(pl["name"])] = (pl["name"], pl.get("num"))
            buteurs = [dict(nom=names[k][0], num=names[k][1], buts=b, present=(k in now) if now else None)
                       for k, b in scorers.most_common(3) if b]
            cont = dict(deja=len(now & last), sur=len(now)) if now and last else None
            rec = dict(saison=season["saison"], niveau=level, division=division_label(season.get("competition")),
                       j=len(mine), v=res.count("V"), n=res.count("N"), d=res.count("D"),
                       bp_moy=round(bp / len(mine), 1), bc_moy=round(bc / len(mine), 1),
                       rangs=rangs, face_a_face=face, continuite=cont, buteurs=buteurs,
                       feuilles=sum(1 for m, side in mine if (m.get("players") or {}).get(side)))
            # continuité inconnue (pas encore de feuille cette saison) : la saison passée compte à moitié
            c = cont["deja"] / cont["sur"] if cont else 0.5
            force = ((bp / len(mine)) / avg * gap ** level, (bc / len(mine)) / avg / gap ** level, c)
            found[team].append((level, rec, force, past_players(mine, now, matches, team)))
    for team, recs in found.items():
        prof = profiles[team]
        recs.sort(key=lambda r: r[0])  # notre division d'abord ; celle du dessus en complément
        level, rec, _, joueurs = recs[0]
        # les joueurs de cette saison déjà là la saison passée : leurs chiffres d'alors
        before = {name_key(j["nom"]): j for j in joueurs}
        for b in prof.get("buteurs") or []:
            j = before.get(name_key(b.get("nom") or ""))
            b["avant"] = j and dict(m=j["m"], buts=j["buts"], moy=j["moy"], reussite=j["reussite"])
        for g in prof.get("gardiens") or []:
            j = before.get(name_key(g.get("nom") or ""))
            g["avant"] = j and dict(m=j["m"], arrets=j["arrets"], pct=j["pct"])
        prof["passe"] = dict(rec, joueurs=joueurs)
        prof["dessus"] = recs[1][1] if len(recs) > 1 else None
        # deux bilans (les deux divisions) : chacun pèse selon la part de l'effectif qui y jouait
        w = [r[2][2] for r in recs]
        w = w if sum(w) else [1] * len(recs)
        priors[team] = (sum(wi * r[2][0] for wi, r in zip(w, recs)) / sum(w),
                        sum(wi * r[2][1] for wi, r in zip(w, recs)) / sum(w), max(r[2][2] for r in recs))
    # d'où viennent les joueurs de cette saison : l'équipe où chacun a le plus joué la saison passée
    played_by = defaultdict(Counter)  # joueur -> {(niveau, équipe): matchs}
    strength, division = {}, {}       # (niveau, équipe) -> (attaque, défense) relatives, écart compris
    for season, level in levels:
        played = season.get("matches") or []
        if not played:
            continue
        division[level] = division_label(season.get("competition"))
        avg = sum(m["home"]["score"] + m["away"]["score"] for m in played) / (2 * len(played))
        acc = defaultdict(lambda: [0, 0, 0])
        for m in played:
            for side, o in (("home", "away"), ("away", "home")):
                a = acc[m[side]["name"]]
                a[0], a[1], a[2] = a[0] + m[side]["score"], a[1] + m[o]["score"], a[2] + 1
                for pl in (m.get("players") or {}).get(side, []):
                    played_by[name_key(pl["name"])][(level, m[side]["name"])] += 1
        for t, (bp, bc, j) in acc.items():
            strength[(level, t)] = (bp / j / avg * gap ** level, bc / j / avg / gap ** level)
    for team, prof in profiles.items():
        now = {name_key(pl["name"]) for m in rosters for side in ("home", "away") if m[side]["name"] == team
               for pl in (m.get("players") or {}).get(side, [])}
        if not now or not played_by:
            continue
        origin = Counter(played_by[k].most_common(1)[0][0] for k in now if played_by.get(k))
        n = sum(origin.values())
        prof["origines"] = dict(saison=year, vus=len(now), retrouves=n,
                                equipes=[dict(equipe=t, niveau=lv, division=division.get(lv), joueurs=c)
                                         for (lv, t), c in origin.most_common(5)])
        if n:  # la force des équipes d'où ils viennent, à proportion des joueurs retrouvés
            priors[team] = (sum(c * strength[o][0] for o, c in origin.items()) / n,
                            sum(c * strength[o][1] for o, c in origin.items()) / n, n / len(now))
    return priors


def cup_chance(forces, avg, club, prof, level, gap, prior=None, home=True, sims=4000, seed=38160):
    """Chances de gagner un match de coupe contre une équipe d'une autre poule, ou d'une autre
    division (level : 1 = celle du dessus). Sa force se lit sur ses matchs, rapportés à ce qu'on
    marque dans sa poule, puis se décale de l'écart de division ; elle part de la moyenne de sa
    division, ou de sa saison passée d'autant plus que l'effectif est resté. Un nul se joue aux
    tirs au but : une chance sur deux."""
    if not forces or club not in forces or not avg:
        return None
    j = prof.get("j") or 0
    c = prior[2] if prior else 0.0
    k = 3 + 2 * c
    out = []
    for scored, sign in (("bp_moy", 1), ("bc_moy", -1)):
        base = gap ** (sign * level)
        if prior:
            base = (1 - c) * base + c * prior[0 if sign > 0 else 1]
        seen = base
        if j and prof.get("bp_moy") is not None and prof.get("bc_moy") is not None:
            ref = (prof["bp_moy"] + prof["bc_moy"]) / 2 or avg
            seen = prof[scored] / ref * gap ** (sign * level)
        out.append((seen * j + base * k) / (j + k))
    att_t, dfn_t = out
    att_u, dfn_u = forces[club]
    rng, won = random.Random(seed), 0.0
    for _ in range(sims):
        fu, ft = math.exp(rng.gauss(0, UNSURE)), math.exp(rng.gauss(0, 1.5 * UNSURE))
        mu = avg * att_u * fu * dfn_t / ft * (1.04 if home else 0.96)
        mt = avg * att_t * ft * dfn_u / fu * (0.96 if home else 1.04)
        gu, gt = max(0, round(rng.gauss(mu, mu ** 0.5))), max(0, round(rng.gauss(mt, mt ** 0.5)))
        won += 1 if gu > gt else 0.5 if gu == gt else 0
    return round(100 * won / sims)


def fr(x):
    return f"{x:.1f}".replace(".", ",")


def recommend_plan(profile, all_profiles):
    """Choisit la pondération selon le profil de l'adversaire."""
    played = [p for p in all_profiles.values() if p["j"]]
    if not profile or not profile["j"]:
        return "equilibre", "Cette équipe n'a pas encore joué : pondération équilibrée."
    if len(played) < 3:
        return "equilibre", "Pas assez de matchs joués dans les poules pour profiler l'adversaire."
    med_bp = statistics.median(p["bp_moy"] for p in played)
    med_bc = statistics.median(p["bc_moy"] for p in played)
    if profile["bp_moy"] >= med_bp * 1.08:
        return "rigueur", (f"Attaque adverse forte ({fr(profile['bp_moy'])} buts/match, "
                           f"médiane {fr(med_bp)}) : priorité à la discipline et à l'impact collectif.")
    if profile["bc_moy"] >= med_bc * 1.08:
        return "attaque", (f"Défense adverse perméable ({fr(profile['bc_moy'])} buts encaissés/match, "
                           f"médiane {fr(med_bc)}) : priorité aux buteurs en forme.")
    return "equilibre", "Adversaire dans la moyenne des deux poules : pondération équilibrée."


def is_staff(row):
    """Une ligne d'encadrement (rôle « coach », « entraîneur ») : pas un joueur."""
    role = norm(row.get("role") or "")
    return "COACH" in role or "ENTRAINEUR" in role


def birthday(text):
    """« 2006-09-20 », « 09-20 », « 20/09 » -> « 09-20 » (le jour seulement, jamais l'année)."""
    text = str(text or "").strip()
    m = re.fullmatch(r"(?:\d{4}-)?(\d{1,2})-(\d{1,2})", text) or re.fullmatch(r"(\d{1,2})/(\d{1,2})(?:/\d{2,4})?", text)
    if not m:
        return None
    month, day = (int(m.group(1)), int(m.group(2))) if "-" in text else (int(m.group(2)), int(m.group(1)))
    return f"{month:02d}-{day:02d}" if 1 <= month <= 12 and 1 <= day <= 31 else None


def birthdays(coach):
    """Les anniversaires de l'effectif et de l'encadrement (caisse noire : le rappel) : [{cle, jour}]."""
    path = ROOT / "roster.csv"
    out = []
    if path.exists():
        with path.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                day = birthday(row.get("naissance"))
                if day and (row.get("nom") or "").strip():
                    out.append(dict(cle=coach if is_staff(row) else "R:" + name_key(row["nom"]), jour=day))
    return out


def load_roster():
    path = ROOT / "roster.csv"
    roster = {}
    if path.exists():
        with path.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                if (row.get("nom") or "").strip() and not is_staff(row):
                    # « non » : indisponible ; « dépannage » : joue seulement s'il manque des joueurs
                    state = norm(row.get("disponible") or "oui")
                    roster[name_key(row["nom"])] = dict(nom=row["nom"].strip(),
                                                        poste=(row.get("poste") or "").strip().upper(),
                                                        disponible=state not in ("NON", "0", "FALSE", "N"),
                                                        depannage=state in ("DEPANNAGE", "RESERVE"),
                                                        tresorier="TRESORIER" in norm(row.get("role") or ""),
                                                        age=AGES.get(norm(row.get("age") or "")))
    return roster


# classes d'âge de l'effectif (demande de l'auteur, 05/10/2026) : à valeur proche, les changements
# font jouer d'abord les plus jeunes, pour une équipe solide et jeune la saison suivante
AGES = {"JEUNE": "jeune", "INTERMEDIAIRE": "intermediaire", "EXPERIMENTE": "experimente", "AGE": "experimente"}


HIST = 0.5  # poids d'un match de la saison passée face à un match de la saison en cours
HIST2 = HIST * HIST  # la saison d'avant (2024-2025) : un quart de match
FIABLE = (3, 6)  # matchs comptés (saison passée pour HIST) : en deçà du 1er, note fragile ; du 2e, indicative
# Les saisons passées s'effacent à mesure que la saison avance (demande de l'auteur, 05/10/2026) : un
# match d'avant pèse HIST × FONDU / (FONDU + matchs de la saison lus) ; au début la saison passée guide,
# puis chaque match joué compte davantage (0,5 au départ, 0,43 après 1 match, 0,25 après 6).
FONDU = 6


def fade(n_season):
    """Facteur des saisons passées après n_season matchs de la saison en cours."""
    return FONDU / (FONDU + n_season)


def reliability(m, m_past, m_older=0, w=HIST, w2=HIST2):
    """Sur combien de matchs repose une note : ceux de la saison, plus ceux de la saison passée
    comptés pour w et ceux de la saison d'avant pour w2, et ce que cela vaut (fragile,
    indicative, solide ; aucune sans match)."""
    n = m + w * m_past + w2 * m_older
    level = "aucune" if not n else "fragile" if n < FIABLE[0] else "indicative" if n < FIABLE[1] else "solide"
    return dict(matchs=round(n, 1), saison=m, passee=m_past, avant=m_older, niveau=level,
                poids_passee=round(w, 2), poids_avant=round(w2, 2))


COUNTS = ("m", "buts", "pen", "tirs", "tirs_connus", "arrets", "jaunes", "deux_min", "rouges", "pris", "cadres")


def merged(h, o):
    """Saison passée et saison d'avant en une seule : les comptes de la seconde pèsent HIST2/HIST de
    ceux de la première (blend les multiplie ensuite par HIST) ; forme et numéros s'additionnent."""
    if not o.get("m"):
        return h
    out = dict(h)
    for k in COUNTS:
        out[k] = (h.get(k) or 0) + HIST2 / HIST * (o.get(k) or 0)
    out["w_buts"], out["w"] = (h.get("w_buts") or 0) + (o.get("w_buts") or 0), (h.get("w") or 0) + (o.get("w") or 0)
    out["nums"] = (h.get("nums") or Counter()) + (o.get("nums") or Counter())
    return out


def season_line(x, saison):
    """Les chiffres d'une saison passée, tels que la fiche du joueur les montre."""
    return dict(saison=saison, m=x["m"], buts=x["buts"], pen=x["pen"], tirs=x["tirs"] or None,
                reussite=round(100 * x["tirs_connus"] / x["tirs"]) if x["tirs"] else None,
                arrets=x["arrets"], pct_arrets=save_pct(x["cadres"] - x["pris"], x["pris"]),
                jaunes=x["jaunes"], deux_min=x["deux_min"], rouges=x["rouges"]) if x["m"] else None


PRUDENCE = 2  # matchs « moyens » ajoutés à chaque note (choix de l'auteur, 05/10/2026)


def shrink_notes(players):
    """Ramène chaque note vers la moyenne de l'effectif, gardiens et joueurs de champ à part,
    d'autant plus qu'elle repose sur peu de matchs : comme si chacun avait aussi joué PRUDENCE
    matchs moyens. Un seul bon match ne fait plus passer un joueur devant un autre beaucoup plus
    vu ; une note sur huit matchs bouge peu. La moyenne pèse chaque joueur par ses matchs comptés.
    La note d'avant reste dans scores_bruts."""
    for gk in (True, False):
        group = [p for p in players if bool(p["gardien"]) == gk and p["fiabilite"]["matchs"]]
        total = sum(p["fiabilite"]["matchs"] for p in group)
        if not total:
            continue
        for plan in PLANS:
            mean = sum(p["scores"][plan] * p["fiabilite"]["matchs"] for p in group) / total
            for p in group:
                n, raw = p["fiabilite"]["matchs"], p["scores"][plan]
                p.setdefault("scores_bruts", {})[plan] = raw
                p["scores"][plan] = round(mean + (raw - mean) * n / (n + PRUDENCE))


def club_matches_of(matches, config):
    """[(match, côté du club, adversaire, buts pour, buts contre)] dans l'ordre des dates."""
    out = []
    for m in sorted(matches, key=lambda x: x.get("date") or ""):
        for side, team, opp, gf, ga in sides(m):
            if is_club(team, config):
                out.append((m, side, opp, gf, ga))
    return out


def player_stats(with_sheet, weight_of):
    """Statistiques par joueur sur des matchs du club avec feuille ; weight_of(i) : poids de forme."""
    players, any_events = {}, False
    for idx, (m, side, opp, gf, ga) in enumerate(with_sheet):
        weight = weight_of(idx)
        events = m.get("events") or []
        any_events = any_events or bool(events)
        clutch = Counter()
        prev = [0, 0]
        for e in events:
            if e["type"] in ("goal", "pen_goal"):
                if e["side"] == side and e["t"] >= 3000 and abs(prev[0] - prev[1]) <= 3:
                    clutch[e.get("num")] += 1
                prev = e.get("score") or prev
        buckets = defaultdict(set)
        for e in events:
            if e.get("side") == side and e.get("num") is not None:
                buckets[e["num"]].add(min(5, int(e["t"] // 600)))
        conceded, estimated = keepers_conceded(m, side)
        for p in m["players"][side]:
            key = name_key(p.get("name")) or f"N{p.get('num')}"
            rec = players.setdefault(key, dict(
                cle=key, nom=p.get("name") or f"n° {p.get('num')}", nums=Counter(),
                m=0, buts=0, pen=0, tirs=0, tirs_connus=0, arrets=0, jaunes=0, deux_min=0,
                rouges=0, clutch=0, w_buts=0.0, w=0.0, diffs=[], journal=[],
                tranches=0, m_deroule=0, pris=0, cadres=0, estime=False))
            pris = conceded.get(p.get("num")) if p.get("saves") else None
            if pris is not None:  # gardien dont les buts pris sont connus pour ce match
                rec["pris"] += pris
                rec["cadres"] += p["saves"] + pris
                rec["estime"] = rec["estime"] or estimated
            if events:
                rec["m_deroule"] += 1
                rec["tranches"] += len(buckets.get(p.get("num"), ()))
            rec["nums"][p.get("num")] += 1
            rec["m"] += 1
            g = p.get("goals") or 0
            rec["buts"] += g
            rec["pen"] += p.get("pen_goals") or 0
            if p.get("shots"):
                rec["tirs"] += p["shots"]
                rec["tirs_connus"] += g
            rec["arrets"] += p.get("saves") or 0
            rec["jaunes"] += p.get("yellow") or 0
            rec["deux_min"] += p.get("two_min") or 0
            rec["rouges"] += p.get("red") or 0
            rec["clutch"] += clutch.get(p.get("num"), 0)
            rec["w_buts"] += weight * g
            rec["w"] += weight
            rec["diffs"].append(gf - ga)
            rec["journal"].append(dict(id=str(m.get("id")), date=m.get("date"), adv=opp, dom=side == "home", res=outcome(gf, ga),
                                       score=f"{gf}-{ga}", buts=g, tirs=p.get("shots"),
                                       jaunes=p.get("yellow") or 0,
                                       deux_min=p.get("two_min") or 0,
                                       rouges=p.get("red") or 0,
                                       arrets=p.get("saves") or 0, pris=pris,
                                       pct=save_pct(p["saves"], pris) if pris is not None else None))
    return players, any_events


EMPTY = dict(m=0, buts=0, pen=0, tirs=0, tirs_connus=0, arrets=0, jaunes=0, deux_min=0, rouges=0,
             w_buts=0.0, w=0.0, pris=0, cadres=0, nums=Counter())


def club_players(matches, config, roster, history=(), older=(), youth=()):
    """Statistiques individuelles du club et notes. La saison passée (history : matchs) sert de
    point de départ : ses matchs comptent pour HIST dans la forme, le tir, la discipline, les
    arrêts et l'assiduité ; l'impact et les fins de match restent ceux de la saison en cours,
    l'équipe autour du joueur ayant changé. Un joueur de la saison passée absent de l'effectif
    n'est pas repris."""
    club_matches = club_matches_of(matches, config)
    with_sheet = [c for c in club_matches if c[0].get("players", {}).get(c[1])]
    n_sheet = len(with_sheet)
    players, any_events = player_stats(with_sheet, lambda i: DECAY ** (n_sheet - 1 - i))
    past_ws = [c for c in club_matches_of(history, config) if c[0].get("players", {}).get(c[1])]
    n_past = len(past_ws)
    hw = HIST * fade(n_sheet)   # un match de la saison passée, à ce point de la saison
    hw2 = HIST2 * fade(n_sheet)
    past, _ = player_stats(past_ws, lambda i: hw * DECAY ** (n_sheet + n_past - 1 - i))
    saison_passee = max((c[0].get("saison") or "" for c in past_ws), default="") or None
    # la saison d'avant (older) : un quart de match chacun
    old_ws = [c for c in club_matches_of(older, config) if c[0].get("players", {}).get(c[1])]
    n_old = len(old_ws)
    old, _ = player_stats(old_ws, lambda i: hw2 * DECAY ** (n_sheet + n_past + n_old - 1 - i))
    saison_avant = max((c[0].get("saison") or "" for c in old_ws), default="") or None
    # les jeunes du club (youth : matchs des moins de 18 ans) : un quart de match, et seulement pour un
    # joueur sans aucun match senior, pour qu'il ait une note
    young_ws = [c for c in club_matches_of(youth, config) if c[0].get("players", {}).get(c[1])]
    young, _ = player_stats(young_ws, lambda i: hw2 * DECAY ** (len(young_ws) - 1 - i))
    young = {k: h for k, h in young.items() if k not in players and k not in past and k not in old}
    saison_jeunes = max((c[0].get("saison") or "" for c in young_ws), default="") or None
    for key, h in list(past.items()) + list(old.items()) + list(young.items()):  # joueurs des saisons passées encore dans l'effectif
        if key not in players and match_name(h["nom"], roster):
            players[key] = dict(EMPTY, cle=key, nom=h["nom"], nums=Counter(), clutch=0, diffs=[], journal=[],
                                tranches=0, m_deroule=0, estime=False)
    all_diffs = [gf - ga for _, _, _, gf, ga in with_sheet]
    blend = lambda r, h, k: r[k] + hw * h[k]
    hist_of = lambda r: merged(merged(past.get(r["cle"], EMPTY), old.get(r["cle"], EMPTY)), young.get(r["cle"], EMPTY))
    form = lambda r, h: (r["w_buts"] + h["w_buts"]) / (r["w"] + h["w"]) if r["w"] + h["w"] else 0
    max_form = max((form(r, hist_of(r)) for r in players.values()), default=0) or 1
    max_clutch = max((r["clutch"] / r["m"] for r in players.values() if r["m"]), default=0) or 1
    max_saves = max((blend(r, hist_of(r), "arrets") / blend(r, hist_of(r), "m")
                     for r in players.values() if blend(r, hist_of(r), "m")), default=0) or 1
    out = []
    seen = set()
    for r in players.values():
        h = hist_of(r)
        rkey = match_name(r["nom"], roster)
        seen.add(rkey)
        ros = roster.get(rkey, {})
        if ros.get("nom"):
            r["nom"] = ros["nom"]  # l'orthographe de l'effectif fait foi à l'affichage
        poste = ros.get("poste", "")
        saves, goals = blend(r, h, "arrets"), blend(r, h, "buts")
        gk = "GB" in poste.split("/") or (not poste and saves > goals and saves > 0)
        m, mw = r["m"], blend(r, h, "m")
        without = n_sheet - m
        rest = (sum(all_diffs) - sum(r["diffs"])) / without if without and m else None
        raw_imp = (sum(r["diffs"]) / m - rest) if rest is not None else 0.0
        shrink = min(m, without) / (min(m, without) + 2) if without and m else 0.0
        impact = raw_imp * shrink
        penal = (blend(r, h, "deux_min") + 3 * blend(r, h, "rouges") + 0.3 * blend(r, h, "jaunes")) / mw
        tirs = blend(r, h, "tirs")
        # % d'arrêts lissé vers 30 % (10 tirs fictifs), ramené sur l'échelle 15 % -> 0, 45 % -> 1
        cadres, pris = blend(r, h, "cadres"), blend(r, h, "pris")
        pct_lisse = (cadres - pris + 3) / (cadres + 10)
        comps = dict(
            att=form(r, h) / max_form,
            eff=(blend(r, h, "tirs_connus") + 2.5) / (tirs + 5) if tirs else 0.5,
            disc=max(0.0, 1 - penal / 2),
            imp=min(1.0, max(0.0, 0.5 + impact / 16)),
            clutch=(r["clutch"] / m) / max_clutch if any_events and m else 0.5,
            assid=min(1.0, mw / (n_sheet + hw * n_past + hw2 * n_old)) if n_sheet + n_past + n_old else 0,
            gk=min(1.0, max(0.0, (pct_lisse - 0.15) / 0.30)) if gk else 0,
            gk_vol=(saves / mw) / max_saves if gk else 0,
        )
        scores = {}
        for plan, w in PLANS.items():
            if gk:  # gardien : d'abord le % d'arrêts, puis le volume, l'impact et l'assiduité
                val = 0.5 * comps["gk"] + 0.15 * comps["gk_vol"] + 0.2 * comps["imp"] + 0.15 * comps["assid"]
            else:
                val = sum(w[k] * comps[k] for k in w)
            scores[plan] = round(100 * val)
        hp, ho, hy = past.get(r["cle"], EMPTY), old.get(r["cle"], EMPTY), young.get(r["cle"], EMPTY)
        passe, avant = season_line(hp, saison_passee), season_line(ho, saison_avant)
        jeunes = season_line(hy, f"-18 {saison_jeunes}" if saison_jeunes else "-18")
        bases = [s for s, x in ((saison_passee, hp), (saison_avant, ho), (f"-18 {saison_jeunes}", hy)) if x["m"]]
        nums = r["nums"] + h["nums"]
        out.append(dict(
            # clé stable : un poste saisi avant le premier match reste attaché au joueur
            cle="R:" + rkey if rkey else r["cle"], nom=r["nom"],
            num=(r["nums"] or nums).most_common(1)[0][0] if nums else None,
            poste=poste, gardien=gk, disponible=ros.get("disponible", True), depannage=ros.get("depannage", False),
            tresorier=ros.get("tresorier", False), age=ros.get("age"),
            m=m, m_total=n_sheet, buts=r["buts"], pen=r["pen"],
            presence=round(r["tranches"] / r["m_deroule"], 1) if r["m_deroule"] else None,
            min_deux=2 * r["deux_min"], tirs=r["tirs"] or None,
            reussite=round(100 * r["tirs_connus"] / r["tirs"]) if r["tirs"] else None,
            arrets=r["arrets"], pris=r["pris"] if r["cadres"] else None,
            tirs_subis=r["cadres"] or None, pct_arrets=save_pct(r["cadres"] - r["pris"], r["pris"]),
            pris_estime=r["estime"],
            jaunes=r["jaunes"], deux_min=r["deux_min"], rouges=r["rouges"],
            buts_moy=round(r["buts"] / m, 1) if m else 0,
            forme_buts=round(form(r, h), 1),
            impact=round(impact, 1), decisifs=r["clutch"],
            comps={k: round(v, 2) for k, v in comps.items()},
            scores=scores, journal=r["journal"], passe=passe, avant=avant, jeunes=jeunes,
            fiabilite=reliability(m, hp["m"], ho["m"] + hy["m"], hw, hw2),
            note_base=("saison" + "".join(" et " + s for s in bases)) if m else (" et ".join(bases) or None)))
    shrink_notes(out)
    out.sort(key=lambda p: -p["scores"]["equilibre"])
    # joueurs de l'effectif jamais inscrits sur une feuille : listés, sans note
    for rkey, ros in sorted(roster.items(), key=lambda kv: norm(kv[1].get("nom") or kv[0])):
        if rkey in seen:
            continue
        out.append(dict(
            cle="R:" + rkey, nom=ros.get("nom") or rkey.title(), num=None, poste=ros.get("poste", ""),
            gardien="GB" in (ros.get("poste") or "").split("/"), disponible=ros.get("disponible", True),
            depannage=ros.get("depannage", False), tresorier=ros.get("tresorier", False), age=ros.get("age"),
            m=0, m_total=n_sheet, presence=None, min_deux=0, buts=0, pen=0, tirs=None, reussite=None,
            arrets=0, pris=None, tirs_subis=None, pct_arrets=None, pris_estime=False,
            jaunes=0, deux_min=0, rouges=0, buts_moy=0, forme_buts=0, impact=0, decisifs=0,
            comps={k: 0 for k in ("att", "eff", "disc", "imp", "clutch", "assid", "gk", "gk_vol")},
            scores={plan: None for plan in PLANS}, journal=[], passe=None, avant=None, jeunes=None, note_base=None,
            fiabilite=reliability(0, 0, 0, hw, hw2)))
    return out, club_matches, with_sheet


def last_matches(current, past, roster, n=3):
    """Les n derniers matchs terminés du club dont la feuille est lue : ceux de la saison, complétés par
    la fin de la saison passée tant qu'il en manque. Pour chacun, qui était sur la feuille (clé du
    joueur, comme dans joueurs) et ce qu'il y a fait. La planification en montre deux ; le troisième
    sert à compter les matchs de suite d'un gardien."""
    out = []
    for m, side, opp, gf, ga in (list(past) + list(current))[-n:]:
        who = {}
        for pl in (m.get("players") or {}).get(side, []):
            rkey = match_name(pl.get("name"), roster)
            key = "R:" + rkey if rkey else name_key(pl.get("name")) or f"N{pl.get('num')}"
            who[key] = dict(buts=pl.get("goals") or 0, arrets=pl.get("saves") or 0)
        out.append(dict(id=str(m.get("id")), date=m.get("date"), adversaire=opp, domicile=side == "home",
                        bp=gf, bc=ga, res=outcome(gf, ga), journee=m.get("journee"), coupe=m.get("coupe"),
                        tour=m.get("tour"), saison=m.get("saison"), joueurs=who))
    return out


def pairs(with_sheet):
    """Résultats de l'équipe quand deux joueurs sont ensemble sur la feuille."""
    acc = defaultdict(lambda: dict(m=0, v=0, n=0, d=0, diff=0, buts=0))
    names = {}
    for m, side, _, gf, ga in with_sheet:
        sheet = m["players"][side]
        for p in sheet:
            names[norm(p.get("name")) or f"N{p.get('num')}"] = p.get("name")
        res = outcome(gf, ga).lower()
        for a, b in itertools.combinations(sorted(sheet, key=lambda p: norm(p.get("name"))), 2):
            ka = norm(a.get("name")) or f"N{a.get('num')}"
            kb = norm(b.get("name")) or f"N{b.get('num')}"
            rec = acc[(ka, kb)]
            rec["m"] += 1
            rec[res] += 1
            rec["diff"] += gf - ga
            rec["buts"] += (a.get("goals") or 0) + (b.get("goals") or 0)
    out = []
    for (ka, kb), r in acc.items():
        if r["m"] >= 2:
            out.append(dict(a=names[ka], b=names[kb], m=r["m"], v=r["v"], n=r["n"],
                            d=r["d"], diff_moy=round(r["diff"] / r["m"], 1),
                            buts_moy=round(r["buts"] / r["m"], 1)))
    out.sort(key=lambda r: (-r["diff_moy"], -r["buts_moy"]))
    return out


UNSURE = 0.08  # incertitude de départ sur la force d'une équipe (±8 % de buts), réduite par les matchs joués


def outlook(matches, fixtures, club, poule, target=1, sims=10000, seed=38160, known=(), priors=None):
    """Course au classement : chances d'atteindre le rang visé et enjeu de chaque match.

    Chaque match restant est simulé à partir des moyennes de buts marqués et
    encaissés, ramenées vers la moyenne de la poule tant qu'il y a peu de matchs.
    Ces forces restent incertaines : chaque saison simulée les tire autour de leur
    valeur, d'autant plus large qu'il y a peu de matchs joués (UNSURE).
    L'enjeu d'un match = chances d'atteindre l'objectif en cas de victoire,
    moins ces chances sinon.
    """
    played = [m for m in matches if str(m.get("poule")) == str(poule)]
    table = {r["equipe"]: r for r in standings(played, known)}
    done = {(m["home"]["name"], m["away"]["name"]) for m in played}
    rest = [f for f in fixtures if str(f.get("poule")) == str(poule)
            and f.get("score_home") is None and f.get("home") and f.get("away")
            and (f["home"], f["away"]) not in done]
    rest.sort(key=lambda f: f.get("date") or "9999")
    teams = set(table) | {f["home"] for f in rest} | {f["away"] for f in rest}
    if not club or club not in teams or not played:
        return None
    for t in teams:
        table.setdefault(t, dict(equipe=t, pts=0, j=0, bp=0, bc=0, diff=0, rang=len(table) + 1))
    mine = [f for f in rest if club in (f["home"], f["away"])]
    leader = max(table.values(), key=lambda r: (r["pts"], r["diff"]))
    base = dict(poule=str(poule), cible=target, rang=table[club]["rang"], pts=table[club]["pts"],
                joues=table[club]["j"], restants=len(mine), leader=leader["equipe"],
                retard=leader["pts"] - table[club]["pts"],
                pts_max=table[club]["pts"] + 3 * len(mine), matchs=[], proba=None, proba_tout=None)
    if not mine:
        listed = [f for f in fixtures if str(f.get("poule")) == str(poule)
                  and club in (f.get("home"), f.get("away"))]
        over = len(listed) >= 2 * (len(teams) - 1) and all(f.get("score_home") is not None for f in listed)
        base["statut"] = "termine" if over else "calendrier_inconnu"
        return base
    total_j = sum(r["j"] for r in table.values()) or 1
    avg = sum(r["bp"] for r in table.values()) / total_j
    priors = priors or {}

    def rate(t, scored):
        """Buts marqués (ou encaissés) attendus, relatifs à la moyenne : les matchs joués, ramenés vers
        une valeur de départ — la moyenne de poule, ou le niveau de la saison passée d'autant plus
        que l'effectif est resté (continuité c), pesant 3 à 5 matchs."""
        r, prior = table[t], priors.get(t)
        c = prior[2] if prior else 0.0
        rel = 1 + ((prior[0] if scored else prior[1]) - 1) * c if prior else 1.0
        k = 3 + 2 * c
        return ((r["bp" if scored else "bc"] + k * avg * rel) / (r["j"] + k)) / avg

    att0 = {t: rate(t, True) for t in table}
    dfn0 = {t: rate(t, False) for t in table}
    k_of = {t: 3 + 2 * (priors[t][2] if t in priors else 0.0) for t in table}
    unsure = {t: UNSURE * (k_of[t] / (table[t]["j"] + k_of[t])) ** 0.5 for t in table}
    rng = random.Random(seed)
    att, dfn = dict(att0), dict(dfn0)

    def draw_strengths():
        for t in table:
            att[t] = att0[t] * math.exp(rng.gauss(0, unsure[t]))
            dfn[t] = dfn0[t] * math.exp(rng.gauss(0, unsure[t]))

    def play(f):
        mh = avg * att[f["home"]] * dfn[f["away"]] * 1.04
        ma = avg * att[f["away"]] * dfn[f["home"]] * 0.96
        return (max(0, round(rng.gauss(mh, mh ** 0.5))), max(0, round(rng.gauss(ma, ma ** 0.5))))

    already = [(m["home"]["name"], m["away"]["name"], m["home"]["score"], m["away"]["score"]) for m in played]

    def season(force_win=False):
        draw_strengths()
        sim, res = list(already), {}
        for f in rest:
            gh, ga = play(f)
            if force_win and club in (f["home"], f["away"]):
                if (gh <= ga) == (f["home"] == club) or gh == ga:
                    hi, lo = max(gh, ga) + (gh == ga), min(gh, ga)
                    gh, ga = (hi, lo) if f["home"] == club else (lo, hi)
            sim.append((f["home"], f["away"], gh, ga))
            if club in (f["home"], f["away"]):
                res[f["id"]] = outcome(gh, ga) if f["home"] == club else outcome(ga, gh)
        draw = {t: rng.random() for t in teams}  # dernier recours : tirage au sort
        rank = rank_teams(list(teams), sim, draw.get).index(club) + 1
        return rank <= target, res, rank

    ok_total = 0
    ranks = Counter()
    stat = {f["id"]: dict(v=0, v_ok=0, o=0, o_ok=0) for f in mine}
    for _ in range(sims):
        ok, res, rank = season()
        ok_total += ok
        ranks[rank] += 1
        for fid, r in res.items():
            s = stat[fid]
            if r == "V":
                s["v"] += 1
                s["v_ok"] += ok
            else:
                s["o"] += 1
                s["o_ok"] += ok
    n_all = max(300, sims // 4)
    base["proba"] = round(100 * ok_total / sims)
    base["proba_tout"] = round(100 * sum(season(True)[0] for _ in range(n_all)) / n_all)
    # chances de chaque rang final : juste quelle que soit la formule de la phase suivante
    base["rangs"] = [round(100 * ranks[r] / sims, 1) for r in range(1, len(teams) + 1)]
    for f in mine:
        s = stat[f["id"]]
        dom = f["home"] == club
        adv = f["away"] if dom else f["home"]
        si_v = 100 * s["v_ok"] / s["v"] if s["v"] else None
        si_o = 100 * s["o_ok"] / s["o"] if s["o"] else None
        enjeu = round(si_v) - round(si_o) if si_v is not None and si_o is not None else None
        base["matchs"].append(dict(
            id=f["id"], date=f.get("date"), provisoire=bool(f.get("date_provisoire")),
            journee=f.get("journee"), adversaire=adv, domicile=dom, salle=f.get("salle"),
            rang_adv=table[adv]["rang"], pts_adv=table[adv]["pts"],
            p_victoire=round(100 * s["v"] / sims),
            si_victoire=None if si_v is None else round(si_v),
            sinon=None if si_o is None else round(si_o), enjeu=enjeu))
    ranked = sorted((m for m in base["matchs"] if m["enjeu"] is not None), key=lambda m: -m["enjeu"])
    keys = {m["id"] for m in ranked[:3] if m["enjeu"] > 0}
    for m in base["matchs"]:
        m["cle"] = m["id"] in keys
    base["statut"] = "en_cours"
    # forces de départ (relatives à la moyenne de la poule) : pour estimer les matchs de coupe
    base["forces"] = {t: [round(att0[t], 3), round(dfn0[t], 3)] for t in table}
    base["moyenne"] = round(avg, 2)
    return base


LIB_CAT = dict(echauffement="Échauffement", technique="Technique individuelle", attaque="Attaque",
               defense="Défense", gardien="Gardien de but", transition="Montée de balle / transition",
               physique="Préparation physique", jeu="Jeu / situation")


def training_axes(club, profiles, players):
    """Axes de travail à l'entraînement, déduits des matchs du club comparés aux deux poules."""
    me = profiles.get(club)
    played = [p for p in profiles.values() if p["j"]]
    if not me or not me["j"] or len(played) < 3:
        return []
    med = lambda key: statistics.median(p[key] for p in played)
    axes = []

    def add(cat, titre, constat, poids):
        axes.append(dict(categorie=cat, libelle=LIB_CAT[cat], titre=titre, constat=constat,
                         poids=round(poids, 2)))

    deux = [p["deux_min_moy"] for p in played if p["deux_min_moy"] is not None]
    m_bc, m_bp, m_ex = med("bc_moy"), med("bp_moy"), statistics.median(deux) if deux else None
    if me["bc_moy"] > m_bc * 1.03:
        add("defense", "Défense", f"{fr(me['bc_moy'])} buts encaissés par match, médiane des poules {fr(m_bc)}.",
            (me["bc_moy"] - m_bc) / m_bc * 4)
    if me["bp_moy"] < m_bp * 0.97:
        add("attaque", "Attaque placée", f"{fr(me['bp_moy'])} buts marqués par match, médiane des poules {fr(m_bp)}.",
            (m_bp - me["bp_moy"]) / m_bp * 4)
    if m_ex and me["deux_min_moy"] is not None and me["deux_min_moy"] > m_ex * 1.15 and me["deux_min_moy"] >= 1:
        add("defense", "Défendre sans faute",
            f"{fr(me['deux_min_moy'])} exclusions de 2 minutes par match, médiane {fr(m_ex)}.",
            (me["deux_min_moy"] - m_ex) / max(m_ex, 1) * 1.5)
    if me.get("periodes_bp"):
        diffs = [a - b for a, b in zip(me["periodes_bp"], me["periodes_bc"])]
        if diffs[5] <= -0.7:
            add("physique", "Fin de match", f"Écart moyen de {fr(diffs[5])} but entre la 50e et la 60e minute.",
                -diffs[5] / 2)
        if diffs[0] <= -0.7:
            add("echauffement", "Entrée en match", f"Écart moyen de {fr(diffs[0])} but dans les dix premières minutes.",
                -diffs[0] / 2)
    if me.get("mt1_bp") is not None:
        drop = (me["mt2_bp"] - me["mt2_bc"]) - (me["mt1_bp"] - me["mt1_bc"])
        if drop <= -1.5:
            add("physique", "Tenir la deuxième mi-temps",
                f"Écart de {fr(me['mt1_bp'] - me['mt1_bc'])} en première mi-temps, {fr(me['mt2_bp'] - me['mt2_bc'])} en seconde.",
                -drop / 4)
    shots = sum(p["tirs"] or 0 for p in players)
    goals = sum(p["buts"] for p in players if p["tirs"])
    if shots >= 20 and goals / shots < 0.5:
        add("technique", "Efficacité au tir", f"{round(100 * goals / shots)} % de réussite sur {shots} tirs relevés.",
            (0.5 - goals / shots) * 6)
    total = sum(p["buts"] for p in players)
    top = max(players, key=lambda p: p["buts"], default=None)
    if top and total and top["buts"] / total >= 0.33:
        add("attaque", "Répartir le danger", f"{top['nom']} marque {round(100 * top['buts'] / total)} % des buts de l'équipe.",
            top["buts"] / total)
    saves = sum(p["arrets"] for p in players)
    against = sum(x["bc"] for x in me["matches"])
    if saves and against and saves / (saves + against) < 0.28:
        add("gardien", "Gardiens", f"{round(100 * saves / (saves + against))} % d'arrêts sur les tirs cadrés relevés.",
            (0.28 - saves / (saves + against)) * 6)
    axes.sort(key=lambda a: -a["poids"])
    return axes[:4]


def poule_view(matches, teams, official, gone=frozenset()):
    """Classement recalculé, et écarts éventuels avec celui de la fédération (pénalités, forfaits).
    Une équipe en forfait général (gone, noms normalisés) reste affichée, en bas et sans rang."""
    rows = standings(matches, teams)
    kept = [r for r in rows if norm(r["equipe"]) not in gone]
    for i, r in enumerate(kept, 1):
        r["rang"] = i
    rows = kept + [dict(r, rang=None, forfait=True) for r in rows if norm(r["equipe"]) in gone]
    off = {norm(k): v for k, v in official_table(official).items()}
    off_j = {norm(k): v for k, v in official_table(official, ("J",)).items()}
    # moins de matchs joués côté fédération : son classement n'est pas encore à jour
    gaps = [dict(equipe=r["equipe"], officiel=off[norm(r["equipe"])], calcule=r["pts"],
                 retard=off_j.get(norm(r["equipe"])) is not None and off_j[norm(r["equipe"])] < r["j"])
            for r in kept if off.get(norm(r["equipe"])) is not None and off[norm(r["equipe"])] != r["pts"]]
    return dict(classement=rows, ecarts=gaps, officiel_lu=bool(off))


LOGOS = "https://media-logos-clubs.ffhandball.fr/128/"


def team_logos(fixtures):
    """Le logo de chaque équipe, tel que ffhandball.fr le publie (image du club, en .webp)."""
    out = {}
    for f in fixtures:
        for side in ("home", "away"):
            name, logo = f.get(side), f.get(f"{side}_logo")
            if name and logo:
                out[name] = LOGOS + logo.rsplit(".", 1)[0] + ".webp"
    return out


PLANIF = "planif.json"  # entrées de la planification figées (data/, repris de etat.enc)


def freeze_plan(players, matchs, sheets, roster, config, history=()):
    """Les propositions de la planification ne bougent qu'après un match du club (une feuille de plus
    lue) ou un changement d'effectif : d'ici là, notes des joueurs et chances de victoire servant à la
    rotation restent celles du moment où elles ont été posées (scores_plan, p_plan, cle), quoi que
    les publications suivantes recalculent. Un match qui entre dans l'horizon reçoit ses valeurs du
    jour. Même résultat pour tout le monde, et d'une ouverture à l'autre."""
    # history : saisons passées et jeunes, avec leurs feuilles lues ; une saison ajoutée relâche aussi
    key = dict(feuilles=sorted(str(s) for s in sheets), forfaits=sorted(config.get("forfaits") or []),
               historique=sorted([x.get("saison") or "", x.get("niveau") or 0, x.get("categorie") or "",
                                  sum(1 for m in x.get("matches") or [] if (m.get("source") or {}).get("fdme"))] for x in history),
               effectif=hashlib.sha256(json.dumps(roster, sort_keys=True, ensure_ascii=False, default=str)
                                       .encode("utf-8")).hexdigest()[:16])
    prev = read_json(DATA / PLANIF, {}) or {}
    same = prev.get("cle") == key
    notes = dict(prev.get("notes") or {}) if same else {}
    probs = dict(prev.get("matchs") or {}) if same else {}
    for p in players:
        notes.setdefault(p["cle"], p.get("scores"))
        p["scores_plan"] = notes[p["cle"]]
    for m in matchs:
        frozen = probs.setdefault(str(m["id"]), dict(p=m.get("p_victoire"), cle=bool(m.get("cle"))))
        m["p_plan"], m["cle"] = frozen["p"], frozen["cle"]
    write_json(DATA / PLANIF, dict(cle=key, notes=notes, matchs=probs, depuis=prev.get("depuis") if same else paris_now().strftime("%Y-%m-%d %H:%M")))
    return (prev.get("depuis") if same else None) or paris_now().strftime("%Y-%m-%d %H:%M")


def cup_ahead(fixtures, config, today, league):
    """Les matchs de coupe à venir du club, pour la planification : pas d'enjeu pour le classement,
    jamais match clé. Victoire estimée : celle d'un match de championnat contre le même adversaire
    s'il y en a un, sinon inconnue (une équipe d'une autre division)."""
    out = []
    for f in fixtures:
        if not f.get("coupe") or f.get("score_home") is not None or (f.get("date") or "9999") < today:
            continue
        dom = is_club(f.get("home"), config)
        if not dom and not is_club(f.get("away"), config):
            continue
        adv = f["away"] if dom else f["home"]
        same = next((m for m in league if m.get("adversaire") == adv), None)
        out.append(dict(id=f["id"], date=f.get("date"), provisoire=bool(f.get("date_provisoire")),
                        journee=None, coupe=f["coupe"], tour=f.get("tour"), adversaire=adv, domicile=dom,
                        salle=f.get("salle"), rang_adv=same and same.get("rang_adv"), pts_adv=None,
                        p_victoire=same and same.get("p_victoire"), si_victoire=None, sinon=None,
                        enjeu=None, cle=False))
    return out


def cup_results(matches, fixtures, config):
    """Le parcours du club en coupe : matchs joués (score, feuille lue) et à venir."""
    played = {m["id"]: m for m in matches if m.get("coupe")}
    out = []
    for f in fixtures:
        if not f.get("coupe"):
            continue
        dom = is_club(f.get("home"), config)
        if not dom and not is_club(f.get("away"), config):
            continue
        m = played.get(str(f["id"]))
        us, them = ("home", "away") if dom else ("away", "home")
        bp, bc = (m[us]["score"], m[them]["score"]) if m else (None, None)
        out.append(dict(id=f["id"], coupe=f["coupe"], tour=f.get("tour"), date=f.get("date"),
                        provisoire=bool(f.get("date_provisoire")), adversaire=f["away"] if dom else f["home"],
                        domicile=dom, bp=bp, bc=bc, res=outcome(bp, bc) if m else None,
                        feuille=bool(m and (m.get("players") or {}).get(us))))
    return sorted(out, key=lambda c: c["date"] or "9999")


def analyze(today=None, roster=None):
    config = load_config()
    today = today or paris_now().date().isoformat()
    matches = [m for m in load_matches() if m.get("played")
               and m["home"].get("score") is not None and m["away"].get("score") is not None
               and m["home"].get("name") and m["away"].get("name")]
    fixtures = read_json(DATA / "fixtures.json", []) or []
    # la feuille peut donner le score avant que la page de la poule (en cache) ne l'affiche
    scored = {m["id"]: m for m in matches}
    for f in fixtures:
        m = scored.get(str(f.get("id")))
        if m and f.get("score_home") is None:
            f["score_home"], f["score_away"] = m["home"]["score"], m["away"]["score"]
    official = read_json(DATA / "official_standings.json", {}) or {}
    roster = roster if roster is not None else load_roster()
    # les coupes comptent pour les joueurs (statistiques, rotation), pas pour le classement
    every_match, every_fixture = matches, fixtures
    all_fixtures = fixtures
    # les matchs d'un adversaire de coupe dans sa propre poule : pour sa fiche, rien d'autre
    outside = [m for m in every_match if m.get("externe")]
    every_match = [m for m in every_match if not m.get("externe")]
    every_fixture = [f for f in every_fixture if not f.get("externe")]
    official = {k: v for k, v in official.items() if not str(k).startswith("ext-")}
    matches = [m for m in every_match if not m.get("coupe")]
    fixtures = [f for f in every_fixture if not f.get("coupe")]
    teams = known_teams(fixtures, official)
    # forfait général (config.yml, constaté par l'auteur) : l'équipe reste affichée, en gris, mais
    # ses matchs ne comptent ni au classement ni dans la simulation, et ne sont plus à préparer
    gone = frozenset(norm(t) for t in config.get("forfaits") or [])
    out_of = lambda f: norm(f.get("home") or "") in gone or norm(f.get("away") or "") in gone
    forfeited = [f for f in fixtures if f.get("score_home") is None and out_of(f)]
    matches = [m for m in matches if not out_of(dict(home=m["home"]["name"], away=m["away"]["name"]))]
    fixtures = [f for f in fixtures if not out_of(f)]
    every_fixture = [f for f in every_fixture if not (f.get("score_home") is None and out_of(f))]

    by_poule = defaultdict(list)
    for m in matches:
        by_poule[str(m.get("poule"))].append(m)
    profiles = team_profiles(matches, teams)
    league_profiles = dict(profiles)
    rivals = {(f["away"] if is_club(f.get("home"), config) else f["home"]) for f in every_fixture
              if f.get("coupe") and (is_club(f.get("home"), config) or is_club(f.get("away"), config))}
    for team, prof in team_profiles(outside).items():   # adversaires de coupe venus d'ailleurs
        if team in rivals and team not in profiles:
            prof["poule_libelle"] = next((m["externe"] for m in outside if team in (m["home"]["name"], m["away"]["name"])), None)
            profiles[team] = prof
    for team in rivals - set(profiles):   # pas encore de match lu : une fiche vide, pour le situer
        profiles[team] = dict(team_profiles([]).get(team) or {}, equipe=team, poule=None, j=0, matches=[], forme=[],
                              bp_moy=None, bc_moy=None, buteurs=[], gardiens=[], jaunes_moy=None, deux_min_moy=None,
                              rouges=None, arrets_pct=None)
    for team in rivals:
        profiles[team]["coupe"] = True
    for team, prof in profiles.items():
        if norm(team) in gone:
            prof["forfait"] = True
    history = all_history = load_history()
    youth = [m for x in history if x.get("categorie") for m in x.get("matches") or []]   # nos jeunes : joueurs seulement
    history = [x for x in history if not x.get("categorie")]
    seasons = [x for x in history if not x.get("niveau")]   # notre division
    above = [x for x in history if x.get("niveau")]         # la division du dessus
    levels = {}  # adversaire de coupe d'une autre poule : niveau de sa division (1 = au-dessus)
    for f in all_fixtures:
        if f.get("externe"):
            for side in ("home", "away"):
                levels[f[side]] = int(f.get("niveau") or 0)
    for team in rivals:
        if levels.get(team):
            profiles[team]["niveau"] = levels[team]
    priors = history_profiles(seasons, profiles, matches, config, above, rosters=every_match + outside)
    for team, prof in profiles.items():
        plan, why = recommend_plan(prof, league_profiles)
        prof["plan"], prof["plan_raison"] = plan, why
    latest = seasons[-1].get("saison") if seasons else None
    older = [m for x in history if latest and (x.get("saison") or "") < latest for m in x.get("matches") or []]
    players, club_matches, with_sheet = club_players(every_match, config, roster,
                                                     history=(seasons[-1].get("matches") or []) if seasons else (),
                                                     older=older, youth=youth)

    club_name = next((t for t in profiles if is_club(t, config)), None)
    upcoming = sorted((f for f in every_fixture if f.get("score_home") is None
                       and (f.get("date") or "9999") >= today
                       and (is_club(f.get("home"), config) or is_club(f.get("away"), config))),
                      key=lambda f: f.get("date") or "9999")
    nxt = None
    if upcoming:
        f = upcoming[0]
        dom = is_club(f.get("home"), config)
        nxt = dict(id=f["id"], date=f.get("date"), provisoire=bool(f.get("date_provisoire")), salle=f.get("salle"),
                   adversaire=f["away"] if dom else f["home"],
                   domicile=dom, journee=f.get("journee"), poule=f.get("poule"),
                   coupe=f.get("coupe"), tour=f.get("tour"))

    squad = config.get("effectif_feuille", "auto")
    if squad == "auto":
        squad = max((len(m["players"][s]) for m, s, *_ in with_sheet), default=12)
        squad = min(16, max(7, squad))

    n_fdme = sum(1 for m in matches if (m.get("players") or {}).get("home"))
    club_poule = profiles[club_name]["poule"] if club_name else None
    target = int((config.get("objectif") or {}).get("rang", 1))
    saison = (outlook(matches, fixtures, club_name, club_poule, target,
                      known=[t for t in teams.get(str(club_poule), ()) if norm(t) not in gone], priors=priors)
              if club_name else None)
    if saison and saison.get("matchs") is not None:  # les matchs de coupe à venir, à leur date
        saison["matchs"] = sorted(saison["matchs"] + cup_ahead(every_fixture, config, today, saison["matchs"]),
                                  key=lambda m: m.get("date") or "9999")
        gap = 1 + float(config.get("ecart_division", ECART))
        for m in saison["matchs"]:  # adversaire d'une autre poule ou d'une autre division
            if m.get("coupe") and m.get("p_victoire") is None:
                m["p_victoire"] = cup_chance(saison.get("forces"), saison.get("moyenne"), club_name,
                                             profiles.get(m["adversaire"]) or {}, levels.get(m["adversaire"], 0),
                                             gap, priors.get(m["adversaire"]), m["domicile"])
    plan_since = freeze_plan(players, (saison or {}).get("matchs") or [], [m["id"] for m, *_ in with_sheet], roster, config,
                             all_history)
    axes = training_axes(club_name, profiles, [p for p in players if p["m"]])
    return dict(
        meta=dict(genere=paris_now().strftime("%Y-%m-%d %H:%M"),
                  saison=config.get("saison"), club=club_name,
                  club_court=config["club"]["nom_affiche"],
                  demo=any((m.get("source") or {}).get("demo") for m in matches),
                  matchs=len(matches), feuilles=n_fdme, effectif=squad,
                  gardiens=int(config.get("gardiens_feuille", 2)), postes_clefs=config.get("postes_clefs") or [],
                  prudence=PRUDENCE,
                  club_matchs=len(club_matches), club_feuilles=len(with_sheet),
                  historique=[x.get("saison") for x in seasons],
                  ecart_division=float(config.get("ecart_division", ECART)), planif_depuis=plan_since),
        prochain=nxt,
        poules={p: poule_view(by_poule.get(p, []), teams.get(p, ()), official.get(p), gone)
                for p in sorted(set(by_poule) | set(teams))},
        resultats=sorted((dict(id=m["id"], poule=str(m.get("poule")), journee=m.get("journee"),
                               date=m.get("date"), dom=m["home"]["name"], ext=m["away"]["name"],
                               sd=m["home"]["score"], se=m["away"]["score"],
                               feuille=bool((m.get("players") or {}).get("home")))
                          for m in matches), key=lambda r: r["date"] or "", reverse=True),
        coupes=cup_results(every_match, every_fixture, config),
        # les deux derniers matchs du club dont la feuille est lue : la planification les montre
        # avant les matchs à venir, pour voir d'un coup d'œil ce que la rotation change
        derniers=last_matches(with_sheet, [c for c in club_matches_of((seasons[-1].get("matches") or []) if seasons else [], config)
                                           if c[0].get("players", {}).get(c[1])], roster),
        logos=team_logos(read_json(DATA / "fixtures.json", []) or []),
        caisse=dict(reglement=caisse.REGLEMENT, coach=caisse.COACH, saison=config.get("saison"),
                    anniversaires=birthdays(caisse.COACH),
                    tresoriers=[p["cle"] for p in players if p.get("tresorier")],
                    propositions=caisse.proposals(with_sheet, roster, [p["cle"] for p in players if p["cle"].startswith("R:")]
                                                  + [caisse.COACH], config.get("saison") or "")),
        a_venir=sorted((dict(poule=str(f.get("poule")), journee=f.get("journee"), date=f.get("date"),
                             provisoire=bool(f.get("date_provisoire")), dom=f.get("home"), ext=f.get("away"),
                             forfait=out_of(f))
                        for f in fixtures + forfeited if f.get("score_home") is None),
                       key=lambda r: r["date"] or "9999")[:40],
        equipes=profiles, joueurs=players, duos=pairs(with_sheet), plans=PLANS,
        saison=saison, axes=axes,
    )


if __name__ == "__main__":
    import json
    d = analyze()
    print(json.dumps(d["meta"], ensure_ascii=False))

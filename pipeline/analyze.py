"""Calcule classements, profils d'équipes, notes des joueurs et associations.

Entrées : data/matches/*.json, data/fixtures.json, roster.csv, config.yml
Sortie  : dictionnaire prêt pour le tableau de bord (docs/data.json).
"""
import csv
import itertools
import math
import random
import re
import statistics
from collections import Counter, defaultdict

from .common import (DATA, ROOT, is_club, load_config, load_matches, match_name, name_key,
                     norm, paris_now, read_json, same_team)

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
        seasons.append(season)
    return seasons


def history_profiles(seasons, profiles, matches, config):
    """Ce que la saison passée dit des équipes d'aujourd'hui : bilan et classement, confrontations
    avec le club, part de l'effectif de cette saison déjà là, devenir des meilleurs buteurs.
    Renvoie aussi, pour la simulation, la force relative de chaque équipe et sa continuité."""
    priors = {}
    same = lambda a, b: same_team(a, b) or (is_club(a, config) and is_club(b, config))
    for prof in profiles.values():
        prof.setdefault("passe", None)
    for season in seasons[-1:]:  # la saison la plus récente
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
            now = {name_key(pl["name"]) for m in matches for side in ("home", "away") if m[side]["name"] == team
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
            prof["passe"] = dict(saison=season["saison"], j=len(mine), v=res.count("V"), n=res.count("N"),
                                 d=res.count("D"), bp_moy=round(bp / len(mine), 1), bc_moy=round(bc / len(mine), 1),
                                 rangs=rangs, face_a_face=face, continuite=cont, buteurs=buteurs,
                                 feuilles=sum(1 for m, side in mine if (m.get("players") or {}).get(side)))
            # continuité inconnue (pas encore de feuille cette saison) : la saison passée compte à moitié
            c = cont["deja"] / cont["sur"] if cont else 0.5
            priors[team] = ((bp / len(mine)) / avg, (bc / len(mine)) / avg, c)
    return priors


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


def load_roster():
    path = ROOT / "roster.csv"
    roster = {}
    if path.exists():
        with path.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                if (row.get("nom") or "").strip():
                    dispo = norm(row.get("disponible") or "oui") not in ("NON", "0", "FALSE", "N")
                    roster[name_key(row["nom"])] = dict(nom=row["nom"].strip(),
                                                        poste=(row.get("poste") or "").strip().upper(),
                                                        disponible=dispo)
    return roster


HIST = 0.5  # poids d'un match de la saison passée face à un match de la saison en cours
FIABLE = (3, 6)  # matchs comptés (saison passée pour HIST) : en deçà du 1er, note fragile ; du 2e, indicative


def reliability(m, m_past):
    """Sur combien de matchs repose une note : ceux de la saison, plus ceux de la saison passée
    comptés pour HIST, et ce que cela vaut (fragile, indicative, solide ; aucune sans match)."""
    n = m + HIST * m_past
    level = "aucune" if not n else "fragile" if n < FIABLE[0] else "indicative" if n < FIABLE[1] else "solide"
    return dict(matchs=round(n, 1), saison=m, passee=m_past, niveau=level)


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
            rec["journal"].append(dict(date=m.get("date"), adv=opp, res=outcome(gf, ga),
                                       score=f"{gf}-{ga}", buts=g, tirs=p.get("shots"),
                                       jaunes=p.get("yellow") or 0,
                                       deux_min=p.get("two_min") or 0,
                                       rouges=p.get("red") or 0,
                                       arrets=p.get("saves") or 0, pris=pris,
                                       pct=save_pct(p["saves"], pris) if pris is not None else None))
    return players, any_events


EMPTY = dict(m=0, buts=0, pen=0, tirs=0, tirs_connus=0, arrets=0, jaunes=0, deux_min=0, rouges=0,
             w_buts=0.0, w=0.0, pris=0, cadres=0, nums=Counter())


def club_players(matches, config, roster, history=()):
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
    past, _ = player_stats(past_ws, lambda i: HIST * DECAY ** (n_sheet + n_past - 1 - i))
    saison_passee = max((c[0].get("saison") or "" for c in past_ws), default="") or None
    for key, h in past.items():  # joueurs de la saison passée encore dans l'effectif
        if key not in players and match_name(h["nom"], roster):
            players[key] = dict(EMPTY, cle=key, nom=h["nom"], nums=Counter(), clutch=0, diffs=[], journal=[],
                                tranches=0, m_deroule=0, estime=False)
    all_diffs = [gf - ga for _, _, _, gf, ga in with_sheet]
    blend = lambda r, h, k: r[k] + HIST * h[k]
    hist_of = lambda r: past.get(r["cle"], EMPTY)
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
            assid=mw / (n_sheet + HIST * n_past) if n_sheet + n_past else 0,
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
        passe = dict(saison=saison_passee, m=h["m"], buts=h["buts"], pen=h["pen"], tirs=h["tirs"] or None,
                     reussite=round(100 * h["tirs_connus"] / h["tirs"]) if h["tirs"] else None,
                     arrets=h["arrets"], pct_arrets=save_pct(h["cadres"] - h["pris"], h["pris"]),
                     jaunes=h["jaunes"], deux_min=h["deux_min"], rouges=h["rouges"]) if h["m"] else None
        nums = r["nums"] + h["nums"]
        out.append(dict(
            # clé stable : un poste saisi avant le premier match reste attaché au joueur
            cle="R:" + rkey if rkey else r["cle"], nom=r["nom"],
            num=(r["nums"] or nums).most_common(1)[0][0] if nums else None,
            poste=poste, gardien=gk, disponible=ros.get("disponible", True),
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
            scores=scores, journal=r["journal"], passe=passe, fiabilite=reliability(m, h["m"]),
            note_base="saison" if m and not h["m"] else "saison et " + saison_passee if m else saison_passee))
    out.sort(key=lambda p: -p["scores"]["equilibre"])
    # joueurs de l'effectif jamais inscrits sur une feuille : listés, sans note
    for rkey, ros in sorted(roster.items(), key=lambda kv: norm(kv[1].get("nom") or kv[0])):
        if rkey in seen:
            continue
        out.append(dict(
            cle="R:" + rkey, nom=ros.get("nom") or rkey.title(), num=None, poste=ros.get("poste", ""),
            gardien="GB" in (ros.get("poste") or "").split("/"), disponible=ros.get("disponible", True),
            m=0, m_total=n_sheet, presence=None, min_deux=0, buts=0, pen=0, tirs=None, reussite=None,
            arrets=0, pris=None, tirs_subis=None, pct_arrets=None, pris_estime=False,
            jaunes=0, deux_min=0, rouges=0, buts_moy=0, forme_buts=0, impact=0, decisifs=0,
            comps={k: 0 for k in ("att", "eff", "disc", "imp", "clutch", "assid", "gk", "gk_vol")},
            scores={plan: None for plan in PLANS}, journal=[], passe=None, note_base=None,
            fiabilite=reliability(0, 0)))
    return out, club_matches, with_sheet


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


def poule_view(matches, teams, official):
    """Classement recalculé, et écarts éventuels avec celui de la fédération (pénalités, forfaits)."""
    rows = standings(matches, teams)
    off = {norm(k): v for k, v in official_table(official).items()}
    off_j = {norm(k): v for k, v in official_table(official, ("J",)).items()}
    # moins de matchs joués côté fédération : son classement n'est pas encore à jour
    gaps = [dict(equipe=r["equipe"], officiel=off[norm(r["equipe"])], calcule=r["pts"],
                 retard=off_j.get(norm(r["equipe"])) is not None and off_j[norm(r["equipe"])] < r["j"])
            for r in rows if off.get(norm(r["equipe"])) is not None and off[norm(r["equipe"])] != r["pts"]]
    return dict(classement=rows, ecarts=gaps, officiel_lu=bool(off))


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

    by_poule = defaultdict(list)
    for m in matches:
        by_poule[str(m.get("poule"))].append(m)
    teams = known_teams(fixtures, official)
    profiles = team_profiles(matches, teams)
    seasons = load_history()
    priors = history_profiles(seasons, profiles, matches, config)
    for team, prof in profiles.items():
        plan, why = recommend_plan(prof, profiles)
        prof["plan"], prof["plan_raison"] = plan, why
    players, club_matches, with_sheet = club_players(matches, config, roster,
                                                     history=(seasons[-1].get("matches") or []) if seasons else ())

    club_name = next((t for t in profiles if is_club(t, config)), None)
    upcoming = sorted((f for f in fixtures if f.get("score_home") is None
                       and (f.get("date") or "9999") >= today
                       and (is_club(f.get("home"), config) or is_club(f.get("away"), config))),
                      key=lambda f: f.get("date") or "9999")
    nxt = None
    if upcoming:
        f = upcoming[0]
        dom = is_club(f.get("home"), config)
        nxt = dict(id=f["id"], date=f.get("date"), provisoire=bool(f.get("date_provisoire")), salle=f.get("salle"),
                   adversaire=f["away"] if dom else f["home"],
                   domicile=dom, journee=f.get("journee"), poule=f.get("poule"))

    squad = config.get("effectif_feuille", "auto")
    if squad == "auto":
        squad = max((len(m["players"][s]) for m, s, *_ in with_sheet), default=12)
        squad = min(16, max(7, squad))

    n_fdme = sum(1 for m in matches if (m.get("players") or {}).get("home"))
    club_poule = profiles[club_name]["poule"] if club_name else None
    target = int((config.get("objectif") or {}).get("rang", 1))
    saison = (outlook(matches, fixtures, club_name, club_poule, target, known=teams.get(str(club_poule), ()),
                      priors=priors)
              if club_name else None)
    axes = training_axes(club_name, profiles, [p for p in players if p["m"]])
    return dict(
        meta=dict(genere=paris_now().strftime("%Y-%m-%d %H:%M"),
                  saison=config.get("saison"), club=club_name,
                  club_court=config["club"]["nom_affiche"],
                  demo=any((m.get("source") or {}).get("demo") for m in matches),
                  matchs=len(matches), feuilles=n_fdme, effectif=squad,
                  gardiens=int(config.get("gardiens_feuille", 2)), postes_clefs=config.get("postes_clefs") or [],
                  club_matchs=len(club_matches), club_feuilles=len(with_sheet),
                  historique=[x.get("saison") for x in seasons]),
        prochain=nxt,
        poules={p: poule_view(by_poule.get(p, []), teams.get(p, ()), official.get(p))
                for p in sorted(set(by_poule) | set(teams))},
        resultats=sorted((dict(id=m["id"], poule=str(m.get("poule")), journee=m.get("journee"),
                               date=m.get("date"), dom=m["home"]["name"], ext=m["away"]["name"],
                               sd=m["home"]["score"], se=m["away"]["score"],
                               feuille=bool((m.get("players") or {}).get("home")))
                          for m in matches), key=lambda r: r["date"] or "", reverse=True),
        a_venir=sorted((dict(poule=str(f.get("poule")), journee=f.get("journee"), date=f.get("date"),
                             provisoire=bool(f.get("date_provisoire")), dom=f.get("home"), ext=f.get("away"))
                        for f in fixtures if f.get("score_home") is None),
                       key=lambda r: r["date"] or "9999")[:40],
        equipes=profiles, joueurs=players, duos=pairs(with_sheet), plans=PLANS,
        saison=saison, axes=axes,
    )


if __name__ == "__main__":
    import json
    d = analyze()
    print(json.dumps(d["meta"], ensure_ascii=False))

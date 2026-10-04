"""Calcule classements, profils d'équipes, notes des joueurs et associations.

Entrées : data/matches/*.json, data/fixtures.json, roster.csv, config.yml
Sortie  : dictionnaire prêt pour le tableau de bord (docs/data.json).
"""
import csv
import datetime as dt
import itertools
import re
import random
import statistics
from collections import Counter, defaultdict

from .common import (DATA, ROOT, is_club, load_config, load_matches, match_name, name_key,
                     norm, read_json)

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
    rows = list(table.values())
    for r in rows:
        r["diff"] = r["bp"] - r["bc"]
        r["forme"] = r["forme"][-5:]
    rows.sort(key=lambda r: (-r["pts"], -r["diff"], -r["bp"], r["equipe"]))
    for i, r in enumerate(rows, 1):
        r["rang"] = i
    return rows


def team_profiles(matches, teams_by_poule=None):
    """Profil de chaque équipe des deux poules (repérage des adversaires)."""
    acc = defaultdict(lambda: dict(matches=[], scorers=defaultdict(
        lambda: dict(buts=0, pen=0, m=0, num=None)), jaunes=0, deux_min=0, rouges=0,
        periods_for=[0] * 6, periods_against=[0] * 6, has_events=0))
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
            for p in m.get("players", {}).get(side, []):
                key = norm(p.get("name")) or f"N{p.get('num')}"
                s = a["scorers"][key]
                s["nom"] = p.get("name") or f"n° {p.get('num')}"
                s["num"] = p.get("num")
                s["buts"] += p.get("goals") or 0
                s["pen"] += p.get("pen_goals") or 0
                s["m"] += 1
                a["jaunes"] += p.get("yellow") or 0
                a["deux_min"] += p.get("two_min") or 0
                a["rouges"] += p.get("red") or 0
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
                          moy=round(s["buts"] / max(1, s["m"]), 1), m=s["m"])
                     for s in scorers if s["buts"] > 0],
            periodes_bp=[round(x / a["has_events"], 1) for x in a["periods_for"]] if a["has_events"] else None,
            periodes_bc=[round(x / a["has_events"], 1) for x in a["periods_against"]] if a["has_events"] else None,
        )
    for poule, teams in (teams_by_poule or {}).items():
        for team in teams:
            out.setdefault(team, dict(
                equipe=team, poule=poule, j=0, bp_moy=None, bc_moy=None, forme=[], matches=[],
                mt1_bp=None, mt2_bp=None, mt1_bc=None, mt2_bc=None, jaunes_moy=None, deux_min_moy=None,
                rouges=None, buteurs=[],
                periodes_bp=None, periodes_bc=None))
    return out


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


def club_players(matches, config, roster):
    """Agrège les statistiques individuelles du club et calcule les notes."""
    club_matches = []
    for m in sorted(matches, key=lambda x: x.get("date") or ""):
        for side, team, opp, gf, ga in sides(m):
            if is_club(team, config):
                club_matches.append((m, side, opp, gf, ga))
    n_total = len(club_matches)
    with_sheet = [c for c in club_matches if c[0].get("players", {}).get(c[1])]
    n_sheet = len(with_sheet)
    players = {}
    any_events = False
    for idx, (m, side, opp, gf, ga) in enumerate(with_sheet):
        weight = DECAY ** (n_sheet - 1 - idx)
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
        for p in m["players"][side]:
            key = norm(p.get("name")) or f"N{p.get('num')}"
            rec = players.setdefault(key, dict(
                cle=key, nom=p.get("name") or f"n° {p.get('num')}", nums=Counter(),
                m=0, buts=0, pen=0, tirs=0, tirs_connus=0, arrets=0, jaunes=0, deux_min=0,
                rouges=0, clutch=0, w_buts=0.0, w=0.0, diffs=[], journal=[],
                tranches=0, m_deroule=0))
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
                                       score=f"{gf}-{ga}", buts=g,
                                       jaunes=p.get("yellow") or 0,
                                       deux_min=p.get("two_min") or 0,
                                       rouges=p.get("red") or 0,
                                       arrets=p.get("saves") or 0))
    all_diffs = [gf - ga for _, _, _, gf, ga in with_sheet]
    max_form = max((r["w_buts"] / r["w"] for r in players.values()), default=0) or 1
    max_clutch = max((r["clutch"] / r["m"] for r in players.values()), default=0) or 1
    max_saves = max((r["arrets"] / r["m"] for r in players.values()), default=0) or 1
    out = []
    seen = set()
    for r in players.values():
        rkey = match_name(r["nom"], roster)
        seen.add(rkey)
        ros = roster.get(rkey, {})
        if ros.get("nom"):
            r["nom"] = ros["nom"]  # l'orthographe de l'effectif fait foi à l'affichage
        poste = ros.get("poste", "")
        gk = poste == "GB" or (not poste and r["arrets"] > r["buts"] and r["arrets"] > 0)
        m = r["m"]
        without = n_sheet - m
        rest = (sum(all_diffs) - sum(r["diffs"])) / without if without else None
        raw_imp = (sum(r["diffs"]) / m - rest) if rest is not None else 0.0
        shrink = min(m, without) / (min(m, without) + 2) if without else 0.0
        impact = raw_imp * shrink
        penal = (r["deux_min"] + 3 * r["rouges"] + 0.3 * r["jaunes"]) / m
        comps = dict(
            att=(r["w_buts"] / r["w"]) / max_form,
            eff=(r["tirs_connus"] + 2.5) / (r["tirs"] + 5) if r["tirs"] else 0.5,
            disc=max(0.0, 1 - penal / 2),
            imp=min(1.0, max(0.0, 0.5 + impact / 16)),
            clutch=(r["clutch"] / m) / max_clutch if any_events else 0.5,
            assid=m / n_sheet if n_sheet else 0,
            gk=(r["arrets"] / m) / max_saves if gk else 0,
        )
        scores = {}
        for plan, w in PLANS.items():
            if gk:
                val = 0.6 * comps["gk"] + 0.25 * comps["imp"] + 0.15 * comps["assid"]
            else:
                val = sum(w[k] * comps[k] for k in w)
            scores[plan] = round(100 * val)
        out.append(dict(
            # clé stable : un poste saisi avant le premier match reste attaché au joueur
            cle="R:" + rkey if rkey else r["cle"], nom=r["nom"], num=r["nums"].most_common(1)[0][0],
            poste=poste, gardien=gk, disponible=ros.get("disponible", True),
            m=m, m_total=n_sheet, buts=r["buts"], pen=r["pen"],
            presence=round(r["tranches"] / r["m_deroule"], 1) if r["m_deroule"] else None,
            min_deux=2 * r["deux_min"], tirs=r["tirs"] or None,
            arrets=r["arrets"], jaunes=r["jaunes"], deux_min=r["deux_min"], rouges=r["rouges"],
            buts_moy=round(r["buts"] / m, 1),
            forme_buts=round(r["w_buts"] / r["w"], 1),
            impact=round(impact, 1), decisifs=r["clutch"],
            comps={k: round(v, 2) for k, v in comps.items()},
            scores=scores, journal=r["journal"]))
    out.sort(key=lambda p: -p["scores"]["equilibre"])
    # joueurs de l'effectif jamais inscrits sur une feuille : listés, sans note
    for rkey, ros in sorted(roster.items(), key=lambda kv: norm(kv[1].get("nom") or kv[0])):
        if rkey in seen:
            continue
        out.append(dict(
            cle="R:" + rkey, nom=ros.get("nom") or rkey.title(), num=None, poste=ros.get("poste", ""),
            gardien=ros.get("poste") == "GB", disponible=ros.get("disponible", True),
            m=0, m_total=n_sheet, presence=None, min_deux=0, buts=0, pen=0, tirs=None, arrets=0,
            jaunes=0, deux_min=0, rouges=0, buts_moy=0, forme_buts=0, impact=0, decisifs=0,
            comps={k: 0 for k in ("att", "eff", "disc", "imp", "clutch", "assid", "gk")},
            scores={plan: None for plan in PLANS}, journal=[]))
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


def outlook(matches, fixtures, club, poule, target=1, sims=10000, seed=38160, known=()):
    """Course au classement : chances d'atteindre le rang visé et enjeu de chaque match.

    Chaque match restant est simulé à partir des moyennes de buts marqués et
    encaissés, ramenées vers la moyenne de la poule tant qu'il y a peu de matchs.
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
    k = 3  # poids de la moyenne de poule, en matchs
    att = {t: ((r["bp"] + k * avg) / (r["j"] + k)) / avg for t, r in table.items()}
    dfn = {t: ((r["bc"] + k * avg) / (r["j"] + k)) / avg for t, r in table.items()}
    rng = random.Random(seed)

    def play(f):
        mh = avg * att[f["home"]] * dfn[f["away"]] * 1.04
        ma = avg * att[f["away"]] * dfn[f["home"]] * 0.96
        return (max(0, round(rng.gauss(mh, mh ** 0.5))), max(0, round(rng.gauss(ma, ma ** 0.5))))

    def season(force_win=False):
        pts = {t: r["pts"] for t, r in table.items()}
        diff = {t: r["diff"] for t, r in table.items()}
        res = {}
        for f in rest:
            gh, ga = play(f)
            if force_win and club in (f["home"], f["away"]):
                if (gh <= ga) == (f["home"] == club) or gh == ga:
                    hi, lo = max(gh, ga) + (gh == ga), min(gh, ga)
                    gh, ga = (hi, lo) if f["home"] == club else (lo, hi)
            pts[f["home"]] += POINTS[outcome(gh, ga)]
            pts[f["away"]] += POINTS[outcome(ga, gh)]
            diff[f["home"]] += gh - ga
            diff[f["away"]] += ga - gh
            if club in (f["home"], f["away"]):
                res[f["id"]] = outcome(gh, ga) if f["home"] == club else outcome(ga, gh)
        order = sorted(pts, key=lambda t: (-pts[t], -diff[t], rng.random()))
        return order.index(club) + 1 <= target, res

    ok_total = 0
    stat = {f["id"]: dict(v=0, v_ok=0, o=0, o_ok=0) for f in mine}
    for _ in range(sims):
        ok, res = season()
        ok_total += ok
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
    for f in mine:
        s = stat[f["id"]]
        dom = f["home"] == club
        adv = f["away"] if dom else f["home"]
        si_v = 100 * s["v_ok"] / s["v"] if s["v"] else None
        si_o = 100 * s["o_ok"] / s["o"] if s["o"] else None
        enjeu = round(si_v) - round(si_o) if si_v is not None and si_o is not None else None
        base["matchs"].append(dict(
            id=f["id"], date=f.get("date"), provisoire=bool(f.get("date_provisoire")),
            journee=f.get("journee"), adversaire=adv, domicile=dom,
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
    today = today or dt.date.today().isoformat()
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
    for team, prof in profiles.items():
        plan, why = recommend_plan(prof, profiles)
        prof["plan"], prof["plan_raison"] = plan, why
    players, club_matches, with_sheet = club_players(matches, config, roster)

    club_name = next((t for t in profiles if is_club(t, config)), None)
    upcoming = sorted((f for f in fixtures if f.get("score_home") is None
                       and (f.get("date") or "9999") >= today
                       and (is_club(f.get("home"), config) or is_club(f.get("away"), config))),
                      key=lambda f: f.get("date") or "9999")
    nxt = None
    if upcoming:
        f = upcoming[0]
        dom = is_club(f.get("home"), config)
        nxt = dict(date=f.get("date"), provisoire=bool(f.get("date_provisoire")),
                   adversaire=f["away"] if dom else f["home"],
                   domicile=dom, journee=f.get("journee"), poule=f.get("poule"))

    squad = config.get("effectif_feuille", "auto")
    if squad == "auto":
        squad = max((len(m["players"][s]) for m, s, *_ in with_sheet), default=12)
        squad = min(16, max(7, squad))

    n_fdme = sum(1 for m in matches if (m.get("players") or {}).get("home"))
    club_poule = profiles[club_name]["poule"] if club_name else None
    target = int((config.get("objectif") or {}).get("rang", 1))
    saison = (outlook(matches, fixtures, club_name, club_poule, target, known=teams.get(str(club_poule), ()))
              if club_name else None)
    axes = training_axes(club_name, profiles, [p for p in players if p["m"]])
    return dict(
        meta=dict(genere=dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
                  saison=config.get("saison"), club=club_name,
                  club_court=config["club"]["nom_affiche"],
                  demo=any((m.get("source") or {}).get("demo") for m in matches),
                  matchs=len(matches), feuilles=n_fdme, effectif=squad,
                  club_matchs=len(club_matches), club_feuilles=len(with_sheet)),
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

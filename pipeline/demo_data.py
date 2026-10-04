"""Génère un jeu de données FICTIF pour tester la chaîne sans le site FFHB.

Usage : python -m pipeline.demo_data
Toutes les équipes (sauf le nom du club) et tous les joueurs sont inventés.
"""
import datetime as dt
import random

from .common import DATA, MATCHES, write_json

CLUB = "HB PAYS DE ST MARCELLIN"
FICTIFS = ["Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot",
           "Golf", "Hotel", "India", "Juliett", "Kilo"]
POSTES = ["GB", "GB", "ALG", "ALG", "ARG", "ARG", "DC", "DC",
          "ARD", "ARD", "ALD", "ALD", "PIV", "PIV"]
NUMS = [1, 12, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 14]


def round_robin(teams):
    """Calendrier aller simple (méthode du cercle)."""
    teams = list(teams)
    n = len(teams)
    days = []
    for d in range(n - 1):
        day = []
        for i in range(n // 2):
            a, b = teams[i], teams[n - 1 - i]
            day.append((a, b) if (d + i) % 2 == 0 else (b, a))
        days.append(day)
        teams = [teams[0]] + [teams[-1]] + teams[1:-1]
    return days


def make_squad(rng, team, idx):
    squad = []
    for k, (num, poste) in enumerate(zip(NUMS, POSTES)):
        name = (f"Joueur {k + 1:02d}" if team == CLUB
                else f"Fictif {idx}{k + 1:02d}")
        squad.append({"num": num, "name": name, "poste": poste,
                      "level": rng.uniform(0.4, 1.6),
                      "rough": rng.uniform(0.2, 1.8)})
    return squad


def simulate(rng, mid, poule, journee, date, home, away, squads, strength):
    sheet = {}
    for side, team in (("home", home), ("away", away)):
        gks = [p for p in squads[team] if p["poste"] == "GB"]
        field = [p for p in squads[team] if p["poste"] != "GB"]
        sheet[side] = gks + rng.sample(field, 10)
    stats = {s: {p["num"]: dict(num=p["num"], name=p["name"], goals=0,
                                pen_goals=0, shots=0, saves=0, yellow=0,
                                two_min=0, red=0) for p in sheet[s]}
             for s in sheet}
    events, score = [], [0, 0]
    out = set()  # disqualifiés : le troisième 2 minutes vaut carton rouge
    t = 0
    base = {"home": 0.52 + 0.06 * (strength[home] - strength[away]),
            "away": 0.48 + 0.06 * (strength[away] - strength[home])}
    ht = None
    while t < 3600:
        t += rng.randint(25, 70)
        if t >= 3600:
            break
        if ht is None and t >= 1800:
            ht = list(score)
        side = "home" if rng.random() < 0.5 else "away"
        other = "away" if side == "home" else "home"
        field = [p for p in sheet[side] if p["poste"] != "GB" and (side, p["num"]) not in out]
        shooter = rng.choices(field, [p["level"] for p in field])[0]
        st = stats[side][shooter["num"]]
        roll = rng.random()
        idx = 0 if side == "home" else 1
        if roll < 0.06:  # sanction : un seul avertissement par joueur, rouge au troisième 2 minutes
            bad = rng.choices(field, [p["rough"] for p in field])[0]
            sb = stats[side][bad["num"]]
            kind = "yellow" if t < 900 and rng.random() < 0.6 and not sb["yellow"] else "two_min"
            sb[kind] += 1
            events.append(dict(t=t, side=side, type=kind, num=bad["num"],
                               score=list(score)))
            if sb["two_min"] == 3:
                sb["red"] = 1
                out.add((side, bad["num"]))
                events.append(dict(t=t, side=side, type="red", num=bad["num"], score=list(score)))
            continue
        pen = roll < 0.14
        st["shots"] += 1
        if rng.random() < base[side] + (0.2 if pen else 0):
            st["goals"] += 1
            if pen:
                st["pen_goals"] += 1
            score[idx] += 1
            events.append(dict(t=t, side=side,
                               type="pen_goal" if pen else "goal",
                               num=shooter["num"], score=list(score)))
        else:
            events.append(dict(t=t, side=side, type="miss",
                               num=shooter["num"], score=list(score)))
            if rng.random() < 0.6:
                gk = sheet[other][0]
                stats[other][gk["num"]]["saves"] += 1
                events.append(dict(t=t, side=other, type="save",
                                   num=gk["num"], score=list(score)))
    ht = ht or list(score)
    return {
        "id": mid, "poule": poule, "journee": journee, "date": date,
        "played": True,
        "home": {"name": home, "score": score[0], "ht": ht[0]},
        "away": {"name": away, "score": score[1], "ht": ht[1]},
        "players": {s: list(stats[s].values()) for s in stats},
        "events": events,
        "source": {"fdme": True, "demo": True},
    }


def generate(played_days=3, seed=38160, data_dir=DATA, matches_dir=MATCHES):
    rng = random.Random(seed)
    poules = {
        "71": [CLUB] + [f"Équipe fictive {n}" for n in FICTIFS[:5]],
        "72": [f"Équipe fictive {n}" for n in FICTIFS[5:11]],
    }
    squads, strength = {}, {}
    for teams in poules.values():
        for team in teams:
            squads[team] = make_squad(rng, team, len(squads) + 1)
            strength[team] = rng.uniform(-1, 1)
    strength[CLUB] = 0.9  # le club joue le haut de tableau dans la démonstration
    start = dt.date(2026, 9, 19)
    fixtures, mid = [], 1000
    for poule, teams in poules.items():
        aller = round_robin(teams)
        retour = [[(b, a) for a, b in day] for day in aller]
        for d, day in enumerate(aller + retour):
            date = start + dt.timedelta(days=7 * d)
            for home, away in day:
                mid += 1
                iso = f"{date.isoformat()}T20:30"
                fx = dict(id=str(mid), poule=poule, journee=d + 1, date=iso,
                          home=home, away=away, score_home=None,
                          score_away=None, url="", pdf_url="")
                if d < played_days:
                    m = simulate(rng, str(mid), poule, d + 1, iso, home, away,
                                 squads, strength)
                    write_json(matches_dir / f"{mid}.json", m)
                    fx["score_home"] = m["home"]["score"]
                    fx["score_away"] = m["away"]["score"]
                fixtures.append(fx)
    write_json(data_dir / "fixtures.json", fixtures)
    roster = [{"nom": p["name"], "poste": p["poste"], "disponible": True}
              for p in squads[CLUB]]
    return {"fixtures": fixtures, "roster": roster}


if __name__ == "__main__":
    out = generate()
    print(f"{len(out['fixtures'])} rencontres fictives générées")

"""Faux site + fausses feuilles PDF pour tester la chaîne de bout en bout.

La structure reprend ce qui a été relevé sur ffhandball.fr le 04/10/2026 : données dans
le HTML servi (<smartfire-component name=… attributes="json">), poules désignées par un
identifiant interne (poule-<id>), une page par journée, feuille de match à l'adresse tirée
de son code. La feuille imite la FDME : un seul tableau où chaque équipe a sa ligne
d'en-tête, puis un déroulé sur deux colonnes sans numéro de joueur. Équipes et joueurs
sont inventés.
"""
import html
import json
import pathlib

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet

VERB = {"goal": "But", "pen_goal": "But 7m", "miss": "Tir", "save": "Arrêt",
        "yellow": "Avertissement", "two_min": "2MN", "red": "Disqualification"}
POULE_IDS = {"71": "9071", "99": "9099"}


def code(fid):
    return f"TST{fid}"


def clock(t):
    """Horloge de la feuille : « 59:32 », puis « 01:00:00 » à partir de la 60e minute."""
    return f"{t // 3600:02d}:{t % 3600 // 60:02d}:{t % 60:02d}" if t >= 3600 else f"{t // 60:02d}:{t % 60:02d}"


def page(folder, blocks):
    """Écrit une page dont les données sont dans le HTML, comme sur le site."""
    folder.mkdir(parents=True, exist_ok=True)
    tags = "".join(f"<smartfire-component name='{name}' attributes=\"{html.escape(json.dumps(data))}\">"
                   f"</smartfire-component>\n" for name, data in blocks.items())
    (folder / "index.html").write_text(f"<!doctype html><html><body>\n{tags}</body></html>", "utf-8")


def make_pdf(match, path):
    doc = SimpleDocTemplate(str(path), pagesize=A4)
    h, a = match["home"], match["away"]
    head = ["Capt", "N°", "NOM Prénom (Nom d'usage)", "Licence", "Type", "JFL",
            "Buts", "7m", "Tirs", "Arrets", "Av.", "2'", "Dis"]
    blank = [""] * 14
    rows = [["Code Renc " + code(match["id"])] + blank[1:],
            [f"{h['name']} / {a['name']}"] + blank[1:12] + [str(h["score"]), str(a["score"])]]
    spans = [0, 1]  # lignes dont la première case couvre la largeur, comme sur la feuille réelle
    names = {}
    for side, label in (("home", "Club recevant"), ("away", "Club visiteur")):
        rows.append([label[::-1]] + head)  # la case verticale sort à l'envers du PDF réel
        for p in match["players"][side]:
            names[(side, p["num"])] = p["name"]
            rows.append(["", "", str(p["num"]), p["name"], "6138012100123", "A", "",
                         str(p["goals"] or ""), str(p["pen_goals"] or ""), str(p["shots"] or ""),
                         str(p["saves"] or ""), "X" if p["yellow"] else "", str(p["two_min"] or ""),
                         "X" if p["red"] else ""])
        rows.append(["Officiel Resp. A", "", "", "OFFICIEL Inventé", "6138012100124"] + blank[5:])
    rows += [["Détail score", "Période 1"] + blank[2:], ["", "REC", "VIS"] + blank[3:],
             ["", str(h["ht"]), str(a["ht"])] + blank[3:]]
    table = Table(rows, colWidths=[50, 20, 20, 90, 60, 20, 20, 22, 20, 22, 26, 20, 18, 20])
    table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                               ("FONTSIZE", (0, 0), (-1, -1), 6)]
                              + [("SPAN", (0, r), (11, r)) for r in spans]))
    # déroulé : première période à gauche, seconde à droite, sans numéro ni équipe
    lines = [(e["t"], [clock(e["t"]), "{:02d} - {:02d}".format(*e["score"]),
                       f"{VERB[e['type']]} {names[(e['side'], e['num'])]}"]) for e in match["events"]]
    before = [e["score"] for e in match["events"] if e["t"] <= 1500] or [[0, 0]]
    lines.append((1500, [clock(1500), "{:02d} - {:02d}".format(*before[-1]), "Temps mort Visiteur"]))
    lines.append((1500, [clock(1500), "{:02d} - {:02d}".format(*before[-1]), "Commotion Joueur Inventé"]))
    lines.sort(key=lambda x: x[0])
    first = [r for t, r in lines if t <= 1800]
    second = [r for t, r in lines if t > 1800]
    pairs = [(first[i] if i < len(first) else ["", "", ""]) + [""] + (second[i] if i < len(second) else ["", "", ""])
             for i in range(max(len(first), len(second)))]
    deroule = Table(pairs, colWidths=[32, 35, 110, 20, 32, 35, 110])
    deroule.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 6)]))
    title = getSampleStyleSheet()["Heading2"]
    doc.build([table, PageBreak(), Paragraph("Déroulé du match", title), deroule])


def build(root, matches, fixtures, poule, sans_date=()):
    """Faux site d'une poule sous root/ ; renvoie l'adresse relative de la compétition.
    sans_date : identifiants de rencontres dont l'horaire n'est pas encore fixé."""
    root = pathlib.Path(root)
    comp = root / "competition"
    by_id = {m["id"]: m for m in matches}
    fx = [f for f in fixtures if f["poule"] == poule]
    days = sorted({f["journee"] for f in fx})
    calendar = json.dumps([dict(journee_numero=d, date_debut=min(f["date"][:10] for f in fx if f["journee"] == d),
                                date_fin="") for d in days])
    poules = [dict(ext_pouleId=pid, libelle=f"POULE {num}", journees=calendar) for num, pid in POULE_IDS.items()]
    page(comp, {"competitions---poule-selector": dict(poules=poules)})
    base = comp / f"poule-{POULE_IDS[poule]}"
    table = [dict(place=str(i), equipe_libelle=t, point="0", joue="0")
             for i, t in enumerate(sorted({f["home"] for f in fx}), 1)]

    def day_blocks(d):
        rows = []
        for f in (x for x in fx if x["journee"] == d):
            m = by_id.get(f["id"])
            rows.append(dict(ext_rencontreId=f["id"], journeeNumero=str(d),
                             date=None if f["id"] in sans_date else f["date"] + ":00+02:00",
                             equipe1Libelle=f["home"], equipe2Libelle=f["away"],
                             equipe1Score=str(f["score_home"]) if f["score_home"] is not None else None,
                             equipe2Score=str(f["score_away"]) if f["score_away"] is not None else None,
                             equipe1ScoreMT=str(m["home"]["ht"]) if m else None,
                             equipe2ScoreMT=str(m["away"]["ht"]) if m else None,
                             fdmCode=code(f["id"])))
            if m:
                c = code(f["id"])
                target = root / "fdm" / "/".join(c[:4]) / f"{c}.pdf"
                target.parent.mkdir(parents=True, exist_ok=True)
                make_pdf(m, target)
        poule_info = dict(ext_pouleId=POULE_IDS[poule], libelle=f"POULE {poule}", journees=calendar)
        return {"competitions---journee-selector": dict(poule=poule_info, selected_numero_journee=str(d)),
                "competitions---rencontre-list": dict(poule=poule_info, selected_numero_journee=str(d),
                                                      rencontres=rows),
                "competitions---mini-classement-or-ads": dict(classements=table)}

    current = next((d for d in days if any(f["journee"] == d and f["score_home"] is None for f in fx)), days[-1])
    page(base, day_blocks(current))
    for d in days:
        page(base / f"journee-{d}", day_blocks(d))
    return "competition/"

"""Lit les feuilles de match (PDF) et produit un JSON par rencontre.

Usage : python -m pipeline.parse_fdme
Entrées : data/fixtures.json (collecte) + raw/fdme/<id>.pdf
Sorties : data/matches/<id>.json

Forme de la feuille FDME relevée en 2026-2027 :
  page 1   un seul tableau. Pour chaque équipe (recevant puis visiteur), une ligne d'en-tête
           « Capt | N° | NOM Prénom | Licence | Type | JFL | Buts | 7m | Tirs | Arrets | Av. | 2' | Dis »
           puis une ligne par joueur. Buts compte les 7 m marqués, Tirs compte tous les tirs
           (buts compris) ; Av. et Dis valent « X ». La case d'équipe, écrite à la verticale,
           sort à l'envers (« tnavecer bulC »).
  page 2+  déroulé sur deux colonnes : « mm:ss  sh - sa  Action NOM Prénom », sans numéro ni
           équipe : on les retrouve par le nom dans le tableau, ou par le score pour un but.
Feuille des saisons précédentes (2025-2026 et avant), lue elle aussi : mêmes tableaux, mais
les mots collés (« DUPONTjean », « ButJRN°51DUPONTjean ») ; le déroulé y donne l'équipe
(JR recevant, JV visiteur) et le numéro du joueur.
Les numéros de licence ne sont jamais conservés, ni les commotions (donnée de santé).
"""
import json
import re
import sys

from .common import DATA, MATCHES, RAW, load_config, match_name, name_key, norm, read_json, write_json

TIME = r"(?:\d{1,2}:)?\d{1,2}:\d{2}"  # « 59:32 », puis « 01:00:00 » à la 60e minute
EVENT_RE = re.compile(r"(?<![\d:])(%s)\s+(\d{1,2})\s*-\s*(\d{1,2})\s+(.+?)"
                      r"(?=\s+%s\s+\d{1,2}\s*-\s*\d{1,2}\s|$)" % (TIME, TIME))
ACTIONS = [  # (début de l'action, type) — du plus précis au plus général ; None = ignorée
    ("BUT 7M", "pen_goal"), ("BUT", "goal"), ("TIR 7M", "miss"), ("TIR", "miss"),
    ("ARRET 7M", "save"), ("ARRET", "save"),
    # trois sanctions à ne pas confondre : avertissement (carton jaune), exclusion de 2 minutes,
    # disqualification (carton rouge, que le carton bleu complète d'un rapport)
    ("AVERTISSEMENT", "yellow"), ("CARTON JAUNE", "yellow"),
    ("2MN", "two_min"), ("2 MN", "two_min"), ("2 MIN", "two_min"),
    ("DISQUALIFICATION", "red"), ("CARTON ROUGE", "red"), ("CARTON BLEU", "blue"),
    ("TEMPS MORT", "timeout"),
    # ancienne feuille : qui entre et sort des buts (pour attribuer les buts pris) ; jamais gardés :
    # commotion et protocole commotion (donnée de santé), temps de régulation comportementale
    ("ENTREE GARDIEN", "gk_in"), ("SORTIE GARDIEN", "gk_out"),
    ("COMMOTION", None), ("PROTOCOLE COMMOTION", None), ("TEMPS DE REGULATION", None),
]
OLD_RE = re.compile(r"^(.+?)J([RV])N°(\d{1,2})(.*)$")  # « ButJRN°51DUPONTjean », ancienne feuille
HEADERS = {"num": ("N", "NO", "NUM"), "name": ("NOM",), "goals": ("BUTS",), "pen_goals": ("7M",),
           "shots": ("TIRS",), "saves": ("ARRETS", "ARRET"), "yellow": ("AV",),
           "two_min": ("2", "2MN", "2 MN"), "red": ("DIS", "DISQ")}


def mask(text):
    """Masque les suites de 6 chiffres ou plus (numéros de licence)."""
    return re.sub(r"\d{6,}", "######", text or "")


def split_name(name):
    """« DUPONTjean » (ancienne feuille, nom et prénom collés) -> « DUPONT jean »."""
    # l'ancienne feuille répète souvent le nom après le prénom (« DUPONTjean-DUPONT ») : retiré ;
    # elle écrit le prénom en minuscules : majuscule initiale. Sans effet sur un nom déjà propre.
    name = re.sub(r"([A-ZÀ-Ý'-]{2,})([a-zà-ÿ])", r"\1 \2", name or "")
    repeated = re.fullmatch(r"(.+?) (.+)-\1", name)
    if repeated:
        name = f"{repeated.group(1)} {repeated.group(2)}"
    return re.sub(r"(?<![A-Za-zÀ-ÿ])[a-zà-ÿ]", lambda c: c.group().upper(), name)


def match_action(label):
    """Type d'action d'après le début du libellé, avec ou sans espaces (ancienne feuille)."""
    compact = label.replace(" ", "")
    return next(((pat, typ) for pat, typ in ACTIONS if label.startswith(pat)
                 or compact.startswith(pat.replace(" ", ""))), None)


def mark(value):
    """Valeur d'une case : un nombre, ou « X » (= 1)."""
    value = str(value or "").strip().upper()
    if value == "X":
        return 1
    m = re.search(r"\d+", value)
    return int(m.group()) if m else 0


def card(value):
    """Case Av. ou Dis : un carton au plus par joueur, quelle que soit la marque (X, D, R, 1…)."""
    value = str(value or "").strip()
    return 0 if value in ("", "0", "-") else 1


def parse_events(text, unknown=None):
    """Événements du déroulé, sans nom de joueur : {t, type, score, actor}.
    unknown : compteur des actions non reconnues, par leur premier mot seulement (jamais un nom)."""
    events = []
    for line in text.splitlines():
        for m in EVENT_RE.finditer(line):
            clock, sh, sa, rest = m.groups()
            t = 0
            for part in clock.split(":"):
                t = t * 60 + int(part)
            old = OLD_RE.match(rest.strip())
            label = norm(old.group(1) if old else rest)
            hit = match_action(label)
            if not hit and unknown is not None and label:
                unknown[label.split()[0]] = unknown.get(label.split()[0], 0) + 1
            if not hit or hit[1] is None or t > 5400:  # prolongations comprises
                continue
            event = dict(t=t, type=hit[1], score=[int(sh), int(sa)])
            if old:  # l'ancienne feuille donne l'équipe et le numéro
                event.update(actor=split_name(" ".join(mask(old.group(4)).split())) or None,
                             side="home" if old.group(2) == "R" else "away", num=int(old.group(3)))
            elif hit[1] == "timeout":  # « Temps mort Visiteur », ou « TempsMortd'EquipeVisiteur » (ancienne)
                compact = label.replace(" ", "")
                event["actor"] = "Visiteur" if "VISITEUR" in compact else "Recevant" if "RECEVANT" in compact else None
            else:
                event["actor"] = " ".join(mask(rest).split()[len(hit[0].split()):]) or None
            events.append(event)
    events.sort(key=lambda e: e["t"])
    return events


def parse_tables(tables):
    """Joueurs de chaque équipe : chaque ligne d'en-tête (avec « Buts ») ouvre une équipe."""
    teams = []
    for table in tables:
        cols = None
        for row in table:
            cells = [norm(c) for c in row]
            if "BUTS" in cells:
                cols = {}
                for field, names in HEADERS.items():
                    for j, c in enumerate(cells):
                        if (c in names or (field == "name" and c.startswith("NOM"))) and field not in cols:
                            cols[field] = j
                label = " ".join(c or "" for c in row)
                label = norm(label) + " " + norm(label[::-1])
                teams.append(dict(side="away" if "CLUB VISITEUR" in label else
                                  "home" if "CLUB RECEVANT" in label else None, players=[]))
                continue
            if not cols or "num" not in cols or "name" not in cols:
                continue

            def cell(field):
                j = cols.get(field)
                return row[j] if j is not None and j < len(row) else None
            num = str(cell("num") or "").strip()
            name = split_name(" ".join(mask(str(cell("name") or "")).replace("#", " ").split()))
            if not re.fullmatch(r"\d{1,2}", num) or len(name) < 3:
                continue
            teams[-1]["players"].append(dict(
                num=int(num), name=name, goals=mark(cell("goals")), pen_goals=mark(cell("pen_goals")),
                shots=mark(cell("shots")) or None, saves=mark(cell("saves")),
                yellow=card(cell("yellow")), two_min=mark(cell("two_min")), red=card(cell("red"))))
    teams = [t for t in teams if t["players"]][:2]  # une équipe peut n'aligner que 5 joueurs
    if len(teams) != 2:
        return None
    if [t["side"] for t in teams] == ["away", "home"]:
        teams.reverse()
    return {"home": teams[0]["players"], "away": teams[1]["players"]}


def sheet_scores(tables):
    """(score final, score à la mi-temps) lus dans l'en-tête et le « Détail score » de la feuille."""
    final = ht = None
    for table in tables:
        for i, row in enumerate(table):
            nums = [int(c) for c in row if re.fullmatch(r"\d{1,3}", str(c or "").strip())]
            if final is None and " / " in str(row[0] or "") and len(nums) == 2:
                final = nums
            if ht is None and any(norm(c) == "PERIODE 1" for c in row):
                for nxt in table[i + 1:i + 4]:
                    vals = [int(c) for c in nxt if re.fullmatch(r"\d{1,3}", str(c or "").strip())]
                    if len(vals) >= 2:
                        ht = vals[:2]
                        break
    return final, ht


def attribute(events, players):
    """Équipe et numéro de chaque événement, par le nom (tableau) ou par le score (but)."""
    index = {}
    for side, plist in (players or {}).items():
        for p in plist:
            index[name_key(p["name"])] = (side, p["num"])
    prev = [0, 0]
    out = []
    for e in events:
        side, num = e.get("side"), e.get("num")
        key = match_name(e["actor"], index) if e["actor"] and num is None else None
        if key:
            side, num = index[key]
        elif e["type"] == "timeout":
            label = norm(e["actor"])
            side = "home" if "RECEVANT" in label else "away" if "VISITEUR" in label else None
        if e["type"] in ("goal", "pen_goal"):
            by_score = "home" if e["score"][0] > prev[0] else "away" if e["score"][1] > prev[1] else None
            if by_score and by_score != side:  # le score fait foi pour l'équipe
                side, num = by_score, None
            prev = e["score"]
        out.append(dict(t=e["t"], side=side, type=e["type"], num=num, score=e["score"],
                        actor=e["actor"]))
    return out


def players_from_events(events):
    """Solution de repli sans tableau : statistiques individuelles depuis le déroulé."""
    out = {"home": {}, "away": {}}
    field = {"goal": "goals", "pen_goal": "goals", "save": "saves",
             "yellow": "yellow", "two_min": "two_min", "red": "red"}
    for e in events:
        if e["side"] not in out or not (e["actor"] or e["num"] is not None):
            continue
        key = e["num"] if e["num"] is not None else name_key(e["actor"])
        p = out[e["side"]].setdefault(key, dict(
            num=e["num"], name=e["actor"] or "", goals=0, pen_goals=0,
            shots=0, saves=0, yellow=0, two_min=0, red=0))
        if e["type"] in field:
            p[field[e["type"]]] += 1
        if e["type"] == "pen_goal":
            p["pen_goals"] += 1
        if e["type"] in ("goal", "pen_goal", "miss"):
            p["shots"] += 1
    return {s: sorted(v.values(), key=lambda p: (p["num"] is None, p["num"] or 0, p["name"]))
            for s, v in out.items()}


def parse_pdf(path):
    import pdfplumber
    texts, tables = [], []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            texts.append(page.extract_text() or "")
            try:
                tables += page.extract_tables() or []
            except Exception:
                pass
    text = "\n".join(texts)
    table_players = parse_tables(tables)
    unknown = {}
    events = attribute(parse_events(text, unknown), table_players)
    quality = dict(tableaux_joueurs=2 if table_players else 0, evenements=len(events))
    if unknown:  # une nouvelle façon d'écrire une action (un carton rouge, par exemple) se verra ici
        quality["actions_inconnues"] = unknown
    if table_players:
        players = table_players
        quality["source_joueurs"] = "tableau"
    elif any(players_from_events(events).values()):
        players = players_from_events(events)
        quality["source_joueurs"] = "deroule"
    else:
        players = {"home": [], "away": []}
        quality["source_joueurs"] = "aucune"
    final, ht = sheet_scores(tables)
    half = [e["score"] for e in events if e["t"] <= 1800]
    ht = ht or (half[-1] if half else None)
    final = final or (events[-1]["score"] if events else None)
    if events and final and events[-1]["score"] != final:
        quality["deroule_incomplet"] = True
    return dict(players=players, events=[{k: v for k, v in e.items() if k != "actor"} for e in events],
                ht=ht, final=final, quality=quality,
                sample=dict(text=mask(text), tables=json.loads(mask(json.dumps(tables, ensure_ascii=False)))))


def build_match(fx, parsed=None):
    match = dict(
        id=str(fx["id"]), poule=str(fx.get("poule")), journee=fx.get("journee"),
        date=fx.get("date"), played=fx.get("score_home") is not None,
        home=dict(name=fx.get("home"), score=fx.get("score_home"), ht=fx.get("ht_home")),
        away=dict(name=fx.get("away"), score=fx.get("score_away"), ht=fx.get("ht_away")),
        players={"home": [], "away": []}, events=[],
        source=dict(fdme=False, url=fx.get("url")))
    if parsed:
        match["players"] = parsed["players"]
        match["events"] = parsed["events"]
        if parsed["ht"] and match["home"]["ht"] is None:
            match["home"]["ht"], match["away"]["ht"] = parsed["ht"]
        if match["home"]["score"] is None and parsed["final"]:
            match["home"]["score"], match["away"]["score"] = parsed["final"]
            match["played"] = True
        elif parsed["final"] and parsed["final"] != [match["home"]["score"], match["away"]["score"]]:
            match["source"].setdefault("alertes", []).append(
                "score du site {}-{}, de la feuille {}-{}".format(
                    match["home"]["score"], match["away"]["score"], *parsed["final"]))
        # une feuille ne compte comme lue que si le match a un score : sinon on la relira
        match["source"].update(fdme=parsed["quality"]["source_joueurs"] != "aucune" and match["played"],
                               qualite=parsed["quality"])
        # contrôle de cohérence : total des buts des joueurs = score
        for side in ("home", "away"):
            total = sum(p["goals"] for p in match["players"][side])
            if match["players"][side] and match[side]["score"] is not None \
                    and total != match[side]["score"]:
                match["source"].setdefault("alertes", []).append(
                    f"{side}: {total} buts individuels pour un score de {match[side]['score']}")
    return match


def main():
    config = load_config()
    fixtures = read_json(DATA / "fixtures.json", []) or []
    samples = 0
    report = dict(lus=0, sans_pdf=0, erreurs=0, alertes=0)
    for fx in fixtures:
        pdf = RAW / "fdme" / f"{fx['id']}.pdf"
        target = MATCHES / f"{fx['id']}.json"
        existing = read_json(target)
        parsed = None
        if pdf.exists():
            try:
                parsed = parse_pdf(pdf)
                report["lus"] += 1
                for word, n in parsed["quality"].get("actions_inconnues", {}).items():
                    report.setdefault("actions_inconnues", {})[word] = report.get("actions_inconnues", {}).get(word, 0) + n
                if config.get("echantillons_debug") and samples < 2:
                    samples += 1
                    write_json(RAW / "sample" / f"fdme_{samples}.json", parsed["sample"])
            except Exception as exc:  # une feuille illisible ne bloque pas la chaîne
                report["erreurs"] += 1
                print(f"[fdme] {pdf.name}: {exc}", file=sys.stderr)
        elif fx.get("score_home") is not None:
            report["sans_pdf"] += 1
        if fx.get("score_home") is None and not parsed:
            continue
        match = build_match(fx, parsed)
        if existing and (existing.get("source") or {}).get("fdme") and not match["source"]["fdme"]:
            continue  # ne pas écraser une feuille déjà lue
        report["alertes"] += len(match["source"].get("alertes", []))
        write_json(target, match)
    write_json(DATA / "rapport_extraction.json", report)
    print(f"[fdme] {report}")


if __name__ == "__main__":
    main()

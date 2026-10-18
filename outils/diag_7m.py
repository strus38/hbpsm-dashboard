"""Diagnostic ponctuel (branche diag-7m) : comment les feuilles écrivent-elles un 7 m manqué ?

Lit raw/fdme/*.pdf et écrit diag/feuilles-7m.json SANS AUCUN NOM : libellés d'actions du déroulé
(le joueur retiré), forme des cases des tableaux (chiffres remplacés par « d »), en-têtes de colonnes.
Tout mot d'un nom vu sur une feuille ou dans l'effectif est retiré ; le fichier est relu avant écriture.
"""
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

import pdfplumber

from pipeline.common import RAW, norm
from pipeline.parse_fdme import EVENT_RE, parse_tables

OUT = Path("diag/feuilles-7m.json")


def shape(value):
    return re.sub(r"\d", "d", str(value if value is not None else "").strip())


def main():  # noqa
    roster_words = {w for line in (os.environ.get("HBPSM_EFFECTIF") or "").splitlines()
                    for w in norm(line.split(",")[0]).split() if len(w) >= 2}
    all_names = set(roster_words)
    labels, cells, headers, lines7, per_match = Counter(), Counter(), Counter(), Counter(), []
    pdfs = sorted((RAW / "fdme").glob("*.pdf"))
    for pdf_path in pdfs:
        texts, tables = [], []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                texts.append(page.extract_text() or "")
                try:
                    tables += page.extract_tables() or []
                except Exception:
                    pass
        players = parse_tables(tables) or {"home": [], "away": []}
        names = {w for side in players.values() for p in side for w in norm(p["name"]).split() if len(w) >= 2}
        all_names |= names
        # en-têtes et forme des cases utiles
        for table in tables:
            cols = None
            for row in table:
                cells_n = [norm(c) for c in row]
                if "BUTS" in cells_n:
                    headers[" | ".join(cells_n)] += 1
                    cols = {c: j for j, c in enumerate(cells_n) if c in ("BUTS", "7M", "TIRS", "ARRETS", "ARRET")}
                    continue
                if cols:
                    for c, j in cols.items():
                        if j < len(row) and row[j] not in (None, ""):
                            cells[f"{c}={shape(row[j])}"] += 1
        stats = Counter()
        for line in "\n".join(texts).splitlines():
            matched = False
            for m in EVENT_RE.finditer(line):
                matched = True
                words = [w for w in norm(m.group(4)).split() if w not in names and w not in roster_words]
                label = " ".join(words)
                labels[label] += 1
                if "7M" in label or "7" in words:
                    stats[label] += 1
            n = norm(line)
            if not matched and ("7M" in n.split() or "7 M" in n):
                lines7[" ".join(w for w in n.split() if w not in names and w not in roster_words and not w.isdigit())] += 1
        table_pen = sum(p.get("pen_goals") or 0 for side in players.values() for p in side)
        per_match.append(dict(pen_tableau=table_pen, deroule_7m=dict(stats)))
    out = dict(signaux=signals(), feuilles=len(pdfs), libelles=labels.most_common(), cases=sorted(cells.items()),
               entetes=headers.most_common(), lignes_7m_hors_deroule=lines7.most_common(40), par_feuille=per_match)
    text = json.dumps(out, ensure_ascii=False, indent=1)
    # relecture : aucun mot d'un nom (3 lettres et plus) ne doit rester
    leaks = {w for w in norm(text).split() if len(w) >= 3 and w in all_names}
    if leaks:
        for w in leaks:
            text = re.sub(rf"\b{re.escape(w)}\b", "‹nom›", text, flags=re.I)
        if {w for w in norm(text).split() if len(w) >= 3 and w in all_names}:
            print("diagnostic refusé : un nom resterait", file=sys.stderr)
            return 1
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    print(f"[diag] {len(pdfs)} feuilles, {sum(labels.values())} événements, {len(labels)} libellés")
    return 0



def signals():
    """Signaux d'un 7 m sur les vraies feuilles (histogrammes seulement, aucun nom) : écart au dernier
    événement, 2 minutes adverse à la même seconde, tireur habituel ; pour les buts 7 m et les autres buts."""
    from pipeline.parse_fdme import attribute, parse_events
    hist = {k: Counter() for k in ("pen_gap", "goal_gap", "pen_2mn", "goal_2mn", "miss_2mn", "miss_2mn_taker",
                                   "miss_taker", "pen_prev", "goal_prev", "miss_prev", "miss_taker_prev")}
    for pdf_path in sorted((RAW / "fdme").glob("*.pdf")):
        texts, tables = [], []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                texts.append(page.extract_text() or "")
                try:
                    tables += page.extract_tables() or []
                except Exception:
                    pass
        players = parse_tables(tables)
        if not players:
            continue
        raw = parse_events("\n".join(texts))
        ev = attribute(raw, players)
        takers = {(s, p["num"]) for s, pl in players.items() for p in pl if p.get("pen_goals")}
        for i, e in enumerate(ev):
            prev = ev[i - 1]["t"] if i else 0
            gap = e["t"] - prev
            two = any(x["type"] == "two_min" and x["side"] and x["side"] != e["side"] and abs(x["t"] - e["t"]) <= 2
                      for x in ev)
            bucket = "0" if gap == 0 else "1-5" if gap <= 5 else "6-20" if gap <= 20 else "21-40" if gap <= 40 else ">40"
            pv = ev[i - 1] if i else None
            prv = "debut" if pv is None else pv["type"] + ("/meme" if pv["side"] == e["side"] else "/autre") + ("@0" if gap == 0 else "@1-5" if gap <= 5 else "")
            if e["type"] == "pen_goal":
                hist["pen_gap"][bucket] += 1
                hist["pen_2mn"][two] += 1
                hist["pen_prev"][prv] += 1
            elif e["type"] == "goal":
                hist["goal_gap"][bucket] += 1
                hist["goal_2mn"][two] += 1
                hist["goal_prev"][prv] += 1
            elif e["type"] == "miss":
                hist["miss_2mn"][two] += 1
                tk = (e["side"], e["num"]) in takers
                hist["miss_taker"][tk] += 1
                hist["miss_prev"][prv] += 1
                if tk:
                    hist["miss_taker_prev"][prv] += 1
                if two:
                    hist["miss_2mn_taker"][tk] += 1
    return {k: {str(a): b for a, b in v.items()} for k, v in hist.items()}


if __name__ == "__main__":
    sys.exit(main())

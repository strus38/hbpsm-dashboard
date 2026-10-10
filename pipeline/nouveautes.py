"""Ce qui a changé d'une publication à l'autre (demande de l'auteur, 10/10/2026 : tout recalculer à chaque nouvelle
feuille, à chaque choix de l'entraîneur avant le match et à tout ce qui peut améliorer les pronostics, et en
avertir chacun par un bandeau).

À chaque publication, la collecte (ou le recalcul que lance une feuille publiée par l'entraîneur) compare les
données qu'elle vient de calculer à celles publiées juste avant (hbpsm.enc, déchiffré) : résultats et feuilles du
club, feuilles et résultats des autres équipes de nos poules, classement, chances d'atteindre l'objectif,
pronostics des prochains matchs, bilans des pronostics, modèle, notes des joueurs, feuilles publiées de
l'entraîneur, propositions du tableau de bord, bilan des choix de l'entraîneur. Un passage qui change quelque
chose ajoute une ligne à data/nouveautes.json (repris de etat.enc) ; la page montre, en bandeau, celles que
l'appareil n'a pas encore vues.

Les éléments `prive` (proposition du tableau de bord, bilan des choix de l'entraîneur) ne s'affichent qu'à
l'entraîneur et à celui qui tient les présences : la proposition tient compte des présences de chacun.
"""
from .common import DATA, read_json, write_json

NAME = "nouveautes.json"   # data/, repris de etat.enc
GARDE = 40                 # lignes gardées
SEUIL_ECART = 0.5          # but : un pronostic qui bouge moins ne se signale pas
SEUIL_P = 3                # points de victoire estimée
SEUIL_CHANCES = 1          # points de chances d'atteindre l'objectif
SEUIL_NOTE = 2             # points de note
PRONOS = 4                 # prochains matchs suivis (la planification)
MODELE = ("dom", "ext", "beta", "gamma")


def _match(m):
    return {k: m.get(k) for k in ("id", "journee", "coupe", "tour", "adversaire", "domicile", "date", "provisoire")}


def _ids(rows):
    return {str(r.get("id")): r for r in rows or []}


def compare(prev, data):
    """Les changements entre les données publiées (prev, None la première fois) et les nouvelles."""
    if not prev or not data:
        return []
    items, club = [], (data.get("meta") or {}).get("club")
    # les matchs du club : un score, une feuille lue
    old = _ids(prev.get("agenda"))
    for m in data.get("agenda") or []:
        o = old.get(str(m["id"]))
        if o is None:
            continue
        read = lambda x: bool(x.get("feuille") or x.get("joueurs"))
        score, sheet = m.get("bp") is not None and o.get("bp") is None, read(m) and not read(o)
        if score or sheet:
            items.append(dict(_match(m), t="resultat", bp=m.get("bp"), bc=m.get("bc"), feuille=read(m), score=score))
    # les autres matchs de nos poules : leurs résultats et leurs feuilles font les forces des adversaires
    was = _ids(prev.get("resultats"))
    others = [r for r in data.get("resultats") or [] if club not in (r.get("dom"), r.get("ext"))]
    res = sum(1 for r in others if str(r.get("id")) not in was)
    sheets = sum(1 for r in others if r.get("feuille") and not (was.get(str(r.get("id"))) or {}).get("feuille"))
    if res or sheets:
        items.append(dict(t="poules", resultats=res, feuilles=sheets))
    s, ps = data.get("saison") or {}, prev.get("saison") or {}
    if s.get("rang") is not None and ps.get("rang") is not None and s["rang"] != ps["rang"]:
        items.append(dict(t="rang", avant=ps["rang"], apres=s["rang"], poule=s.get("poule")))
    if s.get("proba") is not None and ps.get("proba") is not None and abs(s["proba"] - ps["proba"]) >= SEUIL_CHANCES:
        items.append(dict(t="chances", avant=ps["proba"], apres=s["proba"], cible=s.get("cible")))
    # les pronostics des prochains matchs ; un match nouveau au calendrier (tour de coupe)
    before = _ids(ps.get("matchs"))
    for m in (s.get("matchs") or [])[:PRONOS]:
        o = before.get(str(m["id"]))
        if o is None:
            if before:
                items.append(dict(_match(m), t="match", ecart=m.get("ecart"), p=m.get("p_victoire")))
            continue
        de, dp = m.get("ecart"), m.get("p_victoire")
        moved = (de is not None and o.get("ecart") is not None and abs(de - o["ecart"]) >= SEUIL_ECART
                 or dp is not None and o.get("p_victoire") is not None and abs(dp - o["p_victoire"]) >= SEUIL_P)
        if moved:
            items.append(dict(_match(m), t="prono", avant=dict(ecart=o.get("ecart"), p=o.get("p_victoire")),
                              apres=dict(ecart=de, p=dp)))
    # un pronostic confronté à la feuille ; le modèle qui réapprend
    pp, np_ = prev.get("pronostics") or {}, data.get("pronostics") or {}
    done = {str(x.get("id")) for x in pp.get("matchs") or [] if x.get("apres")}
    for x in np_.get("matchs") or []:
        if x.get("apres") and str(x.get("id")) not in done:
            a = x["apres"]
            items.append(dict(_match(x), t="bilan", pour=x.get("pour"), contre=x.get("contre"), ecart=x.get("ecart"),
                              bp=a.get("bp"), bc=a.get("bc"), reel=a.get("ecart")))
    mo, mn = pp.get("modele") or {}, np_.get("modele") or {}
    if mo and mn and any(mo.get(k) != mn.get(k) for k in MODELE):
        items.append(dict(t="modele", matchs=mn.get("n_matchs"), feuilles=mn.get("n_feuilles")))
    # les notes des joueurs
    notes = {p["cle"]: (p.get("scores") or {}).get("equilibre") for p in prev.get("joueurs") or []}
    moved = [p["cle"] for p in data.get("joueurs") or []
             if notes.get(p["cle"]) is not None and (p.get("scores") or {}).get("equilibre") is not None
             and abs(p["scores"]["equilibre"] - notes[p["cle"]]) >= SEUIL_NOTE]
    if moved:
        items.append(dict(t="notes", n=len(moved)))
    # les feuilles publiées de l'entraîneur ; la proposition du tableau de bord (présences comprises : privé)
    so, sn = _ids((prev.get("selections") or {}).get("matchs")), _ids((data.get("selections") or {}).get("matchs"))
    for mid, e in sn.items():
        o = so.get(mid) or {}
        if e.get("retenue") and e["retenue"] != o.get("retenue"):
            items.append(dict(_match(e), t="choix", etat="modifiee" if o.get("retenue") else "publiee"))
        if e.get("auto") and o.get("auto") and e["auto"] != o["auto"]:
            items.append(dict(_match(e), t="proposition", prive=True, plus=sorted(set(e["auto"]) - set(o["auto"])),
                              moins=sorted(set(o["auto"]) - set(e["auto"]))))
    for mid, o in so.items():
        if o.get("retenue") and not (sn.get(mid) or {}).get("retenue"):
            items.append(dict(_match(o), t="choix", etat="retiree"))
    io, inn = pp.get("influence") or {}, np_.get("influence") or {}
    if inn.get("n") and inn.get("n") != io.get("n"):
        items.append(dict(t="influence", prive=True, n=inn["n"], diff=inn.get("diff"), marge=inn.get("marge")))
    return items


def record(items, source, now):
    """Ajoute la ligne de ce passage (source : « collecte » ou « recalcul ») s'il a changé quelque chose ; renvoie
    les lignes gardées, de la plus ancienne à la plus récente."""
    log = read_json(DATA / NAME, []) or []
    if items and not (log and log[-1].get("items") == items):   # une publication refusée puis refaite : pas deux fois
        log = (log + [dict(le=now, source=source, items=items)])[-GARDE:]
        write_json(DATA / NAME, log)
    return log

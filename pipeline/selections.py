"""Ce que l'entraîneur retient face à ce que le tableau de bord propose (demande de l'auteur, 09/10/2026 : garder
la différence entre les propositions et les choix de l'entraîneur, pour mieux comprendre ses choix ; 10/10/2026 :
garder en mémoire chaque proposition et mesurer si ces choix pèsent sur les résultats).

Quand une feuille est publiée (l'entraîneur, ou celui qui tient les présences pour lui), la page joint la
proposition du tableau de bord pour ce match (`suggestion` : la feuille proposée sans ce choix, présences
comprises). choix.enc ne garde que les matchs proches : la collecte archive donc chaque feuille publiée dans
data/selections.json (repris de etat.enc), avec la proposition et, une fois lue, la feuille du match. Ce qui est
retenu ne bouge plus après le coup d'envoi.

Sans feuille publiée, la proposition reste gardée : à chaque collecte et à chaque recalcul, la page elle-même
calcule celle de chaque match à venir (pipeline/suggestions.py, `auto`), et la dernière avant le coup d'envoi
l'emporte. Le choix de l'entraîneur est alors la feuille du match.

Sortie (données chiffrées seulement, D.selections) : les matchs de la saison, du plus ancien au plus récent ; la
page en tire les écarts, match par match et joueur par joueur, et pipeline/pronostic.py ce qu'ils ont donné.
"""
from .common import DATA, read_json, write_json
from .pronostic import kickoff

NAME = "selections.json"


def _load():
    return dict((read_json(DATA / NAME, {}) or {}).get("matchs") or {})


def _view(kept, saison):
    return dict(matchs=sorted((dict(e, id=k) for k, e in kept.items() if e.get("saison") == saison),
                              key=lambda e: e.get("date") or ""))


def _describe(e, m, saison):
    e.update(saison=e.get("saison") or saison, date=m.get("date"), adversaire=m.get("adversaire"),
             domicile=m.get("domicile"), journee=m.get("journee"), coupe=m.get("coupe"), tour=m.get("tour"))
    if m.get("joueurs"):
        e["feuille"] = sorted(m["joueurs"])
    return e


def record(choix, agenda, now, saison):
    """choix : feuilles publiées {match: {joueurs, le, suggestion}} (analyze.published_choices) ; agenda : matchs
    du club (analyze.club_agenda) ; now : « AAAA-MM-JJTHH:MM », heure de Paris ; saison : « 2026-2027 »."""
    kept = _load()
    for m in agenda:
        mid, c = str(m["id"]), (choix or {}).get(str(m["id"])) or {}
        e = dict(kept.get(mid) or {})
        kick = kickoff(m)
        started = bool(kick and now >= kick)
        if c.get("joueurs") and not (e.get("retenue") and started):
            e.update(retenue=sorted(c["joueurs"]), le=c.get("le"))
            if c.get("suggestion"):
                e["proposee"] = sorted(c["suggestion"])
        elif choix and e.get("retenue") and kick and not started:
            for k in ("retenue", "le", "proposee"):   # validation retirée avant le match : la proposition calculée reste
                e.pop(k, None)
        if not (e.get("retenue") or e.get("auto")):
            kept.pop(mid, None)
            continue
        kept[mid] = _describe(e, m, saison)
    write_json(DATA / NAME, dict(v=1, matchs=kept))
    return _view(kept, saison)


def record_auto(auto, agenda, now, saison):
    """auto : {match: [clés]}, la feuille que le tableau de bord propose à cet instant pour chaque match à venir
    (pipeline/suggestions.py). Gardée jusqu'au coup d'envoi : la dernière avant lui l'emporte."""
    kept = _load()
    for m in agenda:
        mid, kick = str(m["id"]), kickoff(m)
        if not (auto or {}).get(mid) or (kick and now >= kick):
            continue
        e = dict(kept.get(mid) or {})
        if e.get("auto") != sorted(auto[mid]):   # l'heure ne bouge qu'avec la proposition : rien à republier sinon
            e.update(auto=sorted(auto[mid]), auto_le=now)
        kept[mid] = _describe(e, m, saison)
    write_json(DATA / NAME, dict(v=1, matchs=kept))
    return _view(kept, saison)

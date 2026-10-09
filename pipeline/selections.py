"""Ce que l'entraîneur retient face à ce que le tableau de bord propose (demande de l'auteur, 09/10/2026 : garder
la différence entre les propositions et les choix de l'entraîneur, pour mieux comprendre ses choix).

Quand une feuille est publiée (l'entraîneur, ou celui qui tient les présences pour lui), la page joint la
proposition du tableau de bord pour ce match (`suggestion` : la feuille proposée sans ce choix, présences
comprises). choix.enc ne garde que les matchs proches : la collecte archive donc chaque feuille publiée dans
data/selections.json (repris de etat.enc), avec la proposition et, une fois lue, la feuille du match. Ce qui est
retenu ne bouge plus après le coup d'envoi.

Sortie (données chiffrées seulement, D.selections) : les matchs de la saison, du plus ancien au plus récent ; la
page en tire les écarts, match par match et joueur par joueur.
"""
from .common import DATA, read_json, write_json
from .pronostic import kickoff

NAME = "selections.json"


def record(choix, agenda, now, saison):
    """choix : feuilles publiées {match: {joueurs, le, suggestion}} (analyze.published_choices) ; agenda : matchs
    du club (analyze.club_agenda) ; now : « AAAA-MM-JJTHH:MM », heure de Paris ; saison : « 2026-2027 »."""
    kept = dict((read_json(DATA / NAME, {}) or {}).get("matchs") or {})
    for m in agenda:
        mid, c = str(m["id"]), (choix or {}).get(str(m["id"])) or {}
        e = dict(kept.get(mid) or {})
        kick = kickoff(m)
        if c.get("joueurs") and not (e.get("retenue") and kick and now >= kick):
            e.update(retenue=sorted(c["joueurs"]), le=c.get("le"))
            if c.get("suggestion"):
                e["proposee"] = sorted(c["suggestion"])
        elif choix and e.get("retenue") and kick and now < kick:
            e = {}   # validation retirée avant le match
        if not e.get("retenue"):
            kept.pop(mid, None)
            continue
        e.update(saison=e.get("saison") or saison, date=m.get("date"), adversaire=m.get("adversaire"),
                 domicile=m.get("domicile"), journee=m.get("journee"), coupe=m.get("coupe"), tour=m.get("tour"))
        if m.get("joueurs"):
            e["feuille"] = sorted(m["joueurs"])
        kept[mid] = e
    write_json(DATA / NAME, dict(v=1, matchs=kept))
    return dict(matchs=sorted((dict(e, id=k) for k, e in kept.items() if e.get("saison") == saison),
                              key=lambda e: e.get("date") or ""))

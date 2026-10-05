"""Caisse noire du groupe : le règlement, les amendes proposées d'après les feuilles de match, et
le registre des amendes et des paiements, publié chiffré.

Le règlement de la saison (document du groupe) est repris ici point par point : la page s'en
sert pour proposer et justifier chaque amende. Les trésoriers (et l'entraîneur), qui ont le
jeton de publication, saisissent les amendes et les paiements ; chaque saisie part chiffrée au
workflow « Caisse noire » (caisse.yml), que ce module applique au registre publie/caisse.enc.
Une amende proposée d'après une feuille n'existe qu'une fois validée par un trésorier.

Usage (dans le workflow) : HBPSM_CLE=… HBPSM_CAISSE='{coffre}' python -m pipeline.caisse
"""
import datetime as dt
import json
import os
import sys

from . import common, vault
from .common import match_name, name_key, read_json, write_json

NAME = "caisse.enc"
COACH = "STAFF:COACH"   # l'entraîneur, membre de la caisse sans être sur l'effectif

# Le règlement 2026-2027, point par point : partie, titre, montant (None : voté, ou en nature),
# unité, rappel du texte. « auto » : proposée d'après les feuilles de match.
REGLEMENT = [
    dict(code="cotisation", partie="Saison", titre="Frais de participation", montant=5, unite="saison", emoji="🎟️",
         texte="Cotisation de 5 € pour la saison, réglée le premier mois (septembre).", auto=True),
    dict(code="bon_point", partie="Saison", titre="Bon point !", montant=1, unite="mois sans amende", emoji="😇",
         texte="Les bons élèves qui finissent le mois sans amende versent une amende participative de 1 €.", auto=True),
    dict(code="retard_paiement", partie="Saison", titre="Échéance des paiements", montant=1, unite="entraînement de retard",
         emoji="⏳", texte="Paiement avant ou après l'entraînement suivant l'annonce des amendes : 1 € par entraînement de retard."),
    dict(code="fausse_denonciation", partie="Saison", titre="Dénonciation", montant=1, unite="fausse dénonciation",
         emoji="🙊", texte="La dénonciation est encouragée ; une dénonciation qui s'avère fausse coûte 1 €."),
    dict(code="bienvenue", partie="Saison", titre="Bienvenue !", montant=None, unite="vote", emoji="🎤",
         texte="Bizutage des nouvelles recrues ; en cas d'oubli ou de refus, participation forfaitaire votée.", vote=True),
    dict(code="exceptionnelle", partie="Saison", titre="Situation exceptionnelle", montant=None, unite="vote", emoji="🚨",
         texte="Faute grave qui pénalise toute l'équipe (ébriété, oubli des maillots ou du sac de ballons…) : montant voté.", vote=True),
    dict(code="presse_nom", partie="Saison", titre="À vos plus beaux sourires !", montant=1, unite="présence du nom",
         emoji="📰", texte="Toute apparition du nom dans la presse ou sur les réseaux : 1 €."),
    dict(code="presse_photo", partie="Saison", titre="À vos plus beaux sourires !", montant=1, unite="présence sur une photo",
         emoji="📸", texte="Toute apparition en photo dans la presse ou sur les réseaux : 1 € (hors photos d'équipe en match)."),
    dict(code="e_sporteasy", partie="Entraînement", titre="Absence / Retard", montant=1, unite="non-renseignement SportEasy",
         emoji="📵", texte="Présence ou absence renseignée sur SportEasy au moins 4 jours avant, 21 h au plus tard."),
    dict(code="e_retard", partie="Entraînement", titre="Absence / Retard", montant=1, unite="tranche de 5 min de retard",
         emoji="🐢", texte="À l'heure SportEasy, sur le terrain, en tenue complète et échauffé : 1 € par tranche de 5 minutes."),
    dict(code="e_oubli", partie="Entraînement", titre="Tête en l'air", montant=1, unite="élément oublié", emoji="🧦",
         texte="Tout oubli de matériel (chasuble, gourde, chaussures, serviette…), emprunts compris : 1 € par élément."),
    dict(code="e_tir_tete", partie="Entraînement", titre="Tireur d'élite", montant=1, unite="tir dans la tête", emoji="🎯",
         texte="Tir dans la tête à l'entraînement, défenseur, gardien ou partenaire : 1 €."),
    dict(code="e_hygiene", partie="Entraînement", titre="Propreté / Hygiène", montant=1, unite="acte dégueulasse", emoji="🤢",
         texte="Tout acte dégueulasse au vestiaire, sur le terrain ou en déplacement : 1 €."),
    dict(code="e_mauvais_esprit", partie="Entraînement", titre="Mauvais esprit", montant=None, unite="vote", emoji="😤",
         texte="Mauvaise attitude, contestation d'arbitrage ou d'amende répétée : montant voté par l'équipe.", vote=True),
    dict(code="e_assiduite", partie="Entraînement", titre="Assiduité", montant=1, unite="semaine sans entraînement", emoji="🛋️",
         texte="Au moins un entraînement par semaine, celui du vendredi ; seuls les blessés (avec preuve) y échappent."),
    dict(code="socquette", partie="Entraînement", titre="Faute de goût", montant=1, unite="port de socquettes", emoji="🩲",
         texte="Socquettes interdites aux entraînements comme aux matchs : 1 €."),
    dict(code="e_scotch", partie="Entraînement", titre="Scotch / Pastis", montant=1, unite="scotch", emoji="🧱",
         texte="Tout scotch à l'entraînement, jeux compris (pas à l'échauffement) : 1 €."),
    dict(code="e_fin_temps", partie="Entraînement", titre="Hop hop hop, fin du temps !", montant=1, unite="5 min dépassées",
         emoji="⏱️", texte="Pour le coach : 1 € par tranche de 5 minutes au-delà du créneau (rentrée au vestiaire)."),
    dict(code="m_sporteasy", partie="Match", titre="Absence / Retard", montant=2, unite="non-renseignement SportEasy",
         emoji="📵", texte="Présence ou absence au match renseignée sur SportEasy au moins 5 jours avant, 21 h au plus tard."),
    dict(code="m_retard", partie="Match", titre="Absence / Retard", montant=2, unite="tranche de 5 min de retard", emoji="🐢",
         texte="À l'heure et au lieu de rendez-vous du coach : 2 € par tranche de 5 minutes."),
    dict(code="m_oubli", partie="Match", titre="Tête en l'air", montant=2, unite="élément oublié", emoji="🧥",
         texte="Tout oubli de matériel le jour du match (veste du club et t-shirt d'échauffement obligatoires) : 2 €."),
    dict(code="m_tir_tete", partie="Match", titre="Tireur d'élite", montant=2, unite="tir dans la tête", emoji="🎯",
         texte="Tir dans la tête en match, défenseur, gardien ou partenaire : 2 €."),
    dict(code="m_2e_2min", partie="Match", titre="Fair-play", montant=2, unite="2e exclusion de 2 min", emoji="🟥",
         texte="Les bouchers sont sanctionnés, et les sanctions se cumulent : 2 € la 2e exclusion de 2 minutes.", auto=True),
    dict(code="m_2min_contestation", partie="Match", titre="Fair-play", montant=3, unite="2 min sur contestation",
         emoji="🗣️", texte="Exclusion de 2 minutes pour contestation : 3 €."),
    dict(code="m_3x2min", partie="Match", titre="Fair-play", montant=5, unite="3e exclusion (3 × 2 min)", emoji="🟥",
         texte="Trois exclusions de 2 minutes dans le match : 5 €, en plus de la 2e.", auto=True),
    dict(code="m_expulsion", partie="Match", titre="Fair-play", montant=10, unite="expulsion directe", emoji="🟥",
         texte="Carton rouge direct (disqualification sans trois exclusions) : 10 €.", auto=True),
    dict(code="m_mauvais_esprit", partie="Match", titre="Mauvais esprit", montant=None, unite="vote", emoji="😤",
         texte="Mauvaise attitude, contestation d'arbitrage ou d'amende répétée : montant voté par l'équipe.", vote=True),
    dict(code="m_relance", partie="Match", titre="Relances", montant=0.5, unite="relance manquée", emoji="🧤",
         texte="Gardiens : relance manquée, 0,50 € à partir de la 2e du match."),
    dict(code="m_penalty", partie="Match", titre="Gérard Penaldo", montant=1, unite="penalty manqué", emoji="🥅",
         texte="Penalty manqué : 1 € à partir du 2e échec du match."),
    dict(code="m_penalty_hors_cadre", partie="Match", titre="Gérard Penaldo", montant=2, unite="penalty hors cadre",
         emoji="🥅", texte="Penalty hors cadre : 2 €, dès le premier."),
    dict(code="m_precision", partie="Match", titre="Précision", montant=1, unite="match à moins de 40 % au tir", emoji="🎳",
         texte="Efficacité au tir sous 40 % (au moins un tir), d'après la feuille de match : 1 € par match.", auto=True),
    dict(code="m_heros", partie="Match", titre="Héros du match", montant=1, unite="dernier but du match", emoji="🦸",
         texte="Le dernier buteur de chaque rencontre est félicité par 1 € dans la caisse.", auto=True),
    dict(code="m_humiliation", partie="Match", titre="Humiliation", montant=2, unite="humiliation", emoji="🤡",
         texte="Gardiens : chaque humiliation (lob, roucoulette, chab…), la réaction du banc fait foi : 2 €."),
    dict(code="m_scotch", partie="Match", titre="Scotch / Pastis", montant=2, unite="scotch", emoji="🧱",
         texte="Scotché par le gardien adverse en match : 2 €."),
    dict(code="m_mvp", partie="Match", titre="MVP", montant=2, unite="homme du match", emoji="🏆",
         texte="L'homme du match élu sur SportEasy s'acquitte de 2 €."),
    dict(code="m_fessee", partie="Match", titre="La fessée !", montant=None, unite="tournée du coach", emoji="🍻",
         texte="Victoire d'au moins 20 buts (championnat, coupe ou amical) : tournée ou présent du coach.", auto=True, nature=True),
]
RULES = {r["code"]: r for r in REGLEMENT}
KINDS = {"amende", "refus", "annule", "paiement"}


def _who(name, roster):
    """La clé d'un joueur de la feuille, comme dans la liste des joueurs du tableau de bord."""
    rkey = match_name(name, roster)
    return "R:" + rkey if rkey else name_key(name)


def proposals(with_sheet, roster, members, saison):
    """Les amendes que les feuilles de match permettent de proposer (à valider par un trésorier),
    chacune justifiée par son point du règlement ; plus la cotisation de chacun pour la saison."""
    out = []

    def add(rule, joueur, motif, m=None, n=1, date=None):
        r = RULES[rule]
        out.append(dict(id=f"{rule}:{m['id'] if m else saison}:{joueur}", regle=rule, joueur=joueur, n=n,
                        montant=None if r["montant"] is None else r["montant"] * n,
                        date=(date or (m or {}).get("date") or "")[:10], match=m and m["id"], motif=motif))

    for m, side, opp, gf, ga in with_sheet:
        if gf is None or ga is None:
            continue
        where = f"contre {opp}" + (f" ({m['coupe']})" if m.get("coupe") else "")
        for p in (m.get("players") or {}).get(side, []):
            who, two, red = _who(p.get("name"), roster), p.get("two_min") or 0, p.get("red") or 0
            if two >= 2:
                add("m_2e_2min", who, f"{two} exclusions de 2 min {where}", m)
            if two >= 3:
                add("m_3x2min", who, f"3 exclusions de 2 min {where}", m)
            if red and two < 3:
                add("m_expulsion", who, f"carton rouge direct {where}", m)
            shots, goals = p.get("shots"), p.get("goals") or 0
            if shots and goals / shots < 0.40:
                add("m_precision", who, f"{goals} but{'s' if goals > 1 else ''} sur {shots} tirs ({round(100 * goals / shots)} %) {where}", m)
        goals = [e for e in m.get("events") or [] if e["type"] in ("goal", "pen_goal")]
        last = goals[-1] if goals and goals[-1]["side"] == side else None   # le dernier but est des nôtres
        scorer = last and next((p for p in m["players"][side] if p.get("num") == last.get("num")), None)
        if scorer:
            add("m_heros", _who(scorer.get("name"), roster), f"dernier but du match {where}", m)
        if gf - ga >= 20:
            add("m_fessee", COACH, f"victoire {gf}-{ga} {where}", m)
    for cle in members:
        add("cotisation", cle, f"cotisation de la saison {saison}", date=f"{saison[:4]}-09-01")
    return out


def check(envelope, secret):
    """Les saisies reçues, déchiffrées et vérifiées : chiffrées avec la phrase du club, de la
    forme attendue ; VaultError sinon. Rien n'en est jamais affiché."""
    if not isinstance(envelope, dict) or int(envelope.get("iterations") or 0) != vault.ITERATIONS:
        raise vault.VaultError("Caisse refusée : coffre de forme inattendue.")
    data = vault.decrypt(envelope, secret)
    ops = data.get("ops") if isinstance(data, dict) else None
    if data.get("format") != "hbpsm-caisse-ops" or data.get("v") != 1 or not isinstance(ops, list) or not 0 < len(ops) <= 200:
        raise vault.VaultError("Caisse refusée : contenu de forme inattendue.")
    text = lambda v, n=200: isinstance(v, str) and len(v) <= n
    for op in ops:
        ok = isinstance(op, dict) and op.get("t") in KINDS and text(op.get("id"), 80) and op.get("id") \
            and text(op.get("par") or "", 120) and text(op.get("le") or "", 40) and text(op.get("note") or "", 300)
        if ok and op["t"] in ("amende", "paiement"):
            amount = op.get("montant")
            ok = text(op.get("joueur"), 120) and (amount is None or (isinstance(amount, (int, float)) and 0 <= amount <= 500))
        if ok and op["t"] == "amende":
            ok = op.get("regle") in RULES and isinstance(op.get("n", 1), int) and 0 < op.get("n", 1) <= 50
        if ok and op["t"] == "annule":
            ok = text(op.get("cible"), 80) and op.get("cible")
        if ok and op["t"] == "refus":
            ok = text(op.get("auto"), 200) and op.get("auto")
        if not ok:
            raise vault.VaultError("Caisse refusée : saisie de forme inattendue.")
    return ops


def main():
    secret = vault.passphrase()
    text = os.environ.get("HBPSM_CAISSE") or ""
    if not text or len(text) > 200_000:
        raise vault.VaultError("Caisse refusée : entrée absente ou trop longue.")
    try:
        envelope = json.loads(text)
    except ValueError as exc:
        raise vault.VaultError("Caisse refusée : entrée illisible.") from exc
    ops = check(envelope, secret)
    path = common.PUBLIE / NAME
    book = vault.decrypt(read_json(path), secret) if path.exists() else dict(format="hbpsm-caisse", v=1, ops=[])
    known = {o["id"] for o in book["ops"]}
    fresh = [o for o in ops if o["id"] not in known]   # une saisie renvoyée n'est comptée qu'une fois
    book["ops"].extend(fresh)
    book["maj"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    common.PUBLIE.mkdir(parents=True, exist_ok=True)
    write_json(path, vault.encrypt(book, secret))
    print(f"[caisse] {len(fresh)} saisie(s) ajoutée(s), {len(book['ops'])} au registre")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except vault.VaultError as exc:
        sys.exit(f"::error::{exc}")

"""Présences aux matchs, et vote de l'homme du match (demandes de l'auteur, 09/10/2026).

Un seul joueur les tient, celui qui a le rôle « présences » dans l'effectif (config.yml, `presences`) :
pour chaque match, il dit sur la page qui vient, ou qui est absent avec un motif (malade, blessé,
vacances, ou autre avec un mot obligatoire). Ces réponses, le joueur que chacun a dit être sur son
appareil (« Vous êtes ») et les votes pour l'homme du match partent chiffrés au dépôt à part des
propositions d'amendes (strus38/hbpsm-cn, même jeton, même workflow), dans le journal presences.enc. La
page en tire tout : statuts, feuille proposée, vote. Tant que les entraînements étaient suivis
(`entrainements`), la collecte y lisait le nombre de présents annoncés à la prochaine séance, pour la
séance exportée vers HANDBALL-training (effectifJoueurs, effectifGardiens) : des nombres, jamais un nom.

Repères des séances et des matchs : « E-AAAA-MM-JJ » (entraînement de ce jour), « M-<rencontre> ».
"""
import datetime as dt
import json
import os
import urllib.request

from . import vault

NAME = "presences.enc"


def url(config):
    """Où le journal est publié (dépôt des propositions, config.yml) ; "" sans ce dépôt."""
    cn = config.get("propositions") or {}
    return f"https://raw.githubusercontent.com/{cn['depot']}/{cn.get('branche') or 'main'}/{NAME}" if cn.get("depot") else ""


def fetch(address):
    """Le journal chiffré tel que publié ; None s'il n'existe pas encore ou si le dépôt ne répond pas."""
    try:
        with urllib.request.urlopen(address, timeout=20) as r:
            return r.read().decode("utf-8")
    except (OSError, ValueError):
        return None


def journal(config, secret=None):
    """Les envois du journal (réponses, « Vous êtes », votes), déchiffrés ; [] sans journal ni phrase."""
    secret = secret or os.environ.get("HBPSM_CLE") or ""
    address = url(config)
    text = fetch(address) if address and secret else None
    if not text:
        return []
    try:
        return (vault.decrypt(json.loads(text), secret) or {}).get("ops") or []
    except (vault.VaultError, ValueError, KeyError, TypeError, AttributeError):
        return []


def _when(stamp):
    try:
        d = dt.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


def op_time(op):
    """L'heure d'un envoi : celle de l'appareil, sauf s'il n'est arrivé que plus d'un jour après (horloge
    fausse) ; alors celle de sa réception. Comme dans la page."""
    le, recu = _when(op.get("le")), _when(op.get("recu"))
    if le and recu and recu - le > dt.timedelta(days=1):
        return recu
    return le or recu or dt.datetime.min.replace(tzinfo=dt.timezone.utc)


def answers(ops, event):
    """La dernière réponse de chaque joueur pour une séance ou un match : {joueur: "present" | "absent"}."""
    said = {}
    mine = [o for o in ops if o.get("t") == "dispo" and event in (o.get("evs") or [])]
    for op in sorted(mine, key=op_time):
        said[op.get("joueur")] = op.get("etat")
    return said


def training_counts(ops, day, players):
    """(joueurs de champ, gardiens) qui ont répondu présent à l'entraînement du jour day, parmi les joueurs
    de l'effectif ; (0, 0) sans réponse (HANDBALL-training : effectif inconnu)."""
    keepers = {p["cle"] for p in players if p.get("gardien") or "GB" in str(p.get("poste") or "").split("/")}
    squad = {p["cle"] for p in players}
    present = [c for c, etat in answers(ops, "E-" + day).items() if etat == "present" and c in squad]
    gk = sum(1 for c in present if c in keepers)
    return len(present) - gk, gk

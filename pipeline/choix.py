"""Choix de l'entraîneur : la feuille qu'il a validée pour chaque match, publiée chiffrée.

La page, en mode entraîneur, chiffre ses feuilles validées avec la phrase du club et lance le
workflow « Choix de l'entraîneur » (choix.yml) avec ce coffre pour seule entrée. Ce module le
vérifie sans jamais rien afficher de son contenu : chiffré avec la phrase du club (sinon il
n'est pas de l'entraîneur), de la forme attendue, de taille raisonnable. Puis il l'écrit dans
publie/choix.enc, que toutes les pages lisent : un match qui y figure est un choix de
l'entraîneur, les autres restent des suggestions.

Usage (dans le workflow) : HBPSM_CLE=… HBPSM_CHOIX='{coffre}' python -m pipeline.choix
"""
import json
import os
import re
import sys

from . import common, vault
from .common import write_json

NAME = "choix.enc"
MAX_TEXT = 60_000   # quatre feuilles de 12 joueurs, chiffrées, tiennent en quelques kilo-octets
MAX_MATCHES = 40
MAX_PLAYERS = 16
MAX_INJURED = 40
MAX_OFF = 200   # séances et matchs annulés sur la saison
ANNULE = re.compile(r"^(E-\d{4}-\d{2}-\d{2}|M-[\w-]{1,30}|\d{4}-\d{2}-\d{2})$")
ENVELOPE = ("format", "v", "kdf", "iterations", "sel", "chiffre", "nonce", "donnees")


def check(envelope, secret):
    """Le coffre reçu, déchiffré et vérifié ; VaultError s'il n'est pas un coffre de choix du club."""
    if not isinstance(envelope, dict) or int(envelope.get("iterations") or 0) != vault.ITERATIONS:
        raise vault.VaultError("Choix refusés : coffre de forme inattendue.")
    data = vault.decrypt(envelope, secret)  # refuse un coffre chiffré avec une autre phrase
    matchs = data.get("matchs") if isinstance(data, dict) else None
    if data.get("format") != "hbpsm-choix" or data.get("v") != 1 or not isinstance(matchs, dict) \
            or len(matchs) > MAX_MATCHES:
        raise vault.VaultError("Choix refusés : contenu de forme inattendue.")
    for choice in matchs.values():
        players = choice.get("joueurs") if isinstance(choice, dict) else None
        # suggestion : la proposition du tableau de bord pour ce match, gardée à côté (pipeline/selections.py)
        sugg = choice.get("suggestion", []) if isinstance(choice, dict) else None
        if not isinstance(players, list) or not 0 < len(players) <= MAX_PLAYERS \
                or not all(isinstance(p, str) and 0 < len(p) < 120 for p in players) \
                or not isinstance(choice.get("le"), str) or not isinstance(sugg, list) or len(sugg) > MAX_PLAYERS \
                or not all(isinstance(p, str) and 0 < len(p) < 120 for p in sugg):
            raise vault.VaultError("Choix refusés : feuille de forme inattendue.")
    # blessés : {joueur: {de: date du premier match manqué, a: date du retour ou null}}
    hurt = data.get("blesses", {})
    if not isinstance(hurt, dict) or len(hurt) > MAX_INJURED or not all(
            isinstance(k, str) and 0 < len(k) < 120 and isinstance(b, dict) and isinstance(b.get("de"), str)
            and len(b["de"]) < 40 and (b.get("a") is None or (isinstance(b.get("a"), str) and len(b["a"]) < 40))
            and set(b) <= {"de", "a"} for k, b in hurt.items()):
        raise vault.VaultError("Choix refusés : blessures de forme inattendue.")
    # absents : {match: [joueurs]}, déclarés par l'entraîneur pour un match
    away = data.get("absents", {})
    if not isinstance(away, dict) or len(away) > MAX_MATCHES or not all(
            isinstance(k, str) and 0 < len(k) < 40 and isinstance(v, list) and len(v) <= MAX_INJURED
            and all(isinstance(x, str) and 0 < len(x) < 120 for x in v) for k, v in away.items()):
        raise vault.VaultError("Choix refusés : absences de forme inattendue.")
    # rendez-vous fixés par l'entraîneur : {match: "HH:MM"} (la page « Ma semaine » de chaque joueur)
    rdv = data.get("rdv", {})
    if not isinstance(rdv, dict) or len(rdv) > MAX_MATCHES or not all(
            isinstance(k, str) and 0 < len(k) < 40 and isinstance(v, str) and len(v) <= 5 for k, v in rdv.items()):
        raise vault.VaultError("Choix refusés : rendez-vous de forme inattendue.")
    # entraînements et matchs annulés par l'entraîneur (vacances, gymnase fermé, match reporté) : « E-AAAA-MM-JJ »,
    # « M-<rencontre> » (et « AAAA-MM-JJ », une séance, comme au début) ; personne n'a à y répondre
    off = data.get("annulees", [])
    if not isinstance(off, list) or len(off) > MAX_OFF or not all(isinstance(d, str) and ANNULE.match(d) for d in off):
        raise vault.VaultError("Choix refusés : séances annulées de forme inattendue.")
    return data


def main():
    secret = vault.passphrase()
    text = os.environ.get("HBPSM_CHOIX") or ""
    if not text or len(text) > MAX_TEXT:
        raise vault.VaultError("Choix refusés : entrée absente ou trop longue.")
    try:
        envelope = json.loads(text)
    except ValueError as exc:
        raise vault.VaultError("Choix refusés : entrée illisible.") from exc
    data = check(envelope, secret)
    common.PUBLIE.mkdir(parents=True, exist_ok=True)
    write_json(common.PUBLIE / NAME, {k: envelope[k] for k in ENVELOPE})  # rien d'autre que le coffre
    print(f"[choix] {len(data['matchs'])} feuille(s) validée(s), {len(data.get('blesses') or {})} blessure(s), "
          f"{sum(len(v) for v in (data.get('absents') or {}).values())} absence(s) publiée(s)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except vault.VaultError as exc:
        sys.exit(f"::error::{exc}")

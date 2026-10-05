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
import sys

from . import common, vault
from .common import write_json

NAME = "choix.enc"
MAX_TEXT = 60_000   # quatre feuilles de 12 joueurs, chiffrées, tiennent en quelques kilo-octets
MAX_MATCHES = 40
MAX_PLAYERS = 16
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
        if not isinstance(players, list) or not 0 < len(players) <= MAX_PLAYERS \
                or not all(isinstance(p, str) and 0 < len(p) < 120 for p in players) \
                or not isinstance(choice.get("le"), str):
            raise vault.VaultError("Choix refusés : feuille de forme inattendue.")
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
    print(f"[choix] {len(data['matchs'])} feuille(s) validée(s) publiée(s)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except vault.VaultError as exc:
        sys.exit(f"::error::{exc}")

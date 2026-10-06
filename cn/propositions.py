"""Propositions d'amendes de la caisse noire HBPSM, déposées depuis la page par n'importe quel joueur.

Ce dépôt (strus38/hbpsm-cn) ne sert qu'à recevoir ces propositions : le jeton de la page ne peut
lancer que ce workflow, jamais valider une amende ni toucher au tableau de bord. Les trésoriers les
valident ou les refusent dans le registre du tableau de bord (strus38/hbpsm-dashboard).

  python propositions.py
Entrées : HBPSM_PROP (coffre chiffré avec la phrase du club, écrit par la page), secret HBPSM_CLE.
Sortie  : propositions.enc, journal chiffré des propositions ; une proposition renvoyée n'est
          comptée qu'une fois. Le dépôt est public : rien n'est jamais déchiffré dans le journal.
"""
import datetime as dt
import json
import os
import pathlib
import sys

import vault

NAME = "propositions.enc"
MAX_TEXT = 20_000   # quelques propositions chiffrées tiennent en quelques kilo-octets
MAX_OPS = 10        # par envoi
MAX_BOOK = 3000     # au-delà, le journal refuse : une saison n'en produit pas autant


def check(envelope, secret):
    """Les propositions reçues, déchiffrées et vérifiées ; VaultError sinon (rien n'est affiché)."""
    if not isinstance(envelope, dict) or int(envelope.get("iterations") or 0) != vault.ITERATIONS:
        raise vault.VaultError("Proposition refusée : coffre de forme inattendue.")
    data = vault.decrypt(envelope, secret)   # refuse un coffre chiffré avec une autre phrase
    ops = data.get("ops") if isinstance(data, dict) else None
    if data.get("format") != "hbpsm-cn" or data.get("v") != 1 or not isinstance(ops, list) or not 0 < len(ops) <= MAX_OPS:
        raise vault.VaultError("Proposition refusée : contenu de forme inattendue.")
    text = lambda v, n: isinstance(v, str) and len(v) <= n
    for op in ops:
        amount, n = (op.get("montant"), op.get("n", 1)) if isinstance(op, dict) else (None, 0)
        ok = (isinstance(op, dict) and op.get("t") == "proposition" and text(op.get("id"), 80) and op.get("id")
              and text(op.get("joueur"), 120) and op.get("joueur") and text(op.get("regle"), 40) and op.get("regle")
              and isinstance(n, int) and 0 < n <= 50 and (amount is None or (isinstance(amount, (int, float)) and 0 <= amount <= 500))
              and text(op.get("date") or "", 10) and text(op.get("note") or "", 300) and text(op.get("par") or "", 120)
              and text(op.get("le") or "", 40) and (op.get("match") is None or text(op.get("match"), 40))
              and set(op) <= {"id", "t", "joueur", "regle", "n", "montant", "date", "note", "par", "le", "match"})
        if not ok:
            raise vault.VaultError("Proposition refusée : saisie de forme inattendue.")
    return ops


def main(path=pathlib.Path(NAME)):
    secret = vault.passphrase()
    text = os.environ.get("HBPSM_PROP") or ""
    if not text or len(text) > MAX_TEXT:
        raise vault.VaultError("Proposition refusée : entrée absente ou trop longue.")
    try:
        envelope = json.loads(text)
    except ValueError as exc:
        raise vault.VaultError("Proposition refusée : entrée illisible.") from exc
    ops = check(envelope, secret)
    path = pathlib.Path(path)
    book = vault.decrypt(json.loads(path.read_text("utf-8")), secret) if path.exists() else dict(format="hbpsm-cn-journal", v=1, ops=[])
    known = {o["id"] for o in book["ops"]}
    fresh = [o for o in ops if o["id"] not in known]
    if len(book["ops"]) + len(fresh) > MAX_BOOK:
        raise vault.VaultError("Proposition refusée : journal plein.")
    book["ops"].extend(fresh)
    book["maj"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    path.write_text(json.dumps(vault.encrypt(book, secret), ensure_ascii=False, indent=1), "utf-8")
    print(f"[propositions] {len(fresh)} ajoutée(s), {len(book['ops'])} au journal")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except vault.VaultError as exc:
        sys.exit(f"::error::{exc}")

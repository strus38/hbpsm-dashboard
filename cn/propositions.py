"""Ce que les joueurs de l'HBPSM envoient depuis la page : propositions d'amendes de la caisse noire,
réponses de présence aux entraînements et aux matchs, « Vous êtes » et vote de l'homme du match.

Ce dépôt (strus38/hbpsm-cn) ne sert qu'à les recevoir : le jeton de la page ne peut lancer que ce
workflow, jamais valider une amende ni toucher au tableau de bord. Les trésoriers valident ou refusent
les amendes dans le registre du tableau de bord (strus38/hbpsm-dashboard) ; les pages lisent les
réponses et les votes pour les présences, la feuille proposée et l'homme du match.

  python propositions.py
Entrées : HBPSM_PROP (coffre chiffré avec la phrase du club, écrit par la page), secret HBPSM_CLE.
Sorties : propositions.enc (propositions d'amendes) et presences.enc (réponses, « Vous êtes », votes),
          journaux chiffrés ; un envoi renvoyé n'est compté qu'une fois ; l'heure de réception est notée
          (« recu »). Le dépôt est public : rien n'est jamais déchiffré dans le journal.
"""
import datetime as dt
import json
import os
import pathlib
import sys

import vault

NAME = "propositions.enc"
PRESENCES = "presences.enc"
MAX_TEXT = 80_000   # quelques dizaines d'envois chiffrés tiennent en quelques dizaines de kilo-octets
MAX_OPS = 40        # par envoi (une boîte d'envoi restée hors connexion)
MAX_BOOK = 3000     # propositions : au-delà, le journal refuse ; une saison n'en produit pas autant
MAX_PRES = 20000    # réponses, « Vous êtes » et votes d'une saison
MAX_EVENTS = 60     # séances et matchs couverts par une réponse (une absence sur une période)
MOTIFS = {"malade", "blesse", "vacances", "autre"}
PRES_KINDS = {"moi", "dispo", "vote"}


def _text(v, n):
    return isinstance(v, str) and len(v) <= n


def _ok(op):
    """Un envoi de la forme attendue : rien d'autre que les champs prévus, chacun de taille raisonnable."""
    if not isinstance(op, dict) or not (_text(op.get("id"), 80) and op.get("id")) or not _text(op.get("le") or "", 40):
        return False
    t = op.get("t")
    if t == "proposition":
        amount, n = op.get("montant"), op.get("n", 1)
        return (_text(op.get("joueur"), 120) and op.get("joueur") and _text(op.get("regle"), 40) and op.get("regle")
                and isinstance(n, int) and 0 < n <= 50 and (amount is None or (isinstance(amount, (int, float)) and 0 <= amount <= 500))
                and _text(op.get("date") or "", 10) and _text(op.get("note") or "", 300) and _text(op.get("par") or "", 120)
                and (op.get("match") is None or _text(op.get("match"), 40))
                and set(op) <= {"id", "t", "joueur", "regle", "n", "montant", "date", "note", "par", "le", "match"})
    who = _text(op.get("joueur"), 120) and op.get("joueur") and _text(op.get("app") or "", 64)
    if t == "moi":   # « Vous êtes » : ce joueur, sur cet appareil
        return bool(who) and set(op) <= {"id", "t", "joueur", "app", "le"}
    if t == "dispo":   # présent, ou absent avec un motif (« autre » : un mot obligatoire)
        evs, etat, motif, texte = op.get("evs"), op.get("etat"), op.get("motif") or "", op.get("texte") or ""
        return (bool(who) and isinstance(evs, list) and 0 < len(evs) <= MAX_EVENTS and all(_text(e, 40) and e for e in evs)
                and etat in ("present", "absent") and _text(texte, 300)
                and (motif == "" if etat == "present" else motif in MOTIFS and (motif != "autre" or texte.strip()))
                and set(op) <= {"id", "t", "joueur", "evs", "etat", "motif", "texte", "app", "le"})
    if t == "vote":   # l'homme du match, par un joueur de la feuille
        return (bool(who) and _text(op.get("match"), 40) and op.get("match") and _text(op.get("pour"), 120) and op.get("pour")
                and set(op) <= {"id", "t", "joueur", "match", "pour", "app", "le"})
    return False


def check(envelope, secret):
    """Les envois reçus, déchiffrés et vérifiés ; VaultError sinon (rien n'est affiché)."""
    if not isinstance(envelope, dict) or int(envelope.get("iterations") or 0) != vault.ITERATIONS:
        raise vault.VaultError("Envoi refusé : coffre de forme inattendue.")
    data = vault.decrypt(envelope, secret)   # refuse un coffre chiffré avec une autre phrase
    ops = data.get("ops") if isinstance(data, dict) else None
    if data.get("format") != "hbpsm-cn" or data.get("v") != 1 or not isinstance(ops, list) or not 0 < len(ops) <= MAX_OPS:
        raise vault.VaultError("Envoi refusé : contenu de forme inattendue.")
    if not all(_ok(op) for op in ops):
        raise vault.VaultError("Envoi refusé : saisie de forme inattendue.")
    return ops


def _append(path, ops, secret, fmt, limit, now):
    """Ajoute au journal chiffré ce qu'il ne connaît pas encore ; rien n'est réécrit sans nouveauté."""
    book = vault.decrypt(json.loads(path.read_text("utf-8")), secret) if path.exists() else dict(format=fmt, v=1, ops=[])
    known = {o["id"] for o in book["ops"]}
    fresh = [dict(o, recu=now) for o in ops if o["id"] not in known]
    fresh = [o for i, o in enumerate(fresh) if o["id"] not in {x["id"] for x in fresh[:i]}]
    if not fresh:
        return 0, len(book["ops"])
    if len(book["ops"]) + len(fresh) > limit:
        raise vault.VaultError("Envoi refusé : journal plein.")
    book["ops"].extend(fresh)
    book["maj"] = now
    path.write_text(json.dumps(vault.encrypt(book, secret), ensure_ascii=False, indent=1), "utf-8")
    return len(fresh), len(book["ops"])


def main(path=pathlib.Path(NAME), presences=None):
    secret = vault.passphrase()
    text = os.environ.get("HBPSM_PROP") or ""
    if not text or len(text) > MAX_TEXT:
        raise vault.VaultError("Envoi refusé : entrée absente ou trop longue.")
    try:
        envelope = json.loads(text)
    except ValueError as exc:
        raise vault.VaultError("Envoi refusé : entrée illisible.") from exc
    ops = check(envelope, secret)
    path = pathlib.Path(path)
    presences = pathlib.Path(presences) if presences else path.with_name(PRESENCES)
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    props = [o for o in ops if o["t"] == "proposition"]
    pres = [o for o in ops if o["t"] in PRES_KINDS]
    if props:
        n, total = _append(path, props, secret, "hbpsm-cn-journal", MAX_BOOK, now)
        print(f"[propositions] {n} ajoutée(s), {total} au journal")
    if pres:
        n, total = _append(presences, pres, secret, "hbpsm-cn-presences", MAX_PRES, now)
        print(f"[présences] {n} envoi(s) ajouté(s), {total} au journal")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except vault.VaultError as exc:
        sys.exit(f"::error::{exc}")

"""Chiffrement des résultats publiés dans un dépôt public.

Le dépôt et ses Releases sont lisibles par tous : tout ce qui porte un nom de
joueur n'y entre que chiffré. La clé est une phrase secrète, connue des seuls
entraîneurs et rangée dans le secret GitHub HBPSM_CLE.

Format du fichier (JSON), relisible par tout outil disposant de WebCrypto :
  format     "hbpsm-chiffre"
  v          1
  kdf        "PBKDF2-SHA256", avec iterations et sel (base64)
  chiffre    "AES-256-GCM", avec nonce (base64)
  donnees    base64 du texte chiffré suivi de l'étiquette d'authentification
Le texte clair est un document JSON encodé en UTF-8.
"""
import base64
import json
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

ITERATIONS = 600_000
MIN_LENGTH = 16


class VaultError(Exception):
    pass


def passphrase(env="HBPSM_CLE"):
    value = (os.environ.get(env) or "").strip()
    if not value:
        raise VaultError(f"Secret {env} absent : ajoute-le dans Settings > Secrets and variables > Actions.")
    if len(value) < MIN_LENGTH:
        raise VaultError(f"Secret {env} trop court : {MIN_LENGTH} caractères au minimum, "
                         "par exemple cinq mots tirés au hasard.")
    return value


def _key(secret, salt, iterations):
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iterations)
    return kdf.derive(secret.strip().encode("utf-8"))


def encrypt(obj, secret, iterations=ITERATIONS):
    salt, nonce = os.urandom(16), os.urandom(12)
    plain = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    sealed = AESGCM(_key(secret, salt, iterations)).encrypt(nonce, plain, None)
    b64 = lambda b: base64.b64encode(b).decode("ascii")
    return dict(format="hbpsm-chiffre", v=1, kdf="PBKDF2-SHA256", iterations=iterations,
                sel=b64(salt), chiffre="AES-256-GCM", nonce=b64(nonce), donnees=b64(sealed))


def decrypt(envelope, secret):
    if envelope.get("format") != "hbpsm-chiffre":
        raise VaultError("Ce fichier n'est pas un fichier chiffré du tableau de bord.")
    d64 = base64.b64decode
    key = _key(secret, d64(envelope["sel"]), int(envelope["iterations"]))
    try:
        plain = AESGCM(key).decrypt(d64(envelope["nonce"]), d64(envelope["donnees"]), None)
    except Exception as exc:
        raise VaultError("Phrase secrète incorrecte ou fichier altéré.") from exc
    return json.loads(plain.decode("utf-8"))

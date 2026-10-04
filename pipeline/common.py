"""Fonctions partagées : chemins, configuration, normalisation des noms."""
import json
import pathlib
import re
import unicodedata

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
MATCHES = DATA / "matches"
RAW = ROOT / "raw"
DOCS = ROOT / "docs"      # aperçu local, jamais versionné
PUBLIE = ROOT / "publie"  # seuls fichiers de résultat versionnés : chiffrés ou sans donnée


def load_config():
    return yaml.safe_load((ROOT / "config.yml").read_text("utf-8"))


def norm(text):
    """Majuscules sans accents ni ponctuation, espaces réduits."""
    text = unicodedata.normalize("NFKD", str(text or ""))
    text = "".join(c for c in text if not unicodedata.combining(c)).upper()
    text = re.sub(r"[^A-Z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def name_key(name):
    """Clé de personne insensible à l'ordre : 'DUPONT Paul' et 'Paul Dupont' donnent la même."""
    return " ".join(sorted(norm(name).split()))


def match_name(name, keys):
    """Retrouve une personne dans un ensemble de clés : égalité, sinon inclusion sans ambiguïté."""
    key = name_key(name)
    if key in keys:
        return key
    mine = set(key.split())
    if len(mine) < 2:
        return None
    hits = [k for k in keys if len(set(k.split()) & mine) >= 2
            and (set(k.split()) <= mine or mine <= set(k.split()))]
    return hits[0] if len(hits) == 1 else None


def is_club(name, config):
    n = norm(name)
    return any(norm(m) in n for m in config["club"]["motifs"])


def read_json(path, default=None):
    path = pathlib.Path(path)
    if not path.exists():
        return default
    return json.loads(path.read_text("utf-8"))


def write_json(path, obj):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), "utf-8")


def load_matches():
    out = []
    for p in sorted(MATCHES.glob("*.json")):
        out.append(json.loads(p.read_text("utf-8")))
    return out

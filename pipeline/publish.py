"""Publication dans un dépôt public : rien de nominatif n'y entre en clair.

  python -m pipeline.publish restore   reprend l'état chiffré de la collecte précédente
  python -m pipeline.publish roster    écrit roster.csv depuis le secret HBPSM_EFFECTIF
  python -m pipeline.publish seal      analyse, chiffre et prépare les fichiers à publier

Fichiers versionnés, dans publie/ :
  hbpsm.enc                   données du tableau de bord et séance à importer, chiffrées
  etat.enc                    état de la collecte (rencontres, feuilles lues), chiffré
  manifeste.json              date et empreinte, sans donnée
  HBPSM-tableau-de-bord.html  la page, sans donnée : elle lit hbpsm.enc et le déchiffre
"""
import datetime as dt
import hashlib
import json
import os
import sys

from . import vault
from .analyze import analyze
from .build_dashboard import app_version, render
from .common import DATA, MATCHES, PUBLIE, ROOT, load_config, read_json, write_json
from .export_training import build_exports

STATE_FILES = ("fixtures.json", "official_standings.json", "rapport_extraction.json")
PAGE_NAME = "HBPSM-tableau-de-bord.html"
VERIF = 600  # secondes entre deux vérifications du manifeste par la page ouverte


def repo_slug(config):
    return os.environ.get("GITHUB_REPOSITORY") or config.get("depot") or ""


def page_config(config):
    slug = repo_slug(config)
    branch = os.environ.get("GITHUB_REF_NAME") or config.get("branche") or "main"
    raw = f"https://raw.githubusercontent.com/{slug}/{branch}/publie/" if slug else ""
    return dict(src=raw + "hbpsm.enc" if raw else "", manifeste=raw + "manifeste.json" if raw else "",
                versions=f"https://github.com/{slug}/releases/latest" if slug else "",
                app=app_version(), club=config["club"]["nom_affiche"], verif=VERIF)


def collect_state():
    state = {name: read_json(DATA / name) for name in STATE_FILES}
    state["matches"] = {p.stem: json.loads(p.read_text("utf-8")) for p in sorted(MATCHES.glob("*.json"))}
    return state


def restore():
    secret = vault.passphrase()  # vérifié d'emblée : inutile de collecter si l'on ne peut pas publier
    path = PUBLIE / "etat.enc"
    if not path.exists():
        print("[état] première collecte : aucun état à reprendre")
        return 0
    state = vault.decrypt(read_json(path), secret)
    for name in STATE_FILES:
        if state.get(name) is not None:
            write_json(DATA / name, state[name])
    for mid, match in (state.get("matches") or {}).items():
        write_json(MATCHES / f"{mid}.json", match)
    print(f"[état] {len(state.get('matches') or {})} rencontres reprises")
    return 0


def roster():
    """Une ligne par joueur : « Prénom Nom », suivi si besoin de « ,POSTE » et « ,non » (indisponible)."""
    text = os.environ.get("HBPSM_EFFECTIF") or ""
    lines = [l.strip() for l in text.replace(";", ",").splitlines() if l.strip()]
    lines = [l for l in lines if not l.lower().startswith("nom,")]
    (ROOT / "roster.csv").write_text("nom,poste,disponible\n" + "\n".join(lines) + "\n", "utf-8")
    print(f"[effectif] {len(lines)} joueurs")
    return 0


def seal(today=None):
    secret = vault.passphrase()
    config = load_config()
    data = analyze(today)
    scratch = ROOT / "raw" / "export"
    _, seance = build_exports(data, scratch, today)
    state = collect_state()
    roster_text = (ROOT / "roster.csv").read_text("utf-8") if (ROOT / "roster.csv").exists() else ""
    digest = hashlib.sha256(json.dumps([state, roster_text, app_version()], sort_keys=True,
                                       ensure_ascii=False).encode("utf-8")).hexdigest()
    previous = read_json(PUBLIE / "manifeste.json", {}) or {}
    changed = previous.get("empreinte") != digest or not (PUBLIE / "hbpsm.enc").exists()
    cfg = page_config(config)
    PUBLIE.mkdir(parents=True, exist_ok=True)
    # la page ne contient aucune donnée : elle peut être publique
    (PUBLIE / PAGE_NAME).write_text(render(None, cfg), "utf-8")
    if changed:
        now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        payload = dict(v=1, genere=now, data=data, seance_hbt=seance)
        write_json(PUBLIE / "hbpsm.enc", vault.encrypt(payload, secret))
        write_json(PUBLIE / "etat.enc", vault.encrypt(state, secret))
        write_json(PUBLIE / "manifeste.json", dict(format="hbpsm-manifeste", v=1, maj=now,
                                                   empreinte=digest, app=cfg["app"]))
    release = changed and data["meta"]["matchs"] > 0
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"change={'oui' if changed else 'non'}\nrelease={'oui' if release else 'non'}\n")
    print(f"[publication] données {'mises à jour' if changed else 'inchangées'} : "
          f"{data['meta']['matchs']} matchs, {data['meta']['feuilles']} feuilles lues")
    return 0


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        sys.exit({"restore": restore, "roster": roster, "seal": seal}[command]())
    except KeyError:
        sys.exit("Usage : python -m pipeline.publish restore | roster | seal")
    except vault.VaultError as exc:
        sys.exit(f"::error::{exc}")

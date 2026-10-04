"""Publication dans un dépôt public : rien de nominatif n'y entre en clair.

  python -m pipeline.publish restore   reprend l'état chiffré de la collecte précédente
  python -m pipeline.publish roster    écrit roster.csv depuis le secret HBPSM_EFFECTIF
  python -m pipeline.publish seal      analyse, chiffre et prépare les fichiers à publier

Fichiers versionnés, dans publie/ :
  hbpsm.enc                   données du tableau de bord et séance à importer, chiffrées
  etat.enc                    état de la collecte (rencontres, feuilles lues), chiffré
  manifeste.json              date et empreinte, sans donnée
  HBPSM-tableau-de-bord.html  la page, sans donnée : elle lit hbpsm.enc et le déchiffre
  seance-prochaine.hbt.json   séance du prochain entraînement, en clair et sans nom de joueur
                              (vérifié avant publication) : HANDBALL-training la lit sans phrase
  historique.enc              saisons passées (pipeline.history), chiffrées ; réécrit seulement
                              quand elles changent, c'est-à-dire presque jamais
"""
import datetime as dt
import hashlib
import json
import os
import sys

from . import vault
from .analyze import analyze
from .build_dashboard import app_version, render
from .common import DATA, MATCHES, PUBLIE, ROOT, load_config, norm, read_json, write_json
from .export_training import build_exports

STATE_FILES = ("fixtures.json", "official_standings.json", "rapport_extraction.json")
PAGE_NAME = "HBPSM-tableau-de-bord.html"
# Séance du prochain entraînement, publiée EN CLAIR pour l'application HANDBALL-training : elle ne
# porte aucun nom de joueur (équipes, chiffres d'équipe, numéros de maillot), ce que seal() vérifie.
SEANCE_NAME = "seance-prochaine.hbt.json"
HISTORY_NAME = "historique.enc"
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


def history_state():
    """Saisons passées collectées : {saison: contenu}."""
    return {p.stem: json.loads(p.read_text("utf-8")) for p in sorted((DATA / "historique").glob("*.json"))}


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
    if (PUBLIE / HISTORY_NAME).exists():
        for saison, content in vault.decrypt(read_json(PUBLIE / HISTORY_NAME), secret).items():
            write_json(DATA / "historique" / f"{saison}.json", content)
        print("[état] saisons passées reprises")
    return 0


def roster():
    """Une ligne par joueur : « Prénom Nom », suivi si besoin de « ,POSTE » et « ,non » (indisponible)."""
    text = os.environ.get("HBPSM_EFFECTIF") or ""
    lines = [l.strip() for l in text.replace(";", ",").splitlines() if l.strip()]
    lines = [l for l in lines if not l.lower().startswith("nom,")]
    (ROOT / "roster.csv").write_text("nom,poste,disponible\n" + "\n".join(lines) + "\n", "utf-8")
    print(f"[effectif] {len(lines)} joueurs")
    return 0


def known_names(state, roster_text):
    """Noms de personnes connus : joueurs des feuilles (les deux équipes) et effectif du club."""
    names = {p.get("name") for m in state["matches"].values()
             for side in ("home", "away") for p in (m.get("players") or {}).get(side, [])}
    names |= {line.split(",")[0] for line in roster_text.splitlines()[1:]}
    return {norm(n) for n in names if n and len(norm(n).split()) >= 2}


def check_public(text, names):
    """Refuse un fichier public où apparaît un nom de personne, dans un ordre ou dans l'autre."""
    words = norm(text).split()
    for name in names:
        parts = name.split()
        for i in range(len(words) - len(parts) + 1):
            if sorted(words[i:i + len(parts)]) == sorted(parts):
                raise vault.VaultError(f"{SEANCE_NAME} contiendrait un nom de joueur : publication refusée.")


def seal(today=None):
    secret = vault.passphrase()
    config = load_config()
    data = analyze(today)
    scratch = ROOT / "raw" / "export"
    _, seance = build_exports(data, scratch, today)
    state = collect_state()
    roster_text = (ROOT / "roster.csv").read_text("utf-8") if (ROOT / "roster.csv").exists() else ""
    hist = history_state()
    hist_digest = hashlib.sha256(json.dumps(hist, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    digest = hashlib.sha256(json.dumps([state, roster_text, app_version(), hist_digest], sort_keys=True,
                                       ensure_ascii=False).encode("utf-8")).hexdigest()
    previous = read_json(PUBLIE / "manifeste.json", {}) or {}
    changed = previous.get("empreinte") != digest or not (PUBLIE / "hbpsm.enc").exists()
    cfg = page_config(config)
    public_seance = json.dumps(seance, ensure_ascii=False, indent=1)
    check_public(public_seance, known_names(state, roster_text))  # avant d'écrire quoi que ce soit
    PUBLIE.mkdir(parents=True, exist_ok=True)
    # la page ne contient aucune donnée : elle peut être publique
    (PUBLIE / PAGE_NAME).write_text(render(None, cfg), "utf-8")
    if changed or not (PUBLIE / SEANCE_NAME).exists():
        (PUBLIE / SEANCE_NAME).write_text(public_seance, "utf-8")
    if hist and (previous.get("historique") != hist_digest or not (PUBLIE / HISTORY_NAME).exists()):
        write_json(PUBLIE / HISTORY_NAME, vault.encrypt(hist, secret))
    if changed:
        now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        payload = dict(v=1, genere=now, data=data, seance_hbt=seance)
        write_json(PUBLIE / "hbpsm.enc", vault.encrypt(payload, secret))
        write_json(PUBLIE / "etat.enc", vault.encrypt(state, secret))
        write_json(PUBLIE / "manifeste.json", dict(format="hbpsm-manifeste", v=1, maj=now,
                                                   empreinte=digest, app=cfg["app"],
                                                   historique=hist_digest if hist else None))
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

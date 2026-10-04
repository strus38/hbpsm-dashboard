"""Assemble la page du tableau de bord.

La même page sert dans deux modes :
- publiée (publie/HBPSM-tableau-de-bord.html) : sans aucune donnée ; à l'ouverture elle
  télécharge le fichier chiffré du dépôt et le déchiffre avec la phrase secrète ;
- aperçu local (python -m pipeline.build_dashboard) : données en clair dans docs/,
  dossier jamais versionné.
"""
import hashlib
import json

from .common import DOCS, ROOT, write_json

TEMPLATE = ROOT / "dashboard" / "template.html"


def app_version():
    return hashlib.sha256(TEMPLATE.read_bytes()).hexdigest()[:12]


def _json(obj):
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")


def render(page_data, cfg=None):
    """page_data=None donne la page publiée, sans donnée."""
    html = TEMPLATE.read_text("utf-8")
    cfg = dict(cfg or {}, app=app_version())
    return html.replace("__DATA__", _json(page_data)).replace("__CFG__", _json(cfg))


def build(data=None, out_dir=DOCS, today=None):
    from .analyze import analyze
    from .export_training import build_exports
    data = data or analyze()
    out_dir.mkdir(parents=True, exist_ok=True)
    _, seance = build_exports(data, out_dir, today)
    write_json(out_dir / "data.json", data)
    (out_dir / "index.html").write_text(render(dict(data, seance_hbt=seance)), "utf-8")
    return data


if __name__ == "__main__":
    d = build()
    print(f"[aperçu local] docs/index.html : {d['meta']['matchs']} matchs, "
          f"{sum(1 for p in d['joueurs'] if p['m'])} joueurs alignés sur {len(d['joueurs'])}")

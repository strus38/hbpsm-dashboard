"""La feuille que propose le tableau de bord pour chaque match à venir, calculée par la page elle-même (demande de
l'auteur, 10/10/2026 : garder en mémoire chaque proposition et la comparer aux choix de l'entraîneur, même quand
il ne publie pas sa feuille).

La rotation et la feuille proposée ne se calculent que dans la page (dashboard/template.html, planning()). La
collecte l'ouvre donc sans écran, avec les données qu'elle vient de calculer, en mode entraîneur (les présences
saisies comptent, comme pour lui), avec les choix publiés (blessés, absents, feuilles des autres matchs) et le
journal des présences : pour chaque match de la planification, la proposition sans le choix de ce match
(suggestionOf, la même que celle jointe à une feuille publiée). Rien d'autre que le fichier local n'est chargé :
ni logos, ni polices, ni dépôt. La page, qui porte les données en clair, n'est écrite que dans un dossier
temporaire effacé aussitôt.

Sans navigateur (Playwright absent, Chrome introuvable), rien n'est calculé et la collecte continue.
HBPSM_SUGGESTIONS=0 coupe ce calcul (tests).
"""
import os
import pathlib
import tempfile

from .build_dashboard import render

TIMEOUT = 60_000   # millisecondes

SCRIPT = """([choix, ops]) => {
  CHOIX = choix && choix.matchs ? choix : null; PRESJ = {ops: ops || []}; DECL = null;
  const out = {};
  for(const r of planning()){ const s = suggestionOf(r.m.id); if(s && s.length) out[String(r.m.id)] = s; }
  return out;
}"""


def launch(p):
    """Le Chrome installé (celui du runner GitHub, celui du poste) ; sinon le Chromium de Playwright."""
    channel = os.environ.get("HBPSM_NAVIGATEUR") or "chrome"
    try:
        return p.chromium.launch(channel=None if channel == "chromium" else channel)
    except Exception:
        return p.chromium.launch()


def snapshot(data, choix=None, journal=None):
    """{match: [clés des joueurs]} pour les matchs de la planification ; None sans navigateur ou si la page
    échoue. choix : choix.enc déchiffré (analyze.published_box) ; journal : les envois des présences."""
    if os.environ.get("HBPSM_SUGGESTIONS", "1") == "0" or not data or not (data.get("saison") or {}).get("matchs"):
        return None
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[propositions] Playwright absent : propositions du tableau de bord non gardées")
        return None
    errors = []
    with tempfile.TemporaryDirectory() as tmp:
        page_file = pathlib.Path(tmp) / "page.html"
        page_file.write_text(render(data, {}), "utf-8")
        try:
            with sync_playwright() as p:
                browser = launch(p)
                try:
                    ctx = browser.new_context(timezone_id="Europe/Paris", locale="fr-FR")
                    # rien ne sort : ni logos (site de la fédération), ni polices, ni dépôt
                    ctx.route("**/*", lambda route: route.continue_() if route.request.url.startswith("file:") else route.abort())
                    page = ctx.new_page()
                    page.on("pageerror", lambda e: errors.append(type(e).__name__))
                    page.goto(page_file.as_uri() + "#entraineur", timeout=TIMEOUT)
                    page.wait_for_function("typeof suggestionOf === 'function' && !!D", timeout=TIMEOUT)
                    out = page.evaluate(SCRIPT, [choix or {}, journal or []])
                finally:
                    browser.close()
        except Exception as exc:   # navigateur introuvable, page en échec : la collecte continue sans
            print(f"[propositions] page non calculée ({type(exc).__name__}) : propositions du tableau de bord non gardées")
            return None
    if errors:   # jamais le message : il pourrait citer une donnée
        print(f"[propositions] {len(errors)} erreur(s) dans la page")
    out = {k: sorted(v) for k, v in (out or {}).items() if isinstance(v, list) and v}
    print(f"[propositions] {len(out)} match(s) : proposition du tableau de bord gardée")
    return out

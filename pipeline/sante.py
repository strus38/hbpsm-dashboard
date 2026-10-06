"""Santé du tableau de bord : ce qui peut casser sans bruit (demande de l'auteur, 06/10/2026).

  python -m pipeline.sante          après la publication, à chaque collecte
  python -m pipeline.sante --echec  quand la collecte elle-même a échoué

Vérifie que le site de la fédération est toujours lu (rencontres de chaque poule, prochain match du
club), que les feuilles du club arrivent et se lisent, et que les jetons n'approchent pas de leur
échéance. Écrit publie/sante.json, public et sans aucun nom (relu contre les noms connus comme les
autres fichiers publics), que la page affiche en bandeau ; ouvre une issue GitHub « Tableau de bord :
alerte » (son auteur en est prévenu par mail), la met à jour, et la ferme quand tout va bien.
"""
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.request

from .common import DATA, PUBLIE, ROOT, is_club, load_config, load_matches, paris_now, read_json, write_json

NAME = "sante.json"
TITLE = "Tableau de bord : alerte"
FEUILLE_JOURS = 3    # une feuille du club attendue depuis plus de 3 jours : signalée
JETON_JOURS = 30     # un jeton qui expire dans moins d'un mois : signalé
API = "https://api.github.com"


def token_days(token, repo, now=None):
    """Jours avant l'échéance d'un jeton GitHub à grain fin (en-tête de l'API) ; « sans échéance » s'il
    n'en a pas, « refusé » s'il ne marche plus, None s'il n'a pas pu être vérifié."""
    if not token or not repo:
        return None
    req = urllib.request.Request(f"{API}/repos/{repo}", headers={"Authorization": f"Bearer {token}",
                                                                 "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            end = resp.headers.get("github-authentication-token-expiration")
    except urllib.error.HTTPError as exc:
        return "refusé" if exc.code in (401, 403) else None
    except (urllib.error.URLError, OSError):
        return None
    if not end:
        return "sans échéance"
    try:
        when = dt.datetime.strptime(end.strip()[:19], "%Y-%m-%d %H:%M:%S").date()
    except ValueError:
        return None
    return (when - (now or paris_now().date())).days


def checks(config, fixtures, matches, report, today, tokens):
    """Les alertes du moment : [{niveau, code, message}], sans aucun nom de personne."""
    out = []
    add = lambda niveau, code, message: out.append(dict(niveau=niveau, code=code, message=message))
    league = [f for f in fixtures if not f.get("coupe") and not f.get("externe")]
    for p in config.get("poules") or []:
        if not any(str(f.get("poule")) == str(p.get("id")) for f in league):
            add("alerte", f"poule-{p.get('id')}", f"Poule {p.get('id')} : aucune rencontre lue sur le site de la fédération "
                                                   "(le site a peut-être changé).")
    ours = lambda f: is_club(f.get("home"), config) or is_club(f.get("away"), config)
    mine = [f for f in fixtures if ours(f) and not f.get("externe")]
    season_end = f"{str(config.get('saison') or '2000-2001')[5:9]}-06-30"
    if mine and today <= season_end and not any((f.get("date") or "")[:10] >= today and f.get("score_home") is None for f in mine):
        add("alerte", "prochain", "Aucun prochain match du club trouvé sur le site de la fédération.")
    read = {str(m.get("id")) for m in matches if (m.get("players") or {}).get("home")}
    late = [f for f in mine if f.get("score_home") is not None and str(f.get("id")) not in read and f.get("pdf_url") is not False
            and (f.get("date") or "9999")[:10] <= (dt.date.fromisoformat(today) - dt.timedelta(days=FEUILLE_JOURS)).isoformat()]
    if late:
        add("info", "feuilles", f"{len(late)} feuille{'s' if len(late) > 1 else ''} de match du club attendue{'s' if len(late) > 1 else ''} "
                                f"depuis plus de {FEUILLE_JOURS} jours : les notes et la rotation ne les comptent pas encore.")
    if (report or {}).get("erreurs"):
        n = report["erreurs"]
        add("alerte", "illisibles", f"{n} feuille{'s' if n > 1 else ''} de match illisible{'s' if n > 1 else ''} "
                                    "(le format des feuilles a peut-être changé).")
    unknown = (report or {}).get("actions_inconnues") or []
    if unknown:
        add("info", "libelles", f"Libellés inconnus sur les feuilles : {', '.join(sorted(map(str, unknown))[:5])}.")
    for label, days in tokens.items():
        if days == "refusé":
            add("alerte", f"jeton-{label}", f"Jeton {label} refusé par GitHub : il faut en créer un nouveau.")
        elif isinstance(days, int) and days < JETON_JOURS:
            add("alerte" if days < 7 else "info", f"jeton-{label}",
                f"Jeton {label} : expire dans {max(days, 0)} jour{'s' if days > 1 else ''}, à renouveler.")
    return out


def issue(alerts, failed=False):
    """Ouvre, met à jour ou ferme l'issue d'alerte du dépôt (GITHUB_TOKEN du workflow) ; sans effet ailleurs."""
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        return None
    def call(method, path, body=None):
        req = urllib.request.Request(f"{API}{path}", method=method, data=json.dumps(body).encode("utf-8") if body else None,
                                     headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                                              "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read() or b"null")
    try:
        found = [i for i in call("GET", f"/repos/{repo}/issues?state=open&per_page=50") or []
                 if i.get("title") == TITLE and not i.get("pull_request")]
        if alerts or failed:
            lines = (["La collecte quotidienne a échoué : voir l'onglet Actions."] if failed else []) \
                + [f"- **{a['niveau']}** : {a['message']}" for a in alerts]
            body = "\n".join(lines) + "\n\n_Écrit par la collecte ; l'issue se ferme d'elle-même quand tout va bien._"
            if found:
                if found[0].get("body") != body:
                    call("PATCH", f"/repos/{repo}/issues/{found[0]['number']}", dict(body=body))
            else:
                call("POST", f"/repos/{repo}/issues", dict(title=TITLE, body=body))
            return "ouverte"
        for i in found:
            call("POST", f"/repos/{repo}/issues/{i['number']}/comments", dict(body="Tout est rentré dans l'ordre."))
            call("PATCH", f"/repos/{repo}/issues/{i['number']}", dict(state="closed"))
        return "fermée" if found else None
    except (urllib.error.URLError, OSError, ValueError) as exc:   # l'issue est un plus : jamais bloquante
        print(f"[santé] issue non mise à jour : {type(exc).__name__}", file=sys.stderr)
        return None


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    failed = "--echec" in argv
    config = load_config()
    today = paris_now().date().isoformat()
    tokens = {}
    cn = (config.get("propositions") or {}).get("depot")
    if os.environ.get("HBPSM_JETON_CN"):
        tokens["des propositions"] = token_days(os.environ["HBPSM_JETON_CN"], cn)
    if os.environ.get("HBPSM_JETON_PUBLICATION"):   # facultatif : le jeton de l'entraîneur et des trésoriers
        tokens["de publication"] = token_days(os.environ["HBPSM_JETON_PUBLICATION"], os.environ.get("GITHUB_REPOSITORY"))
    alerts = [] if failed else checks(config, read_json(DATA / "fixtures.json", []) or [], load_matches(),
                                      read_json(DATA / "rapport_extraction.json", {}) or {}, today, tokens)
    if failed:
        alerts = [dict(niveau="alerte", code="collecte", message="La dernière collecte a échoué : les données peuvent dater.")]
    path = PUBLIE / NAME
    previous = read_json(path, {}) or {}
    same = [a["code"] for a in previous.get("alertes") or []] == [a["code"] for a in alerts] \
        and [a["message"] for a in previous.get("alertes") or []] == [a["message"] for a in alerts]
    state = dict(format="hbpsm-sante", v=1, etat="alerte" if any(a["niveau"] == "alerte" for a in alerts) else "info" if alerts else "ok",
                 alertes=alerts, depuis=previous.get("depuis") if same and previous.get("depuis") else paris_now().strftime("%Y-%m-%d %H:%M"))
    if not same or not path.exists():   # ne réécrit (et ne recommite) que si quelque chose change
        from . import publish
        text = json.dumps(state, ensure_ascii=False, indent=1)
        publish.check_public(text, publish.known_names(publish.collect_state(),
                                                       (ROOT / "roster.csv").read_text("utf-8") if (ROOT / "roster.csv").exists() else "",
                                                       publish.history_state()))
        PUBLIE.mkdir(parents=True, exist_ok=True)
        write_json(path, state)
    seen = ", ".join(f"{label} " + (f"{days} j" if isinstance(days, int) else days or "non vérifié") for label, days in tokens.items())
    print(f"[santé] {state['etat']} : {len(alerts)} point(s) à surveiller ; jetons : {seen or 'aucun'} ; "
          f"issue : {issue(alerts, failed) or 'rien à faire'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

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
  tableau-public.json         ce qui ne nomme aucun joueur (prochain match, chances, classements,
                              repérage par numéros, axes, logos des clubs en petites images) :
                              l'écran « Tableau de bord » de HANDBALL-training le lit sans phrase ;
                              vérifié avant publication
  matchs.ics                  calendrier des matchs du club (pipeline/agenda.py), auquel chacun
                              s'abonne : équipes, dates, gymnases, scores ; vérifié avant publication
La page part aussi sur GitHub Pages (workflow) : elle ne contient aucune donnée.
"""
import base64
import datetime as dt
import hashlib
import io
import json
import os
import pathlib
import sys
import time

from . import agenda, collect, presences, vault
from .analyze import analyze, published_cancellations
from .build_dashboard import app_version, render
from .common import DATA, MATCHES, PUBLIE, ROOT, load_config, norm, read_json, write_json
from .export_training import build_exports

STATE_FILES = ("fixtures.json", "official_standings.json", "rapport_extraction.json", "planif.json", "chances.json",
               "pronostics.json")
PAGE_NAME = "HBPSM-tableau-de-bord.html"
# Séance du prochain entraînement, publiée EN CLAIR pour l'application HANDBALL-training : elle ne
# porte aucun nom de joueur (équipes, chiffres d'équipe, numéros de maillot), ce que seal() vérifie.
SEANCE_NAME = "seance-prochaine.hbt.json"
HISTORY_NAME = "historique.enc"
PUBLIC_NAME = "tableau-public.json"
VERIF = 600  # secondes entre deux vérifications du manifeste par la page ouverte
LOGO_PX = 64  # côté des logos intégrés au résumé public
LOGO_PAUSE = 0.5  # secondes entre deux logos téléchargés (seuls les nouveaux le sont)


def repo_slug(config):
    return os.environ.get("GITHUB_REPOSITORY") or config.get("depot") or ""


def page_config(config):
    slug = repo_slug(config)
    branch = os.environ.get("GITHUB_REF_NAME") or config.get("branche") or "main"
    raw = f"https://raw.githubusercontent.com/{slug}/{branch}/publie/" if slug else ""
    return dict(src=raw + "hbpsm.enc" if raw else "", manifeste=raw + "manifeste.json" if raw else "",
                choix=raw + "choix.enc" if raw else "", caisse=raw + "caisse.enc" if raw else "",
                sante=raw + "sante.json" if raw else "", ics=raw + agenda.NAME if raw else "",
                depot=slug, branche=branch,
                **cn_config(config),
                iterations=vault.ITERATIONS,  # la page chiffre les choix de l'entraîneur comme le coffre
                versions=f"https://github.com/{slug}/releases/latest" if slug else "",
                app=app_version(), club=config["club"]["nom_affiche"], verif=VERIF)


def pages_url(config):
    """L'adresse de la page sur GitHub Pages : « propriétaire/dépôt » -> https://propriétaire.github.io/dépôt/."""
    owner, _, repo = repo_slug(config).partition("/")
    return f"https://{owner}.github.io/{repo}/" if owner and repo else ""


def cn_config(config):
    """Le dépôt des propositions d'amendes (caisse noire) : où les envoyer, où les relire. Le jeton,
    lui, n'est jamais dans la page publique : il voyage dans les données chiffrées."""
    cn = config.get("propositions") or {}
    if not cn.get("depot"):
        return dict(cn="", cn_depot="", cn_workflow="", presences="")
    branch = cn.get("branche") or "main"
    # les réponses de présence, les « Vous êtes » et les votes de l'homme du match : même dépôt, même workflow
    return dict(cn=f"https://raw.githubusercontent.com/{cn['depot']}/{branch}/propositions.enc", cn_depot=cn["depot"],
                cn_branche=branch, cn_workflow=cn.get("workflow") or "proposer.yml", presences=presences.url(config))


def collect_state():
    state = {name: read_json(DATA / name) for name in STATE_FILES}
    state["matches"] = {p.stem: json.loads(p.read_text("utf-8")) for p in sorted(MATCHES.glob("*.json"))}
    return state


def history_state():
    """Saisons passées collectées (et matchs de nos jeunes) : {fichier: contenu}."""
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
    """Une ligne par joueur : « Prénom Nom », suivi si besoin de « ,POSTE », de « ,non »
    (indisponible) ou « ,dépannage » (joue seulement s'il manque des joueurs), de « ,trésorier »
    (tient la caisse noire) ou « ,hors caisse » (n'y participe pas), de sa tranche d'âge de 5 ans à partir de 18 ans : « ,18-22 », « ,23-27 »…
    (âge atteint dans l'année où la saison commence ; jamais l'année de naissance), du jour de son anniversaire « ,MM-JJ »
    (sans l'année) et, s'il ne reste pas toute la saison, du dernier mois ou jour où il est disponible
    « ,AAAA-MM » ou « ,AAAA-MM-JJ », et de l'avis de l'auteur, 1 à 5 étoiles « ,4 » (jamais affiché). Une
    ligne de rôle « coach » donne l'anniversaire de l'entraîneur, sans en faire un joueur."""
    text = os.environ.get("HBPSM_EFFECTIF") or ""
    lines = [l.strip() for l in text.replace(";", ",").splitlines() if l.strip()]
    lines = [l for l in lines if not l.lower().startswith("nom,")]
    (ROOT / "roster.csv").write_text("nom,poste,disponible,role,age,naissance,jusqu_au,avis\n" + "\n".join(lines) + "\n", "utf-8")
    staff = sum(1 for l in lines if any(w in norm(l.split(",")[3] if l.count(",") >= 3 else "") for w in ("COACH", "ENTRAINEUR")))
    print(f"[effectif] {len(lines) - staff} joueurs" + (f", {staff} de l'encadrement" if staff else ""))
    return 0


def known_names(state, roster_text, history=None):
    """Noms de personnes connus : joueurs des feuilles (les deux équipes, saison passée comprise)
    et effectif du club."""
    matches = list(state["matches"].values())
    matches += [m for season in (history or {}).values() for m in season.get("matches") or []]
    names = {p.get("name") for m in matches
             for side in ("home", "away") for p in (m.get("players") or {}).get(side, [])}
    names |= {line.split(",")[0] for line in roster_text.splitlines()[1:]}
    return {norm(n) for n in names if n and len(norm(n).split()) >= 2}


def team_public(e):
    """Profil d'équipe sans nom de personne : les joueurs à surveiller par leur numéro."""
    if not e:
        return None
    keep = ("equipe", "poule", "j", "bp_moy", "bc_moy", "forme", "mt1_bp", "mt2_bp", "mt1_bc", "mt2_bc",
            "deux_min_moy", "jaunes_moy", "rouges", "arrets_pct", "periodes_bp", "periodes_bc", "plan", "plan_raison",
            "niveau", "poule_libelle", "forfait")
    out = {k: e.get(k) for k in keep}
    out["buteurs"] = [{k: b.get(k) for k in ("num", "buts", "pen", "m", "moy", "tirs", "reussite")} for b in e.get("buteurs") or []]
    out["gardiens"] = [{k: g.get(k) for k in ("num", "m", "arrets", "pris", "pct", "estime")} for g in e.get("gardiens") or []]
    x = e.get("passe")
    out["passe"] = None if not x else dict(
        {k: x.get(k) for k in ("saison", "niveau", "division", "j", "v", "n", "d", "bp_moy", "bc_moy", "rangs",
                               "face_a_face", "continuite", "feuilles")},
        buteurs=[{k: b.get(k) for k in ("num", "buts", "present")} for b in x.get("buteurs") or []])
    o = e.get("origines")
    out["origines"] = None if not o else dict({k: o.get(k) for k in ("saison", "vus", "retrouves")},
                                              equipes=[{k: t.get(k) for k in ("equipe", "niveau", "division", "joueurs")}
                                                       for t in o.get("equipes") or []])
    y = e.get("dessus")
    out["dessus"] = None if not y else {k: y.get(k) for k in ("saison", "niveau", "division", "j", "v", "n", "d",
                                                              "bp_moy", "bc_moy", "rangs", "continuite")}
    return out


def public_summary(data):
    """Ce que HANDBALL-training montre sans phrase : l'équipe, jamais un joueur par son nom."""
    club, s = data["meta"].get("club"), data.get("saison") or {}
    nxt = dict(data["prochain"]) if data.get("prochain") else None
    if nxt:
        found = next((m for m in s.get("matchs") or [] if m.get("id") == nxt.get("id")), {})
        nxt.update({k: found.get(k) for k in ("p_victoire", "enjeu", "cle", "rang_adv")})
    keep_m = ("journee", "coupe", "tour", "date", "provisoire", "adversaire", "domicile", "p_victoire", "enjeu", "cle", "rang_adv")
    return dict(
        format="hbpsm-public", v=1, genere=data["meta"]["genere"], club=club, club_court=data["meta"].get("club_court"),
        saison=data["meta"].get("saison"), feuilles=data["meta"].get("club_feuilles"), prochain=nxt,
        adversaire=team_public((data.get("equipes") or {}).get(nxt["adversaire"])) if nxt else None,
        nous=team_public((data.get("equipes") or {}).get(club)),
        objectif=None if not s else dict({k: s.get(k) for k in ("statut", "poule", "cible", "rang", "pts", "restants",
                                                                  "proba", "proba_tout", "rangs", "pts_max")},
                                         matchs=[{k: m.get(k) for k in keep_m} for m in s.get("matchs") or []]),
        poules={p: [{k: r.get(k) for k in ("rang", "equipe", "pts", "j", "v", "n", "d", "bp", "bc", "diff", "forme", "forfait")}
                    for r in v["classement"]] for p, v in (data.get("poules") or {}).items()},
        resultats=[{k: r.get(k) for k in ("poule", "journee", "date", "dom", "ext", "sd", "se")} for r in (data.get("resultats") or [])[:16]],
        axes=[{k: a.get(k) for k in ("titre", "libelle", "constat")} for a in data.get("axes") or []])


def code_version():
    """Empreinte du calcul (pipeline et réglages) : le changer republie, même sans nouvelle feuille."""
    h = hashlib.sha256()
    for path in sorted(pathlib.Path(__file__).parent.glob("*.py")) + [ROOT / "config.yml"]:
        if path.exists():
            h.update(path.read_bytes())
    return h.hexdigest()[:12]


def small_logo(url):
    """Le logo réduit, en image intégrée (data:) : HANDBALL-training le montre sans rien télécharger."""
    from PIL import Image
    img = Image.open(io.BytesIO(collect.fetch(url)))
    img.thumbnail((LOGO_PX, LOGO_PX))
    out = io.BytesIO()
    img.save(out, "WEBP", quality=80)
    return "data:image/webp;base64," + base64.b64encode(out.getvalue()).decode("ascii")


def embed_logos(board, logos, previous):
    """Ajoute au résumé public le logo des équipes qu'il nomme. Le serveur des logos n'autorise pas
    l'application à les lire elle-même, et elle doit marcher hors connexion : ils viennent donc dans
    le résumé, réduits. Ceux du résumé précédent sont repris tant que leur adresse ne change pas."""
    teams = {board.get("club")} | {r.get("equipe") for v in board["poules"].values() for r in v}
    teams |= {m.get("adversaire") for m in [board.get("prochain") or {}] + ((board.get("objectif") or {}).get("matchs") or [])}
    teams |= {r.get(k) for r in board.get("resultats") or [] for k in ("dom", "ext")}
    old_img, old_src = previous.get("logos") or {}, previous.get("logos_sources") or {}
    imgs, srcs = {}, {}
    for team in sorted(t for t in teams if t and logos.get(t)):
        url = logos[team]
        if old_src.get(team) == url and str(old_img.get(team) or "").startswith("data:image/"):
            imgs[team] = old_img[team]
        else:
            try:
                imgs[team] = small_logo(url)
            except Exception as exc:  # logo absent ou illisible : l'application montre les initiales
                print(f"[publication] logo non repris ({team}) : {type(exc).__name__}")
                continue
            time.sleep(LOGO_PAUSE)
        srcs[team] = url
    board["logos"], board["logos_sources"] = imgs, srcs
    return board


def check_public(text, names):
    """Refuse un fichier public où apparaît un nom de personne, dans un ordre ou dans l'autre."""
    words = norm(text).split()
    for name in names:
        parts = name.split()
        for i in range(len(words) - len(parts) + 1):
            if sorted(words[i:i + len(parts)]) == sorted(parts):
                raise vault.VaultError("un fichier public contiendrait un nom de joueur : publication refusée.")


def seal(today=None):
    secret = vault.passphrase()
    config = load_config()
    data = analyze(today)
    scratch = ROOT / "raw" / "export"
    # l'effectif annoncé de la prochaine séance : les réponses de présence des joueurs (dépôt hbpsm-cn) ; les
    # séances et matchs annulés par l'entraîneur (choix.enc) : séance suivante, match marqué annulé au calendrier
    cancelled = published_cancellations()
    _, seance = build_exports(data, scratch, today, presences.journal(config, secret), cancelled)
    state = collect_state()
    roster_text = (ROOT / "roster.csv").read_text("utf-8") if (ROOT / "roster.csv").exists() else ""
    hist = history_state()
    hist_digest = hashlib.sha256(json.dumps(hist, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    jeton = hashlib.sha256((os.environ.get("HBPSM_JETON_CN") or "").encode("utf-8")).hexdigest()[:12]   # un jeton posé : republier
    effectif = [seance["contenu"]["seance"][k] for k in ("effectifJoueurs", "effectifGardiens")] + sorted(cancelled)   # republier
    digest = hashlib.sha256(json.dumps([state, roster_text, app_version(), code_version(), hist_digest, jeton, effectif], sort_keys=True,
                                       ensure_ascii=False).encode("utf-8")).hexdigest()
    previous = read_json(PUBLIE / "manifeste.json", {}) or {}
    changed = previous.get("empreinte") != digest or not (PUBLIE / "hbpsm.enc").exists()
    cfg = page_config(config)
    public_seance = json.dumps(seance, ensure_ascii=False, indent=1)
    public_board = json.dumps(public_summary(data), ensure_ascii=False, indent=1)
    names = known_names(state, roster_text, history_state())
    calendar = agenda.calendar(state["fixtures.json"] or [], config, pages_url(config), cancelled)
    check_public(public_seance, names)  # avant d'écrire quoi que ce soit
    check_public(public_board, names)
    check_public(" ".join(calendar), names)
    PUBLIE.mkdir(parents=True, exist_ok=True)
    # la page ne contient aucune donnée : elle peut être publique
    (PUBLIE / PAGE_NAME).write_text(render(None, cfg), "utf-8")
    if changed or not (PUBLIE / SEANCE_NAME).exists():
        (PUBLIE / SEANCE_NAME).write_text(public_seance, "utf-8")
    if changed or not (PUBLIE / PUBLIC_NAME).exists():
        # les logos s'ajoutent après la relecture : des images, rangées sous des noms d'équipes déjà relus
        board = embed_logos(json.loads(public_board), data.get("logos") or {}, read_json(PUBLIE / PUBLIC_NAME, {}) or {})
        (PUBLIE / PUBLIC_NAME).write_text(json.dumps(board, ensure_ascii=False, indent=1), "utf-8")
    agenda.save(calendar, PUBLIE / agenda.NAME)   # réécrit seulement si un match change
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

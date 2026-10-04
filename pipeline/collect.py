"""Collecte hebdomadaire sur ffhandball.fr.

Usage : python -m pipeline.collect
Sorties :
  data/fixtures.json            toutes les rencontres vues (jouées ou à venir)
  data/official_standings.json  classement tel qu'affiché par la FFHB
  raw/fdme/<id>.pdf             feuilles de match (non versionnées)
  raw/pages/                    données lues sur chaque page (non versionnées)

Relevé sur le site le 04/10/2026 : chaque page sert ses données dans le HTML même,
  <smartfire-component name="competitions---rencontre-list" attributes="{…json…}">,
donc une requête HTTP suffit, sans navigateur. L'API JSON qu'appelle la page renvoie
des données brouillées : on ne s'en sert pas. Pages lues :
  <compétition>/                          liste des poules (poule-selector)
  <compétition>/poule-<id>/               calendrier des journées, journée en cours, classement
  <compétition>/poule-<id>/journee-<n>/   rencontres de la journée n
  <compétition>/poule-<id>/rencontre-<n>/ gymnase des 4 prochains matchs du club, une fois fixé
Feuille de match : FDM + chemin tiré de son code (WAGWUHC -> W/A/G/W/WAGWUHC.pdf).
"""
import datetime as dt
import gzip
import html
import http.client
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

from .common import DATA, MATCHES, RAW, ROOT, is_club, load_config, norm, read_json, write_json

UA = "hbpsm-dashboard/1.0 (suivi hebdomadaire de deux poules; +https://github.com/strus38/hbpsm-dashboard)"
FDM = "https://fdm.fdme.ffhandball.fr/"
PAUSE = 1.0     # secondes entre deux pages : rester léger avec le site
OUBLI = 21      # jours après lesquels une rencontre sans feuille n'est plus recherchée
BLOCK_RE = re.compile(r"<smartfire-component\s+name=(['\"])([\w-]+)\1\s+attributes=\"([^\"]*)\"")


class Ralenti(OSError):
    """Le site demande de ralentir (HTTP 429) : attendre `wait` secondes, ou reprendre plus tard."""

    def __init__(self, wait):
        super().__init__(f"le site demande de ralentir ({wait} s)")
        self.wait = wait


def fetch(url, tries=3):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    body = gzip.decompress(body)
            return body
        except urllib.error.HTTPError as exc:
            if exc.code != 429:
                raise
            try:
                wait = int(exc.headers.get("Retry-After") or 60)
            except ValueError:  # une date plutôt qu'un nombre de secondes
                wait = 60
            raise Ralenti(wait) from None
        except (ConnectionResetError, http.client.IncompleteRead):  # coupure en cours de transfert
            if attempt == tries - 1:
                raise
            time.sleep(2 * (attempt + 1))


def blocks(text):
    """{nom: données} des blocs d'une page."""
    out = {}
    for m in BLOCK_RE.finditer(text):
        try:
            out.setdefault(m.group(2), json.loads(html.unescape(m.group(3))))
        except ValueError:
            pass
    return out


def page_data(url, raw_name):
    """Blocs « competitions--- » d'une page ; une copie part dans raw/pages."""
    data = {k: v for k, v in blocks(fetch(url).decode("utf-8", "replace")).items()
            if k.startswith("competitions---")}
    write_json(RAW / "pages" / f"{raw_name}.json", dict(url=url, blocs=data))
    time.sleep(PAUSE)
    return data


def clean(name):
    return " ".join(str(name or "").split()) or None


def score(value):
    return int(value) if re.fullmatch(r"\d{1,3}", str(value or "")) else None


def iso_date(value):
    """'2026-10-03T21:00:00+02:00' -> '2026-10-03T21:00' (heure locale affichée par le site)."""
    m = re.match(r"(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}:\d{2}))?", str(value or ""))
    if not m:
        return None
    return f"{m.group(1)}T{m.group(2)}" if m.group(2) else m.group(1)


def pdf_url(code):
    code = str(code or "").strip().upper()
    return f"{FDM}{'/'.join(code[:4])}/{code}.pdf" if re.fullmatch(r"[A-Z0-9]{5,}", code) else None


def journees(data):
    """{numéro: date de début} depuis le calendrier de la poule."""
    poule = (data.get("competitions---journee-selector") or {}).get("poule") or \
        (data.get("competitions---rencontre-list") or {}).get("poule") or {}
    try:
        days = json.loads(poule.get("journees") or "[]")
    except ValueError:
        days = []
    return {int(d["journee_numero"]): d.get("date_debut") for d in days if d.get("journee_numero")}


def fixture(r, poule, base, start=None):
    rid = str(r["ext_rencontreId"])
    num = str(r.get("journeeNumero") or "")
    fx = dict(id=rid, poule=poule, journee=int(num) if num.isdigit() else None,
              date=iso_date(r.get("date")), home=clean(r.get("equipe1Libelle")),
              away=clean(r.get("equipe2Libelle")), score_home=score(r.get("equipe1Score")),
              score_away=score(r.get("equipe2Score")), ht_home=score(r.get("equipe1ScoreMT")),
              ht_away=score(r.get("equipe2ScoreMT")), url=f"{base}rencontre-{rid}/",
              pdf_url=pdf_url(r.get("fdmCode")), equipement=str(r.get("equipementId") or "") or None)
    if not fx["date"] and start:  # horaire pas encore fixé : début du week-end de la journée
        fx.update(date=start, date_provisoire=True)
    return fx


def standings(data, url):
    rows = (data.get("competitions---mini-classement-or-ads") or data.get("competitions---classement")
            or {}).get("classements") or []
    if not rows:
        return None
    rows = sorted(rows, key=lambda r: int(r.get("place") or 99))
    return dict(entetes=["Pos.", "Équipe", "Pts", "J", "G", "N", "P", "BP", "BC", "Diff"],
                lignes=[[str(r.get(k) or "0") if k != "equipe_libelle" else clean(r.get(k))
                         for k in ("place", "equipe_libelle", "point", "joue", "gagne", "nul",
                                   "perdu", "butPlus", "butMoins", "diff")] for r in rows],
                url=url)


def venue(data):
    """Gymnase d'une rencontre, lu sur sa page ; None tant que la fédération ne l'a pas fixé."""
    e = (data.get("competitions---rencontre-salle") or {}).get("equipement") or {}
    if not e.get("libelle"):
        return None
    return dict(nom=clean(e.get("libelle")), rue=clean(e.get("rue")),
                code_postal=clean(e.get("codePostal")), ville=clean(e.get("ville")))


def add_venues(fixtures, old, is_ours, limit=4):
    """Gymnase des prochains matchs du club, pour la convocation : une page de rencontre par
    match, seulement quand la fédération a fixé la salle ou l'a changée depuis la dernière fois."""
    upcoming = sorted((f for f in fixtures.values() if f["score_home"] is None
                       and (is_ours(f["home"]) or is_ours(f["away"]))),
                      key=lambda f: f.get("date") or "9999")[:limit]
    for fx in upcoming:
        before = old.get(fx["id"]) or {}
        if before.get("salle") and before.get("equipement") == fx["equipement"]:
            fx["salle"] = before["salle"]
        elif fx["equipement"]:
            fx["salle"] = venue(page_data(fx["url"], f"{fx['poule']}_rencontre_{fx['id']}"))


def discover(config):
    """Adresse de chaque poule, lue dans la liste des poules de la page de la compétition."""
    comp = config["competition"].rstrip("/") + "/"
    data = page_data(comp, "competition")
    found = {}
    for p in (data.get("competitions---poule-selector") or {}).get("poules") or []:
        m = re.search(r"\bPOULE\s*(\w+)\b", norm(p.get("libelle")))
        if m and p.get("ext_pouleId"):
            found.setdefault(m.group(1), f"{comp}poule-{p['ext_pouleId']}/")
    print(f"[collecte] poules repérées sur la page de la compétition : {sorted(found) or 'aucune'}")
    return found


def set_urls(config):
    """Enregistre dans config.yml les URL fournies au lancement (URL_71, URL_72)."""
    path = ROOT / "config.yml"
    text = path.read_text("utf-8")
    changed = False
    for poule in config["poules"]:
        url = (os.environ.get(f"URL_{poule['id']}") or "").strip()
        if url and url != poule.get("url"):
            poule["url"] = url
            text = re.sub(r'(- id: "%s"\s*\n\s*url: )"[^"]*"' % poule["id"],
                          lambda m: f'{m.group(1)}"{url}"', text)
            changed = True
    if changed:
        path.write_text(text, "utf-8")


def finished(fixtures, known, now):
    """Journée close : toutes ses rencontres jouées, et leur feuille lue ou abandonnée."""
    limit = (dt.date.fromisoformat(now[:10]) - dt.timedelta(days=OUBLI)).isoformat()
    return bool(fixtures) and all(
        f.get("score_home") is not None and (known.get(f["id"]) or (f.get("date") or "") < limit)
        for f in fixtures)


def crawl_poule(poule, known, old, now, is_ours=None):
    """Rencontres et classement d'une poule. Une journée close n'est pas relue.
    now : date et heure locales, '2026-10-04T19:30'.
    is_ours : reconnaît le club, dont on lit aussi le gymnase des prochains matchs."""
    base = poule["url"].rstrip("/") + "/"
    pid = str(poule["id"])
    first = page_data(base, f"{pid}_poule")
    days = journees(first)
    official = standings(first, base)
    current = first.get("competitions---rencontre-list") or {}
    lists = {}
    if str(current.get("selected_numero_journee") or "").isdigit():
        lists[int(current["selected_numero_journee"])] = current.get("rencontres") or []
    for n in sorted(days):
        if n in lists:
            continue
        before = [f for f in old.values() if str(f.get("poule")) == pid and f.get("journee") == n]
        if finished(before, known, now):
            continue
        data = page_data(f"{base}journee-{n}/", f"{pid}_journee_{n}")
        lists[n] = (data.get("competitions---rencontre-list") or {}).get("rencontres") or []
    fixtures = {}
    for n, rows in lists.items():
        for r in rows:
            if r.get("ext_rencontreId"):
                fx = fixture(r, pid, base, days.get(n))
                fixtures[fx["id"]] = fx
    if is_ours:
        add_venues(fixtures, old, is_ours)
    sheets = 0
    for fx in fixtures.values():
        target = RAW / "fdme" / f"{fx['id']}.pdf"
        # score absent mais coup d'envoi passé : le site peut afficher une copie en cache de deux
        # heures, la feuille donne alors le score (avant le match, son adresse répond 404)
        played = fx["score_home"] is not None or (fx["date"] or "9999") < now
        if not played or not fx["pdf_url"] or known.get(fx["id"]) or target.exists():
            continue
        try:
            body = fetch(fx["pdf_url"])
            if body[:4] == b"%PDF":
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(body)
                sheets += 1
        except Ralenti:  # les feuilles restantes attendront le prochain passage
            print("[collecte] le serveur des feuilles demande de ralentir : suite au prochain passage", file=sys.stderr)
            break
        except (urllib.error.URLError, OSError) as exc:  # feuille pas encore déposée : au prochain passage
            print(f"[collecte] feuille {fx['id']}: {exc}", file=sys.stderr)
        time.sleep(PAUSE)
    print(f"[collecte] poule {pid}: {len(lists)} journées lues sur {len(days)}, "
          f"{len(fixtures)} rencontres, {sheets} feuilles téléchargées, "
          f"classement officiel {'oui' if official else 'non'}")
    return fixtures, official


def main():
    config = load_config()
    set_urls(config)
    known = {}
    for p in MATCHES.glob("*.json"):
        m = json.loads(p.read_text("utf-8"))
        known[m["id"]] = (m.get("source") or {}).get("fdme") and not (m.get("source") or {}).get("demo")
    old = {f["id"]: f for f in (read_json(DATA / "fixtures.json", []) or []) if not f.get("demo")}
    officials = read_json(DATA / "official_standings.json", {}) or {}
    now = dt.datetime.now().strftime("%Y-%m-%dT%H:%M")
    if not all(p.get("url") for p in config["poules"]):
        found = discover(config)
        for p in config["poules"]:
            if not p.get("url") and found.get(p["id"]):
                os.environ[f"URL_{p['id']}"] = found[p["id"]]
        set_urls(config)
    missing = [p["id"] for p in config["poules"] if not p.get("url")]
    if missing:
        print(f"[collecte] URL manquante pour la poule {', '.join(missing)} : "
              "renseigne-la au lancement du workflow ou dans config.yml", file=sys.stderr)
    for poule in config["poules"]:
        if not poule.get("url"):
            continue
        try:
            fixtures, official = crawl_poule(poule, known, old, now, lambda t: is_club(t, config))
        except (urllib.error.URLError, OSError) as exc:  # site injoignable : l'état précédent reste valable
            print(f"[collecte] poule {poule['id']}: {exc}", file=sys.stderr)
            missing.append(poule["id"])
            continue
        old.update(fixtures)  # le site fait foi : une rencontre relue remplace l'ancienne
        if official:
            officials[poule["id"]] = official
    write_json(DATA / "fixtures.json", sorted(old.values(), key=lambda f: (f.get("date") or "9999", f["id"])))
    write_json(DATA / "official_standings.json", officials)
    return 0 if not missing else 2


if __name__ == "__main__":
    sys.exit(main())

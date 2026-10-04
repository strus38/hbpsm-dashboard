"""Saisons précédentes : les matchs du club et de ses adversaires d'aujourd'hui.

Usage : python -m pipeline.history [--force]
Entrées : config.yml (historique : saison et adresse de la compétition), data/fixtures.json
          (équipes de la saison en cours)
Sorties : data/historique/<saison>.json  rencontres, classements et feuilles lues (jamais versionné ;
                                         publié chiffré dans publie/historique.enc)
          raw/historique/<saison>/fdme/  feuilles PDF (jamais versionnées)

Une saison finie ne change plus : elle est collectée une fois, puis gardée. La collecte lit
chaque poule de la compétition, garde celles où jouait le club ou une équipe de la saison en
cours, lit toutes leurs journées, puis les feuilles des seuls matchs de ces équipes. Le serveur
des feuilles limite le débit (HTTP 429) : elles se lisent une toutes les SHEET_PAUSE secondes,
en attendant le délai qu'il demande, dans un budget de temps par passage ; le passage suivant
reprend où le précédent s'est arrêté. Les
déroulés ne sont gardés que pour les matchs du club (buts pris par chaque gardien) : tableaux et
scores suffisent pour les autres, et le fichier chiffré reste léger.
"""
import sys
import urllib.error

from . import collect, parse_fdme
from .common import DATA, RAW, is_club, load_config, read_json, same_team, write_json

HISTORY = DATA / "historique"


SHEET_PAUSE = 4      # secondes entre deux feuilles : le serveur des feuilles limite le débit (429)
SHEET_BUDGET = 900   # secondes au plus par passage pour les feuilles ; la suite au passage suivant


def collect_season(saison, competition, current, is_ours):
    """Rencontres et classements des poules utiles d'une saison passée, sans les feuilles."""
    comp = competition.rstrip("/") + "/"
    tag = f"historique_{saison}"
    poules = (collect.page_data(comp, f"{tag}_competition").get("competitions---poule-selector") or {}).get("poules") or []
    relevant = lambda t: bool(t) and (is_ours(t) or any(same_team(t, c) for c in current))
    out = dict(saison=saison, competition=comp, poules={}, matches=[])
    for p in poules:
        base = f"{comp}poule-{p['ext_pouleId']}/"
        try:
            first = collect.page_data(base, f"{tag}_{p['ext_pouleId']}")
        except urllib.error.HTTPError as exc:  # une poule disparue ne bloque pas la saison
            print(f"[historique] poule {p.get('libelle')}: {exc}", file=sys.stderr)
            continue
        table = collect.standings(first, base)
        teams = [row[1] for row in (table or {}).get("lignes", [])]
        if not any(relevant(t) for t in teams):
            continue
        days = collect.journees(first)
        fixtures = {}
        for n in sorted(days):
            data = collect.page_data(f"{base}journee-{n}/", f"{tag}_{p['ext_pouleId']}_j{n}")
            for r in (data.get("competitions---rencontre-list") or {}).get("rencontres") or []:
                if r.get("ext_rencontreId"):
                    fx = collect.fixture(r, p["libelle"], base, days.get(n))
                    fixtures[fx["id"]] = fx
        out["poules"][p["libelle"]] = dict(id=p["ext_pouleId"], classement=table, equipes=teams)
        for fx in sorted(fixtures.values(), key=lambda f: (f.get("date") or "", f["id"])):
            if fx["score_home"] is None:
                continue
            match = parse_fdme.build_match(fx, None)
            match.update(saison=saison, phase=p["libelle"])
            match["source"] = dict(fdme=False, pdf=fx["pdf_url"], utile=relevant(fx["home"]) or relevant(fx["away"]))
            out["matches"].append(match)
    print(f"[historique] {saison} : {len(out['poules'])} poules ({', '.join(out['poules'])}), {len(out['matches'])} matchs")
    return out


def read_sheet(match, path, is_ours):
    """Complète un match avec sa feuille : joueurs, mi-temps, et le déroulé pour les matchs du club."""
    fx = dict(id=match["id"], poule=match["poule"], journee=match.get("journee"), date=match.get("date"),
              home=match["home"]["name"], away=match["away"]["name"], score_home=match["home"]["score"],
              score_away=match["away"]["score"], ht_home=match["home"].get("ht"), ht_away=match["away"].get("ht"))
    new = parse_fdme.build_match(fx, parse_fdme.parse_pdf(path))
    new.update(saison=match["saison"], phase=match["phase"])
    new["source"].update(pdf=match["source"].get("pdf"), utile=True)
    new["source"].pop("url", None)
    if not (is_ours(fx["home"]) or is_ours(fx["away"])):
        new["events"] = []
    return new


def fetch_sheets(season, target, is_ours, budget=SHEET_BUDGET):
    """Télécharge et lit les feuilles utiles qui manquent, en respectant le débit demandé par le
    serveur ; enregistre au fur et à mesure. Renvoie le nombre de feuilles encore à lire."""
    start = collect.time.monotonic()
    folder = RAW / "historique" / season["saison"] / "fdme"
    todo = [i for i, m in enumerate(season["matches"])
            if m["source"].get("utile") and m["source"].get("pdf") and not m["source"].get("fdme")]
    done = 0
    for n, i in enumerate(todo):
        m = season["matches"][i]
        path = folder / f"{m['id']}.pdf"
        while not path.exists():
            try:
                body = collect.fetch(m["source"]["pdf"])
                if body[:4] == b"%PDF":
                    folder.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(body)
                collect.time.sleep(SHEET_PAUSE)
                break
            except collect.Ralenti as exc:
                if collect.time.monotonic() - start + exc.wait > budget:
                    print(f"[historique] le serveur des feuilles demande de ralentir : {len(todo) - n} feuilles "
                          "à lire au prochain passage", file=sys.stderr)
                    write_json(target, season)
                    return len(todo) - n
                collect.time.sleep(min(exc.wait, 120))
            except (urllib.error.URLError, OSError) as exc:
                print(f"[historique] feuille {m['id']}: {exc}", file=sys.stderr)
                break
        if path.exists():
            try:
                season["matches"][i] = read_sheet(m, path, is_ours)
                done += 1
            except Exception as exc:  # une feuille illisible ne bloque pas la saison
                print(f"[historique] {path.name}: {exc}", file=sys.stderr)
        if done and done % 10 == 0:
            write_json(target, season)
    write_json(target, season)
    left = sum(1 for m in season["matches"] if m["source"].get("utile") and m["source"].get("pdf")
               and not m["source"].get("fdme"))
    return left


def main():
    config = load_config()
    force = "--force" in sys.argv
    is_ours = lambda t: is_club(t, config)
    current = {f[side] for f in read_json(DATA / "fixtures.json", []) or [] for side in ("home", "away") if f.get(side)}
    for entry in config.get("historique") or []:
        target = HISTORY / f"{entry['saison']}.json"
        season = None if force else read_json(target)
        if season is None:
            if not current:
                print("[historique] calendrier de la saison en cours inconnu : collecte remise à plus tard", file=sys.stderr)
                return 0
            try:
                season = collect_season(entry["saison"], entry["competition"], current, is_ours)
            except (urllib.error.URLError, OSError) as exc:  # site injoignable : on réessaiera au prochain passage
                print(f"[historique] {entry['saison']} : {exc}", file=sys.stderr)
                continue
            write_json(target, season)
        left = fetch_sheets(season, target, is_ours)
        read = sum(1 for m in season["matches"] if m["source"].get("fdme"))
        print(f"[historique] {entry['saison']} : {read} feuilles lues" + (f", {left} à venir" if left else ", complète"))
    return 0


if __name__ == "__main__":
    sys.exit(main())

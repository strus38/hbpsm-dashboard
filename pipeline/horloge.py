"""Horloge de la collecte (.github/workflows/horloge.yml) : faut-il lancer « Collecte quotidienne » maintenant ?

Horaire (demande de l'auteur, 11/10/2026), heure de Paris : le dimanche et le lundi toutes les deux heures de 6 h à
22 h, du mardi au samedi à 6 h, 12 h et 18 h.

Les lancements programmés de GitHub partent avec des heures de retard, ou pas du tout : du 19/10 au 08/11/2026, du
mardi au samedi deux ou trois collectes sur trois, le dimanche et le lundi deux à quatre sur neuf, celle de 6 h partie
entre 10 h et 14 h ; le dimanche 08/11, rien avant 12 h 53, alors que les feuilles du samedi soir arrivaient. Avant,
chaque horaire avait son seul passage (et son double de l'autre saison, qui ne faisait rien) : un passage sauté, c'était
une collecte perdue. Depuis le
08/11/2026 (demande de l'auteur : « rends l'horloge moins fragile »), l'horloge passe toutes les heures et chaque passage
rattrape l'horaire manqué : il lance la collecte quand aucune collecte réussie n'a eu lieu depuis le dernier horaire
passé, d'après la date `collecte` du manifeste (écrite quand les deux poules sont lues : un site de la fédération en
panne, 502 ou 504, fait donc réessayer au passage suivant). Pas de collecte :
  - quand une collecte est en cours ou attend son tour (elle part du dernier état) ; un recalcul ne compte pas, il ne
    lit pas le site, et une collecte lancée prend sa place dans la file ;
  - quand l'horaire suivant arrive dans moins d'une demi-heure (`MARGE`) : son propre passage s'en charge.
L'heure d'été et l'heure d'hiver n'ont plus de ligne chacune : tout se compte à l'heure de Paris. Les collectes lancées
par cron-job.org ou à la main comptent comme les autres.

Bibliothèque standard seulement : le workflow ne lit que ce fichier et le manifeste, sans rien installer.
Usage (workflow) : python3 pipeline/horloge.py publie/manifeste.json <collectes.json>
  collectes.json : `gh run list --workflow weekly.yml --json status,displayTitle`
  écrit « lancer=oui » ou « lancer=non » dans $GITHUB_OUTPUT et dit pourquoi dans le journal.
"""
import datetime as dt
import json
import os
import sys
from zoneinfo import ZoneInfo

PARIS = ZoneInfo("Europe/Paris")
DEUX_HEURES = tuple(range(6, 23, 2))
TROIS_FOIS = (6, 12, 18)
# heures de Paris, par jour de la semaine (0 = lundi, comme datetime.weekday)
HORAIRE = {0: DEUX_HEURES, 1: TROIS_FOIS, 2: TROIS_FOIS, 3: TROIS_FOIS, 4: TROIS_FOIS, 5: TROIS_FOIS, 6: DEUX_HEURES}
MARGE = dt.timedelta(minutes=30)
COLLECTE = "Collecte quotidienne"   # run-name de weekly.yml pour une collecte ; un recalcul a un autre nom
JOURS = ("lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim.")


def slots_of(day):
    """Les horaires de collecte d'un jour (date), à l'heure de Paris."""
    return [dt.datetime(day.year, day.month, day.day, h, tzinfo=PARIS) for h in HORAIRE[day.weekday()]]


def last_slot(now):
    """Le dernier horaire passé (ou l'instant même) avant `now`."""
    now = now.astimezone(PARIS)
    for back in range(8):
        passed = [s for s in slots_of(now.date() - dt.timedelta(days=back)) if s <= now]
        if passed:
            return passed[-1]
    raise ValueError("aucun horaire dans la semaine")


def next_slot(now):
    """Le prochain horaire, strictement après `now`."""
    now = now.astimezone(PARIS)
    for ahead in range(8):
        coming = [s for s in slots_of(now.date() + dt.timedelta(days=ahead)) if s > now]
        if coming:
            return coming[0]
    raise ValueError("aucun horaire dans la semaine")


def parse_utc(text):
    """« 2026-11-07T20:51:35Z » -> date et heure (avec fuseau) ; None si absente ou illisible."""
    try:
        when = dt.datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return when if when.tzinfo else when.replace(tzinfo=dt.timezone.utc)


def fmt(when):
    """« dim. 08/11 12:00 », à l'heure de Paris."""
    when = when.astimezone(PARIS)
    return f"{JOURS[when.weekday()]} {when:%d/%m %H:%M}"


def decide(now, last_ok, runs):
    """(lancer ?, pourquoi). `last_ok` : dernière collecte réussie (None : jamais) ; `runs` : passages de weekly.yml."""
    busy = [r for r in runs or [] if r.get("displayTitle") == COLLECTE and r.get("status") != "completed"]
    if busy:
        return False, "une collecte est en cours ou attend son tour : elle part du dernier état"
    slot = last_slot(now)
    if last_ok and last_ok >= slot:
        return False, f"collecte réussie {fmt(last_ok)}, après l'horaire de {fmt(slot)} : rien à faire"
    since = f"dernière collecte réussie : {fmt(last_ok)}" if last_ok else "aucune collecte réussie connue"
    coming = next_slot(now)
    if coming - now < MARGE:
        return False, f"horaire de {fmt(coming)} dans moins de 30 min : son passage s'en charge ({since})"
    return True, f"aucune collecte réussie depuis l'horaire de {fmt(slot)} ({since}) : collecte lancée"


def read(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def main(argv=None, now=None):
    argv = sys.argv[1:] if argv is None else argv
    manifest = read(argv[0], {}) if argv else {}
    runs = read(argv[1], []) if len(argv) > 1 else []
    now = now or dt.datetime.now(dt.timezone.utc)
    last_ok = parse_utc((manifest if isinstance(manifest, dict) else {}).get("collecte"))
    go, why = decide(now, last_ok, runs if isinstance(runs, list) else [])
    print(f"[horloge] {fmt(now)} : {why}")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"lancer={'oui' if go else 'non'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Le calendrier des matchs du club (publie/matchs.ics), public et sans aucun nom de joueur.

Chacun s'y abonne une fois dans son agenda (Google, iPhone, Outlook) : les matchs de la saison, en
championnat et en coupe, s'y mettent à jour d'eux-mêmes quand la fédération fixe un horaire ou un
gymnase (demande de l'auteur, 06/10/2026). Horaire pas encore fixé : le week-end de la journée, en
journée entière, « horaire à confirmer ». Match joué : son score. Les matchs contre une équipe en
forfait général n'y sont pas. Le fichier n'est réécrit que si un match change.
"""
import datetime as dt
import re

from .common import is_club, norm

NAME = "matchs.ics"
DUREE = 90  # minutes inscrites pour un match
STAMP = "DTSTAMP:@"  # posé à l'écriture
VTIMEZONE = ["BEGIN:VTIMEZONE", "TZID:Europe/Paris",
             "BEGIN:DAYLIGHT", "TZOFFSETFROM:+0100", "TZOFFSETTO:+0200", "TZNAME:CEST", "DTSTART:19700329T020000",
             "RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU", "END:DAYLIGHT",
             "BEGIN:STANDARD", "TZOFFSETFROM:+0200", "TZOFFSETTO:+0100", "TZNAME:CET", "DTSTART:19701025T030000",
             "RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU", "END:STANDARD", "END:VTIMEZONE"]


def short_team(name, config):
    """« P16M DIV2 RTE NORD DROME HANDBALL 2 » -> « Nord Drome 2 » (comme dans la page)."""
    if is_club(name, config):
        return config["club"]["nom_affiche"]
    t = str(name or "")
    words = [w for w in re.sub(r"^P\d+[MF]?\s*(DIV\d*)?\s*-?\s*", "", t, flags=re.I).split()
             if not re.fullmatch(r"HB|HBC|HANDBALL|CLUB|RTE|ENTENTE|-", w, flags=re.I)]
    base = re.sub(r"(^|[\s-])(\S)", lambda m: m.group(1) + m.group(2).upper(), (" ".join(words[:2]) or t).lower())
    num = re.search(r"[\s-](\d)\s*$", t)
    return f"{base} {num.group(1)}" if num and not base.endswith(num.group(1)) else base


def competition_label(url):
    """« …/2eme-division-masculine-p16-aura-30501/ » -> « 2e division P16 AURA »."""
    m = re.search(r"/([a-z0-9-]+?)-\d+/?$", url or "")
    if not m:
        return "Championnat"
    words = [w for w in m.group(1).split("-") if w not in ("masculine", "masculin")]
    out = []
    for w in words:
        n = re.fullmatch(r"(\d+)(?:ere|eme)", w)
        out.append(f"{n.group(1)}{'re' if n.group(1) == '1' else 'e'}" if n else w.upper() if w in ("p16", "aura") else w)
    return " ".join(out)


def tour_label(tour):
    """« 1ER TOUR » -> « 1er tour »."""
    return str(tour or "").lower() or "tour à venir"


def where(salle):
    if not salle:
        return ""
    nice = lambda s: " ".join(w.capitalize() for w in str(s).split())
    return ", ".join(x for x in (nice(salle.get("nom") or ""), nice(salle.get("rue") or ""),
                                 " ".join(x for x in (salle.get("code_postal") or "", nice(salle.get("ville") or "")) if x)) if x)


def text(value):
    return str(value).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def fold(line):
    """Lignes de 75 octets au plus (RFC 5545), la suite précédée d'une espace."""
    out, cur = [], ""
    for ch in line:
        if len((cur + ch).encode("utf-8")) > 74:
            out.append(cur)
            cur = " " + ch
        else:
            cur += ch
    out.append(cur)
    return "\r\n".join(out)


def calendar(fixtures, config, page=""):
    """Les lignes du calendrier ; DTSTAMP en attente (STAMP), posé à l'écriture."""
    gone = {norm(t) for t in config.get("forfaits") or []}
    league = competition_label(config.get("competition"))
    club = config["club"]["nom_affiche"]
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//HBPSM//Tableau de bord//FR", "CALSCALE:GREGORIAN",
             "METHOD:PUBLISH", f"X-WR-CALNAME:{text(club)} · matchs seniors", "X-WR-TIMEZONE:Europe/Paris",
             "REFRESH-INTERVAL;VALUE=DURATION:PT6H", "X-PUBLISHED-TTL:PT6H", *VTIMEZONE]
    ours = [f for f in fixtures if f.get("date") and not f.get("externe")
            and (is_club(f.get("home"), config) or is_club(f.get("away"), config))]
    for f in sorted(ours, key=lambda f: (f["date"], str(f.get("id")))):
        dom = is_club(f.get("home"), config)
        if norm(f["away"] if dom else f["home"]) in gone:
            continue
        home, away = short_team(f["home"], config), short_team(f["away"], config)
        played = f.get("score_home") is not None and f.get("score_away") is not None
        what = f"{f['coupe']}, {tour_label(f.get('tour'))}" if f.get("coupe") else f"J{f.get('journee') or '?'}"
        tbd = bool(f.get("date_provisoire")) or len(f["date"]) <= 10
        title = (f"{home} {f['score_home']}-{f['score_away']} {away}" if played else f"{home} – {away}") + f" · {what}"
        day = dt.date.fromisoformat(f["date"][:10])
        if tbd and not played:
            title += " (horaire à confirmer)"
        about = [f"{f['coupe']}, {tour_label(f.get('tour'))}" if f.get("coupe")
                 else f"{league}, poule {f.get('poule')}, journée {f.get('journee') or '?'}",
                 "À domicile" if dom else "À l'extérieur"]
        if played:
            about.append(f"Résultat : {home} {f['score_home']}-{f['score_away']} {away}")
        elif tbd:
            about.append("Horaire pas encore fixé par la fédération : le match se joue ce week-end-là.")
        if f.get("url"):
            about.append(f"Feuille de match et résultats : {f['url']}")
        if page:
            about.append(f"Tableau de bord : {page}")
        lines += ["BEGIN:VEVENT", f"UID:hbpsm-{f.get('id')}@hbpsm-dashboard", STAMP]
        if tbd:
            lines += [f"DTSTART;VALUE=DATE:{day:%Y%m%d}", f"DTEND;VALUE=DATE:{day + dt.timedelta(days=2):%Y%m%d}"]
            if not played:
                lines.append("STATUS:TENTATIVE")
        else:
            start = dt.datetime.fromisoformat(f["date"][:16])
            lines += [f"DTSTART;TZID=Europe/Paris:{start:%Y%m%dT%H%M%S}",
                      f"DTEND;TZID=Europe/Paris:{start + dt.timedelta(minutes=DUREE):%Y%m%dT%H%M%S}"]
        lines.append(f"SUMMARY:{text(title)}")
        if where(f.get("salle")):
            lines.append(f"LOCATION:{text(where(f.get('salle')))}")
        lines.append("DESCRIPTION:" + text("\n".join(about)))
        if f.get("url"):
            lines.append(f"URL:{f['url']}")
        lines.append("END:VEVENT")
    return lines + ["END:VCALENDAR"]


def save(lines, path, now=None):
    """Écrit le calendrier s'il a changé (DTSTAMP mis à part) ; dit s'il l'a écrit."""
    body = "\r\n".join(fold(line) for line in lines) + "\r\n"
    old = path.read_bytes().decode("utf-8") if path.exists() else ""
    if re.sub(r"DTSTAMP:\d{8}T\d{6}Z", STAMP, old) == body:
        return False
    stamp = (now or dt.datetime.now(dt.timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body.replace(STAMP, f"DTSTAMP:{stamp}").encode("utf-8"))
    return True

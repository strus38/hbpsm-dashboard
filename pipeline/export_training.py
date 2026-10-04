"""Passerelle vers l'application de préparation de séances (HANDBALL-training).

Usage : python -m pipeline.export_training
Sorties, publiées avec le tableau de bord :
  docs/entrainement.json          constats de la semaine (contrat neutre, lisible par tout outil)
  docs/seance-prochaine.hbt.json  séance à importer telle quelle dans l'application

Les deux projets restent indépendants : ce fichier respecte le format d'échange
.hbt.json de l'application, et rien d'autre ne les relie. La séance arrive sans
exercice : le tableau de bord dit quoi travailler, l'entraîneur choisit comment.
"""
import datetime as dt

from .analyze import analyze
from .common import DOCS, load_config, paris_now, read_json, write_json

FORMAT_VERSION = 3  # version du format .hbt.json visée ; les versions suivantes le relisent
JOURS = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]
MOIS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]


def date_fr(iso):
    try:
        d = dt.date.fromisoformat(iso[:10])
    except (TypeError, ValueError):
        return "date à confirmer"
    return f"{JOURS[d.weekday()]} {d.day} {MOIS[d.month - 1]}"


def next_training(today, days):
    d = dt.date.fromisoformat(today)
    for i in range(1, 8):
        cand = d + dt.timedelta(days=i)
        if cand.weekday() in days:
            return cand.isoformat()
    return (d + dt.timedelta(days=1)).isoformat()


def objective_text(data):
    nxt, axes = data.get("prochain"), data.get("axes") or []
    parts = []
    if nxt:
        when = date_fr(nxt.get("date")) + (" (week-end, date à confirmer)" if nxt.get("provisoire") else "")
        parts.append(f"Avant {nxt['adversaire']} (journée {nxt.get('journee') or '?'}, {when}, "
                     f"{'à domicile' if nxt.get('domicile') else 'à l’extérieur'}).")
    for i, a in enumerate(axes[:3], 1):
        parts.append(f"{i}) {a['titre']} [{a['libelle']}] : {a['constat']}")
    if not data["meta"].get("club_feuilles"):
        parts.append("Aucune feuille de match du club n'a encore été lue.")
    elif not axes:
        parts.append("Aucun écart marqué par rapport aux autres équipes : entretenir les acquis.")
    adv = (data.get("equipes") or {}).get(nxt["adversaire"]) if nxt else None
    if adv:
        watch = ", ".join(f"n° {b['num']} ({b['moy']:.1f} buts/match)".replace(".", ",")
                          for b in adv["buteurs"][:2])
        parts.append(f"Adversaire : {adv['bp_moy']:.1f} buts marqués et {adv['bc_moy']:.1f} encaissés par match"
                     .replace(".", ",") + (f" ; à surveiller : {watch}." if watch else "."))
    return " ".join(parts)


def build_exports(data=None, out_dir=DOCS, today=None):
    data = data or read_json(out_dir / "data.json") or analyze()
    config = load_config()
    conf = config.get("entrainement") or {}
    today = today or paris_now().date().isoformat()
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    nxt = data.get("prochain")
    brief = dict(
        format="hbpsm-dashboard/entrainement", version=1, genere=data["meta"]["genere"],
        club=data["meta"].get("club"), demo=data["meta"].get("demo", False),
        prochain=nxt, axes=data.get("axes") or [], objectif=objective_text(data),
        adversaire=(data.get("equipes") or {}).get(nxt["adversaire"]) if nxt else None,
        saison={k: v for k, v in (data.get("saison") or {}).items() if k != "matchs"} or None)
    write_json(out_dir / "entrainement.json", brief)
    titre = f"Préparer {nxt['adversaire']}" if nxt else "Séance de la semaine"
    seance = dict(
        id=f"tableau-de-bord-{today}", titre=titre[:80],
        date=next_training(today, conf.get("jours") or [1, 4]),
        equipe=conf.get("equipe", ""), categorieAge=conf.get("categorie_age", ""),
        objectifSeance=brief["objectif"], effectifJoueurs=0, effectifGardiens=0,
        espaceDisponible="", retour="", retourEcritLe="", exercices=[], creeLe=now, modifieLe=now)
    fichier = dict(format="handball-training", version=FORMAT_VERSION, exporteLe=now,
                   application="hbpsm-dashboard", contenu=dict(type="seance", seance=seance))
    write_json(out_dir / "seance-prochaine.hbt.json", fichier)
    return brief, fichier


if __name__ == "__main__":
    b, _ = build_exports()
    print(f"[entraînement] {len(b['axes'])} axes de travail ; séance à importer prête")

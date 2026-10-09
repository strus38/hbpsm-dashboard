"""Tests de la chaîne. Lancer : python -m pytest -q"""
import datetime as dt
import functools
import http.server
import json
import os
import threading

import pytest

from pipeline import analyze as an
from pipeline import caisse, choix, collect, common, demo_data, parse_fdme, presences, pronostic, publish, sante, vault
from pipeline.build_dashboard import build, render
from pipeline.export_training import build_exports
import pathlib
import sys

ROOT_DIR = pathlib.Path(__file__).resolve().parents[1]


def chrome(p):
    """Le Chrome installé sur le poste ; HBPSM_NAVIGATEUR=chromium pour celui de Playwright."""
    channel = os.environ.get("HBPSM_NAVIGATEUR") or "chrome"
    return p.chromium.launch(channel=None if channel == "chromium" else channel)


def serve(directory, handler=http.server.SimpleHTTPRequestHandler):
    """Serveur local sur un port libre ; renvoie (serveur, adresse de base)."""
    handler = functools.partial(handler, directory=str(directory))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_port}/"


class Quiet(http.server.SimpleHTTPRequestHandler):
    seen = []

    def log_message(self, *a, **k):
        Quiet.seen.append(self.path)


@pytest.fixture()
def sandbox(tmp_path, monkeypatch):
    """Redirige data/, raw/ et docs/ vers un dossier temporaire."""
    data, raw = tmp_path / "data", tmp_path / "raw"
    for mod in (common, an, collect, parse_fdme, publish, choix, caisse, sante, pronostic):
        for name, val in (("DATA", data), ("MATCHES", data / "matches"), ("RAW", raw),
                          ("PUBLIE", tmp_path / "publie")):
            if hasattr(mod, name):
                monkeypatch.setattr(mod, name, val)
    monkeypatch.setattr(publish, "ROOT", tmp_path)
    monkeypatch.setattr(presences, "fetch", lambda address: None)   # jamais le vrai journal des présences
    monkeypatch.setattr(sante, "ROOT", tmp_path)
    monkeypatch.setattr(an, "ROOT", tmp_path)  # roster.csv du poste (vrais noms) jamais lu par les tests
    monkeypatch.setattr(an, "load_matches", lambda: [
        json.loads(p.read_text("utf-8")) for p in sorted((data / "matches").glob("*.json"))])
    return tmp_path


def demo(sandbox, **kw):
    return demo_data.generate(data_dir=sandbox / "data", matches_dir=sandbox / "data" / "matches", **kw)


def test_classement_et_notes(sandbox):
    demo(sandbox)
    d = an.analyze("2026-10-04")
    for poule in d["poules"].values():
        rows = poule["classement"]
        assert sum(r["bp"] for r in rows) == sum(r["bc"] for r in rows)
        assert all(r["pts"] == 3 * r["v"] + 2 * r["n"] + r["d"] for r in rows)
        assert [r["pts"] for r in rows] == sorted((r["pts"] for r in rows), reverse=True)
    assert d["meta"]["club"] == demo_data.CLUB
    assert d["prochain"]["journee"] == 4
    notes = [p for p in d["joueurs"] if p["m"]]
    assert notes and all(0 <= s <= 100 for p in notes for s in p["scores"].values())
    assert all(p["scores"]["equilibre"] is None for p in d["joueurs"] if not p["m"])
    club = next(r for r in d["poules"]["71"]["classement"] if r["equipe"] == demo_data.CLUB)
    assert sum(p["buts"] for p in d["joueurs"]) == club["bp"]
    assert all(e["plan"] in an.PLANS for e in d["equipes"].values())
    assert all(isinstance(j["dom"], bool) for p in d["joueurs"] for j in p["journal"])   # domicile / extérieur, pour l'équilibre


def test_sans_donnees(sandbox):
    (sandbox / "data" / "matches").mkdir(parents=True)
    d = an.analyze("2026-10-04")
    assert not any(p["m"] for p in d["joueurs"]) and d["poules"] == {} and d["prochain"] is None
    build(d, sandbox / "docs")
    assert (sandbox / "docs" / "index.html").exists()


# Lignes de la feuille FDME telles que pdfplumber les extrait (forme relevée sur une vraie
# feuille en 2026-2027, noms inventés) : un seul tableau, une ligne d'en-tête par équipe.
ENTETE = ["", "", "", "Capt", "", "N°", "NOM Prénom (Nom d'usage)", "", "", "", "", "Licence", "",
          "Type", "JFL", "", "Buts", "7m", "", "Tirs", "", "Arrets", "Av.", "", "2'", "", "Dis"]


def ligne(num, nom, buts="", pen="", tirs="", arrets="", av="", deux="", dis="", capt=""):
    return ["", "", "", capt, "", str(num), nom, "", "", "", "", "6138012100123", "", "A", "", "",
            buts, pen, "", tirs, "", arrets, av, "", deux, "", dis]


FEUILLE = [
    ["Organisateur", "", "", "", "LIGUE INVENTÉE (5100000)"] + [""] * 22,
    ["CLUB ALPHA / CLUB BRAVO"] + [""] * 19 + ["6", "", "3"] + [""] * 4,
    ["# - tnavecer bulC", "AHPLA BULC"] + ENTETE[2:],
    ligne(1, "GARDIEN Alpha", arrets="9"),
    ligne(7, "DUPONT Jean", buts="4", pen="1", tirs="5", av="X", capt="X"),
    ligne(9, "ESSAI Basile", buts="2", tirs="2", deux="2"),
    ["", "", "", "Officiel Resp. A", "", "", "OFFICIEL Alpha", "", "", "", "", "6138012100999"] + [""] * 15,
    ["# - ruetisiv bulC", "OVARB BULC"] + ENTETE[2:],
    ligne(4, "TESTARD Octave", buts="3", tirs="5", dis="X"),
    ligne(16, "PORTIER Bravo", arrets="2"),
    [""] * 27,
    ["erocs liatéD", "", "Période 1"] + [""] * 24,
    ["", "", "REC", "", "", "", "", "VIS"] + [""] * 19,
    ["", "", "3", "", "", "", "", "2", "", "", "", "6", "", "", "", "", "", "", "3"] + [""] * 8,
]
DEROULE = ("PERIODE 1 31:10 4 - 2 But ESSAI Basile\n"
           "Temps Score Action 33:00 4 - 2 Arrêt PORTIER Bravo\n"
           "00:45 01 - 00 But 7m DUPONT Jean 0123456789012 41:00 4 - 2 Tir DUPONT Jean\n"
           "05:30 01 - 01 But TESTARD Octave 44:00 4 - 2 2MN ESSAI Basile\n"
           "10:00 02 - 01 But DUPONT Jean 50:00 5 - 2 But DUPONT Jean\n"
           "18:44 02 - 01 Commotion TESTARD Octave 55:00 5 - 3 But TESTARD Octave\n"
           "20:00 02 - 01 Temps mort Visiteur 59:59 5 - 3 Arrêt GARDIEN Alpha\n"
           "22:00 02 - 02 But TESTARD Octave 01:00:00 6 - 3 But ESSAI Basile\n"
           "29:00 03 - 02 But DUPONT Jean\n")


def test_feuille_forme_reelle():
    """Tableau unique, cases « X », deux colonnes de déroulé, heure au-delà de 59:59."""
    players = parse_fdme.parse_tables([FEUILLE])
    assert [p["num"] for p in players["home"]] == [1, 7, 9] and [p["num"] for p in players["away"]] == [4, 16]
    jean = players["home"][1]
    assert (jean["goals"], jean["pen_goals"], jean["shots"], jean["yellow"]) == (4, 1, 5, 1)
    assert players["home"][2]["two_min"] == 2 and players["away"][0]["red"] == 1
    assert players["home"][0]["saves"] == 9 and players["away"][1]["saves"] == 2
    assert parse_fdme.sheet_scores([FEUILLE]) == ([6, 3], [3, 2])
    ev = parse_fdme.attribute(parse_fdme.parse_events(DEROULE), players)
    assert len(ev) == 14 and ev[-1]["t"] == 3600 and ev[-1]["score"] == [6, 3]
    goals = [(e["side"], e["num"]) for e in ev if e["type"] in ("goal", "pen_goal")]
    assert goals.count(("home", 7)) == 4 and goals.count(("away", 4)) == 3 and len(goals) == 9
    assert ("away", "timeout", None) in [(e["side"], e["type"], e["num"]) for e in ev]
    assert ("away", 16) in [(e["side"], e["num"]) for e in ev if e["type"] == "save"]
    assert "0123456789012" not in json.dumps(ev) and "COMMOTION" not in json.dumps(ev).upper()


def test_feuille_sans_tableau():
    """Repli sur le déroulé : l'équipe d'un but se déduit du score."""
    ev = parse_fdme.attribute(parse_fdme.parse_events(DEROULE), None)
    stats = parse_fdme.players_from_events(ev)
    assert sum(p["goals"] for p in stats["home"]) == 6 and sum(p["goals"] for p in stats["away"]) == 3


def test_blocs_du_site():
    """Données lues dans le HTML servi, comme sur ffhandball.fr."""
    page = ("<smartfire-component name='toaster'></smartfire-component><smartfire-component "
            "name='competitions---rencontre-list' attributes=\"{&quot;rencontres&quot;:[{&quot;"
            "ext_rencontreId&quot;:&quot;12&quot;,&quot;journeeNumero&quot;:&quot;2&quot;,&quot;date&quot;:"
            "null,&quot;equipe1Libelle&quot;:&quot;CLUB  A&quot;,&quot;equipe2Libelle&quot;:&quot;CLUB B&quot;,"
            "&quot;equipe1Score&quot;:null,&quot;fdmCode&quot;:&quot;ABCDEFG&quot;}]}\"></smartfire-component>")
    rows = collect.blocks(page)["competitions---rencontre-list"]["rencontres"]
    fx = collect.fixture(rows[0], "71", "https://exemple/poule-1/", start="2026-10-10")
    assert fx["home"] == "CLUB A" and fx["score_home"] is None and fx["journee"] == 2
    assert fx["date"] == "2026-10-10" and fx["date_provisoire"]
    assert fx["pdf_url"] == collect.FDM + "A/B/C/D/ABCDEFG.pdf"
    assert collect.iso_date("2026-10-03T21:00:00+02:00") == "2026-10-03T21:00"
    assert collect.pdf_url("") is None and collect.score("") is None and collect.score("32") == 32


def test_bout_en_bout_faux_site(sandbox, monkeypatch):
    """Collecte -> PDF -> JSON -> analyse sur un faux site local, puis second passage léger."""
    pytest.importorskip("reportlab")
    from tests import mock_site
    src = sandbox / "source"
    out = demo_data.generate(data_dir=src, matches_dir=src / "matches")
    truth = {p.stem: json.loads(p.read_text("utf-8")) for p in (src / "matches").glob("*.json")}
    later = next(f["id"] for f in out["fixtures"] if f["poule"] == "71" and f["journee"] == 5)
    site = sandbox / "site"
    rel = mock_site.build(site, list(truth.values()), out["fixtures"], "71", sans_date={later})
    server, base = serve(site, Quiet)
    monkeypatch.setattr(collect, "FDM", base + "fdm/")
    monkeypatch.setattr(collect, "PAUSE", 0)
    now = "2026-10-04T23:00"
    try:
        found = collect.discover(dict(common.load_config(), competition=base + rel))
        assert found["71"] == base + rel + "poule-9071/" and "99" in found
        poule = dict(id="71", url=found["71"])
        fixtures, official = collect.crawl_poule(poule, {}, {}, now)
        played = [f for f in out["fixtures"] if f["poule"] == "71" and f["score_home"] is not None]
        assert len(fixtures) == 30 and official and official["lignes"]
        assert sum(1 for f in fixtures.values() if f["score_home"] is not None) == len(played)
        assert len(list((sandbox / "raw" / "fdme").glob("*.pdf"))) == len(played)
        assert fixtures[later]["date_provisoire"] and fixtures[later]["date"] == \
            min(f["date"][:10] for f in out["fixtures"] if f["poule"] == "71" and f["journee"] == 5)
        common.write_json(sandbox / "data" / "fixtures.json", list(fixtures.values()))
        parse_fdme.main()
        for f in played:
            got = json.loads((sandbox / "data" / "matches" / f"{f['id']}.json").read_text("utf-8"))
            ref = truth[f["id"]]
            assert got["home"]["name"] == ref["home"]["name"] and got["home"]["score"] == ref["home"]["score"]
            assert got["source"]["fdme"] and "alertes" not in got["source"]
            for side in ("home", "away"):
                keys = ("goals", "saves", "yellow", "two_min", "red")
                want = {p["num"]: tuple(p[k] for k in keys) for p in ref["players"][side]}
                have = {p["num"]: tuple(p[k] for k in keys) for p in got["players"][side]}
                assert have == want
            assert (got["home"]["ht"], got["away"]["ht"]) == (ref["home"]["ht"], ref["away"]["ht"])
            assert len([e for e in got["events"] if e["num"] is None and e["type"] != "timeout"]) == 0
            assert "6138012100123" not in json.dumps(got)
        # second passage : journées closes et feuilles déjà lues ne sont pas redemandées
        known = {f["id"]: True for f in played}
        Quiet.seen.clear()
        again, _ = collect.crawl_poule(poule, known, fixtures, now)
        assert len(again) >= 21 and not any("/fdm/" in p for p in Quiet.seen)
        assert not any(f"journee-{d}/" in p for p in Quiet.seen for d in (1, 2, 3))
    finally:
        server.shutdown()
    d = an.analyze("2026-10-04")
    assert d["prochain"] and d["meta"]["feuilles"] == len(played) and d["joueurs"]


def test_course_au_classement(sandbox):
    demo(sandbox)
    s = an.analyze("2026-10-04")["saison"]
    assert s["statut"] == "en_cours" and s["restants"] == len(s["matchs"]) == 7
    assert 0 <= s["proba"] <= s["proba_tout"] <= 100 and abs(sum(s["rangs"]) - 100) < 1
    assert s["pts_max"] == s["pts"] + 3 * s["restants"]
    assert 1 <= sum(m["cle"] for m in s["matchs"]) <= 3
    for m in s["matchs"]:
        assert m["si_victoire"] >= m["sinon"] and m["enjeu"] == m["si_victoire"] - m["sinon"]



def test_pronostics_gardes_puis_compares(sandbox, monkeypatch):
    """Le pronostic de chaque match du club est gardé jusqu'au coup d'envoi, puis confronté à la feuille ;
    les saisons lues apprennent au modèle l'avantage du terrain et le poids des présents."""
    demo(sandbox)
    d = an.analyze("2026-10-04")
    p = d["pronostics"]
    cal = p["modele"]
    assert 1 < cal["dom"] < 1.2 and 0.85 < cal["ext"] < 1 and 0 <= cal["beta"] <= 1 and cal["gamma"] >= 0
    assert p["equipe"]["base"] > 0 and all(q["taux"] >= 0 for q in d["joueurs"])
    assert all(q.get("sr") is not None for q in d["joueurs"] if q["gardien"] and q["m"])
    club = [m for m in d["saison"]["matchs"] if not m.get("coupe")]
    nxt = club[0]
    assert [x["id"] for x in p["matchs"]] == [m["id"] for m in d["saison"]["matchs"]]
    first = p["matchs"][0]
    assert first["fige"] == "2026-10-04T00:00" and first["apres"] is None and p["suivi"]["n"] == 0
    assert (first["pour"], first["ecart"], first["p"]) == (nxt["buts_pour"], nxt["ecart"], nxt["p_victoire"])
    assert first["contre"] == round(nxt["buts_pour"] - nxt["ecart"], 1) and first["nous"]["bp_moy"] is not None
    assert first["surveiller"] in range(6) and first["exploiter"] in range(6)
    # coup d'envoi passé, match pas encore lu : le pronostic d'avant reste, les suivants se mettent à jour
    later = an.analyze("2026-10-11")["pronostics"]["matchs"]
    assert later[0]["fige"] == "2026-10-04T00:00" and later[1]["fige"] == "2026-10-11T00:00"
    # l'entraîneur avait retenu une feuille pour ce match (publiée, chiffrée)
    monkeypatch.setenv("HBPSM_CLE", PHRASE)
    kept = [q["cle"] for q in d["joueurs"] if q["gardien"]][:2] + [q["cle"] for q in d["joueurs"] if not q["gardien"]][:10]
    common.write_json(sandbox / "publie" / "choix.enc", vault.encrypt(
        dict(format="hbpsm-choix", v=1, matchs={nxt["id"]: dict(joueurs=kept, le="2026-10-09")}), PHRASE, iterations=2000))
    # le match est joué, la feuille lue : la réalité en face du pronostic, et ce que les présents expliquent
    demo(sandbox, played_days=4)
    d2 = an.analyze("2026-10-12")
    x = next(x for x in d2["pronostics"]["matchs"] if x["id"] == nxt["id"])
    real = json.loads((sandbox / "data" / "matches" / f"{nxt['id']}.json").read_text("utf-8"))
    side, other = ("home", "away") if real["home"]["name"] == demo_data.CLUB else ("away", "home")
    a = x["apres"]
    assert x["fige"] == "2026-10-04T00:00" and a["feuille"]
    assert (a["bp"], a["bc"], a["ecart"]) == (real[side]["score"], real[other]["score"], real[side]["score"] - real[other]["score"])
    assert a["mt"] == [real[side]["ht"], real[other]["ht"]] and sum(a["periodes"][0]) == a["bp"]
    assert a["deux_min"][0] == sum(q["two_min"] for q in real["players"][side])
    assert 50 < a["presents"]["nous"]["part"] < 150 and 50 < a["presents"]["eux"]["part"] < 150
    assert a["corrige"]["ecart"] == round(a["corrige"]["pour"] - a["corrige"]["contre"], 1)
    assert a["retenue"]["part"] > 0
    s = d2["pronostics"]["suivi"]
    assert s["n"] == 1 and s["erreur"] == abs(round(a["ecart"] - x["ecart"], 1)) and s["n_presents"] == 1
    # une fois la feuille lue, la comparaison ne bouge plus
    assert an.analyze("2026-10-13")["pronostics"]["matchs"][0]["apres"] == a
    # l'état de la collecte les garde
    assert "pronostics.json" in publish.STATE_FILES

def test_trajectoire_et_courbe_du_match():
    """La course : rang du club après chaque journée et marge sur la place visée (d'avance sur le premier
    dehors, de retard sur le dernier dedans) ; l'écart au score, but après but, vu du club."""
    def m(j, h, a, sh, sa):
        return dict(journee=j, date=f"2026-09-{10 + j:02d}", home=dict(name=h, score=sh), away=dict(name=a, score=sa))
    ms = [m(1, "Club A", "Club B", 21, 20), m(1, "Club C", "Club D", 25, 10), m(2, "Club A", "Club C", 30, 20), m(2, "Club B", "Club D", 18, 17)]
    teams = {"Club A", "Club B", "Club C", "Club D"}
    assert an.trajectory(ms, teams, "Club A", 2) == [dict(journee=1, rang=2, sur=4, pts=3, marge=2, dedans=True),
                                                    dict(journee=2, rang=1, sur=4, pts=6, marge=2, dedans=True)]
    assert [(t["rang"], t["marge"], t["dedans"]) for t in an.trajectory(ms, teams, "Club B", 2)] == [(3, -2, False), (3, 0, False)]
    assert an.trajectory(ms, teams, "Club D", 2, gone=frozenset({"CLUB D"})) == []   # forfait général : hors course
    ev = [dict(t=60, side="home", type="goal", score=[1, 0]), dict(t=125, side="away", type="miss"),
          dict(t=300, side="away", type="pen_goal", score=[1, 1]), dict(t=1800, side="away", type="goal", score=[1, 2])]
    assert an.score_curve(dict(events=ev), "away") == [[0, 0], [1.0, -1], [5.0, 0], [30.0, 1]]
    assert an.score_curve(dict(events=ev), "home") == [[0, 0], [1.0, 1], [5.0, 0], [30.0, -1]]
    assert an.score_curve(dict(events=[]), "home") is None


def test_seance_a_importer(sandbox):
    """Le fichier respecte le format d'échange .hbt.json de l'application d'entraînement."""
    demo(sandbox)
    d = an.analyze("2026-10-04")
    brief, fichier = build_exports(d, sandbox / "docs", today="2026-10-05")
    f = json.loads((sandbox / "docs" / "seance-prochaine.hbt.json").read_text("utf-8"))
    assert f == fichier
    assert f["format"] == "handball-training" and f["version"] == 3
    seance = f["contenu"]["seance"]
    assert f["contenu"]["type"] == "seance" and seance["exercices"] == []
    assert seance["date"] == "2026-10-06" and seance["equipe"] == "Seniors garçons"
    for key in ("id", "titre", "categorieAge", "objectifSeance", "effectifJoueurs", "effectifGardiens",
                "espaceDisponible", "retour", "retourEcritLe", "creeLe", "modifieLe"):
        assert key in seance
    assert seance["objectifSeance"] == brief["objectif"] and d["prochain"]["adversaire"] in seance["titre"]
    assert all(a["categorie"] in an.LIB_CAT for a in brief["axes"])
    assert json.loads((sandbox / "docs" / "entrainement.json").read_text("utf-8"))["version"] == 1


def test_effectif_et_feuilles(sandbox):
    """Le nom de l'effectif (Prénom Nom) retrouve celui de la feuille (NOM Prénom)."""
    keys = {common.name_key(n): n for n in ("Firmin Testard", "Anatole Essai", "Gaspard Essai", "Célestin Bidule")}
    assert keys[common.match_name("TESTARD Firmin", keys)] == "Firmin Testard"
    assert keys[common.match_name("ESSAI GASPARD", keys)] == "Gaspard Essai"
    assert keys[common.match_name("BIDULE Celestin Octave", keys)] == "Célestin Bidule"
    assert common.match_name("ESSAI", keys) is None and common.match_name("DUPONT Jean", keys) is None
    demo(sandbox)
    roster = {common.name_key(n): dict(nom=n, poste="", disponible=True)
              for n in ("01 Joueur", "Jamais Aligné")}
    d = an.analyze("2026-10-04", roster=roster)
    assert next(p for p in d["joueurs"] if p["nom"] == "01 Joueur")["m"] == 3
    absent = d["joueurs"][-1]
    assert absent["nom"] == "Jamais Aligné" and absent["m"] == 0 and absent["m_total"] == 3


PHRASE = "cinq mots tires au hasard"


def test_publication_chiffree(sandbox, monkeypatch):
    """Rien de nominatif en clair dans publie/, et l'état se reprend d'un lancement à l'autre."""
    monkeypatch.setattr(vault, "ITERATIONS", 2000)
    monkeypatch.setattr(vault.encrypt, "__defaults__", (2000,))
    monkeypatch.delenv("HBPSM_CLE", raising=False)
    with pytest.raises(vault.VaultError):
        publish.seal("2026-10-04")
    monkeypatch.setenv("HBPSM_CLE", "court")
    with pytest.raises(vault.VaultError):
        publish.seal("2026-10-04")
    monkeypatch.setenv("HBPSM_CLE", PHRASE)
    demo(sandbox)
    publish.seal("2026-10-04")
    out = sandbox / "publie"
    assert sorted(p.name for p in out.iterdir()) == ["HBPSM-tableau-de-bord.html", "etat.enc", "hbpsm.enc", "manifeste.json",
                                                    "matchs.ics", publish.SEANCE_NAME, publish.PUBLIC_NAME]
    for p in out.iterdir():
        text = p.read_text("utf-8")
        assert "Joueur 0" not in text and "Fictif" not in text, p.name  # aucun nom de joueur en clair
        if p.name not in (publish.SEANCE_NAME, publish.PUBLIC_NAME, "matchs.ics"):  # seuls les fichiers publics nomment les équipes
            assert "quipe fictive" not in text, p.name
    board = json.loads((out / publish.PUBLIC_NAME).read_text("utf-8"))
    assert board["format"] == "hbpsm-public" and board["prochain"] and board["poules"]["71"]
    assert all(set(b) <= {"num", "buts", "pen", "m", "moy", "tirs", "reussite"} for b in board["adversaire"]["buteurs"])
    seance = json.loads((out / publish.SEANCE_NAME).read_text("utf-8"))
    assert seance["format"] == "handball-training" and seance["contenu"]["seance"]["exercices"] == []
    box = vault.decrypt(json.loads((out / "hbpsm.enc").read_text("utf-8")), PHRASE)
    assert box["data"]["meta"]["matchs"] == 18 and box["seance_hbt"]["format"] == "handball-training"
    with pytest.raises(vault.VaultError):
        vault.decrypt(json.loads((out / "hbpsm.enc").read_text("utf-8")), "une autre phrase secrete")
    # inchangé : pas de nouvelle version
    before = (out / "hbpsm.enc").read_text("utf-8")
    publish.seal("2026-10-04")
    assert (out / "hbpsm.enc").read_text("utf-8") == before
    # reprise de l'état sur une machine vierge
    import shutil
    shutil.rmtree(sandbox / "data")
    publish.restore()
    assert len(list((sandbox / "data" / "matches").glob("*.json"))) == 18
    assert an.analyze("2026-10-04")["meta"]["matchs"] == 18


def test_effectif_depuis_secret(sandbox, monkeypatch):
    monkeypatch.setenv("HBPSM_EFFECTIF", "nom,poste,disponible\nIsidore Exemple\n\nJean Modele;GB\n")
    publish.roster()
    assert (sandbox / "roster.csv").read_text("utf-8") == "nom,poste,disponible,role,age,naissance,jusqu_au,avis\nIsidore Exemple\nJean Modele,GB\n"


def test_page_publiee_dechiffre(sandbox, monkeypatch):
    """La page sans donnée, ouverte en fichier local, lit le coffre, voit passer les nouvelles
    données sans être rouverte, et garde la dernière copie hors connexion."""
    pw = pytest.importorskip("playwright.sync_api")
    monkeypatch.setattr(vault.encrypt, "__defaults__", (2000,))
    monkeypatch.setenv("HBPSM_CLE", PHRASE)
    demo(sandbox)
    publish.seal("2026-10-04")
    out = sandbox / "publie"

    class Handler(http.server.SimpleHTTPRequestHandler):
        def end_headers(self):  # comme raw.githubusercontent.com
            self.send_header("Access-Control-Allow-Origin", "*")
            super().end_headers()

        def log_message(self, *a, **k):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory=str(out)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}/"
    page_file = sandbox / "tableau.html"
    html = render(None, dict(src=base + "hbpsm.enc", manifeste=base + "manifeste.json", versions="",
                             choix=base + "choix.enc", caisse=base + "caisse.enc", depot="exemple/depot", branche="main", iterations=2000,
                             club="HBPSM", verif=1))
    assert "Joueur 0" not in html
    page_file.write_text(html, "utf-8")
    with pw.sync_playwright() as p:
        browser = chrome(p)
        ctx = browser.new_context()
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(page_file.as_uri() + "#entraineur")  # comme depuis HANDBALL-training : l'entraîneur modifie
        page.wait_for_selector("#phrase")
        page.fill("#phrase", "mauvaise phrase secrete")
        page.click("#unlock")
        page.wait_for_selector(".err")
        assert "incorrecte" in page.inner_text(".err")
        page.fill("#phrase", PHRASE)
        page.click("#unlock")
        page.wait_for_selector("header.top h1")
        # la page s'ouvre sur la planification
        assert page.get_attribute("nav.tabs button[data-tab=planif]", "aria-selected") == "true"
        assert "Planification" in page.inner_text("h1") and "Joueur 0" in page.inner_text("main")
        # Semaine : le bilan du dernier match joué en tête ; « Ma semaine » : ce qui concerne un joueur
        page.click("nav.tabs button[data-tab=semaine]")
        assert page.locator(".bilan").count() == 1
        page.evaluate("document.querySelector('.bilan').open = true")   # ouvert 4 jours après le match : le test ne dépend pas du jour
        assert "Buteurs" in page.inner_text(".bilan")
        # pronostics : celui du prochain match dans la Projection ; après le match, la comparaison (bilan de la
        # Semaine, Adversaires, Saison) ; l'écart attendu de chaque feuille d'après les présents (appris)
        assert page.evaluate("D.pronostics.modele.beta") > 0 and page.evaluate("PLAN.every(r => r.goalsAdj != null)")
        page.evaluate("""(() => { const x = D.derniers.slice(-1)[0];
          D.pronostics.matchs.unshift(Object.assign({}, D.pronostics.matchs[0], {id: x.id, adversaire: x.adversaire, domicile: x.domicile,
            date: x.date, journee: x.journee, coupe: null, fige: "2026-10-02T07:00", surveiller: 4, exploiter: 0,
            apres: {v: 1, bp: x.bp, bc: x.bc, ecart: x.bp - x.bc, res: x.res, feuille: true, mt: [12, 10],
              periodes: [[1, 2, 3, 4, 5, 6], [6, 5, 4, 3, 2, 1]], deux_min: [2, 3], jaunes: [1, 2], rouges: [0, 0], arrets: [35, 28],
              presents: {nous: {part: 92, gardien: 2.4, joueurs: 12, absents: [{cle: D.joueurs[0].cle, taux: 5.1}]},
                         eux: {part: 104, gardien: -1.2, joueurs: 13, absents: [{nom: "Buteur Invente", taux: 4.2}]}},
              retenue: {part: 95, gardien: 0, pour: 27, contre: 25, ecart: 2}, corrige: {pour: 26.5, contre: 24.8, ecart: 1.7}}}));
          D.pronostics.suivi = {n: 1, vainqueur: 1, sur: 1, erreur: 2.3, biais: 2.3, n_presents: 1, erreur_avant: 2.3, erreur_presents: 1.1};
          render(true); document.querySelector('.bilan').open = true; document.querySelector('.prono-bilan').open = true; })()""")
        assert "Pronostic et réalité" in page.inner_text(".bilan") and "manquaient" in page.inner_text(".prono-bilan")
        page.click("nav.tabs button[data-tab=saison]")
        assert "Nos pronostics et la réalité" in page.inner_text("main") and "vainqueur trouvé 1 fois sur 1" in page.inner_text("main")
        page.click("nav.tabs button[data-tab=adv]")
        adv = page.evaluate("D.derniers.slice(-1)[0].adversaire")
        page.select_option("#adv", adv)
        assert "Lecture" in page.inner_text("main") and "Buteur Invente" in page.inner_text("main")
        page.select_option("#adv", page.evaluate("D.saison.matchs[0].adversaire"))
        assert "Gardé tel quel" in page.inner_text("main")
        page.click("nav.tabs button[data-tab=semaine]")
        page.click("nav.tabs button[data-tab=moi]")
        assert "Choisissez qui vous êtes" in page.inner_text("main")
        page.evaluate("localStorage.setItem('hbpsm:moi', D.joueurs.find(p => p.m).cle); render(true)")
        assert page.locator(".moi-statut").count() == 1 + page.evaluate("PLAN.length") and "Ma caisse noire" in page.inner_text("main")
        page.evaluate("localStorage.removeItem('hbpsm:moi')")
        # santé : un bandeau quand quelque chose cloche ; les jetons, pour l'entraîneur et les trésoriers seulement
        page.evaluate("""SANTE = {etat: "alerte", alertes: [{niveau: "alerte", code: "poule-71", message: "Poule 71 : aucune rencontre lue."},
          {niveau: "info", code: "jeton-des propositions", message: "Jeton des propositions : expire dans 10 jours."}]}; render(true)""")
        assert "aucune rencontre lue" in page.inner_text(".sante") and "Jeton" in page.inner_text(".sante")
        page.evaluate("SANTE = null; render(true)")
        page.click("nav.tabs button[data-tab=planif]")
        # la page a évolué : un fichier gardé sur l'ordinateur se télécharge de nouveau (en ligne, elle se
        # recharge d'elle-même dès que GitHub sert la nouvelle)
        page.evaluate("NEWER = true; render(true)")
        assert "Une version plus récente de ce fichier existe" in page.inner_text("#app")
        page.evaluate("NEWER = false; render(true)")
        # les deux derniers matchs joués, avant les quatre à venir : qui était sur la feuille
        assert page.evaluate("D.derniers.length") == 3 and page.locator(".plan .h.past").count() == 2
        on = page.evaluate("D.derniers.slice(-2).reduce((a, x) => a + D.joueurs.filter(p => x.joueurs[p.cle]).length, 0)")
        assert on > 0 and page.locator(".plan .pc.on").count() == on
        # jamais deux fois de suite la même équipe : au moins 2 changements, depuis le dernier match joué
        changes = page.evaluate("""(() => { const last = D.derniers.slice(-1)[0];
          let prev = D.joueurs.filter(p => last.joueurs[p.cle]);
          return planning().map(r => { const c = r.sel.filter(p => !prev.includes(p)).length; prev = r.sel; return c; }); })()""")
        assert len(changes) == 4 and min(changes) >= 2, changes
        # un gardien : pas plus de 3 matchs de suite, matchs joués de la saison compris ; avec deux gardiens
        # seulement, impossible : signalé ; un troisième (un joueur de champ passé gardien) suffit
        assert page.evaluate("D.joueurs.filter(isGK).length") == 2 and page.evaluate("planning().some(r => r.gbSuite)")
        third = page.evaluate("(() => { const p = D.joueurs.filter(q => !isGK(q) && dispo(q) && !depOf(q)).slice(-1)[0]; S.postes[p.cle] = 'GB';"
                              " D.derniers.forEach(x => { x.vraie = x.saison; x.saison = '2000-2001'; }); return p.cle; })()")   # sans les matchs joués
        runs = page.evaluate("""(() => { const P = planning(), seq = [...D.derniers.filter(x => !x.saison || x.saison === D.meta.saison)
            .map(x => p => !!x.joueurs[p.cle]), ...P.map(r => p => r.sel.includes(p))];
          return D.joueurs.filter(isGK).map(g => { let run = 0, top = 0; for(const has of seq){ run = has(g) ? run + 1 : 0; top = Math.max(top, run); } return top; }); })()""")
        # début de saison : les jeunes gardiens jouent autant l'un que l'autre, à un match près
        share = page.evaluate("""(() => { const gks = D.joueurs.filter(isGK), keep = gks.map(g => g.age);
          gks.forEach(g => g.age = "jeune");
          const P = planning(), tot = g => (g.journal || []).length + P.filter(r => r.gks.includes(g)).length;
          const t = gks.map(tot); gks.forEach((g, i) => g.age = keep[i]); return {t, ecart: Math.max(...t) - Math.min(...t)}; })()""")
        assert share["ecart"] <= 1, share
        page.evaluate(f"delete S.postes[{json.dumps(third)}]; D.derniers.forEach(x => {{ x.saison = x.vraie; delete x.vraie; }})")
        assert len(runs) == 3 and max(runs) <= 3, runs
        # classe d'âge (paramètre, jamais affichée) : quand il faut changer, un titulaire plus âgé sort d'abord
        older_out = page.evaluate("""(() => { const keep = D.joueurs.map(p => p.age); S.regle = 0;
          const P0 = planning(), x = P0[0].sel.find(p => !isGK(p) && pinOf(p, P0[0].m) !== "in");
          D.joueurs.forEach(p => p.age = "jeune"); x.age = "experimente";
          const ok = planning().some(r => r.forced.includes(x) && r.resting.includes(x));
          D.joueurs.forEach((p, i) => p.age = keep[i]); S.regle = 1; return ok; })()""")
        assert older_out and "experimente" not in page.inner_text("main") and "+40" not in page.inner_text("main")
        # disponible jusqu'à une date : plus proposé après, et à besoin égal il passe après tous les autres
        leave = page.evaluate("""(() => { const g = D.joueurs.filter(isGK), x = g[g.length - 1], P0 = planning();
          x.jusqu_au = P0[1].m.date.slice(0, 10); render(true);
          const P = planning(), cells = [...document.querySelectorAll('.plan button.cell[data-cell$="|' + x.cle + '"]')].map(c => c.title);
          const out = {after: P.slice(2).some(r => r.sel.includes(x)), need: P.need(x), cells,
                       last: D.joueurs.every(p => p === x || ageRank(p) < ageRank(x))};
          delete x.jusqu_au; render(true); return out; })()""")
        assert not leave["after"] and leave["need"] == 1 and leave["last"], leave
        assert sum("disponible jusqu'au" in c for c in leave["cells"]) == 2, leave["cells"]
        # deux joueurs de même nom et même initiale : le nom court allonge le prénom
        short = page.evaluate("""(() => { D.joueurs.push({nom: "Isabeau Exemple"}, {nom: "Isidore Exemple"});
          const out = [playerShort("Isabeau Exemple"), playerShort("Isidore Exemple"), playerShort("Zéphyrin Modele")];
          D.joueurs.splice(-2, 2); return out; })()""")
        assert short == ["Isa. Exemple", "Isi. Exemple", "Z. Modele"], short
        assert "proposé" in page.inner_text(".plan") and "retenu" not in page.inner_text(".plan .h")
        # le risque s'explique : son coût dans l'étiquette, le calcul au toucher
        page.locator(".plan .h.foot button.risk").first.click()
        assert page.inner_text("#why").startswith("Risque ")
        page.locator("#why button").first.click()
        page.click("nav.tabs button[data-tab=semaine]")
        assert page.inner_text(".matchcard h1").split("\n")[1:] == ["VS", "HBPSM"]   # HBPSM à l'extérieur
        # tous les matchs dans son agenda : Google (abonnement) et webcal (iPhone, Outlook)
        page.evaluate("CFG.ics = 'https://exemple.test/publie/matchs.ics'; render(true)")
        assert page.locator(".matchcard a[href='webcal://exemple.test/publie/matchs.ics']").count() == 1
        assert "cid=webcal%3A%2F%2Fexemple.test" in page.get_attribute(".matchcard a[href*='calendar.google.com/calendar/r?cid=']", "href")
        page.evaluate("CFG.ics = ''; render(true)")
        assert page.locator(".matchcard summary:has-text('Tous les matchs')").count() == 0
        # en buts : l'écart attendu de la feuille, les buts évités d'un gardien, le coût des exclusions
        assert page.evaluate("butsTxt(-2.46, 1)") == "−2,5" and page.evaluate("butsTxt(3)") == "+3"
        assert page.evaluate("planning()[0].goalsAdj !== undefined")
        line = page.evaluate("""(() => { const g = D.joueurs.find(isGK); const keep = g.evites_cumul;
          g.evites_cumul = {tirs: 140, valeur: 15, par_match: 2.1, marge: 1.4, moyenne: 31,
            detail: [{saison: "2026-2027", poids: 1, tirs: 18, valeur: 4}, {saison: "2025-2026", poids: 0.43, tirs: 280, valeur: 29}]};
          const t = evitesLine(g); g.evites_cumul = keep; return t; })()""")
        assert "Buts évités" in line and "+2,1 ± 1,4 buts par match" in line and "31 %" in line and "compté à 43 %" in line
        note = page.evaluate("(() => { const k = D.meta.exclusion; D.meta.exclusion = {cout: -0.44, n: 376}; const t = exclNote(); D.meta.exclusion = k; return t; })()")
        assert "environ 0,4 but" in note and "376" in note
        # mode causerie : cinq écrans, au clavier, fermé par Échap
        page.click("button[data-talk]")
        title = "document.querySelector('#talk h2').textContent"
        assert page.locator("#talk .tk-dots button").count() == 5 and page.evaluate(title) == "Le match"
        page.keyboard.press("ArrowRight")
        assert page.evaluate(title) == "L'adversaire"
        page.click("#talk .tk-dots button >> nth=4")
        assert page.evaluate(title) == "Notre équipe" and page.locator("#talk .court, #talk .tk-sub").count() >= 1
        page.keyboard.press("Escape")
        assert page.locator("#talk").count() == 0
        # l'image du bilan, fabriquée dans la page ; l'installation, seulement en ligne (https)
        image = page.evaluate("(async () => { const b = await bilanImage(); return b ? [b.type, b.size] : null; })()")
        assert image is None or (image[0] == "image/png" and image[1] > 20000), image
        assert page.evaluate("installCard()") == ""
        # feuille de 12 joueurs dont 2 gardiens pour chacun des 4 prochains matchs
        sheet = "(k => { const r = planning()[k]; return [r.sel.length, r.gks.length, r.missing, r.missingGK]; })"
        assert [page.evaluate(sheet + "(%d)" % k) for k in range(4)] == [[12, 2, 0, 0]] * 4
        page.evaluate("(() => { const g = planning()[0].gks[0]; S.absents[g.cle] = true; })()")
        assert page.evaluate(sheet + "(0)") == [12, 1, 0, 1]  # un seul gardien disponible : signalé
        page.evaluate("S.absents = {}")
        # rotation : jamais sur un match clé, d'abord sur les matchs les plus abordables ; chaque entrant
        # prend la place d'un joueur au repos, et chacun joue au moins 1 des 4 matchs (les échanges de la
        # règle des 2 changements d'un match au suivant, forced, se comptent à part)
        rot = page.evaluate("""(() => { S.regle = 1; const P = planning(), rq = r => r.rotated.filter(p => !r.forced.includes(p));
          const easy = P.filter(r => !r.m.cle).sort((a, b) => (b.m.p_victoire ?? 50) - (a.m.p_victoire ?? 50));
          return {cle: P.filter(r => r.m.cle).map(r => rq(r).length), ordre: easy.map(r => rq(r).length),
                  paires: P.every(r => r.rotated.length === r.resting.length && r.sel.length === 12),
                  manque: D.joueurs.filter(p => P.apps(p) < P.need(p)).length,
                  libre: (S.regle = 0, planning().every(r => !rq(r).length)),
                  gb2: (S.regle = 2, planning().every(r => { const g = rq(r).filter(isGK).length;
                    return g <= 1 || (g === 2 && !r.m.cle && r.m.p_victoire >= ROT_GB2); }))}; })()""")
        page.evaluate("S.regle = 1")
        assert all(n == 0 for n in rot["cle"]) and rot["paires"] and rot["libre"] and rot["gb2"]
        assert sum(rot["ordre"]) > 0 and rot["ordre"] == sorted(rot["ordre"], reverse=True) and rot["manque"] == 0
        # postes clefs : 2 pivots et 4 arrières sur chaque feuille, rotation comprise ; un 2e poste compte
        cov = page.evaluate("""(() => { const champ = D.joueurs.filter(p => !isGK(p)), cycle = ["PIV","ARG","DC","ALG","ALD","ARD"];
          champ.forEach((p, i) => S.postes[p.cle] = cycle[i % cycle.length]);
          const res = [0, 1, 2].map(q => { S.regle = q; return planning().every(r => r.postesOk); });
          champ.filter(p => poste(p) === "PIV").forEach(p => S.postes[p.cle] = "ALG");
          const sans = planning()[0].postesOk;
          S.postes[champ[0].cle] = "ALG/PIV"; S.postes[champ[1].cle] = "ALD/PIV";
          const deux = planning().every(r => r.postesOk && r.sel.length === 12);
          S.postes = {}; S.regle = 1; return {res, sans, deux}; })()""")
        assert cov == {"res": [True, True, True], "sans": False, "deux": True}
        # poste pour poste : un second poste partagé (ARD) ne suffit pas, l'entrant tient le poste principal
        # du sortant ; tous les droitiers en 2e poste ARD, comme dans l'effectif
        swaps = page.evaluate("""(() => { const champ = D.joueurs.filter(p => !isGK(p)), cycle = ["PIV","ARG","DC","ALG","ALD","ARD"];
          champ.forEach((p, i) => { const c = cycle[i % cycle.length]; S.postes[p.cle] = c === "ALD" || c === "ARD" ? c : c + "/ARD"; });
          const out = planning().flatMap(r => r.rotated.filter(p => !isGK(p)).map(p => compat(p, r.why[p.cle])));
          S.postes = {}; return {n: out.length, mini: Math.min(...out), loin: compat({poste: "PIV/ARD", cle: "a"}, {poste: "DC/ARD", cle: "b"})}; })()""")
        assert swaps["n"] > 0 and swaps["mini"] >= 2 and swaps["loin"] == 1, swaps
        # en dépannage : jamais retenu tant qu'il y a assez de joueurs, retenu quand il en manque
        dep = page.evaluate("""(() => { const champ = D.joueurs.filter(p => !isGK(p)), cycle = ["PIV","ARG","DC","ALG","ALD","ARD"];
          champ.forEach((p, i) => S.postes[p.cle] = cycle[i % cycle.length]);
          const d = champ[3]; S.depannage = {[d.cle]: true};
          const jamais = [0, 1, 2].every(q => { S.regle = q; const P = planning(); return P.every(r => !r.sel.includes(d)) && P.need(d) === 0; });
          S.regle = 1; const m0 = planning()[0].m.id; S.dm[m0] = {};
          champ.filter(p => p !== d).slice(-3).forEach(p => S.dm[m0][p.cle] = "a");
          const besoin = planning()[0].sel.includes(d);
          S.postes = {}; S.depannage = {}; S.dm = {}; return {jamais, besoin}; })()""")
        assert dep == {"jamais": True, "besoin": True}
        # le terrain de la semaine montre les 12 : le sept de départ, les autres sous leur poste
        court = page.evaluate("""(() => { const champ = D.joueurs.filter(p => !isGK(p)), cycle = ["PIV","ARG","DC","ALG","ALD","ARD"];
          champ.forEach((p, i) => S.postes[p.cle] = cycle[i % cycle.length]);
          const r = planning()[0], st = startSeven(r), b = benchOf(r, st), box = document.createElement("div");
          box.innerHTML = courtSVG(st, b);
          const lus = [...box.querySelectorAll(".tok:not(.vide) .nm")].map(t => t.textContent).join(" / ").split("/").map(x => x.trim()).filter(Boolean);
          const prenoms = lus.every(x => r.sel.some(p => firstName(p) === x));
          const gb2 = (b.GB || []).length, keep = D.joueurs;
          D.joueurs = [{nom: "Zéphyrin Alpha"}, {nom: "Zéphyrin Beta"}, {nom: "Onésime Gamma"}];
          const homonymes = D.joueurs.map(firstName); D.joueurs = keep;
          S.postes = {}; return {feuille: r.sel.length, noms: lus.length, prenoms, gb2, homonymes}; })()""")
        assert court == {"feuille": 12, "noms": 12, "prenoms": True, "gb2": 1, "homonymes": ["Zéphyrin A.", "Zéphyrin B.", "Onésime"]}
        # le gymnase s'ouvre dans Maps ; le match s'ajoute à l'agenda, heure de Paris (rien si l'horaire n'est pas fixé)
        cal = page.evaluate("""(() => { const salle = {nom: "GYMNASE DU PARC", rue: "1 RUE DU STADE", code_postal: "38000", ville: "VILLE"};
          const m = {id: "m9", date: "2026-10-10T23:30", domicile: false, adversaire: D.saison.matchs[0].adversaire, journee: 4, salle};
          const e = matchEvent(m), ics = icsText(e);
          return {debut: e.debut, fin: e.fin, lieu: e.lieu, titre: e.titre.endsWith("HBPSM"),
                  provisoire: matchEvent(Object.assign({}, m, {provisoire: true})), sans_heure: matchEvent(Object.assign({}, m, {date: "2026-10-10"})),
                  ics: ics.includes("DTSTART;TZID=Europe/Paris:20261010T233000\\r\\n") && ics.includes("LOCATION:GYMNASE DU PARC\\\\, 1 RUE DU STADE\\\\, 38000 VILLE")
                       && ics.split("\\r\\n").every(l => l.length <= 75),
                  maps: mapsUrl(salle), google: googleAgenda(e).includes("dates=20261010T233000/20261011T010000&ctz=Europe/Paris")}; })()""")
        assert cal == {"debut": "20261010T233000", "fin": "20261011T010000", "lieu": "GYMNASE DU PARC, 1 RUE DU STADE, 38000 VILLE",
                       "titre": True, "provisoire": None, "sans_heure": None, "ics": True, "google": True,
                       "maps": "https://www.google.com/maps/search/?api=1&query=GYMNASE%20DU%20PARC%2C%201%20RUE%20DU%20STADE%2C%2038000%20VILLE"}
        # téléphone : aucun onglet ne déborde ; « explique » montre la raison d'une case sans la changer
        page.set_viewport_size({"width": 360, "height": 780})
        # téléphone : un mode clair au choix (par défaut, la page suit le téléphone) ; rien sur PC
        page.wait_for_timeout(200)
        assert page.locator("#theme-btn").is_visible() and page.evaluate("document.documentElement.dataset.theme") is None
        page.click("#theme-btn")
        assert page.evaluate("document.documentElement.dataset.theme") == "light"
        page.click("#theme-btn")
        assert page.evaluate("document.documentElement.dataset.theme") is None
        for tab in ("semaine", "planif", "convoc", "presences", "joueurs", "adv", "saison"):
            page.evaluate("t => { S.tab = t; render(false); }", tab)
            assert page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth") <= 0, tab
            # rien ne déborde de sa case (les colonnes de la planification sont étroites)
            assert page.evaluate("""() => [...document.querySelectorAll('.plan > div:not(.who), td')].every(c => {
              const b = c.getBoundingClientRect();
              return [...c.querySelectorAll('*')].every(e => { const r = e.getBoundingClientRect();
                return !r.width || getComputedStyle(e).display === 'none' || (r.left >= b.left - 1 && r.right <= b.right + 1); }); })""") is True, tab
        page.evaluate("S.tab = 'planif'; render(false)")
        page.click("button[data-tap=why]")
        before = page.evaluate("JSON.stringify(S.pin)")
        page.locator("button.cell.in").first.click()
        assert page.locator("#why").is_visible() and page.evaluate("JSON.stringify(S.pin)") == before
        page.click("button[data-tap=edit]")
        # téléphone : un match à la fois, choisi par les pastilles du haut ; le menu d'onglets reste en bas
        n = page.evaluate("planning().length")
        assert page.locator(".plan.single .h.foot").count() == 1 and page.locator("button.pm").count() == n
        page.locator("button.pm").nth(1).click()
        assert page.evaluate("S.pm") == 1 and "on" in page.get_attribute("button.pm >> nth=1", "class")
        assert page.evaluate("getComputedStyle(document.querySelector('nav.tabs')).position") == "fixed"
        # quatre onglets selon le mode (ici l'entraîneur), les autres sous « Plus »
        assert page.locator("nav.tabs button[data-tab=adv]").is_hidden() and page.locator("nav.tabs [data-plus]").is_visible()
        page.click("nav.tabs [data-plus]")
        assert sorted(page.evaluate("[...document.querySelectorAll('#plus-menu button[data-tab]')].map(b => b.dataset.tab)")) == ["adv", "caisse", "joueurs", "moi", "saison"]
        page.click("#plus-menu button[data-tab=adv]")
        assert page.evaluate("S.tab") == "adv" and page.locator("#plus-menu").is_hidden() and "on" in page.get_attribute("nav.tabs [data-plus]", "class")
        page.click("nav.tabs button[data-tab=planif]")
        page.set_viewport_size({"width": 1100, "height": 900})
        page.wait_for_function("document.querySelectorAll('.plan .h.foot').length > 1", timeout=3000)
        assert not page.locator("#theme-btn").is_visible()
        assert page.locator(".plan .h.foot").count() == n and page.locator("button.pm").count() == 0
        page.evaluate("S.pm = 0; save()")
        # un match de coupe dans la planification : nommé comme tel, la rotation y passe d'abord
        cup = page.evaluate("""(() => { const m = D.saison.matchs[1];
          D.saison.matchs.splice(1, 0, Object.assign({}, m, {id: "coupe-1", coupe: "Coupe de France", tour: "1ER TOUR",
            journee: null, p_victoire: null, enjeu: null, cle: false, effectif: 14}));
          S.regle = 1; const P = planning(), r = P.find(x => x.m.coupe);
          const res = {label: roundOf(r.m), advice: !r.postesOk || advice(r).startsWith("Match de coupe"),   // un poste manquant passe avant
                       most: P.every(x => x.rotated.length + x.extra.length <= r.rotated.length + r.extra.length) && r.extra.length > 0,
                       taille: [r.size, r.sel.length, r.gks.length, squadTitle(r).includes("14"), P.filter(x => !x.m.coupe).every(x => x.size === 12)]};
          // un gardien qui ne reste pas toute la saison : en coupe d'abord, en championnat après tous les autres
          const t = D.joueurs.filter(q => !isGK(q) && dispo(q) && !depOf(q)).slice(-1)[0]; S.postes[t.cle] = "GB";   // un 3e gardien
          const g = D.joueurs.filter(isGK).sort((a, b) => val(a, r.m) - val(b, r.m))[0];
          const league = Q => Q.filter(x => !x.m.coupe && x.gks.includes(g)).length, base = league(planning());
          g.jusqu_au = "2099-12-31"; const Q = planning();
          res.coupe = Q.find(x => x.m.coupe).gks.includes(g); res.moins = league(Q) <= base;
          delete g.jusqu_au; delete S.postes[t.cle]; D.saison.matchs.splice(1, 1); return res; })()""")
        assert cup == {"label": "Coupe de France · 1er tour", "advice": True, "most": True, "coupe": True, "moins": True,
                       "taille": [14, 14, 2, True, True]}
        # adversaires : le club figure aussi dans la liste, en tête
        assert page.evaluate("opponent().names[0] === D.meta.club")
        # planification : un clic écarte un retenu, la feuille se complète avec un autre
        page.click("nav.tabs button[data-tab=planif]")
        first = page.locator("button.cell.in").first
        cle = first.get_attribute("data-cell").split("|")[1]
        first.click()
        assert page.evaluate("planning()[0].sel.some(p => p.cle === %r)" % cle) is False
        assert page.evaluate(sheet + "(0)")[0] == 12 and page.locator("button.cell.man").count() == 1
        page.click("button[data-reset=all]")
        assert page.locator("button.cell.man").count() == 0
        # convocation : le message porte les 12 de la planification
        page.click("nav.tabs button[data-tab=convoc]")
        message = page.input_value("#message")
        assert "Gardiens : " in message and "Joueurs : " in message
        assert message.count("(") >= 12
        page.click("nav.tabs button[data-tab=joueurs]")
        main = page.inner_text("main")
        assert "× 2 min" in main and "Réussite au tir" in main and "Arrêts sur tirs cadrés" in main
        page.click("nav.tabs button[data-tab=saison]")
        # matchs à gagner : une barre par match de championnat ; parcours de l'équipe : un point par saison,
        # la saison en cours complétée d'après le classement
        saison = page.evaluate("""(() => ({barres: document.querySelectorAll('.stakes .sk').length,
          ligue: D.saison.matchs.filter(m => !m.coupe).length, points: document.querySelectorAll('.parcours-chart circle').length,
          parcours: D.parcours.length, encours: !!document.querySelector('.parcours-chart circle.now'),
          place: parcoursList().find(e => e.en_cours).phases[0].place, statut: D.saison.statut}))()""")
        assert saison["points"] == saison["parcours"] > 0 and saison["encours"] and saison["place"], saison
        assert saison["statut"] == "en_cours" and saison["barres"] == saison["ligue"] > 0, saison
        # la course (rang après chaque journée), notre équipe, des raccourcis ; nos matchs d'abord dans la poule
        course = page.evaluate("""(() => ({points: document.querySelectorAll('.line-chart.traj circle').length, journees: D.trajectoire.length,
          equipe: !!document.getElementById('j-equipe'), raccourcis: document.querySelectorAll('nav.jump button').length,
          nos: document.getElementById('j-resultats').nextElementSibling.nextElementSibling.querySelectorAll('.res').length}))()""")
        assert course["points"] == course["journees"] > 0 and course["equipe"] and course["raccourcis"] >= 5, course
        page.click("[data-toute]")
        toute = page.evaluate("document.getElementById('j-resultats').nextElementSibling.nextElementSibling.querySelectorAll('.res').length")
        assert toute == page.evaluate("D.resultats.filter(r => r.poule === String(D.saison.poule)).length") > course["nos"]
        page.click("[data-toute]")
        page.click("nav.tabs button[data-tab=joueurs]")
        page.select_option("#jtri", "buts")
        buts = page.evaluate("[...document.querySelectorAll('#j-champ + .pcs details')].map(d => D.joueurs.find(p => p.cle === d.dataset.cle).buts)")
        assert len(buts) > 3 and buts == sorted(buts, reverse=True) and "buts" in page.inner_text("#j-champ + .pcs .pc-key")
        page.select_option("#jtri", "note")
        page.click("nav.tabs button[data-tab=adv]")
        # une projection, pas un face-à-face : chacun sur ses propres matchs
        main = page.inner_text("main")
        assert "Projection : nos chiffres face aux leurs" in main and "Pas un résultat entre nos deux équipes" in main
        assert page.locator(".vs td.mieux").count() > 0
        page.click("nav.tabs button[data-tab=saison]")
        page.wait_for_function("() => document.getElementById('club-etat').textContent.startsWith('à jour')")
        assert page.evaluate("D.meta.matchs") == 18
        demo(sandbox, played_days=4)  # une nouvelle collecte est publiée pendant que la page est ouverte
        publish.seal("2026-10-04")
        page.wait_for_function("() => D && D.meta.matchs === 24", timeout=20000)
        assert page.get_attribute("nav.tabs button[data-tab=saison]", "aria-selected") == "true"
        # l'entraîneur valide la feuille du 1er match : elle part chiffrée au workflow « Choix de l'entraîneur »
        sent = []

        def github(route):
            cors = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "*", "Access-Control-Allow-Methods": "POST"}
            if route.request.method == "OPTIONS":
                return route.fulfill(status=204, headers=cors)
            sent.append(dict(url=route.request.url, auth=route.request.headers.get("authorization"),
                             body=json.loads(route.request.post_data)))
            route.fulfill(status=204, headers=cors)

        ctx.route("https://api.github.com/**", github)
        page.click("nav.tabs button[data-tab=planif]")
        assert page.evaluate("planning()[0].etat") == "suggestion"
        page.locator("[data-valider]").first.click()   # sans jeton : il est demandé
        page.wait_for_selector("#jeton")
        assert sent == [] and page.evaluate("planning()[0].etat") == "attente"
        page.fill("#jeton", "jeton-de-test")
        page.click("button[data-jeton]")
        page.wait_for_function("() => PUB === 'envoyee'", timeout=20000)
        assert len(sent) == 1 and sent[0]["auth"] == "Bearer jeton-de-test"
        assert sent[0]["url"].endswith("/repos/exemple/depot/actions/workflows/choix.yml/dispatches")
        envelope = json.loads(sent[0]["body"]["inputs"]["choix"])
        assert "Joueur" not in sent[0]["body"]["inputs"]["choix"]  # chiffré : aucun nom en clair
        monkeypatch.setattr(vault, "ITERATIONS", 2000)
        chosen = choix.check(envelope, PHRASE)   # ce que vérifiera le workflow
        first = page.evaluate("String(planning()[0].m.id)")
        assert sorted(chosen["matchs"][first]["joueurs"]) == sorted(page.evaluate("planning()[0].sel.map(p => p.cle)"))
        # le workflow l'écrit dans publie/choix.enc : la page la retrouve, publiée
        monkeypatch.setenv("HBPSM_CHOIX", json.dumps(envelope))
        assert choix.main() == 0 and (out / "choix.enc").exists()
        assert page.evaluate("fetchChoices().then(c => { render(true); return c; })")
        assert page.evaluate("planning()[0].etat") == "publiee" and page.evaluate("planning()[1].etat") == "suggestion"

        def wait_sent(n):
            for _ in range(200):
                if len(sent) >= n:
                    return
                page.wait_for_timeout(100)
            raise AssertionError("rien envoyé à GitHub")

        def publish_last():   # ce que fait le workflow, puis la page relit les choix
            monkeypatch.setenv("HBPSM_CHOIX", sent[-1]["body"]["inputs"]["choix"])
            assert choix.main() == 0
            page.evaluate("fetchChoices().then(() => render(true))")
            return choix.check(json.loads(sent[-1]["body"]["inputs"]["choix"]), PHRASE)

        # retirer la validation : elle quitte ce qui est publié, le match redevient une suggestion
        page.once("dialog", lambda d: d.accept())
        page.locator("[data-retirer]").first.click()
        wait_sent(2)
        assert page.evaluate("planning()[0].etat") == "retrait"
        assert first not in publish_last()["matchs"]
        assert page.evaluate("planning()[0].etat") == "suggestion" and page.evaluate("Object.keys(S.retire)") == []
        # puis la revalider : de nouveau le choix de l'entraîneur
        page.locator("[data-valider]").first.click()
        wait_sent(3)
        chosen = publish_last()
        assert page.evaluate("planning()[0].etat") == "publiee"
        # blessé, absent : l'entraîneur les déclare d'un clic (… incertain → absent → blessé) ; ils sortent
        # des propositions des matchs concernés, puis partent avec la publication, pour tout le monde
        hurt = page.evaluate("""(() => { const P = planning(), r = P[1], p = r.sel.find(q => !isGK(q)), id = String(r.m.id);
          S.dm[id] = Object.assign(S.dm[id] || {}, {[p.cle]: "a"});   // absent pour ce match
          cycleCell(id, p.cle);   // → blessé à partir de ce match
          const after = planning();
          const out = {cle: p.cle, hors: after.slice(1).every(x => !x.sel.includes(p) && availOf(p, x.m) === "a"),
                       avant: availOf(p, after[0].m), attente: statusPending()};
          cycleCell(String(after[3].m.id), p.cle);   // rétabli à partir du 4e match
          out.retour = availOf(p, planning()[3].m) !== "a" && availOf(p, planning()[2].m) === "a";
          const q = planning()[2].sel.find(x => !isGK(x) && x !== p), id2 = String(planning()[2].m.id);
          S.dm[id2] = Object.assign(S.dm[id2] || {}, {[q.cle]: "i"}); cycleCell(id2, q.cle);   // incertain → absent
          out.absent = q.cle; out.id2 = id2; out.sorti = !planning()[2].sel.includes(q) && availOf(q, planning()[3].m) !== "a";
          render(true); return out; })()""")
        assert hurt["hors"] and hurt["avant"] != "a" and hurt["attente"] and hurt["retour"] and hurt["sorti"]
        page.locator("[data-publier-blessures]").click()
        wait_sent(4)
        published = publish_last()
        assert published["blesses"][hurt["cle"]]["a"] and hurt["absent"] in published["absents"][hurt["id2"]]
        assert isinstance(published["rdv"], dict)   # les rendez-vous partent avec les choix (« Ma semaine »)
        assert not page.evaluate("statusPending()") and page.locator("[data-publier-blessures]").count() == 0
        # caisse noire : un trésorier met une amende ; elle part chiffrée au workflow « Caisse noire »
        page.click("nav.tabs button[data-tab=caisse]")
        page.locator("[data-cpick-j]").first.click()
        page.locator("[data-cpart=Match]").click()
        page.locator("[data-cpick-r=m_oubli]").click()
        page.locator("[data-cn='1']").click()
        page.fill("#cnote", "veste du club")
        # seuls les joueurs à jour de leur cotisation mettent une amende : d'abord qui il est, puis sa cotisation
        assert page.locator("[data-cgo]").is_disabled() and "qui vous êtes" in page.inner_text(".picker .cstop")
        coach = page.evaluate("D.caisse.coach")
        page.select_option("#cme", coach)
        assert page.locator("[data-cgo]").is_disabled() and "cotisation" in page.inner_text(".picker .cstop")
        page.locator(f"[data-ccot$='{coach}']").click()   # « Payé » : on peut toujours la régler
        wait_sent(5)
        assert page.locator(".picker .cstop").count() == 0
        page.locator("[data-cgo]").click()
        wait_sent(6)
        assert sent[-1]["url"].endswith("/actions/workflows/caisse.yml/dispatches")
        ops = caisse.check(json.loads(sent[-1]["body"]["inputs"]["ops"]), PHRASE)
        assert [(o["t"], o.get("regle"), o.get("n"), o["montant"]) for o in ops] == [("amende", "cotisation", 1, 5), ("paiement", None, None, 5),
                                                                                     ("amende", "m_oubli", 2, 4)]
        assert ops[-1]["note"] == "veste du club" and ops[-1]["par"] == coach
        monkeypatch.setenv("HBPSM_CAISSE", sent[-1]["body"]["inputs"]["ops"])
        assert caisse.main() == 0
        assert page.evaluate("fetchCaisse().then(() => { render(true); return [outbox().length, ledger().fines.length]; })") == [0, 2]
        # les comptes : payé et reste d'un coup d'œil (total, barre, cotisation en pastille, « À régler » puis « À jour »)
        comptes = page.text_content(".comptes")
        assert "Encaissé 5 € sur 9 €" in comptes and "À régler" in comptes and "5 € payés sur 9 € · 1 amende" in comptes
        assert "4 € à payer" in comptes and "🎟️ payée" in comptes and "À jour" not in comptes
        assert page.evaluate("[...document.querySelectorAll('.comptes .cbar .p')].map(e => e.style.width)") == ["55.6%", "55.6%"]
        # penalties manqués : 1 € à partir du 2e échec du match, 2 € dès un hors cadre
        pens = page.evaluate("""(() => { const p = {id: "m_penalty:x:check", motif: "penalties contre Club", date: "2026-10-10", match: "x"};
          const out = [[1, 0], [2, 0], [2, 1], [1, 1]].map(([a, h]) => { PENS[p.id] = {"R:A": {a, h}};
            return penaltyOps(p).filter(o => o.t === "amende").map(o => o.regle + ":" + o.montant).join(","); });
          delete PENS[p.id]; return out; })()""")
        assert pens == ["", "m_penalty:1", "m_penalty_hors_cadre:2,m_penalty:1", "m_penalty_hors_cadre:2"]
        server.shutdown()  # hors connexion : la copie locale suffit, sans redemander la phrase
        server.server_close()
        page.reload()
        page.wait_for_selector("header.top h1")
        assert page.evaluate("D.meta.matchs") == 24  # la copie gardée est la plus récente
        # rouverte, la page revient sur la planification, même après la saison
        assert page.get_attribute("nav.tabs button[data-tab=planif]", "aria-selected") == "true"
        page.click("nav.tabs button[data-tab=saison]")
        assert "hors connexion" in page.inner_text(".status") and "hors connexion" in page.inner_text("#club-etat")
        # ouverte directement (sans « #entraineur ») : consultation seulement, rien ne se modifie
        ro = ctx.new_page()
        ro.on("pageerror", lambda e: errors.append(str(e)))
        ro.goto(page_file.as_uri())
        ro.wait_for_selector("header.top h1")
        # un joueur qui a dit qui il est sur cet appareil : la page s'ouvre sur « Ma semaine »
        assert ro.evaluate("S.tab") == "moi" and ro.get_attribute("nav.tabs button[data-tab=moi]", "aria-selected") == "true"
        ro.click("nav.tabs button[data-tab=planif]")
        assert ro.inner_text("#club-mode") == "consultation" and ro.locator(".lecture-only").first.is_visible()
        # un lien vers un onglet l'ouvre directement
        lk = ctx.new_page()
        lk.goto(page_file.as_uri() + "#saison")
        lk.wait_for_selector("header.top h1")
        assert lk.evaluate("S.tab") == "saison" and lk.evaluate("COACH") is False
        lk.close()
        assert not ro.locator("#regle").is_visible() and not ro.locator("[data-export]").is_visible()
        before = ro.evaluate("JSON.stringify([S.pin, S.dm])")
        ro.locator("button.cell.in").first.click()
        assert ro.locator("#why").is_visible() and ro.evaluate("JSON.stringify([S.pin, S.dm])") == before
        ro.click("nav.tabs button[data-tab=convoc]")
        assert ro.locator("#rdv").count() == 0 and not ro.locator("[data-copy]").is_visible()
        ro.wait_for_function("() => CHOIX !== null", timeout=10000)
        assert ro.evaluate("PLAN.map(r => r.etat)") == ["choix", "suggestion", "suggestion", "suggestion"]
        assert sorted(ro.evaluate("PLAN[0].sel.map(p => p.cle)")) == sorted(chosen["matchs"][first]["joueurs"])
        # blessé et absent publiés : en consultation aussi, ils sortent des propositions
        assert ro.evaluate("""((c, a, id2) => { const P = planning(), p = D.joueurs.find(x => x.cle === c), q = D.joueurs.find(x => x.cle === a);
          return !P[2].sel.includes(p) && !P[2].sel.includes(q) && availOf(q, P.find(r => String(r.m.id) === id2).m) === "a"; })""" +
                           f"({json.dumps(hurt['cle'])}, {json.dumps(hurt['absent'])}, {json.dumps(hurt['id2'])})")
        # en consultation, ce que l'entraîneur a saisi dans ce navigateur ne change rien : la même
        # proposition qu'un navigateur où rien n'a été saisi
        assert ro.evaluate("""(() => { const pick = () => JSON.stringify(planning().map(r => r.sel.map(p => p.cle)));
          const saved = JSON.stringify(S), m = planning()[1].m.id;
          S.dm[m] = {[D.joueurs[0].cle]: "a", [D.joueurs[1].cle]: "a"}; S.regle = 2; const a = pick();
          Object.assign(S, {postes: {}, absents: {}, depannage: {}, dm: {}, pin: {}, regle: 1});
          const b = pick(); S = JSON.parse(saved);
          return a === b; })()""")
        ro.click("nav.tabs button[data-tab=semaine]")
        assert "choisis par l'entraîneur" in ro.inner_text("h2") and "Choix de l'entraîneur" in ro.inner_text(".etat-ligne")
        assert ro.locator("[data-valider]").count() == 0
        ro.evaluate("localStorage.removeItem('hbpsm:jeton')")   # un joueur sans le jeton
        ro.click("nav.tabs button[data-tab=caisse]")
        # le rappel d'anniversaire : celui du jour, puis les 30 prochains jours
        bday = ro.evaluate("""(() => { const keep = D.caisse.anniversaires, k = D.joueurs[0].cle, k2 = D.joueurs[1].cle;
          D.caisse.anniversaires = [{cle: k, jour: "10-05"}, {cle: k2, jour: "10-06"}, {cle: D.caisse.coach, jour: "10-20"}];
          const html = birthdayBlock(new Date(2026, 9, 5)); D.caisse.anniversaires = keep; return html; })()""")
        assert "aujourd" in bday and "demain" in bday and "dans 15 jours" in bday and "Coach" in bday
        ro.wait_for_function("() => CAISSE !== null", timeout=10000)
        assert ro.evaluate("ledger().fines.length") == 2 and ro.locator("[data-cval]").count() == 0
        ro.locator("[data-cpick-j]").first.click()
        ro.locator("[data-cpick-r=m_oubli]").click()
        assert ro.locator("[data-cgo]").count() == 0 and ro.locator("[data-cdenonce]").count() == 1
        # seul un joueur à jour de sa cotisation dénonce : il dit qui il est ; l'entraîneur (payée) oui, sans elle non
        ro.evaluate("localStorage.removeItem('hbpsm:moi'); localStorage.setItem('hbpsm:moi-aucun', '1'); render(true)")
        assert ro.locator("[data-cdenonce]").is_disabled() and "qui vous êtes" in ro.inner_text(".picker .cstop")
        ro.evaluate(f"setMe({json.dumps(coach)}); render(true)")
        assert ro.locator("[data-cdenonce]").is_enabled() and ro.locator(".picker .cstop").count() == 0
        ro.evaluate("window.__caisse = CAISSE; CAISSE = {ops: CAISSE.ops.filter(o => o.regle !== 'cotisation')}; render(true)")
        assert ro.locator("[data-cdenonce]").is_disabled() and "réglez vos" in ro.inner_text(".picker .cstop")
        ro.evaluate("CAISSE = window.__caisse; render(true)")
        assert ro.locator("[data-cdenonce]").is_enabled()
        # hors caisse (effectif, ou « ne participe pas » d'un trésorier, qui se retire) : ni amende, ni dénonciation ;
        # la proposition d'un joueur pas à jour de sa cotisation est irrecevable
        hors = ro.evaluate("""(() => { const c = D.caisse.coach, keep = [D.caisse.hors, CAISSE, CN], r = {};
          D.caisse.hors = [c];
          const L = ledger();
          r.effectif = !participants(L).includes(c) && blocage(c, L, false).includes("ne participe pas");
          const sortie = {id: "r:cotisation:x:R:T1", t: "refus", auto: "cotisation:x:R:T1", par: "", le: "2026-10-08", note: ""};
          CAISSE = {ops: [...(CAISSE.ops || []), sortie]};
          r.sorti = ledger().out.has("R:T1") && ledger().sortis["R:T1"] === sortie.id;
          CAISSE.ops.push({id: "a:t", t: "annule", cible: sortie.id, par: "", le: "2026-10-08", note: ""});
          r.reintegre = !ledger().out.has("R:T1");
          D.caisse.hors = ["R:T2"];
          CN = {ops: [{id: "prop:t1", t: "proposition", joueur: c, regle: "m_oubli", n: 1, montant: 2, par: "R:T1", le: "2026-10-08"},
                      {id: "prop:t2", t: "proposition", joueur: "R:T2", regle: "m_oubli", n: 1, montant: 2, par: c, le: "2026-10-08"}]};
          const P = caisseProposals(ledger());
          r.irrecevable = (P.find(p => p.id === "prop:t1") || {}).irrecevable === true && !P.some(p => p.id === "prop:t2");
          [D.caisse.hors, CAISSE, CN] = keep; return r; })()""")
        assert hors == dict(effectif=True, sorti=True, reintegre=True, irrecevable=True)
        # téléphone : la dénonciation se partage directement (menu de partage du téléphone)
        ro.set_viewport_size({"width": 360, "height": 780})
        ro.evaluate("navigator.share = async d => { window.__partage = d; }; render(true)")
        # les comptes tiennent à 360 px : nom, barre et reste, sans la ligne de détail
        assert ro.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth") <= 0
        assert ro.locator(".comptes .cbar").first.is_visible() and not ro.locator(".comptes .cdet").first.is_visible()
        ro.locator("[data-cshare]").click()
        ro.wait_for_function("() => window.__partage", timeout=3000)
        assert "Dénonciation pour la caisse noire, par Coach" in ro.evaluate("window.__partage.text")
        ro.set_viewport_size({"width": 1100, "height": 900})
        ro.wait_for_function("() => !document.querySelector('[data-cshare]')", timeout=3000)
        # avec le jeton des propositions (dans les données chiffrées), il propose l'amende directement :
        # elle part au dépôt à part, tout le monde la voit, seul un trésorier la valide
        ro.evaluate("""D.caisse.jeton_cn = "jeton-cn-test"; CFG.cn = CFG.caisse.replace("caisse.enc", "propositions.enc");
          CFG.cn_depot = "exemple/cn"; CFG.cn_workflow = "proposer.yml"; render(true)""")
        ro.evaluate("localStorage.removeItem('hbpsm:moi'); localStorage.setItem('hbpsm:moi-aucun', '1'); render(true)")
        assert ro.locator("[data-cpropose]").is_disabled()   # d'abord : qui propose ?
        ro.evaluate(f"setMe({json.dumps(coach)}); render(true)")
        before = len(sent)
        ro.locator("[data-cpropose]").click()
        wait_sent(before + 1)
        assert sent[-1]["url"].endswith("/repos/exemple/cn/actions/workflows/proposer.yml/dispatches")
        assert sent[-1]["auth"] == "Bearer jeton-cn-test" and "Joueur" not in sent[-1]["body"]["inputs"]["prop"]
        import importlib.util
        spec = importlib.util.spec_from_file_location("propositions_cn", ROOT_DIR / "cn" / "propositions.py",
                                                      submodule_search_locations=None)
        sys.path.insert(0, str(ROOT_DIR / "cn"))
        cn = importlib.util.module_from_spec(spec); spec.loader.exec_module(cn)
        monkeypatch.setattr(cn.vault, "ITERATIONS", 2000)
        monkeypatch.setattr(cn.vault.encrypt, "__defaults__", (2000,))
        monkeypatch.setenv("HBPSM_PROP", sent[-1]["body"]["inputs"]["prop"])
        assert cn.main(out / "propositions.enc") == 0   # ce que fait le workflow du dépôt à part
        ro.evaluate("fetchCN().then(() => render(true))")
        ro.wait_for_function("() => caisseProposals(ledger()).some(p => p.joueurs)", timeout=10000)
        prop_id = ro.evaluate("caisseProposals(ledger()).find(p => p.joueurs).id")
        assert "proposée par" in ro.inner_text("main") and ro.locator(f"[data-cval='{prop_id}']").count() == 0
        page.evaluate("localStorage.setItem('hbpsm:jeton', 'jeton-de-test')")   # un trésorier
        page.evaluate("fetchCN().then(() => render(true))")
        page.click("nav.tabs button[data-tab=caisse]")
        page.wait_for_selector(f"[data-cval='{prop_id}']", timeout=10000)
        before = len(sent)
        page.locator(f"[data-cval='{prop_id}']").click()
        wait_sent(before + 1)
        assert sent[-1]["url"].endswith("/actions/workflows/caisse.yml/dispatches")
        assert [o["auto"] for o in caisse.check(json.loads(sent[-1]["body"]["inputs"]["ops"]), PHRASE)] == [prop_id]
        browser.close()
    assert errors == []


def test_workflows_lisibles():
    """Chaque workflow (le tableau de bord et le dépôt des propositions) est un YAML que GitHub sait lire,
    avec ses déclencheurs : un « : » mal placé dans un nom d'étape suffit à le rendre muet."""
    import yaml
    files = sorted((ROOT_DIR / ".github" / "workflows").glob("*.yml")) + sorted((ROOT_DIR / "cn" / ".github" / "workflows").glob("*.yml"))
    assert len(files) >= 4
    for f in files:
        d = yaml.safe_load(f.read_text("utf-8"))
        assert (d.get(True) or d.get("on")) and d.get("jobs"), f.name


def test_calendrier_des_matchs(tmp_path):
    """Le calendrier auquel chacun s'abonne : les matchs du club (championnat et coupe), à l'heure de Paris,
    horaire à confirmer en journée entière, score des matchs joués, rien contre une équipe en forfait ;
    lignes de 75 octets au plus ; réécrit seulement si un match change."""
    from pipeline import agenda
    config = dict(common.load_config(), forfaits=["P16M DIV2 CLUB FORFAIT 2"],
                  competition="https://exemple/competitions/saison-2026-2027-22/regional/2eme-division-masculine-p16-aura-30501/")
    club = config["club"]["motifs"][0]
    base = dict(poule="71", score_home=None, score_away=None, url="https://exemple/rencontre/")
    fixtures = [dict(base, id="1", journee=1, date="2026-10-03T21:00", home=club, away="P16M DIV2 CLUB BRAVO 2", score_home=32, score_away=19),
                dict(base, id="2", journee=2, date="2026-10-10T20:30", home="CLUB CHARLIE", away=club,
                     salle=dict(nom="GYMNASE DES ESSAIS", rue="RUE DU TEST", code_postal="38000", ville="VILLE FICTIVE")),
                dict(base, id="3", journee=3, date="2026-11-07", date_provisoire=True, home=club, away="CLUB DELTA"),
                dict(base, id="4", journee=4, date="2026-11-14", date_provisoire=True, home="P16M DIV2 CLUB FORFAIT 2", away=club),
                dict(base, id="5", poule="coupe", coupe="Coupe de France", tour="1ER TOUR", date="2026-10-17T18:00", home="CLUB ECHO", away=club),
                dict(base, id="6", journee=1, date="2026-10-03T21:00", home="CLUB CHARLIE", away="CLUB DELTA")]
    lines = agenda.calendar(fixtures, config, "https://exemple.github.io/tableau/")
    events = "\n".join(lines).split("BEGIN:VEVENT")[1:]
    assert len(events) == 4   # le forfait et le match des autres n'y sont pas
    assert "SUMMARY:HBPSM 32-19 Bravo 2 · J1" in events[0] and "DTSTART;TZID=Europe/Paris:20261003T210000" in events[0]
    assert "DTEND;TZID=Europe/Paris:20261003T223000" in events[0]
    assert "LOCATION:Gymnase Des Essais\\, Rue Du Test\\, 38000 Ville Fictive" in events[1]
    assert "SUMMARY:Echo – HBPSM · Coupe de France\\, 1er tour" in events[2]
    assert "DTSTART;VALUE=DATE:20261107" in events[3] and "DTEND;VALUE=DATE:20261109" in events[3] and "STATUS:TENTATIVE" in events[3]
    assert "(horaire à confirmer)" in events[3] and "2e division P16 AURA\\, poule 71\\, journée 3" in events[3]
    path = tmp_path / "matchs.ics"
    assert agenda.save(lines, path) and all(len(l.encode("utf-8")) <= 75 for l in path.read_bytes().decode("utf-8").split("\r\n"))
    first = path.read_bytes()
    assert not agenda.save(lines, path) and path.read_bytes() == first   # rien de changé : pas réécrit
    fixtures[2]["date"], fixtures[2]["date_provisoire"] = "2026-11-07T20:00", False
    assert agenda.save(agenda.calendar(fixtures, config), path) and b"20261107T200000" in path.read_bytes()


def test_application_installable():
    """La page sur GitHub Pages s'installe sur l'écran d'accueil : manifeste lisible, icônes présentes,
    copiées avec la page par le workflow."""
    import yaml
    man = json.loads((ROOT_DIR / "dashboard" / "manifest.webmanifest").read_text("utf-8"))
    assert man["display"] == "standalone" and man["start_url"] == "./"
    assert all((ROOT_DIR / "dashboard" / i["src"]).exists() for i in man["icons"])
    assert {i["sizes"] for i in man["icons"]} >= {"192x192", "512x512"} and any(i["purpose"] == "maskable" for i in man["icons"])
    steps = yaml.safe_load((ROOT_DIR / ".github" / "workflows" / "weekly.yml").read_text("utf-8"))["jobs"]["collecte"]["steps"]
    pages = next(s["run"] for s in steps if "GitHub Pages" in (s.get("name") or ""))
    assert "manifest.webmanifest" in pages and "sw.js" in pages and "icons" in pages
    template = (ROOT_DIR / "dashboard" / "template.html").read_text("utf-8")
    assert 'rel="manifest"' in template and 'serviceWorker.register("sw.js")' in template


def test_sante(sandbox, monkeypatch):
    """La santé du tableau de bord : poule non lue, feuilles qui tardent ou illisibles, jetons qui expirent ;
    un fichier public sans nom, réécrit seulement quand quelque chose change."""
    config = dict(common.load_config(), poules=[{"id": "71"}, {"id": "72"}], saison="2026-2027")
    club = config["club"]["motifs"][0]
    fixtures = [dict(id="1", poule="71", home=club, away="CLUB BRAVO", date="2026-10-01T20:00", score_home=30, score_away=20, pdf_url="x"),
                dict(id="2", poule="71", home="CLUB BRAVO", away=club, date="2026-11-01T20:00", score_home=None, score_away=None)]
    out = sante.checks(config, fixtures, [], dict(erreurs=2, actions_inconnues=["Bizarre"]), "2026-10-06",
                       {"des propositions": 12, "de publication": "refusé"})
    codes = {a["code"]: a["niveau"] for a in out}
    assert codes == {"poule-72": "alerte", "feuilles": "info", "illisibles": "alerte", "libelles": "info",
                     "jeton-des propositions": "info", "jeton-de publication": "alerte"}
    assert sante.checks(config, fixtures + [dict(fixtures[1], id="3", poule="72")],
                        [dict(id="1", players=dict(home=[1]))], {}, "2026-10-06", {}) == []
    # de février à avril : la formule de la deuxième phase est à prendre en compte (rappel pour l'entraîneur)
    late = [dict(fixtures[1], id="9", poule=p, date="2027-05-01T20:00") for p in ("71", "72")]
    assert [a["code"] for a in sante.checks(config, late, [], {}, "2027-02-15", {})] == ["rappel-phase2"]
    seen = dict(config, objectif=dict(config["objectif"], phase2="vue"))
    assert sante.checks(seen, late, [], {}, "2027-02-15", {}) == []
    demo(sandbox)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert sante.main([]) == 0
    first = (sandbox / "publie" / "sante.json").read_text("utf-8")
    assert json.loads(first)["format"] == "hbpsm-sante" and "Joueur" not in first
    assert sante.main([]) == 0 and (sandbox / "publie" / "sante.json").read_text("utf-8") == first   # rien de changé : pas réécrit
    assert sante.main(["--echec"]) == 0 and json.loads((sandbox / "publie" / "sante.json").read_text("utf-8"))["etat"] == "alerte"


def test_depot_des_propositions(tmp_path, monkeypatch):
    """Le dépôt à part (strus38/hbpsm-cn) n'accepte que des propositions chiffrées avec la phrase du club, de la
    forme attendue, sans doublon ; son module de chiffrement est celui du tableau de bord."""
    assert (ROOT_DIR / "cn" / "vault.py").read_bytes() == (ROOT_DIR / "pipeline" / "vault.py").read_bytes()
    import importlib.util
    sys.path.insert(0, str(ROOT_DIR / "cn"))
    spec = importlib.util.spec_from_file_location("propositions_cn2", ROOT_DIR / "cn" / "propositions.py")
    cn = importlib.util.module_from_spec(spec); spec.loader.exec_module(cn)
    monkeypatch.setattr(cn.vault, "ITERATIONS", 2000)
    monkeypatch.setenv("HBPSM_CLE", PHRASE)
    prop = dict(id="prop:1", t="proposition", joueur="R:EXEMPLE ISIDORE", regle="m_oubli", n=1, montant=2,
                date="2026-10-10", note="gourde", par="R:MODELE JEAN", le="2026-10-10T20:00:00Z", match=None)
    send = lambda ops, phrase=PHRASE, fmt="hbpsm-cn": monkeypatch.setenv("HBPSM_PROP", json.dumps(cn.vault.encrypt(
        dict(format=fmt, v=1, ops=ops), phrase, 2000)))
    book = tmp_path / "propositions.enc"
    send([prop])
    assert cn.main(book) == 0 and cn.main(book) == 0   # renvoyée : comptée une fois
    assert [o["id"] for o in cn.vault.decrypt(json.loads(book.read_text("utf-8")), PHRASE)["ops"]] == ["prop:1"]
    for bad in (dict(ops=[dict(prop, id="prop:2", t="amende")]), dict(ops=[dict(prop, id="prop:3", montant=1000)]),
                dict(ops=[dict(prop, id="prop:4", jeton="x")]), dict(ops=[prop], fmt="hbpsm-caisse-ops"),
                dict(ops=[prop], phrase="une autre phrase bien longue")):
        send(**bad)
        with pytest.raises(cn.vault.VaultError):
            cn.main(book)


def cn_module(monkeypatch, name):
    """Le module du dépôt à part (strus38/hbpsm-cn), chiffrement allégé pour les tests."""
    import importlib.util
    sys.path.insert(0, str(ROOT_DIR / "cn"))
    spec = importlib.util.spec_from_file_location(name, ROOT_DIR / "cn" / "propositions.py")
    cn = importlib.util.module_from_spec(spec); spec.loader.exec_module(cn)
    monkeypatch.setattr(cn.vault, "ITERATIONS", 2000)
    monkeypatch.setattr(cn.vault.encrypt, "__defaults__", (2000,))
    return cn


def test_depot_des_presences(tmp_path, monkeypatch):
    """Réponses de présence, « Vous êtes » et votes (demande de l'auteur, 09/10/2026) : même dépôt et même workflow que
    les propositions, rangés à part dans presences.enc, avec l'heure de réception ; absent : un motif, « autre » : un mot."""
    cn = cn_module(monkeypatch, "propositions_cn_pres")
    monkeypatch.setenv("HBPSM_CLE", PHRASE)
    send = lambda ops: monkeypatch.setenv("HBPSM_PROP", json.dumps(cn.vault.encrypt(dict(format="hbpsm-cn", v=1, ops=ops), PHRASE, 2000)))
    moi = dict(id="moi:1", t="moi", joueur="R:EXEMPLE ISIDORE", app="appareil-1", le="2026-10-09T10:00:00.000Z")
    oui = dict(id="d:1", t="dispo", joueur="R:EXEMPLE ISIDORE", evs=["E-2026-10-16", "M-42"], etat="present", motif="", texte="",
               app="appareil-1", le="2026-10-09T10:01:00.000Z")
    non = dict(oui, id="d:2", evs=["E-2026-10-20"], etat="absent", motif="autre", texte="mariage")
    vote = dict(id="vote:1", t="vote", match="42", joueur="R:EXEMPLE ISIDORE", pour="R:MODELE JEAN", app="appareil-1", le="2026-10-11T22:00:00.000Z")
    prop = dict(id="prop:1", t="proposition", joueur="R:MODELE JEAN", regle="m_oubli", n=1, montant=2, date="2026-10-10",
                note="", par="R:EXEMPLE ISIDORE", le="2026-10-10T20:00:00Z", match=None)
    send([moi, oui, non, vote, prop])
    book, pres = tmp_path / "propositions.enc", tmp_path / "presences.enc"
    assert cn.main(book) == 0 and cn.main(book) == 0   # renvoyés : comptés une fois
    journal = cn.vault.decrypt(json.loads(pres.read_text("utf-8")), PHRASE)
    assert [o["id"] for o in journal["ops"]] == ["moi:1", "d:1", "d:2", "vote:1"] and all(o["recu"].endswith("Z") for o in journal["ops"])
    assert [o["id"] for o in cn.vault.decrypt(json.loads(book.read_text("utf-8")), PHRASE)["ops"]] == ["prop:1"]
    for bad in (dict(non, id="d:3", motif=""),                       # absent sans motif
                dict(non, id="d:4", texte="  "),                     # « autre » sans un mot
                dict(oui, id="d:5", motif="malade"),                 # présent avec un motif
                dict(non, id="d:6", motif="fatigue"),                # motif inconnu
                dict(oui, id="d:7", evs=["E-2026-10-16"] * 61),      # trop de séances d'un coup
                dict(oui, id="d:8", etat="peut-etre"),
                dict(vote, id="vote:2", pour=""), dict(moi, id="moi:2", nom="en clair")):
        send([bad])
        with pytest.raises(cn.vault.VaultError):
            cn.main(book)
    # ce que lit la collecte : les présents d'une séance, joueurs de champ et gardiens, jamais un nom
    joueurs = [dict(cle="R:EXEMPLE ISIDORE", poste="ARG", gardien=False), dict(cle="R:MODELE JEAN", poste="GB", gardien=True),
               dict(cle="R:ESSAI ZEPHYRIN", poste="PIV", gardien=False)]
    ops = journal["ops"] + [dict(id="d:9", t="dispo", joueur="R:MODELE JEAN", evs=["E-2026-10-16"], etat="present", le="2026-10-09T11:00:00Z"),
                            dict(id="d:10", t="dispo", joueur="R:ESSAI ZEPHYRIN", evs=["E-2026-10-16"], etat="present", le="2026-10-09T11:00:00Z"),
                            dict(id="d:11", t="dispo", joueur="R:ESSAI ZEPHYRIN", evs=["E-2026-10-16"], etat="absent", motif="malade", le="2026-10-10T08:00:00Z")]
    assert presences.training_counts(ops, "2026-10-16", joueurs) == (1, 1)   # le dernier mot compte
    assert presences.training_counts(ops, "2026-10-13", joueurs) == (0, 0)
    # une horloge fausse : arrivé plus d'un jour après, c'est l'heure de réception qui compte
    late = dict(id="x", le="2026-10-01T10:00:00Z", recu="2026-10-05T10:00:00Z")
    assert presences.op_time(late).day == 5 and presences.op_time(dict(late, recu="2026-10-01T10:05:00Z")).day == 1


def test_presences_dans_la_collecte(sandbox, monkeypatch):
    """La collecte : les matchs du club et les délais pour la page, l'effectif annoncé de la prochaine séance dans le
    fichier de HANDBALL-training, les séances annulées publiées par l'entraîneur."""
    demo(sandbox)
    (sandbox / "roster.csv").write_text("nom,poste,disponible\n" + "".join(f"{n},{p}\n" for n, p in zip(
        [f"Joueur {k:02d}" for k in range(1, 15)], demo_data.POSTES)), "utf-8")
    d = an.analyze("2026-10-04")
    assert d["presences"]["delai_jours"] == 4 and d["presences"]["jours"] == [1, 4] and d["presences"]["vote_heures"] == 48
    ag = d["agenda"]
    assert ag and all(m["id"] and "adversaire" in m for m in ag) and ag == sorted(ag, key=lambda m: m["date"] or "9999")
    played = [m for m in ag if m["bp"] is not None]
    assert played and all(k.startswith("R:") for m in played for k in m["joueurs"]) and any(m["joueurs"] for m in played)
    assert {m["id"] for m in ag} >= {str(m["id"]) for m in d["saison"]["matchs"]}
    keepers = [p["cle"] for p in d["joueurs"] if p["gardien"]]
    field = [p["cle"] for p in d["joueurs"] if not p["gardien"] and p["cle"].startswith("R:")]
    ops = [dict(id=f"d:{k}", t="dispo", joueur=c, evs=["E-2026-10-06"], etat="present", le="2026-10-01T10:00:00Z")
           for k, c in enumerate(keepers[:1] + field[:9])]
    _, fichier = build_exports(d, sandbox / "docs", today="2026-10-05", answers=ops)
    s = fichier["contenu"]["seance"]
    assert s["date"] == "2026-10-06" and (s["effectifJoueurs"], s["effectifGardiens"]) == (9, 1)
    assert "Joueur 0" not in json.dumps(fichier, ensure_ascii=False)
    # séances annulées : publiées avec les choix de l'entraîneur, de la forme attendue
    monkeypatch.setattr(vault, "ITERATIONS", 2000)
    monkeypatch.setenv("HBPSM_CLE", PHRASE)
    good = dict(format="hbpsm-choix", v=1, matchs={}, annulees=["2026-10-27", "2026-10-30"])
    monkeypatch.setenv("HBPSM_CHOIX", json.dumps(vault.encrypt(good, PHRASE, 2000)))
    assert choix.main() == 0
    for bad in (dict(good, annulees="2026-10-27"), dict(good, annulees=["27/10"])):
        monkeypatch.setenv("HBPSM_CHOIX", json.dumps(vault.encrypt(bad, PHRASE, 2000)))
        with pytest.raises(vault.VaultError):
            choix.main()


def test_presences_dans_la_page(sandbox, monkeypatch):
    """Dans la page (demande de l'auteur, 09/10/2026) : chacun dit qui il est, un nom déjà pris est signalé et l'on
    peut se redéclarer ; chacun répond pour lui seul et ne voit que ses réponses ; l'entraîneur voit tout, bouge la
    feuille, annule une séance ; sans réponse à temps, l'amende est proposée ; l'homme du match est élu par les
    joueurs de la feuille, son nom visible de tous et son amende proposée."""
    pw = pytest.importorskip("playwright.sync_api")
    monkeypatch.setattr(vault, "ITERATIONS", 2000)
    monkeypatch.setattr(vault.encrypt, "__defaults__", (2000,))
    monkeypatch.setenv("HBPSM_CLE", PHRASE)
    monkeypatch.setenv("HBPSM_JETON_CN", "jeton-cn-test")
    demo(sandbox)
    (sandbox / "roster.csv").write_text("nom,poste,disponible\n" + "".join(f"{n},{p}\n" for n, p in zip(
        [f"Joueur {k:02d}" for k in range(1, 15)], demo_data.POSTES)), "utf-8")
    publish.seal("2026-10-04")
    out = sandbox / "publie"
    cn = cn_module(monkeypatch, "propositions_cn_page")

    class Handler(http.server.SimpleHTTPRequestHandler):
        def end_headers(self):  # comme raw.githubusercontent.com
            self.send_header("Access-Control-Allow-Origin", "*")
            super().end_headers()

        def log_message(self, *a, **k):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory=str(out)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}/"
    page_file = sandbox / "tableau.html"
    page_file.write_text(render(None, dict(src=base + "hbpsm.enc", manifeste=base + "manifeste.json", versions="",
                                           choix=base + "choix.enc", caisse=base + "caisse.enc", depot="exemple/depot", branche="main",
                                           cn=base + "propositions.enc", cn_depot="exemple/cn", cn_branche="main", cn_workflow="proposer.yml",
                                           presences=base + "presences.enc", iterations=2000, club="HBPSM", verif=600)), "utf-8")
    sent, errors = [], []

    def github(route):
        cors = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "*", "Access-Control-Allow-Methods": "POST"}
        if route.request.method == "OPTIONS":
            return route.fulfill(status=204, headers=cors)
        sent.append(dict(url=route.request.url, body=json.loads(route.request.post_data)))
        route.fulfill(status=204, headers=cors)

    def wait_sent(pg, n):
        for _ in range(200):
            if len(sent) >= n:
                return
            pg.wait_for_timeout(100)
        raise AssertionError("rien envoyé à GitHub")

    def apply(*pages):   # ce que fait le workflow du dépôt à part, puis chaque page relit le journal
        monkeypatch.setenv("HBPSM_PROP", sent[-1]["body"]["inputs"]["prop"])
        assert sent[-1]["url"].endswith("/repos/exemple/cn/actions/workflows/proposer.yml/dispatches")
        assert cn.main(out / "propositions.enc") == 0
        for pg in pages:
            pg.evaluate("fetchPresences().then(() => render(true))")
            pg.wait_for_function("() => cnOutbox().length === 0", timeout=10000)
        return cn.check(json.loads(sent[-1]["body"]["inputs"]["prop"]), PHRASE)

    with pw.sync_playwright() as p:
        browser = chrome(p)

        def device(hash=""):
            ctx = browser.new_context()
            ctx.route("https://api.github.com/**", github)
            pg = ctx.new_page()
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.goto(page_file.as_uri() + hash)
            pg.wait_for_selector("#phrase")
            pg.fill("#phrase", PHRASE)
            pg.click("#unlock")
            pg.wait_for_selector("header.top h1")
            pg.wait_for_function("() => PRESJ !== null", timeout=10000)   # pas encore de journal : vide
            return pg

        # 1. « Vous êtes » : demandé d'emblée ; le choix part au dépôt à part
        a = device()
        assert a.locator(".qui").is_visible() and "Qui êtes-vous" in a.inner_text(".qui")
        squad = a.evaluate("squad().map(p => p.cle)")
        assert len(squad) == 14
        k1, k2, k3 = [a.evaluate(f"D.joueurs.find(p => p.nom === 'Joueur {n}').cle") for n in ("05", "06", "07")]
        a.click(f".qui [data-qui='{k1}']")
        wait_sent(a, 1)
        assert a.evaluate("stored(MOI)") == k1 and a.evaluate("S.tab") == "moi" and a.locator(".qui").count() == 0
        assert [(o["t"], o["joueur"]) for o in apply(a)] == [("moi", k1)] and not (out / "propositions.enc").exists()
        # un autre appareil prend le même nom : signalé ; il confirme, puis se redéclare sous le sien
        b = device()
        assert "déjà pris" in b.inner_text(f".qui [data-qui='{k1}']")
        b.click(f".qui [data-qui='{k1}']")
        assert "déjà été choisi sur un autre appareil" in b.inner_text(".qui")
        b.click("[data-qui-ok]")
        wait_sent(b, 2)
        apply(a, b)
        assert "Un autre appareil s'est aussi déclaré comme Joueur 05" in a.inner_text("main")
        b.click("[data-qui-open]")
        b.click(f".qui [data-qui='{k2}']")
        wait_sent(b, 3)
        apply(a, b)
        assert b.evaluate("stored(MOI)") == k2 and "Un autre appareil" not in a.inner_text("main")

        # 2. les réponses : présent d'un geste ; absent avec un motif, « autre » avec un mot obligatoire
        ev = a.evaluate("events(addDays(ymd(new Date()), 6), addDays(ymd(new Date()), 13)).find(e => e.type === 'e').id")
        a.evaluate("""(() => { const d = addDays(ymd(new Date()), 10), adv = D.saison.matchs[0].adversaire;
          D.agenda.push({id: "9901", date: d + "T20:30", provisoire: false, adversaire: adv, domicile: true, joueurs: []});
          S.tab = "presences"; render(false); })()""")
        assert "Mes réponses" in a.inner_text("main") and "ont dit venir" not in a.inner_text("main")
        a.click(f"[data-rep='{ev}']")
        wait_sent(a, 4)
        assert [(o["t"], o["etat"], o["evs"]) for o in apply(a)] == [("dispo", "present", [ev])]
        a.click("[data-rep-abs='M-9901']")
        a.click("[data-motif=autre]")
        assert a.locator("[data-rep-envoi]").is_disabled()
        a.fill("#pf-texte", "mariage de mon frère")
        assert a.locator("[data-rep-envoi]").is_enabled()
        a.click("[data-rep-envoi]")
        wait_sent(a, 5)
        ops = apply(a)
        assert [(o["etat"], o["motif"], o["texte"], o["evs"]) for o in ops] == [("absent", "autre", "mariage de mon frère", ["M-9901"])]
        assert a.evaluate(f"statusOf({json.dumps(k1)}, {{id: '{ev}', day: '{ev[2:]}'}}).etat") == "present"
        assert "✓ présent" in a.inner_text("main") and "✕ absent" in a.inner_text("main")
        # une période d'absence : tous les entraînements et matchs de ces jours-là
        a.click("[data-periode]")
        assert a.evaluate("PF.ev") == "periode"
        a.evaluate("PF.du = addDays(ymd(new Date()), 20); PF.au = addDays(ymd(new Date()), 26)")
        assert len(a.evaluate("periodEvents()")) >= 2
        a.click("[data-rep-annule]")
        # tout le calendrier de la saison, mois par mois : « présent » d'un coup à ce qui reste sans réponse
        a.evaluate("D.presences.fin = addDays(ymd(new Date()), 100); render(true)")
        assert a.locator("details.mois").count() >= 4
        mo = a.evaluate("addDays(ymd(new Date()), 40).slice(0, 7)")
        a.evaluate(f"""document.querySelector('details[data-keep="mois-{mo}"]').open = true""")
        n = len(sent)
        a.click(f"[data-rep-mois='{mo}']")
        wait_sent(a, n + 1)
        ops = apply(a)
        assert ops[0]["etat"] == "present" and len(ops[0]["evs"]) >= 4 and all(e[2:9] == mo or e.startswith("M-") for e in ops[0]["evs"])
        assert "tout est répondu" in a.inner_text(f"""details[data-keep="mois-{mo}"] summary""")
        # avant le début des présences (config.yml, presences.debut), rien n'est demandé
        assert a.evaluate("""(() => { const k = D.presences.debut, d = addDays(ymd(new Date()), 3); D.presences.debut = d;
          const ok = events(ymd(new Date()), addDays(d, 10)).every(e => e.day >= d) && presStart() === d; D.presences.debut = k; return ok; })()""")

        # 3. un joueur ne voit que ses réponses : ni celles des autres, ni leur nombre ; en consultation, la
        # feuille proposée ne tient compte que de la sienne
        b.evaluate("""(() => { D.agenda.push({id: "9901", date: addDays(ymd(new Date()), 10) + "T20:30", adversaire: D.saison.matchs[0].adversaire,
          domicile: true, joueurs: []}); S.tab = "presences"; render(false); })()""")
        assert b.evaluate(f"playerSays(byCle({json.dumps(k1)}), {{id: '9901', date: addDays(ymd(new Date()), 10)}})") == "attente"
        assert "mariage" not in b.inner_text("main") and "ont dit venir" not in b.inner_text("main") and "Joueur 05" not in b.inner_text("main")
        m0 = b.evaluate("PLAN[0].m.id")
        mine = b.evaluate(f"""(() => {{ const e = "M-" + {json.dumps(m0)};
          PRESJ.ops.push({{id: "t1", t: "dispo", joueur: {json.dumps(k1)}, evs: [e], etat: "absent", motif: "malade", le: new Date().toISOString()}},
                         {{id: "t2", t: "dispo", joueur: {json.dumps(k2)}, evs: [e], etat: "absent", motif: "vacances", le: new Date().toISOString()}});
          DECL = null; const r = planning()[0];
          return [availOf(byCle({json.dumps(k1)}), r.m), availOf(byCle({json.dumps(k2)}), r.m), r.sel.some(p => p.cle === {json.dumps(k2)})]; }})()""")
        assert mine == ["d", "a", False], mine

        # 4. l'entraîneur voit tout : les réponses, leurs motifs, et bouge la feuille d'un geste
        c = device("#entraineur")
        assert c.locator(".qui").count() == 0
        c.evaluate("S.tab = 'presences'; render(false)")
        assert "Les matchs" in c.inner_text("main") and "Les entraînements" in c.inner_text("main")
        board = c.evaluate(f"""(() => {{ const m = PLAN[0].m, e = "M-" + m.id, gk = D.joueurs.filter(isGK), fld = D.joueurs.filter(p => !isGK(p));
          const says = (p, etat, motif) => PRESJ.ops.push({{id: "c" + p.cle, t: "dispo", joueur: p.cle, evs: [e], etat, motif: motif || "", texte: "",
                                                            le: new Date().toISOString()}});
          gk.forEach(p => says(p, "present")); fld.slice(0, 10).forEach(p => says(p, "present")); says(fld[10], "absent", "malade");
          DECL = null; render(true); const r = PLAN[0], quiet = fld[11];
          return {{n: r.sel.length, all: r.sel.every(p => statusOf(p.cle, evMatch(m)).etat === "present"), quiet: quiet.cle,
                   out: availOf(quiet, m), nr: noAnswerOut(quiet, m), sick: fld[10].cle}}; }})()""")
        assert board["n"] == 12 and board["all"] and board["out"] == "a" and board["nr"], board
        assert "Malade" in c.inner_text(".board") and "Sans réponse" in c.inner_text(".board")
        c.click(f".board [data-sel$='|{board['quiet']}|in']")
        assert c.evaluate(f"PLAN[0].sel.some(p => p.cle === {json.dumps(board['quiet'])})") and c.evaluate("PLAN[0].sel.length") == 12
        c.click(f".board [data-sel$='|{board['quiet']}|out']")
        assert not c.evaluate(f"PLAN[0].sel.some(p => p.cle === {json.dumps(board['quiet'])})")
        # en planification, la case dit pourquoi
        c.evaluate("S.tab = 'planif'; render(false)")
        assert "il l'a dit (🤒 Malade)" in c.get_attribute(f".plan button.cell[data-cell='{m0}|{board['sick']}']", "title")
        # pas assez de réponses : comme avant, parmi tous les disponibles
        c.evaluate("PRESJ.ops = PRESJ.ops.filter(o => !String(o.id).startsWith('c')); render(true)")
        assert c.evaluate(f"availOf(byCle({json.dumps(board['sick'])}), PLAN[0].m)") == "d"
        # une séance annulée : publiée avec les choix ; plus personne n'y répond
        day = c.evaluate("events(addDays(ymd(new Date()), 1), addDays(ymd(new Date()), 8)).find(e => e.type === 'e').day")
        c.evaluate("S.tab = 'presences'; render(false)")
        c.locator(f"[data-annule='{day}']").dispatch_event("click")   # dans le tiroir de la séance
        assert c.evaluate("statusPending()") and c.evaluate(f"annuleesNow()") == [day]
        c.evaluate("localStorage.setItem('hbpsm:jeton', 'jeton-de-test')")
        before = len(sent)
        c.click("[data-publier-blessures]")
        wait_sent(c, before + 1)
        assert sent[-1]["url"].endswith("/actions/workflows/choix.yml/dispatches")
        assert choix.check(json.loads(sent[-1]["body"]["inputs"]["choix"]), PHRASE)["annulees"] == [day]

        # 5. sans réponse à temps : l'amende du règlement, proposée aux trésoriers ; à l'heure, rien ; en retard, dit
        fines = c.evaluate(f"""(() => {{ const today = ymd(new Date()); D.presences.amendes_depuis = addDays(today, -12); D.presences.debut = "";
          const past = events(addDays(today, -12), today).filter(e => e.type === "e" && deadline(e) < new Date());
          const [e1, e2] = past, k = {json.dumps(k1)};
          PRESJ.ops.push({{id: "f1", t: "dispo", joueur: k, evs: [e1.id], etat: "absent", motif: "blesse", le: new Date(deadline(e1) - 3600e3).toISOString()}},
                         {{id: "f2", t: "dispo", joueur: k, evs: [e2.id], etat: "present", le: new Date(deadline(e2).getTime() + 3600e3).toISOString()}});
          DECL = null; const F = presenceFines(ledger()).filter(f => f.joueur === k && f.regle === "e_sporteasy");
          return {{ids: F.map(f => f.id), e1: e1.id, e2: e2.id, motif: (F.find(f => f.id.includes(e2.id)) || {{}}).motif || "",
                   regle: [...new Set(F.map(f => f.regle))], n: past.length}}; }})()""")
        assert fines["n"] >= 2 and len(fines["ids"]) == fines["n"] - 1, fines
        assert not any(fines["e1"] in i for i in fines["ids"]) and "en retard" in fines["motif"] and fines["regle"] == ["e_sporteasy"]
        assert "mariage" not in json.dumps(fines) and "blesse" not in json.dumps(fines)

        # 6. l'homme du match : les joueurs de la feuille votent pendant 48 h, pas pour eux-mêmes
        ago = a.evaluate("""(() => { const d = new Date(Date.now() - 3 * 3600e3), two = n => String(n).padStart(2, "0");
          return ymd(d) + "T" + two(d.getHours()) + ":" + two(d.getMinutes()); })()""")
        hdm = json.dumps(dict(id="9902", date=ago, provisoire=False, adversaire="Equipe Fictive", domicile=False,
                              bp=30, bc=25, joueurs=[k1, k2, k3]))
        # un match d'avant la mise en place du vote (config.yml, presences.vote_depuis) : pas de vote
        assert c.evaluate(f"(() => {{ D.presences.vote_depuis = addDays(ymd(new Date()), 1); return ballot({hdm}) === null; }})()")
        for pg in (a, b, c):
            pg.evaluate(f"D.presences.vote_depuis = ''; D.agenda.push({hdm}); render(true)")
        a.evaluate("S.tab = 'moi'; render(false)")
        assert a.locator(".vote [data-vote]").count() == 2 and a.locator(f".vote [data-vote='9902|{k1}']").count() == 0
        n = len(sent)
        a.click(f".vote [data-vote='9902|{k2}']")
        wait_sent(a, n + 1)
        n = len(sent)
        assert [(o["t"], o["match"], o["pour"]) for o in apply(a, b, c)] == [("vote", "9902", k2)]
        b.evaluate("S.tab = 'presences'; render(false)")
        b.click(f".vote [data-vote='9902|{k1}']")
        wait_sent(b, n + 1)
        apply(a, b, c)
        c.evaluate(f"PRESJ.ops.push({{id: 'v3', t: 'vote', match: '9902', joueur: {json.dumps(k3)}, pour: {json.dumps(k2)}, le: new Date().toISOString()}}); DECL = null; render(true)")
        assert "2 votes sur 3" in a.inner_text(".vote") and "Joueur 06" not in a.inner_text(".vote .small.muted")
        res = c.evaluate("""(() => { const m = agendaList().find(x => x.id === "9902"), later = new Date(Date.now() + 3 * 86400e3), b = ballot(m, later);
          return {elus: b.elus, top: b.top, votants: b.votants, card: voteCard(b, ""),
                  fines: motmFines(ledger(), later).map(f => [f.regle, f.joueur, f.montant])}; })()""")
        assert res["elus"] == [k2] and res["top"] == 2 and res["votants"] == 3, res
        assert "Joueur 06" in res["card"] and "2 voix sur 3" in res["card"] and res["fines"] == [["m_mvp", k2, 2]]
        # sans feuille lue, ce sont les joueurs retenus et publiés par l'entraîneur qui votent
        assert c.evaluate(f"""(() => {{ const keep = CHOIX; CHOIX = {{matchs: {{"9903": {{joueurs: [{json.dumps(k1)}, {json.dumps(k3)}]}}}}}};
          const el = electors({{id: "9903", joueurs: []}}); CHOIX = keep; return el; }})()""") == [k1, k3]

        # téléphone : rien ne déborde
        for pg in (a, c):
            pg.set_viewport_size({"width": 360, "height": 780})
            pg.evaluate("S.tab = 'presences'; render(false)")
            assert pg.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth") <= 0
        browser.close()
    server.shutdown()
    assert errors == []


def test_debut_de_saison(sandbox):
    """Situation réelle de début de saison : un seul match, des équipes qui n'ont pas joué,
    pas de calendrier, pas de feuille."""
    common.write_json(sandbox / "data" / "fixtures.json", [dict(
        id="1", poule="71", home=demo_data.CLUB, away="Club B 2", score_home=32, score_away=19)])
    lignes = [["1", demo_data.CLUB, "3"], ["2", "Club B 2", "0"], ["3", "Club C", "0"]]
    common.write_json(sandbox / "data" / "official_standings.json",
                      {"71": dict(entetes=["#", "Équipe", "Pts"], lignes=lignes)})
    parse_fdme.main()
    d = an.analyze("2026-10-04")
    rows = d["poules"]["71"]["classement"]
    assert [(r["equipe"], r["pts"], r["j"]) for r in rows] == [
        (demo_data.CLUB, 3, 1), ("Club B 2", 1, 1), ("Club C", 0, 0)]
    assert d["poules"]["71"]["ecarts"] == [dict(equipe="Club B 2", officiel=0, calcule=1, retard=False)]
    assert d["equipes"]["Club C"]["j"] == 0 and d["equipes"]["Club B 2"]["deux_min_moy"] is None
    assert d["saison"]["statut"] == "calendrier_inconnu" and d["prochain"] is None and d["axes"] == []
    build(d, sandbox / "docs")


def test_feuille_avant_la_poule(sandbox):
    """Score connu par la feuille seule (page de la poule en cache), classement fédéral en retard,
    horaire du match suivant pas encore fixé."""
    club = demo_data.CLUB
    common.write_json(sandbox / "data" / "fixtures.json", [
        dict(id="1", poule="71", journee=1, date="2026-10-03T21:00", home=club, away="Club B",
             score_home=None, score_away=None),
        dict(id="2", poule="71", journee=2, date="2026-10-10", date_provisoire=True, home="Club B",
             away=club, score_home=None, score_away=None)])
    common.write_json(sandbox / "data" / "matches" / "1.json", dict(
        id="1", poule="71", journee=1, date="2026-10-03T21:00", played=True,
        home=dict(name=club, score=30, ht=15), away=dict(name="Club B", score=20, ht=10),
        players={"home": [], "away": []}, events=[], source=dict(fdme=True)))
    common.write_json(sandbox / "data" / "official_standings.json", {"71": dict(
        entetes=["Pos.", "Équipe", "Pts", "J"], lignes=[["1", club, "0", "0"], ["2", "Club B", "0", "0"]])})
    d = an.analyze("2026-10-03")
    assert d["prochain"]["adversaire"] == "Club B" and d["prochain"]["provisoire"]
    assert [r["dom"] for r in d["a_venir"]] == ["Club B"]
    assert all(e["retard"] for e in d["poules"]["71"]["ecarts"]) and len(d["poules"]["71"]["ecarts"]) == 2
    assert d["saison"]["restants"] == 1


def test_trois_sanctions(sandbox):
    """Carton jaune, exclusion de 2 minutes et carton rouge restent distincts, de la feuille à l'analyse."""
    assert [parse_fdme.card(v) for v in ("X", "D", "R", "1", "", "0", None)] == [1, 1, 1, 1, 0, 0, 0]
    unknown = {}
    ev = parse_fdme.parse_events("10:00 1 - 0 Carton rouge ESSAI Basile 40:00 1 - 0 Carton bleu ESSAI Basile\n"
                                 "13:00 1 - 0 Avertissement DUPONT Jean 44:00 1 - 0 Exclusion directe DUPONT Jean\n",
                                 unknown)
    assert [e["type"] for e in ev] == ["red", "yellow", "blue"] and unknown == {"EXCLUSION": 1}
    players = parse_fdme.parse_tables([FEUILLE])
    common.write_json(sandbox / "data" / "matches" / "1.json", dict(
        id="1", poule="71", journee=1, date="2026-10-03T21:00", played=True,
        home=dict(name=demo_data.CLUB, score=6, ht=3), away=dict(name="Club B", score=3, ht=2),
        players=players, events=[], source=dict(fdme=True)))
    d = an.analyze("2026-10-04")
    jean = next(p for p in d["joueurs"] if p["nom"] == "DUPONT Jean")
    basile = next(p for p in d["joueurs"] if p["nom"] == "ESSAI Basile")
    assert (jean["jaunes"], jean["deux_min"], jean["rouges"]) == (1, 0, 0)
    assert (basile["jaunes"], basile["deux_min"], basile["rouges"], basile["min_deux"]) == (0, 2, 0, 4)
    assert basile["journal"][0]["deux_min"] == 2 and jean["journal"][0]["jaunes"] == 1
    us, them = d["equipes"][demo_data.CLUB], d["equipes"]["Club B"]
    assert (us["jaunes_moy"], us["deux_min_moy"], us["rouges"]) == (1.0, 2.0, 0)
    assert (them["jaunes_moy"], them["deux_min_moy"], them["rouges"]) == (0.0, 0.0, 1)


def test_fiabilite_des_notes():
    """Une note dit sur combien de matchs elle repose : la saison passée compte pour moitié."""
    assert an.reliability(0, 0)["niveau"] == "aucune"
    assert an.reliability(1, 2) == dict(matchs=2.0, saison=1, passee=2, avant=0, niveau="fragile", poids_passee=0.5, poids_avant=0.25)
    assert an.reliability(0, 8)["niveau"] == "indicative" and an.reliability(1, 14)["niveau"] == "solide"


def test_notes_fragiles_ramenees():
    """Une note sur peu de matchs est ramenée vers la moyenne de son groupe ; une note solide bouge peu."""
    mk = lambda note, n, gk=False: dict(gardien=gk, scores={k: note for k in an.PLANS}, fiabilite=dict(matchs=n))
    solide, fragile, gb = mk(70, 10), mk(30, 1), mk(90, 1, gk=True)
    an.shrink_notes([solide, fragile, gb])
    mean = (70 * 10 + 30) / 11
    assert fragile["scores"]["equilibre"] == round(mean + (30 - mean) / 3) and fragile["scores_bruts"]["equilibre"] == 30
    assert abs(solide["scores"]["equilibre"] - 70) <= 1
    assert gb["scores"]["equilibre"] == 90  # seul gardien noté : sa propre moyenne


def test_choix_de_l_entraineur(sandbox, monkeypatch):
    """Le workflow n'écrit que des choix chiffrés avec la phrase du club, de la forme attendue."""
    monkeypatch.setattr(vault, "ITERATIONS", 2000)
    monkeypatch.setenv("HBPSM_CLE", PHRASE)
    good = dict(format="hbpsm-choix", v=1, matchs={"42": dict(joueurs=["R:EXEMPLE ISIDORE"], le="2026-10-09T20:00:00Z")})
    env = vault.encrypt(good, PHRASE, 2000)
    monkeypatch.setenv("HBPSM_CHOIX", json.dumps(dict(env, extra="ignoré")))
    assert choix.main() == 0
    written = json.loads((sandbox / "publie" / "choix.enc").read_text("utf-8"))
    assert "extra" not in written and vault.decrypt(written, PHRASE) == good
    # blessés et absents déclarés par l'entraîneur : publiés avec les feuilles
    status = dict(good, blesses={"R:EXEMPLE ISIDORE": dict(de="2026-10-10T20:30", a=None)}, absents={"42": ["R:MODELE JEAN"]})
    monkeypatch.setenv("HBPSM_CHOIX", json.dumps(vault.encrypt(status, PHRASE, 2000)))
    assert choix.main() == 0
    assert vault.decrypt(json.loads((sandbox / "publie" / "choix.enc").read_text("utf-8")), PHRASE)["absents"] == {"42": ["R:MODELE JEAN"]}
    refused = [vault.encrypt(good, "une autre phrase bien longue", 2000),             # pas la phrase du club
               vault.encrypt(dict(good, format="autre"), PHRASE, 2000),               # pas des choix
               vault.encrypt(dict(good, matchs={"1": dict(joueurs=["x"] * 20, le="")}), PHRASE, 2000),
               vault.encrypt(dict(good, blesses={"R:X": dict(de="2026-10-10", a=None, note="?")}), PHRASE, 2000),
               vault.encrypt(dict(good, absents={"42": "R:X"}), PHRASE, 2000),         # une liste attendue
               vault.encrypt(dict(good, rdv={"42": "19:15:00 trop long"}), PHRASE, 2000),
               vault.encrypt(good, PHRASE, 1000)]                                      # chiffrement affaibli
    for bad in refused:
        monkeypatch.setenv("HBPSM_CHOIX", json.dumps(bad))
        with pytest.raises(vault.VaultError):
            choix.main()
    monkeypatch.setenv("HBPSM_CHOIX", "pas du json")
    with pytest.raises(vault.VaultError):
        choix.main()


def test_coupe_collectee(monkeypatch):
    """Coupe : chaque tour est une poule d'une journée ; seuls les matchs du club sont gardés, et un
    tour clos (match joué, feuille lue) n'est plus relu."""
    row = lambda rid, home, away: dict(ext_rencontreId=rid, equipe1Libelle=home, equipe2Libelle=away,
                                       date="2026-10-17T18:00:00+02:00", fdmCode=None, equipementId=None,
                                       journeeNumero="1", equipe1Score=None, equipe2Score=None)
    tours = [dict(ext_pouleId="1", libelle="1ER TOUR", journees='[{"journee_numero":1,"date_debut":"2026-10-17","date_fin":"2026-10-18"}]'),
             dict(ext_pouleId="2", libelle="2EME TOUR", journees='[{"journee_numero":1,"date_debut":"2026-11-21","date_fin":"2026-11-22"}]')]
    page = lambda pid, rows: {"competitions---poule-selector": {"poules": tours},
                              "competitions---rencontre-list": {"poule": {"ext_pouleId": pid}, "rencontres": rows}}
    pages = []

    def fake(url, name):
        pages.append(url)
        if url.endswith("poule-2/"):
            return page("2", [row("21", "Club Ailleurs", "Club Loin")])
        return page("1", [row("11", "Club Bravo", "Club Alpha"), row("12", "Club Ailleurs", "Club Loin")])

    monkeypatch.setattr(collect, "page_data", fake)
    monkeypatch.setattr(collect, "fetch_sheets", lambda fixtures, known, now: 0)
    cup = dict(nom="Coupe de France", url="https://exemple/coupe-de-france-departementale-masculine-1/")
    ours = lambda t: t == "Club Alpha"
    got = collect.crawl_cup(cup, {}, {}, "2026-10-05T07:00", ours)
    assert list(got) == ["11"] and len(pages) == 2   # la page de la coupe montre le 1er tour ; le 2e est lu
    fx = got["11"]
    assert (fx["coupe"], fx["tour"], fx["tour_id"], fx["poule"]) == ("Coupe de France", "1ER TOUR", "1", "coupe")
    # le 1er tour joué et sa feuille lue, le 2e passé sans le club : plus rien à relire que la page d'entrée
    pages.clear()
    played = dict(fx, score_home=20, score_away=30)
    collect.crawl_cup(cup, {"11": True}, {"11": played}, "2026-11-30T07:00", ours)
    assert pages == [cup["url"]]


def test_adversaire_de_coupe_venu_d_ailleurs(monkeypatch):
    """Un adversaire de coupe d'une autre division : retrouvé dans les compétitions voisines, seuls
    ses matchs sont lus, marqués « externe » avec le nom de sa compétition."""
    voisine = {"competitions---poule-selector": {
        "phases": [{"libelle": "1ERE DIVISION MASCULINE P16 AURA"}],
        "poules": [{"id": "900", "ext_pouleId": "4242", "libelle": "POULE 6"}]},
        "competitions---calendar-button": {"equipes": [{"libelle": "CLUB LOINTAIN", "pouleId": "900"},
                                                       {"libelle": "CLUB TIERS", "pouleId": "900"}]}}
    monkeypatch.setattr(collect, "page_data", lambda url, name: voisine)
    calls = []

    def poule(p, known, old, now, is_ours=None, only=None):
        calls.append(p)
        rows = [dict(id="1", home="CLUB LOINTAIN", away="CLUB TIERS"), dict(id="2", home="CLUB TIERS", away="CLUB AUTRE")]
        return {r["id"]: r for r in rows if only(r)}, {"entetes": [], "lignes": []}

    monkeypatch.setattr(collect, "crawl_poule", poule)
    config = dict(common.load_config(), voisines=[{"url": "https://exemple/1ere-division-1/", "niveau": 1}])
    club = config["club"]["motifs"][0]
    old = {"c1": dict(id="c1", coupe="Coupe de France", home="CLUB LOINTAIN", away=club),
           "l1": dict(id="l1", poule="71", home=club, away="CLUB BRAVO")}
    fixtures, officials = collect.crawl_rivals(config, {}, old, "2026-10-05T07:00")
    assert calls[0]["id"] == "ext-4242" and calls[0]["url"] == "https://exemple/1ere-division-1/poule-4242/"
    assert list(fixtures) == ["1"] and fixtures["1"]["externe"] == "1re division masculine P16 AURA, poule 6"
    assert fixtures["1"]["niveau"] == 1 and list(officials) == ["ext-4242"]
    # une compétition voisine donnée par sa seule adresse : notre niveau
    assert collect.crawl_rivals(dict(config, voisines=["https://exemple/1ere-division-1/"]), {}, old, "2026-10-05T07:00")[0]["1"]["niveau"] == 0
    # un adversaire de coupe déjà dans nos poules n'est pas recherché ailleurs
    calls.clear()
    old["c1"]["home"] = "CLUB BRAVO"
    assert collect.crawl_rivals(config, {}, old, "2026-10-05T07:00") == ({}, {}) and calls == []


def test_coupe_dans_la_saison(sandbox):
    """Un match de coupe : hors classement, dans les statistiques des joueurs, dans les matchs à venir."""
    demo(sandbox)
    before = an.analyze("2026-10-04")
    matches = sandbox / "data" / "matches"
    club_match = next(json.loads(f.read_text("utf-8")) for f in sorted(matches.glob("*.json"))
                      if demo_data.CLUB in (json.loads(f.read_text("utf-8"))["home"]["name"],
                                            json.loads(f.read_text("utf-8"))["away"]["name"])
                      and json.loads(f.read_text("utf-8"))["players"]["home"])
    side = "home" if club_match["home"]["name"] == demo_data.CLUB else "away"
    other = "away" if side == "home" else "home"
    cup_played = dict(club_match, id="9001", poule="coupe", journee=None, date="2026-09-20T18:00",
                      coupe="Coupe de France", tour="1ER TOUR")
    cup_played[other] = dict(club_match[other], name="Club Lointain")
    common.write_json(matches / "9001.json", cup_played)
    fixtures = json.loads((sandbox / "data" / "fixtures.json").read_text("utf-8"))
    base = dict(poule="coupe", coupe="Coupe de France", journee=None, score_home=None, score_away=None)
    fixtures.append(dict(base, id="9001", tour="1ER TOUR", date="2026-09-20T18:00",
                         home=cup_played["home"]["name"], away=cup_played["away"]["name"],
                         score_home=cup_played["home"]["score"], score_away=cup_played["away"]["score"]))
    fixtures.append(dict(base, id="9002", tour="2EME TOUR", date="2026-10-24T18:00", home="Club Lointain 2", away=demo_data.CLUB))
    common.write_json(sandbox / "data" / "fixtures.json", fixtures)
    d = an.analyze("2026-10-04")
    # hors classement : ni poule, ni résultat, ni adversaire nouveau dans les équipes
    assert "coupe" not in d["poules"] and all(r["id"] != "9001" for r in d["resultats"])
    assert d["equipes"]["Club Lointain"]["coupe"] and d["equipes"]["Club Lointain"]["j"] == 0  # sa fiche, vide pour l'instant
    assert d["poules"] == before["poules"]
    # dans les statistiques : chaque joueur de la feuille compte un match de plus
    m_before = {p["cle"]: p["m"] for p in before["joueurs"]}
    on_sheet = {p["name"] for p in club_match["players"][side]}
    assert any(p["m"] == m_before.get(p["cle"], 0) + 1 for p in d["joueurs"])
    assert d["meta"]["club_feuilles"] == before["meta"]["club_feuilles"] + 1 and on_sheet
    # dans les matchs à venir, à sa date : pas d'enjeu, jamais match clé
    cup = next(m for m in d["saison"]["matchs"] if m.get("coupe"))
    assert (cup["id"], cup["tour"], cup["enjeu"], cup["cle"], cup["journee"]) == ("9002", "2EME TOUR", None, False, None)
    assert cup["effectif"] == 14   # 14 joueurs sur la feuille en Coupe de France (config.yml, règlement)
    assert all(m.get("effectif") is None for m in d["saison"]["matchs"] if not m.get("coupe"))
    dates = [m["date"] for m in d["saison"]["matchs"]]
    assert dates == sorted(dates)
    assert [c["id"] for c in d["coupes"]] == ["9001", "9002"] and d["coupes"][0]["res"] in "VND"
    # l'adversaire du 2e tour joue ailleurs : un de ses matchs, lu dans sa poule, lui fait une fiche
    label = "1re division masculine P16 AURA, poule 6"
    away = dict(club_match, id="9101", poule="ext-4242", journee=1, date="2026-09-27T20:00", externe=label)
    away["home"] = dict(club_match["home"], name="Club Lointain 2")
    away["away"] = dict(club_match["away"], name="Club Tiers")
    common.write_json(matches / "9101.json", away)
    fixtures.append(dict(id="9101", poule="ext-4242", externe=label, journee=1, date=away["date"], home="Club Lointain 2",
                         away="Club Tiers", score_home=away["home"]["score"], score_away=away["away"]["score"]))
    common.write_json(sandbox / "data" / "fixtures.json", fixtures)
    d2 = an.analyze("2026-10-04")
    rival = d2["equipes"]["Club Lointain 2"]
    assert rival["poule_libelle"] == label and rival["coupe"] and rival["j"] == 1
    assert "Club Tiers" not in d2["equipes"] and d2["poules"] == d["poules"] and d2["resultats"] == d["resultats"]


def test_caisse_registre(sandbox, monkeypatch):
    """Le workflow « Caisse noire » ajoute au registre chiffré les saisies des trésoriers : une
    saisie renvoyée n'est comptée qu'une fois, une saisie malformée ou mal chiffrée est refusée."""
    monkeypatch.setattr(vault, "ITERATIONS", 2000)
    monkeypatch.setenv("HBPSM_CLE", PHRASE)
    fine = dict(id="a1", t="amende", joueur="R:EXEMPLE ISIDORE", regle="m_oubli", n=2, montant=4,
                date="2026-10-10", note="veste du club", par="R:MODELE JEAN", le="2026-10-10T20:00:00Z")
    pay = dict(id="p1", t="paiement", joueur="R:EXEMPLE ISIDORE", montant=4, par="R:MODELE JEAN", le="2026-10-12T19:00:00Z")
    send = lambda ops, phrase=PHRASE: monkeypatch.setenv("HBPSM_CAISSE", json.dumps(vault.encrypt(
        dict(format="hbpsm-caisse-ops", v=1, ops=ops), phrase, 2000)))
    send([fine])
    assert caisse.main() == 0
    send([fine, pay])   # la première saisie, renvoyée, n'est pas comptée deux fois
    assert caisse.main() == 0
    book = vault.decrypt(json.loads((sandbox / "publie" / "caisse.enc").read_text("utf-8")), PHRASE)
    assert [o["id"] for o in book["ops"]] == ["a1", "p1"]
    for bad in ([dict(fine, id="a2", regle="inventee")], [dict(fine, id="a3", montant=1000)], [dict(pay, id="p2", t="vol")]):
        send(bad)
        with pytest.raises(vault.VaultError):
            caisse.main()
    send([dict(fine, id="a4")], "une autre phrase bien longue")
    with pytest.raises(vault.VaultError):
        caisse.main()
    # reprise d'un état tenu ailleurs : par un secret temporaire, vérifiée, sans doublon ; rien sans secret
    monkeypatch.delenv("HBPSM_CAISSE_IMPORT", raising=False)
    assert caisse.import_main() == 0
    reprise = dict(format="hbpsm-caisse-ops", v=1, ops=[dict(fine, id="imp:1"), dict(pay, id="imp:2"), dict(fine, id="a1")])
    monkeypatch.setenv("HBPSM_CAISSE_IMPORT", json.dumps(reprise))
    assert caisse.import_main() == 0 and caisse.import_main() == 0
    book = vault.decrypt(json.loads((sandbox / "publie" / "caisse.enc").read_text("utf-8")), PHRASE)
    assert [o["id"] for o in book["ops"]] == ["a1", "p1", "imp:1", "imp:2"]
    monkeypatch.setenv("HBPSM_CAISSE_IMPORT", json.dumps(dict(reprise, ops=[dict(fine, id="imp:3", regle="inventee")])))
    with pytest.raises(vault.VaultError):
        caisse.import_main()


def test_caisse_propositions():
    """D'après la feuille : 2e et 3e exclusions, rouge direct, moins de 40 % au tir, dernier but,
    victoire de +20 ; et la cotisation de chacun. Chaque proposition cite son point du règlement."""
    players = [dict(name="Isidore EXEMPLE", num=7, goals=1, shots=5, two_min=3, red=1),
               dict(name="Jean MODELE", num=9, goals=6, shots=8, two_min=0, red=1),
               dict(name="Basile TIREUR", num=10, goals=4, shots=6, two_min=2, red=0)]
    m = dict(id="m1", date="2026-10-10T20:30", players={"home": players, "away": []},
             events=[dict(t=100, side="home", type="goal", num=9), dict(t=3500, side="home", type="goal", num=10)])
    roster = {an.name_key("Isidore Exemple"): dict(nom="Isidore Exemple")}
    props = caisse.proposals([(m, "home", "Club Bravo", 41, 20)], roster, ["R:" + an.name_key("Isidore Exemple")], "2026-2027")
    by = {(p["regle"], p["joueur"]): p for p in props}
    isidore = "R:" + an.name_key("Isidore Exemple")
    assert {r for r, j in by if j == isidore} == {"m_2e_2min", "m_3x2min", "m_precision", "cotisation"}
    assert ("m_expulsion", an.name_key("Jean MODELE")) in by          # rouge sans trois exclusions
    assert ("m_2e_2min", an.name_key("Basile TIREUR")) in by and ("m_heros", an.name_key("Basile TIREUR")) in by
    assert ("m_fessee", caisse.COACH) in by and by[("m_fessee", caisse.COACH)]["montant"] is None
    assert by[("m_3x2min", isidore)]["montant"] == 5 and by[("m_precision", isidore)]["motif"].startswith("1 but sur 5 tirs (20 %)")
    assert all(p["regle"] in caisse.RULES and p["id"] for p in props) and len({p["id"] for p in props}) == len(props)
    # la feuille ne dit pas qu'un 7 m est manqué : une vérification par match, avec les joueurs de la feuille
    check = next(p for p in props if p.get("check"))
    assert (check["id"], check["regle"], check["tireurs"], len(check["feuille"])) == ("m_penalty:m1:check", "m_penalty", [], 3)


def test_noms_ancienne_feuille():
    """Ancienne feuille : nom et prénom collés, nom parfois répété après le prénom, prénom en minuscules."""
    cases = {"DUPONTjean-DUPONT": "DUPONT Jean", "MARTIN-DUPRÉlouis-hilarion": "MARTIN-DUPRÉ Louis-Hilarion",
             "DE LA TOURonesime-DE LA TOUR": "DE LA TOUR Onesime", "DUPONT Jean": "DUPONT Jean", "Jean DUPONT": "Jean DUPONT"}
    assert {k: parse_fdme.split_name(k) for k in cases} == cases


def test_effectif_depannage(sandbox):
    """Dans l'effectif, « dépannage » : disponible, mais seulement s'il manque des joueurs."""
    (sandbox / "roster.csv").write_text("nom,poste,disponible\nIsidore Exemple,PIV,dépannage\n"
                                        "Jean Modele,GB,\nOctave Blesse,DC,non\n", "utf-8")
    r = {v["nom"]: v for v in an.load_roster().values()}
    assert r["Isidore Exemple"]["disponible"] and r["Isidore Exemple"]["depannage"]
    assert r["Jean Modele"]["disponible"] and not r["Jean Modele"]["depannage"]
    assert not r["Octave Blesse"]["disponible"] and not r["Octave Blesse"]["depannage"]


def test_heure_de_paris():
    """Heures et dates sont celles de Paris, même sur une machine en UTC (runner GitHub)."""
    now = common.paris_now()
    assert now.utcoffset() in (dt.timedelta(hours=1), dt.timedelta(hours=2))
    assert common.PARIS.utcoffset(dt.datetime(2026, 7, 1, 12)) == dt.timedelta(hours=2)
    assert common.PARIS.utcoffset(dt.datetime(2027, 1, 15, 12)) == dt.timedelta(hours=1)


def test_gardiens_et_tirs(sandbox):
    """Buts pris et % d'arrêts des gardiens, tirs et réussite des joueurs, pour le club et l'adversaire."""
    save = lambda t, num: dict(t=t, side="home", type="save", num=num, score=[0, 0])
    goal = lambda t: dict(t=t, side="away", type="goal", num=4, score=[0, 0])
    match = dict(home=dict(score=10), away=dict(score=5), players={"home": [
        dict(num=1, saves=2), dict(num=16, saves=2), dict(num=7, saves=0)], "away": []},
        events=[goal(300), save(600, 1), goal(900), save(1200, 1), goal(1700),
                goal(1900), save(2000, 16), save(2500, 16), goal(3000)])
    # avant le premier arrêt d'une mi-temps : le prochain gardien de cette mi-temps
    assert an.keepers_conceded(match, "home") == ({1: 3, 16: 2}, True)
    match["players"]["home"] = [dict(num=1, saves=4)]
    assert an.keepers_conceded(match, "home") == ({1: 5}, False)
    match["players"]["home"], match["events"] = [dict(num=1, saves=2), dict(num=16, saves=2)], []
    assert an.keepers_conceded(match, "home") == ({}, True)  # deux gardiens sans déroulé : inconnu
    # l'ancienne feuille dit qui entre et sort des buts : exact, et rien pour le but vide (jeu à 7)
    change = lambda t, typ, num: dict(t=t, side="home", type=typ, num=num, score=[0, 0])
    match["events"] = [change(0, "gk_in", 1), goal(300), save(600, 1), change(1500, "gk_out", 1), goal(1600),
                       change(1700, "gk_in", 16), goal(1900), save(2000, 16), goal(2500), goal(3000)]
    assert an.keepers_conceded(match, "home") == ({1: 1, 16: 3}, False)
    assert [parse_fdme.match_action(x)[1] for x in ("ENTREEGARDIEN", "SORTIE GARDIEN")] == ["gk_in", "gk_out"]
    assert all(parse_fdme.match_action(x)[1] is None for x in ("PROTOCOLECOMMOTION", "TEMPSDEREGULATIONCOMPORTEMENTAL"))
    common.write_json(sandbox / "data" / "matches" / "1.json", dict(
        id="1", poule="71", journee=1, date="2026-10-03T21:00", played=True,
        home=dict(name=demo_data.CLUB, score=6, ht=3), away=dict(name="Club B", score=3, ht=2),
        players=parse_fdme.parse_tables([FEUILLE]), events=[], source=dict(fdme=True)))
    d = an.analyze("2026-10-04")
    gk = next(p for p in d["joueurs"] if p["nom"] == "GARDIEN Alpha")
    assert gk["gardien"] and (gk["arrets"], gk["pris"], gk["tirs_subis"], gk["pct_arrets"]) == (9, 3, 12, 75)
    assert gk["journal"][0]["pct"] == 75 and not gk["pris_estime"]
    jean = next(p for p in d["joueurs"] if p["nom"] == "DUPONT Jean")
    assert (jean["buts"], jean["tirs"], jean["reussite"]) == (4, 5, 80) and jean["journal"][0]["tirs"] == 5
    them = d["equipes"]["Club B"]
    assert them["arrets_pct"] == 25 and them["gardiens"][0]["num"] == 16 and them["gardiens"][0]["pris"] == 6
    assert next(b for b in them["buteurs"] if b["num"] == 4)["reussite"] == 60


def test_seance_publique_sans_nom(sandbox, monkeypatch):
    """La séance publiée en clair pour HANDBALL-training est refusée si un nom de joueur s'y glisse."""
    monkeypatch.setattr(vault.encrypt, "__defaults__", (2000,))
    monkeypatch.setenv("HBPSM_CLE", PHRASE)
    demo(sandbox)
    (sandbox / "roster.csv").write_text("nom,poste,disponible\nIsidore Exemple,GB\n", "utf-8")
    publish.seal("2026-10-04")  # rien de nominatif : publiée
    assert (sandbox / "publie" / publish.SEANCE_NAME).exists()
    names = publish.known_names(publish.collect_state(), (sandbox / "roster.csv").read_text("utf-8"))
    assert "ISIDORE EXEMPLE" in names and any(n.startswith("FICTIF") for n in names)
    publish.check_public('{"objectif": "Rien que des numéros : n° 12"}', names)
    for fuite in ('{"objectif": "Surveiller EXEMPLE Isidore"}', '{"titre": "Joueur 03 en forme"}'):
        with pytest.raises(vault.VaultError):
            publish.check_public(fuite, names)


def test_division_du_dessus():
    """Une équipe de la division du dessus la saison passée compte plus forte, d'autant plus qu'elle a
    gardé ses joueurs ; l'équipe 2 d'un club n'est pas son équipe 1 ; un adversaire de coupe d'une
    division au-dessus fait une victoire estimée plus basse."""
    assert not common.same_team("CLUB ALPHA 2", "P16M DIV1 - CLUB ALPHA")
    assert common.same_team("P16M DIV - CLUB ALPHA- 2", "CLUB ALPHA 2 (FG)") and common.same_team("HBC ALPHA-2", "HBC ALPHA 2")
    config = dict(common.load_config(), ecart_division=0.12)
    pl = lambda *names: [dict(name=n, num=i + 1, goals=1) for i, n in enumerate(names)]
    game = lambda h, a, ph=(), pa=(): dict(home=dict(name=h, score=25), away=dict(name=a, score=25),
                                           players=dict(home=list(ph), away=list(pa)), date="2025-11-01")
    ours = dict(saison="2025-2026", competition="https://exemple/2eme-division-masculine-1/", poules={},
                matches=[game("CLUB BRAVO", "CLUB CHARLIE"), game("CLUB ECHO", "CLUB CHARLIE")])
    above = dict(saison="2025-2026", niveau=1, competition="https://exemple/1ere-division-masculine-2/", poules={},
                 matches=[game("CLUB DELTA", "CLUB ECHO", pl("Zéphyrin Alpha", "Onésime Beta"), pl("Hilarion Gamma")),
                          game("CLUB ECHO", "CLUB DELTA", pl("Hilarion Gamma"), pl("Zéphyrin Alpha", "Onésime Beta"))])
    # cette saison, Delta a gardé ses deux joueurs ; Echo, sans feuille, a joué dans les deux divisions ;
    # Foxtrot, nouvelle entente, réunit un joueur d'Echo et un inconnu
    now = [game("CLUB DELTA", "CLUB BRAVO", pl("Zéphyrin Alpha", "Onésime Beta"), pl("Eudes Gamma")),
           game("CLUB FOXTROT", "CLUB BRAVO", pl("Hilarion Gamma", "Aristide Beta"))]
    profiles = {t: {} for t in ("CLUB BRAVO", "CLUB DELTA", "CLUB ECHO", "CLUB FOXTROT")}
    priors = an.history_profiles([ours], profiles, now, config, [above])
    assert profiles["CLUB FOXTROT"]["passe"] is None and priors["CLUB FOXTROT"] == pytest.approx((1.12, 1 / 1.12, 0.5))
    assert profiles["CLUB FOXTROT"]["origines"] == dict(saison="2025-2026", vus=2, retrouves=1, equipes=[
        dict(equipe="CLUB ECHO", niveau=1, division="1re division", joueurs=1)])
    assert priors["CLUB BRAVO"] == (1.0, 1.0, 0.5) and profiles["CLUB BRAVO"]["dessus"] is None
    assert priors["CLUB DELTA"] == pytest.approx((1.12, 1 / 1.12, 1.0))
    delta = profiles["CLUB DELTA"]["passe"]
    assert (delta["niveau"], delta["division"], delta["continuite"]) == (1, "1re division", {"deja": 2, "sur": 2})
    assert priors["CLUB ECHO"] == pytest.approx(((1 + 1.12) / 2, (1 + 1 / 1.12) / 2, 0.5))   # les deux bilans, à poids égal
    assert profiles["CLUB ECHO"]["passe"]["niveau"] == 0 and profiles["CLUB ECHO"]["dessus"]["niveau"] == 1
    # en coupe : le même bilan vaut moins de chances face à une équipe de la division du dessus
    forces, prof = {"CLUB BRAVO": [1.0, 1.0]}, dict(j=4, bp_moy=25.0, bc_moy=25.0)
    same_div = an.cup_chance(forces, 25.0, "CLUB BRAVO", prof, 0, 1.12)
    above_div = an.cup_chance(forces, 25.0, "CLUB BRAVO", prof, 1, 1.12)
    assert 45 <= same_div <= 65 and above_div <= same_div - 15
    assert an.cup_chance({}, 25.0, "CLUB BRAVO", prof, 1, 1.12) is None


def test_saison_d_avant(sandbox):
    """La saison d'avant (2024-2025) complète les chiffres de nos joueurs, pour un quart de match."""
    assert an.reliability(2, 4, 8) == dict(matchs=6.0, saison=2, passee=4, avant=8, niveau="solide", poids_passee=0.5, poids_avant=0.25)
    # les saisons passées s'effacent à mesure que la saison avance
    assert an.fade(0) == 1 and an.HIST * an.fade(6) == 0.25 and an.fade(12) < an.fade(6) < an.fade(1)
    assert an.reliability(2, 4, 8, an.HIST * an.fade(6), an.HIST2 * an.fade(6))["matchs"] == 4.0
    m = an.merged(dict(an.EMPTY, m=2, buts=4, w=1.0, w_buts=2.0), dict(an.EMPTY, m=4, buts=8, w=0.5, w_buts=1.0))
    assert (m["m"], m["buts"], m["w"], m["w_buts"]) == (4.0, 8.0, 1.5, 3.0)
    demo(sandbox)
    club = [json.loads(f.read_text("utf-8")) for f in sorted((sandbox / "data" / "matches").glob("*.json"))]
    club = [x for x in club if demo_data.CLUB in (x["home"]["name"], x["away"]["name"]) and x["players"]["home"]]
    older = [dict(x, id="old" + str(x["id"]), date="2024-11-0" + str(i + 1), saison="2024-2025") for i, x in enumerate(club[:3])]
    common.write_json(sandbox / "data" / "historique" / "2024-2025-niveau1.json",
                      dict(saison="2024-2025", niveau=1, competition="https://exemple/1ere-division-masculine-1/", poules={}, matches=older))
    common.write_json(sandbox / "data" / "historique" / "2025-2026.json",
                      dict(saison="2025-2026", competition="https://exemple/2eme-division-masculine-1/", poules={}, matches=[]))
    d = an.analyze("2026-10-04")
    seen = [p for p in d["joueurs"] if p.get("avant")]
    assert seen and all(p["avant"]["saison"] == "2024-2025" and p["avant"]["m"] >= 1 for p in seen)
    assert all(p["fiabilite"]["avant"] == p["avant"]["m"] for p in seen)
    assert any("2024-2025" in (p.get("note_base") or "") for p in seen)


def test_saison_plus_ancienne_pour_un_joueur_revenu(sandbox):
    """Une saison plus ancienne (2023-2024) donne une note au joueur revenu au club, sans aucun match
    plus récent ; elle ne touche pas aux autres, et ne se mêle pas à la saison d'avant (2024-2025)."""
    demo(sandbox)
    club = [json.loads(f.read_text("utf-8")) for f in sorted((sandbox / "data" / "matches").glob("*.json"))]
    club = [x for x in club if demo_data.CLUB in (x["home"]["name"], x["away"]["name"]) and x["players"]["home"]]
    side = lambda x: "home" if x["home"]["name"] == demo_data.CLUB else "away"
    older = [dict(x, id="old" + str(x["id"]), date="2024-11-0" + str(i + 1), saison="2024-2025") for i, x in enumerate(club[:2])]
    ancient = []
    for i, x in enumerate(club[:2]):
        y = json.loads(json.dumps(x))
        y.update(id=f"anc-{i}", date=f"2023-11-0{i + 1}", saison="2023-2024")
        y["players"][side(y)] = [dict(y["players"][side(y)][0], name="REVENU Onésime", goals=0, saves=12, num=16)] + y["players"][side(y)][1:]
        ancient.append(y)
    for name, saison, matches in (("2024-2025-niveau1", "2024-2025", older), ("2023-2024-niveau2", "2023-2024", ancient)):
        common.write_json(sandbox / "data" / "historique" / f"{name}.json",
                          dict(saison=saison, niveau=1, competition="https://exemple/1ere-division-masculine-1/", poules={}, matches=matches))
    common.write_json(sandbox / "data" / "historique" / "2025-2026.json",
                      dict(saison="2025-2026", competition="https://exemple/2eme-division-masculine-1/", poules={}, matches=[]))
    regular = club[0]["players"][side(club[0])][1]["name"]
    roster = {common.name_key(n): dict(nom=n, poste="GB" if n == "Onésime Revenu" else "", disponible=True)
              for n in ("Onésime Revenu", regular)}
    d = an.analyze("2026-10-04", roster=roster)
    back = next(x for x in d["joueurs"] if x["nom"] == "Onésime Revenu")
    assert back["m"] == 0 and back["ancienne"]["saison"] == "2023-2024" and back["ancienne"]["m"] == 2
    assert back["ancienne"]["arrets"] == 24 and back["scores"]["equilibre"] is not None and back["avant"] is None
    assert back["fiabilite"]["avant"] == 2 and "2023-2024" in back["note_base"]
    others = [x for x in d["joueurs"] if x["nom"] != "Onésime Revenu"]
    assert all(not x.get("ancienne") for x in others)   # les autres : rien de 2023-2024
    assert all(x["avant"]["saison"] == "2024-2025" for x in others if x.get("avant"))


def test_experience_et_tranches_d_age(sandbox):
    """L'expérience au club (matchs depuis 2015, comptés davantage plus haut) entre pour une part dans la
    note, sans être affichée ; les tranches d'âge de 5 ans se lisent dans l'effectif, les anciens mots aussi."""
    assert [an.age_class(x) for x in ("18-22", " 23 - 27 ", "jeune", "Expérimenté", "", "x")] \
        == ["18-22", "23-27", "jeune", "experimente", None, None]
    demo(sandbox)
    before = {x["cle"]: x for x in an.analyze("2026-10-04")["joueurs"]}
    club = [json.loads(f.read_text("utf-8")) for f in sorted((sandbox / "data" / "matches").glob("*.json"))]
    club = [x for x in club if demo_data.CLUB in (x["home"]["name"], x["away"]["name"]) and x["players"]["home"]][:2]
    old = [dict(x, id="exc" + str(x["id"]), date=f"2021-11-0{i + 1}", saison="2021-2022") for i, x in enumerate(club)]
    side = lambda x: "home" if x["home"]["name"] == demo_data.CLUB else "away"
    config = common.load_config()
    counts = an.experience_of([], [dict(matches=old, niveau=3)], config)
    # saison sans feuilles (avant 2018-2019) : les matchs de la page « statistiques » de la poule
    from pipeline import history
    rows = history.club_rows(dict(rowsData=[dict(nom="EXEMPLE", prenom="ISIDORE", matchCount="12", totalButs="30",
                                                 equipeLibelle=demo_data.CLUB),
                                            dict(nom="AUTRE", prenom="JOUEUR", matchCount="9", equipeLibelle="CLUB BRAVO")]),
                             lambda t: common.is_club(t, config))
    assert rows == [dict(name="EXEMPLE ISIDORE", m=12, buts=30, arrets=0)]
    assert an.experience_of([], [dict(matches=[], joueurs_club=rows, niveau=4)], config) \
        == {common.name_key("Isidore Exemple"): 12 * (1 + 4 * an.EXP_NIVEAU)}
    first = common.name_key(club[0]["players"][side(club[0])][0]["name"])
    assert counts[first] == (1 + 3 * an.EXP_NIVEAU) * sum(
        1 for x in old if first in {common.name_key(q["name"]) for q in x["players"][side(x)]})
    common.write_json(sandbox / "data" / "historique" / "2021-2022-niveau3.json",
                      dict(saison="2021-2022", niveau=3, competition="https://exemple/excellence-1/", poules={}, matches=old))
    common.write_json(sandbox / "data" / "historique" / "2025-2026.json",
                      dict(saison="2025-2026", competition="https://exemple/2eme-division-masculine-1/", poules={}, matches=[]))
    after = {x["cle"]: x for x in an.analyze("2026-10-04")["joueurs"]}
    keys = {common.name_key(q["name"]) for x in old for q in x["players"][side(x)]} & set(before) & set(after)
    assert keys and all(after[k]["comps"]["exp"] > before[k]["comps"]["exp"] for k in keys)
    assert all(after[k]["scores_bruts"]["equilibre"] >= before[k]["scores_bruts"]["equilibre"] for k in keys)
    assert all(after[k]["comps"]["exp"] == before[k]["comps"]["exp"] for k in set(before) - keys if k in after)
    template = (ROOT_DIR / "dashboard" / "template.html").read_text("utf-8")
    shown = next(l for l in template.splitlines() if l.startswith("const COMP_NOM"))
    assert "exp:" not in shown and "xpérience" not in shown   # jamais affichée


def test_avis_de_l_auteur(sandbox):
    """L'avis de l'auteur (1 à 5 étoiles) compte pour un quart de la note d'un joueur, sans être affiché ;
    sans avis, rien ne change. Les fins de match restent neutres tant que personne n'a d'action décisive."""
    assert [an.opinion(x) for x in ("5", " 3 ", "0", "6", "", "x")] == [5, 3, None, None, None, None]
    demo(sandbox)
    club = [json.loads(f.read_text("utf-8")) for f in sorted((sandbox / "data" / "matches").glob("*.json"))]
    club = [x for x in club if demo_data.CLUB in (x["home"]["name"], x["away"]["name"]) and x["players"]["home"]]
    side = "home" if club[0]["home"]["name"] == demo_data.CLUB else "away"
    names = [q["name"] for q in club[0]["players"][side][1:3]]
    roster = {common.name_key(n): dict(nom=n, poste="", disponible=True) for n in names}
    base = {x["nom"]: x for x in an.analyze("2026-10-04", roster=roster)["joueurs"]}
    roster[common.name_key(names[0])]["avis"] = 5
    rated = {x["nom"]: x for x in an.analyze("2026-10-04", roster=roster)["joueurs"]}
    raw0, raw1 = base[names[0]]["scores_bruts"]["equilibre"], rated[names[0]]["scores_bruts"]["equilibre"]
    assert abs(raw1 - round(100 * ((1 - an.AVIS_POIDS) * raw0 / 100 + an.AVIS_POIDS))) <= 1
    assert rated[names[1]]["scores_bruts"] == base[names[1]]["scores_bruts"]   # sans avis : inchangé
    assert all(0 <= x["comps"]["clutch"] <= 1 for x in rated.values())
    template = (ROOT_DIR / "dashboard" / "template.html").read_text("utf-8")
    assert "avis" not in next(l for l in template.splitlines() if l.startswith("const COMP_NOM"))


def test_parler_en_buts(sandbox):
    """En buts plutôt qu'en pourcentages : buts évités par un gardien face au gardien moyen, coût d'une
    exclusion de 2 minutes, écart attendu de chaque match."""
    assert an.goals_saved(dict(cadres=100, pris=60, m=5), 0.3, "2025-2026") == dict(
        saison="2025-2026", tirs=100, valeur=10, par_match=2.0, moyenne=30)
    assert an.goals_saved(dict(cadres=50, pris=30, m=3), 0.3, "2025-2026") is None   # trop peu de tirs
    # cette saison et la passée cumulées, la passée comptant à moitié ; marge à 95 %
    mix = an.goals_saved_mix(dict(cadres=40, pris=24, m=2), dict(cadres=200, pris=130, m=10), 0.3, 0.3, 0.5, ("2026-2027", "2025-2026"))
    assert mix["tirs"] == 140 and mix["valeur"] == round(4 + 0.5 * 10) and mix["par_match"] == round(9 / 7, 1)
    assert mix["marge"] > 0 and [x["saison"] for x in mix["detail"]] == ["2026-2027", "2025-2026"]
    assert an.goals_saved_mix(dict(cadres=20, pris=12, m=1), None, 0.3, 0.3, 0.5, ("2026-2027", None)) is None
    config = common.load_config()
    club = config["club"]["motifs"][0]
    events = [dict(t=100, side="home", type="goal"), dict(t=600, side="home", type="two_min"),
              dict(t=650, side="away", type="goal"), dict(t=700, side="away", type="pen_goal"),
              dict(t=2000, side="home", type="goal")]
    match = dict(id="x", date="2026-01-01", home=dict(name=club, score=2), away=dict(name="CLUB BRAVO", score=2), events=events)
    assert an.exclusion_cost([match], config) == (-2.0, 1)   # deux buts pris pendant l'exclusion, rythme du match nul
    demo(sandbox)
    d = an.analyze("2026-10-04")
    assert 0 < an.league_save_rate([json.loads(f.read_text("utf-8")) for f in (sandbox / "data" / "matches").glob("*.json")]) < 1
    m = d["saison"]["matchs"][0]
    assert m["ecart"] is not None and m["buts_pour"] > 0 and isinstance(d["meta"]["exclusion"], dict)


def test_anniversaires(sandbox):
    """Caisse noire : le jour d'anniversaire de chacun (jamais l'année), entraîneur compris, sans en faire un joueur."""
    assert an.birthday("2006-09-20") == "09-20" and an.birthday("20/09") == "09-20" and an.birthday("09-20") == "09-20"
    assert an.birthday("") is None and an.birthday("31/13") is None
    (sandbox / "roster.csv").write_text("nom,poste,disponible,role,age,naissance\nIsidore Exemple,GB,,,,03-14\n"
                                        "Jean Modele,ARG,,hors caisse,,\nZéphyrin,,,coach,,12-25\n", "utf-8")
    roster = an.load_roster()
    assert sorted(v["nom"] for v in roster.values()) == ["Isidore Exemple", "Jean Modele"]   # l'entraîneur n'est pas un joueur
    # hors caisse : un joueur qui ne participe pas à la caisse noire (pas de cotisation à lui demander)
    assert [roster[common.name_key(n)]["hors_caisse"] for n in ("Isidore Exemple", "Jean Modele")] == [False, True]
    caisse_page = an.analyze("2026-10-04", roster=roster)["caisse"]
    assert caisse_page["hors"] == ["R:" + common.name_key("Jean Modele")]
    assert {p["joueur"] for p in caisse_page["propositions"] if p["regle"] == "cotisation"} == {"R:" + common.name_key("Isidore Exemple"), caisse.COACH}
    assert an.birthdays(caisse.COACH) == [dict(cle="R:" + common.name_key("Isidore Exemple"), jour="03-14"),
                                          dict(cle=caisse.COACH, jour="12-25")]


def test_disponible_jusqu_a_une_date(sandbox):
    """Un joueur qui ne reste pas toute la saison : le dernier jour où il est disponible (fin du mois si
    seul le mois est donné), repris sur sa fiche pour la page."""
    assert [an.until(x) for x in ("2027-04", "04/2027", "2027-04-15", "15/04/2027", "2027-02", "", "2027-13")] \
        == ["2027-04-30", "2027-04-30", "2027-04-15", "2027-04-15", "2027-02-28", None, None]
    (sandbox / "roster.csv").write_text("nom,poste,disponible,role,age,naissance,jusqu_au\nIsidore Exemple,GB,,,intermediaire,,2027-04\n"
                                        "Jean Modele,ARG,,,,\n", "utf-8")
    roster = an.load_roster()
    assert [roster[common.name_key(n)]["jusqu_au"] for n in ("Isidore Exemple", "Jean Modele")] == ["2027-04-30", None]
    players, _, _ = an.club_players([], {}, roster)
    assert {x["nom"]: x["jusqu_au"] for x in players} == {"Isidore Exemple": "2027-04-30", "Jean Modele": None}


def test_jeunes_pour_un_joueur_sans_match_senior(sandbox):
    """Les matchs de nos moins de 18 ans donnent une note au joueur de l'effectif qui n'a aucun match
    senior ; ils ne touchent pas aux autres, ni à la force des adversaires."""
    demo(sandbox)
    club = [json.loads(f.read_text("utf-8")) for f in sorted((sandbox / "data" / "matches").glob("*.json"))]
    club = [x for x in club if demo_data.CLUB in (x["home"]["name"], x["away"]["name"]) and x["players"]["home"]][:2]
    young = []
    for i, x in enumerate(club):
        side = "home" if x["home"]["name"] == demo_data.CLUB else "away"
        y = json.loads(json.dumps(x))
        y.update(id=f"m18-{i}", date=f"2026-03-0{i + 1}", saison="2025-2026")
        y["players"][side] = [dict(y["players"][side][0], name="ALIGNE Jamais", goals=4, num=99)] + y["players"][side][1:]
        young.append(y)
    common.write_json(sandbox / "data" / "historique" / "2025-2026-m18.json",
                      dict(saison="2025-2026", categorie="M18", competition="https://exemple/m18-1/", poules={}, matches=young))
    regular = club[0]["players"]["home" if club[0]["home"]["name"] == demo_data.CLUB else "away"][1]["name"]
    roster = {common.name_key(n): dict(nom=n, poste="", disponible=True) for n in ("Jamais Aligné", regular)}
    d = an.analyze("2026-10-04", roster=roster)
    new = next(p for p in d["joueurs"] if p["nom"] == "Jamais Aligné")
    assert new["m"] == 0 and new["jeunes"]["m"] == 2 and new["jeunes"]["buts"] == 8 and new["scores"]["equilibre"] is not None
    assert all(not p.get("jeunes") for p in d["joueurs"] if p["nom"] != "Jamais Aligné")   # les autres : rien des -18


def test_planification_figee_entre_deux_matchs(sandbox):
    """Les entrées de la planification (notes, chances de victoire, match clé) restent celles posées
    tant qu'aucune feuille du club n'arrive : mêmes propositions d'une publication à l'autre."""
    demo(sandbox)
    d = an.analyze("2026-10-04")
    m0, path = d["saison"]["matchs"][0], sandbox / "data" / an.PLANIF
    assert m0["p_plan"] == m0["p_victoire"] and all(p["scores_plan"] == p["scores"] for p in d["joueurs"])
    state = json.loads(path.read_text("utf-8"))
    state["matchs"][str(m0["id"])]["p"] = 1   # comme si le calcul avait bougé depuis
    path.write_text(json.dumps(state), "utf-8")
    again = an.analyze("2026-10-04")["saison"]["matchs"][0]
    assert again["p_plan"] == 1 and again["p_victoire"] == m0["p_victoire"]   # affichage à jour, rotation figée
    state["cle"]["feuilles"] = state["cle"]["feuilles"][:-1]   # une feuille du club de plus depuis : on repart
    path.write_text(json.dumps(state), "utf-8")
    assert an.analyze("2026-10-04")["saison"]["matchs"][0]["p_plan"] == m0["p_victoire"]


def test_forfait_general(sandbox, monkeypatch):
    """Une équipe en forfait général reste au classement, en bas et sans rang ; ses matchs ne
    comptent plus, ni dans la simulation ni dans les matchs à préparer."""
    demo(sandbox)
    before = an.analyze("2026-10-04")
    gone = next(m["adversaire"] for m in before["saison"]["matchs"] if not m.get("coupe"))
    config = dict(common.load_config(), forfaits=[gone])
    monkeypatch.setattr(an, "load_config", lambda: config)
    d = an.analyze("2026-10-04")
    rows = d["poules"]["71"]["classement"]
    assert rows[-1]["equipe"] == gone and rows[-1]["forfait"] and rows[-1]["rang"] is None
    assert [r["rang"] for r in rows[:-1]] == list(range(1, len(rows)))
    assert all(m["adversaire"] != gone for m in d["saison"]["matchs"])
    assert len(d["saison"]["rangs"]) == len(before["saison"]["rangs"]) - 1
    assert all(r["forfait"] == (gone in (r["dom"], r["ext"])) for r in d["a_venir"])
    assert d["equipes"][gone]["forfait"] and d["prochain"]["adversaire"] != gone


def test_logos_du_resume_public(monkeypatch):
    """Les logos entrent réduits dans le résumé public ; un logo déjà reçu n'est pas retéléchargé."""
    import io
    from PIL import Image
    png = io.BytesIO()
    Image.new("RGB", (128, 128), "navy").save(png, "PNG")
    asked = []
    def fetch(url):
        asked.append(url)
        if "casse" in url:
            raise OSError("illisible")
        return png.getvalue()
    monkeypatch.setattr(collect, "fetch", fetch)
    monkeypatch.setattr(publish, "LOGO_PAUSE", 0)
    board = lambda: {"club": "CLUB ALPHA", "poules": {"71": [{"equipe": "CLUB ALPHA"}, {"equipe": "CLUB BRAVO"}]},
                     "prochain": {"adversaire": "CLUB BRAVO"}, "objectif": None, "resultats": []}
    logos = {"CLUB ALPHA": "https://logos.test/a.webp", "CLUB BRAVO": "https://logos.test/casse.webp",
             "CLUB HORS RESUME": "https://logos.test/h.webp"}
    first = publish.embed_logos(board(), logos, {})
    assert set(first["logos"]) == {"CLUB ALPHA"} and first["logos"]["CLUB ALPHA"].startswith("data:image/webp;base64,")
    img = Image.open(io.BytesIO(__import__("base64").b64decode(first["logos"]["CLUB ALPHA"].split(",", 1)[1])))
    assert img.size == (publish.LOGO_PX, publish.LOGO_PX)
    assert sorted(asked) == ["https://logos.test/a.webp", "https://logos.test/casse.webp"]   # jamais l'équipe hors résumé
    asked.clear()
    again = publish.embed_logos(board(), logos, json.loads(json.dumps(first)))
    assert again["logos"] == first["logos"] and asked == ["https://logos.test/casse.webp"]   # repris, pas retéléchargé
    asked.clear()
    publish.embed_logos(board(), dict(logos, **{"CLUB ALPHA": "https://logos.test/a2.webp"}), first)
    assert "https://logos.test/a2.webp" in asked   # le club a changé de logo


def test_gymnase_des_prochains_matchs(monkeypatch):
    """Le gymnase n'est lu que pour les prochains matchs du club, et seulement quand il change."""
    pages = []
    bloc = {"competitions---rencontre-salle": {"equipement": {"libelle": "GYMNASE  DU  PARC", "rue": "1 RUE DU STADE",
                                                             "codePostal": "38000", "ville": "VILLE"}, "mapsApiKey": "x"}}
    monkeypatch.setattr(collect, "page_data", lambda url, name: pages.append(url) or bloc)
    fx = lambda i, home, equip, score=None: dict(id=str(i), poule="71", home=home, away="Autre", score_home=score,
                                                 date=f"2026-10-{10 + i:02d}T20:00", equipement=equip, url=f"u{i}")
    ours = lambda t: t == "Club"
    fixtures = {"1": fx(1, "Club", "55"), "2": fx(2, "Club", None), "3": fx(3, "Autre", "56"), "4": fx(4, "Club", "57", 30)}
    collect.add_venues(fixtures, {}, ours)
    assert pages == ["u1"]  # salle fixée, match du club, à venir ; ni l'autre poule, ni le match joué
    assert fixtures["1"]["salle"] == dict(nom="GYMNASE DU PARC", rue="1 RUE DU STADE", code_postal="38000", ville="VILLE")
    assert "salle" not in fixtures["2"] and "mapsApiKey" not in json.dumps(fixtures)
    again = {"1": fx(1, "Club", "55")}
    collect.add_venues(again, fixtures, ours)  # même salle qu'au passage précédent : pas de nouvelle page
    assert pages == ["u1"] and again["1"]["salle"]["nom"] == "GYMNASE DU PARC"


def test_departage_reglementaire():
    """Égalité de points : confrontations directes d'abord, différence générale ensuite (règlement AURA)."""
    # X et Y à 4 points : X a battu Y d'un but, Y a une bien meilleure différence générale
    order = an.rank_teams(["X", "Y", "W", "V"], [("X", "Y", 21, 20), ("Y", "W", 40, 10), ("X", "V", 15, 20)])
    assert order.index("X") < order.index("Y")
    # égalité à trois en cercle : différence de buts des confrontations directes
    assert an.rank_teams(["A", "B", "C"], [("A", "B", 20, 25), ("A", "C", 30, 10), ("B", "C", 20, 22)]) == ["A", "B", "C"]
    # sans confrontation directe : différence générale, puis buts marqués
    assert an.rank_teams(["P", "Q", "R"], [("P", "R", 30, 20), ("Q", "R", 25, 20)]) == ["P", "Q", "R"]


def test_saison_passee_collectee(sandbox, monkeypatch):
    """Une saison passée se collecte une fois : poules où jouaient le club ou ses adversaires
    d'aujourd'hui, feuilles de leurs matchs, déroulé gardé pour les seuls matchs du club."""
    pytest.importorskip("reportlab")
    from pipeline import history
    from tests import mock_site
    src = sandbox / "source"
    out = demo_data.generate(data_dir=src, matches_dir=src / "matches")
    truth = {p.stem: json.loads(p.read_text("utf-8")) for p in (src / "matches").glob("*.json")}
    site = sandbox / "site"
    rel = mock_site.build(site, list(truth.values()), out["fixtures"], "71")
    server, base = serve(site, Quiet)
    monkeypatch.setattr(collect, "FDM", base + "fdm/")
    monkeypatch.setattr(collect, "PAUSE", 0)
    config = common.load_config()
    monkeypatch.setattr(history, "SHEET_PAUSE", 0)
    is_ours = lambda t: common.is_club(t, config)
    try:
        season = history.collect_season("2025-2026", base + rel, {"Équipe fictive Alpha"}, is_ours)
        assert not any(m["source"]["fdme"] for m in season["matches"])  # les feuilles viennent ensuite
        assert history.fetch_sheets(season, sandbox / "h.json", is_ours) == 0
    finally:
        server.shutdown()
    played = [m for m in season["matches"] if m["played"]]
    assert set(season["poules"]) == {"POULE 71"} and len(played) == 9  # la poule 99 (injoignable) est sautée
    ours = [m for m in played if demo_data.CLUB in (m["home"]["name"], m["away"]["name"])]
    assert ours and all(m["events"] for m in ours)
    assert all(not m["events"] for m in played if m not in ours)
    assert all(m["saison"] == "2025-2026" and m["source"]["fdme"] for m in played
               if {m["home"]["name"], m["away"]["name"]} & {demo_data.CLUB, "Équipe fictive Alpha"})


def test_saison_passee_exploitee(sandbox):
    """La saison passée donne une note provisoire aux joueurs de l'effectif pas encore alignés,
    le bilan et la continuité des adversaires, et la force de départ dans la simulation."""
    club = demo_data.CLUB
    pl = lambda name, num, goals=0, shots=None, saves=0: dict(num=num, name=name, goals=goals, pen_goals=0, shots=shots,
                                                              saves=saves, yellow=0, two_min=0, red=0)
    def match(i, home, away, sh, sa, ph, pa, saison=None, poule="71"):
        m = dict(id=str(i), poule=poule, journee=1, date=f"2026-0{i}-01T20:00" if not saison else f"2025-1{i % 3}-0{i}T20:00",
                 played=True, home=dict(name=home, score=sh, ht=None), away=dict(name=away, score=sa, ht=None),
                 players=dict(home=ph, away=pa), events=[], source=dict(fdme=True))
        if saison:
            m.update(saison=saison, phase="POULE 5A")
        return m
    ours_now = [pl("GARDIEN Alpha", 1, saves=10), pl("TIREUR Basile", 7, 6, 9), pl("AILIER Corentin", 9, 4, 6)]
    them_now = [pl("ADVERSE Firmin", 4, 5, 8), pl("ADVERSE Gaspard", 5, 3, 5), pl("NOUVEAU Hector", 6, 2, 4)]
    common.write_json(sandbox / "data" / "matches" / "1.json", match(1, club, "Club Bravo", 12, 10, ours_now, them_now))
    past = [match(i, "HBPSM", "CLUB BRAVO", 30, 20 + i,
                  [pl("GARDIEN Alpha", 1, saves=12), pl("TIREUR Basile", 7, 8, 12), pl("ABSENT Isidore", 11, 9, 11),
                   pl("PARTI Octave", 13, 5, 7)],
                  [pl("ADVERSE Firmin", 4, 10, 15), pl("ADVERSE Gaspard", 5, 6, 9), pl("ANCIEN Leon", 8, 4, 6)],
                  saison="2025-2026", poule="5A") for i in (1, 2)]
    common.write_json(sandbox / "data" / "historique" / "2025-2026.json", dict(saison="2025-2026", poules={
        "POULE 5A": dict(id="1", equipes=[], classement=dict(entetes=["Pos.", "Équipe", "Pts"], lignes=[
            ["1", "HBPSM", "6"], ["2", "CLUB BRAVO", "2"]]))}, matches=past))
    roster = {common.name_key(n): dict(nom=n, poste="", disponible=True)
              for n in ("Alpha Gardien", "Basile Tireur", "Corentin Ailier", "Isidore Absent")}
    d = an.analyze("2026-01-02", roster=roster)
    by = {p["nom"]: p for p in d["joueurs"]}
    assert by["Isidore Absent"]["m"] == 0 and by["Isidore Absent"]["scores"]["equilibre"] is not None
    assert by["Isidore Absent"]["passe"]["buts"] == 18 and by["Isidore Absent"]["note_base"] == "2025-2026"
    assert "PARTI Octave" not in by and by["Corentin Ailier"]["passe"] is None
    assert by["Basile Tireur"]["passe"]["m"] == 2 and by["Basile Tireur"]["note_base"] == "saison et 2025-2026"
    bravo = d["equipes"]["Club Bravo"]["passe"]
    assert (bravo["j"], bravo["d"], bravo["rangs"][0]["rang"]) == (2, 2, 2)
    assert bravo["continuite"] == dict(deja=2, sur=3) and len(bravo["face_a_face"]) == 2
    assert bravo["buteurs"][0]["nom"] == "ADVERSE Firmin" and bravo["buteurs"][0]["present"] is True
    assert any(b["nom"] == "ANCIEN Leon" and b["present"] is False for b in bravo["buteurs"])
    # chaque joueur de la saison passée, revus d'abord ; un buteur d'aujourd'hui garde ses chiffres d'alors
    js = bravo["joueurs"]
    assert js[0]["present"] is True and [j["present"] for j in js] == sorted((j["present"] for j in js), reverse=True)
    leon = next(j for j in js if j["nom"] == "ANCIEN Leon")
    assert leon["present"] is False and leon["m"] >= 1 and not leon["gardien"]
    firmin = next(b for b in d["equipes"]["Club Bravo"]["buteurs"] if b["nom"] == "ADVERSE Firmin")
    assert firmin["avant"] and firmin["avant"]["buts"] == next(j for j in js if j["nom"] == "ADVERSE Firmin")["buts"]


def test_saison_passee_publiee_chiffree(sandbox, monkeypatch):
    """La saison passée part chiffrée dans historique.enc, revient à la reprise, et n'est pas réécrite
    tant qu'elle ne change pas."""
    monkeypatch.setattr(vault.encrypt, "__defaults__", (2000,))
    monkeypatch.setenv("HBPSM_CLE", PHRASE)
    demo(sandbox)
    common.write_json(sandbox / "data" / "historique" / "2025-2026.json",
                      dict(saison="2025-2026", poules={}, matches=[dict(home=dict(name="Fictif 201"))]))
    publish.seal("2026-10-04")
    enc = sandbox / "publie" / publish.HISTORY_NAME
    assert enc.exists() and "Fictif 201" not in enc.read_text("utf-8")
    before = enc.read_text("utf-8")
    publish.seal("2026-10-04")
    assert enc.read_text("utf-8") == before
    import shutil
    shutil.rmtree(sandbox / "data")
    publish.restore()
    back = json.loads((sandbox / "data" / "historique" / "2025-2026.json").read_text("utf-8"))
    assert back["matches"][0]["home"]["name"] == "Fictif 201"


def test_feuilles_ralenties(sandbox, monkeypatch):
    """Le serveur des feuilles demande de ralentir : on attend dans le budget, sinon on reprend plus tard."""
    from pipeline import history
    season = dict(saison="2025-2026", matches=[dict(id=str(i), poule="5A", journee=1, date="2025-10-04", saison="2025-2026",
                  phase="POULE 5A", home=dict(name="A", score=20, ht=None), away=dict(name="B", score=18, ht=None),
                  players={"home": [], "away": []}, events=[], source=dict(fdme=False, pdf=f"u{i}", utile=True))
                  for i in range(3)])
    calls, naps = [], []
    def fetch(url):
        calls.append(url)
        raise collect.Ralenti(600)
    monkeypatch.setattr(collect, "fetch", fetch)
    monkeypatch.setattr(collect.time, "sleep", naps.append)
    left = history.fetch_sheets(season, sandbox / "h.json", lambda t: False, budget=60)
    assert left == 3 and calls == ["u0"] and naps == []  # 600 s dépassent le budget : on s'arrête net
    assert json.loads((sandbox / "h.json").read_text("utf-8"))["matches"][0]["source"]["pdf"] == "u0"
    tries = iter([collect.Ralenti(5), b"pas un pdf", b"pas un pdf", b"pas un pdf"])
    monkeypatch.setattr(collect, "fetch", lambda url: (lambda x: (_ for _ in ()).throw(x) if isinstance(x, Exception) else x)(next(tries)))
    history.fetch_sheets(season, sandbox / "h.json", lambda t: False, budget=60)
    assert naps[0] == 5  # délai demandé respecté, puis reprise

"""Tests de la chaîne. Lancer : python -m pytest -q"""
import datetime as dt
import functools
import http.server
import json
import os
import threading

import pytest

from pipeline import analyze as an
from pipeline import collect, common, demo_data, parse_fdme, publish, vault
from pipeline.build_dashboard import build, render
from pipeline.export_training import build_exports


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
    for mod in (common, an, collect, parse_fdme, publish):
        for name, val in (("DATA", data), ("MATCHES", data / "matches"), ("RAW", raw),
                          ("PUBLIE", tmp_path / "publie")):
            if hasattr(mod, name):
                monkeypatch.setattr(mod, name, val)
    monkeypatch.setattr(publish, "ROOT", tmp_path)
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
    assert sorted(p.name for p in out.iterdir()) == ["HBPSM-tableau-de-bord.html", "etat.enc",
                                                    "hbpsm.enc", "manifeste.json", publish.SEANCE_NAME, publish.PUBLIC_NAME]
    for p in out.iterdir():
        text = p.read_text("utf-8")
        assert "Joueur 0" not in text and "Fictif" not in text, p.name  # aucun nom de joueur en clair
        if p.name not in (publish.SEANCE_NAME, publish.PUBLIC_NAME):  # seuls les fichiers publics nomment les équipes
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
    assert (sandbox / "roster.csv").read_text("utf-8") == "nom,poste,disponible\nIsidore Exemple\nJean Modele,GB\n"


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
                             club="HBPSM", verif=1))
    assert "Joueur 0" not in html
    page_file.write_text(html, "utf-8")
    with pw.sync_playwright() as p:
        browser = chrome(p)
        ctx = browser.new_context()
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(page_file.as_uri())
        page.wait_for_selector("#phrase")
        page.fill("#phrase", "mauvaise phrase secrete")
        page.click("#unlock")
        page.wait_for_selector(".err")
        assert "incorrecte" in page.inner_text(".err")
        page.fill("#phrase", PHRASE)
        page.click("#unlock")
        page.wait_for_selector("header.top h1")
        assert "HBPSM contre" in page.inner_text("h1") and "Joueur 0" in page.inner_text("main")
        # feuille de 12 joueurs dont 2 gardiens pour chacun des 4 prochains matchs
        sheet = "(k => { const r = planning()[k]; return [r.sel.length, r.gks.length, r.missing, r.missingGK]; })"
        assert [page.evaluate(sheet + "(%d)" % k) for k in range(4)] == [[12, 2, 0, 0]] * 4
        page.evaluate("(() => { const g = planning()[0].gks[0]; S.absents[g.cle] = true; })()")
        assert page.evaluate(sheet + "(0)") == [12, 1, 0, 1]  # un seul gardien disponible : signalé
        page.evaluate("S.absents = {}")
        # rotation : jamais sur un match clé, d'abord sur les matchs les plus abordables ; chaque entrant
        # prend la place d'un joueur au repos, et chacun joue au moins 1 des 4 matchs
        rot = page.evaluate("""(() => { S.regle = 1; const P = planning();
          const easy = P.filter(r => !r.m.cle).sort((a, b) => (b.m.p_victoire ?? 50) - (a.m.p_victoire ?? 50));
          return {cle: P.filter(r => r.m.cle).map(r => r.rotated.length), ordre: easy.map(r => r.rotated.length),
                  paires: P.every(r => r.rotated.length === r.resting.length && r.sel.length === 12),
                  manque: D.joueurs.filter(p => P.apps(p) < P.need(p)).length,
                  libre: (S.regle = 0, planning().every(r => !r.rotated.length)),
                  gb2: (S.regle = 2, planning().every(r => { const g = r.rotated.filter(isGK).length;
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
        page.wait_for_function("() => document.getElementById('club-etat').textContent.startsWith('à jour')")
        assert page.evaluate("D.meta.matchs") == 18
        demo(sandbox, played_days=4)  # une nouvelle collecte est publiée pendant que la page est ouverte
        publish.seal("2026-10-04")
        page.wait_for_function("() => D && D.meta.matchs === 24", timeout=20000)
        assert page.get_attribute("nav.tabs button[data-tab=saison]", "aria-selected") == "true"
        server.shutdown()  # hors connexion : la copie locale suffit, sans redemander la phrase
        server.server_close()
        page.reload()
        page.wait_for_selector("header.top h1")
        assert page.evaluate("D.meta.matchs") == 24  # la copie gardée est la plus récente
        assert "hors connexion" in page.inner_text(".status") and "hors connexion" in page.inner_text("#club-etat")
        browser.close()
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
    assert an.reliability(1, 2) == dict(matchs=2.0, saison=1, passee=2, niveau="fragile")
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

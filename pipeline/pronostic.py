"""Pronostics des matchs du club, gardés puis confrontés à la feuille (demande de l'auteur, 09/10/2026).

Avant chaque match, la projection de l'onglet Adversaires (nos moyennes face aux leurs, score attendu,
victoire estimée, tranches à surveiller et à exploiter) est gardée telle qu'elle était à la dernière
collecte avant le coup d'envoi : data/pronostics.json, repris de etat.enc. Après le match, la feuille
dit ce qu'il en a été (score, mi-temps, tranches, discipline, gardiens) et qui jouait de chaque côté.

Ce que les résultats et les présents apprennent au modèle (calibrate), sur toutes les saisons lues :
- l'avantage du terrain, mesuré sur tous les matchs prévus avec ce qu'on savait avant eux (au lieu des
  ±4 % posés au départ) : il sert à la simulation de la saison et aux matchs de coupe ;
- ce que coûte un buteur absent : la force de frappe d'une feuille, ce sont ses six meilleurs buteurs de
  champ (les six joueurs de champ sur le terrain) ; une équipe dont la force de frappe alignée vaut une part
  p de celle de ses feuilles habituelles marque environ 1 + β (p − 1) fois ses buts attendus (les autres
  compensent : β est bien en dessous de 1). Six plutôt que tous : une feuille plus longue ne marque pas plus,
  et un nouveau venu inconnu ne compte que s'il fait partie des six ;
- ce que vaut le gardien aligné : chaque point d'arrêts de plus que le gardien habituel de l'équipe
  retire environ γ points de pour cent aux buts attendus de l'adversaire.
β et γ partent d'une valeur a priori et suivent les feuilles à mesure qu'elles s'accumulent. La page
s'en sert pour l'écart attendu de la feuille proposée (Semaine) ; ici, pour dire après coup ce que les
présents expliquent de l'écart entre le pronostic et le score.
"""
import math
from collections import Counter, defaultdict

from . import analyze as an
from .common import DATA, is_club, match_name, name_key, read_json, same_team, write_json

NAME = "pronostics.json"   # data/, repris de etat.enc
V = 2                      # version du calcul de la réalité : une autre version refait les bilans déjà faits
                           # (2 : la proposition du tableau de bord et l'équipe jouée, chiffrées, 10/10/2026)
GARDE = 80                 # pronostics gardés (un peu plus de deux saisons)

DOM, EXT = 1.04, 0.96      # avantage du terrain posé au départ (buts attendus à domicile, à l'extérieur)
N_DOM = 200                # matchs fictifs à 1,04 / 0,96 : le terrain se mesure sur des centaines de matchs
BETA, BETA_SD = 0.5, 0.25  # a priori : la moitié des buts d'un absent manque au score
GAMMA, GAMMA_SD = 1.4, 0.5 # a priori : 1 / (1 − 30 % d'arrêts), tous les tirs cadrés restant les mêmes
K_BUTS = 3                 # matchs moyens ajoutés au taux de buts d'un joueur
K_GB = 40                  # tirs cadrés moyens ajoutés au % d'arrêts d'un gardien
MIN_AVANT = 3              # matchs joués par chaque équipe avant d'en prévoir un (calibrage)
MIN_FEUILLES = 3           # feuilles d'une équipe avant de dire qui manquait
SIX = 6                    # joueurs de champ sur le terrain : la force de frappe d'une feuille


def player_key(pl):
    return name_key(pl.get("name")) or f"N{pl.get('num')}"


def club_key(roster):
    """La clé d'un joueur du club, comme dans joueurs : « R:… » s'il est dans l'effectif."""
    def key(pl):
        rkey = match_name(pl.get("name"), roster) if roster else None
        return "R:" + rkey if rkey else player_key(pl)
    return key


# ---------------------------------------------------------------- qui joue : buts habituels, gardiens
def team_model(entries, keyf=player_key, conceded=None):
    """Ce qu'une équipe a l'habitude d'aligner, d'après ses feuilles : [(match, côté, poids)].
    taux : buts par match de chaque joueur de champ, ramenés vers la moyenne de l'équipe (K_BUTS) ; base :
    force de frappe d'une feuille habituelle (frappe) ; sr : % d'arrêts de chaque gardien, ramené vers
    celui de l'équipe (K_GB tirs) ; part : sa part des tirs cadrés subis ; noms : pour dire qui manquait."""
    conceded = conceded or an.keepers_conceded
    g, n, sv, fc, noms = defaultdict(float), defaultdict(float), defaultdict(float), defaultdict(float), {}
    for m, side, w in entries:
        against, _ = conceded(m, side)
        for pl in m["players"][side]:
            k = keyf(pl)
            noms[k] = pl.get("name") or f"n° {pl.get('num')}"
            if pl.get("saves"):   # un gardien : hors de la force de frappe
                if pl.get("num") in against:
                    sv[k] += w * pl["saves"]
                    fc[k] += w * (pl["saves"] + against[pl["num"]])
                continue
            g[k] += w * (pl.get("goals") or 0)
            n[k] += w
    tn = sum(n.values())
    if not tn:
        return None
    moyen = sum(g.values()) / tn
    model = dict(taux={k: (g[k] + K_BUTS * moyen) / (n[k] + K_BUTS) for k in n}, moyen=moyen)
    sums = [(frappe(model, field(m, side, keyf)), w) for m, side, w in entries]
    base = sum(s * w for s, w in sums) / sum(w for _, w in sums)
    taux = model["taux"]
    faced = sum(fc.values())
    tr = sum(sv.values()) / faced if faced else None
    return dict(taux=taux, moyen=moyen, base=base, tr=tr, noms=noms, apps=dict(n), feuilles=len(entries),
                sr={k: (sv[k] + K_GB * tr) / (fc[k] + K_GB) for k in fc} if tr is not None else {},
                part={k: fc[k] / faced for k in fc} if faced else {})


def field(m, side, keyf=player_key):
    """Les joueurs de champ d'une feuille jouée (ceux qui n'ont pas fait d'arrêt)."""
    return [keyf(pl) for pl in m["players"][side] if not pl.get("saves")]


def frappe(model, keys):
    """La force de frappe d'une feuille : les taux de ses six meilleurs buteurs de champ (un inconnu
    compte pour la moyenne de l'équipe)."""
    return sum(sorted((model["taux"].get(k, model["moyen"]) for k in keys), reverse=True)[:SIX])


def presence(model, keys, keepers=None):
    """(force de frappe des joueurs de champ alignés, keys, rapportée à celle d'une feuille habituelle ;
    % d'arrêts des gardiens alignés moins celui du gardien habituel). keepers : {clé: poids} (tirs subis
    dans le match, sinon part habituelle)."""
    if not model or not model["base"]:
        return 1.0, 0.0
    pi = frappe(model, keys) / model["base"]
    dsr = 0.0
    if model["tr"] is not None and keepers:
        w = {k: v for k, v in keepers.items() if v > 0} or {k: 1.0 for k in keepers}
        mix = sum(v * model["sr"].get(k, model["tr"]) for k, v in w.items()) / sum(w.values())
        dsr = mix - model["tr"]
    return pi, dsr


def sheet_presence(model, m, side, keyf=player_key, conceded=None):
    """La présence d'une feuille jouée : les gardiens pèsent les tirs qu'ils ont subis dans le match."""
    against, _ = (conceded or an.keepers_conceded)(m, side)
    keepers = {keyf(pl): pl["saves"] + against.get(pl.get("num"), 0) for pl in m["players"][side] if pl.get("saves")}
    return presence(model, field(m, side, keyf), keepers)


def adjust(pour, contre, cal, nous=(1.0, 0.0), eux=(1.0, 0.0)):
    """Buts attendus de chaque côté selon qui joue : nos buteurs et leur gardien font nos buts, et
    inversement."""
    p = pour * (1 + cal["beta"] * (nous[0] - 1)) * (1 - cal["gamma"] * eux[1])
    c = contre * (1 + cal["beta"] * (eux[0] - 1)) * (1 - cal["gamma"] * nous[1])
    return round(p, 1), round(c, 1)


# ---------------------------------------------------------------- ce que les saisons lues apprennent
def _poules(matches):
    by = defaultdict(list)
    for m in matches:
        if m.get("coupe") or m["home"].get("score") is None or m["away"].get("score") is None:
            continue
        by[(str(m.get("poule")), str(m.get("phase") or ""))].append(m)
    for ms in by.values():
        ms.sort(key=lambda m: m.get("date") or "")
    return by.values()


def _expected(tab, avg, h, a, k=3):
    rate = lambda t, i: ((tab[t][i] + k * avg) / (tab[t][2] + k)) / avg
    return avg * rate(h, 0) * rate(a, 1), avg * rate(a, 0) * rate(h, 1)


def _solve(rows, prior, prior_sd):
    """Moindres carrés à deux coefficients, ramenés vers l'a priori : (coefficients, écarts-types)."""
    n = len(rows)
    if n < 2:
        return list(prior), list(prior_sd)
    sxx = [[sum(r[0][i] * r[0][j] for r in rows) for j in range(2)] for i in range(2)]
    sxy = [sum(r[0][i] * r[1] for r in rows) for i in range(2)]
    det = sxx[0][0] * sxx[1][1] - sxx[0][1] ** 2
    if det > 1e-9:
        b = [(sxx[1][1] * sxy[0] - sxx[0][1] * sxy[1]) / det, (sxx[0][0] * sxy[1] - sxx[0][1] * sxy[0]) / det]
        s2 = sum((r[1] - b[0] * r[0][0] - b[1] * r[0][1]) ** 2 for r in rows) / max(1, n - 2)
    else:
        s2 = sum(r[1] ** 2 for r in rows) / n
    a = [[sxx[i][j] / s2 + (1 / prior_sd[i] ** 2 if i == j else 0) for j in range(2)] for i in range(2)]
    y = [sxy[i] / s2 + prior[i] / prior_sd[i] ** 2 for i in range(2)]
    det = a[0][0] * a[1][1] - a[0][1] ** 2
    b = [(a[1][1] * y[0] - a[0][1] * y[1]) / det, (a[0][0] * y[1] - a[0][1] * y[0]) / det]
    return b, [math.sqrt(a[1][1] / det), math.sqrt(a[0][0] / det)]


def calibrate(seasons):
    """seasons : les matchs de chaque saison lue, la saison en cours comprise. Renvoie l'avantage du
    terrain, β et γ, et ce que vaut le modèle sur les saisons passées (vainqueur trouvé, erreur)."""
    rows = []   # (buts attendus dom., ext., buts marqués dom., ext.)
    for matches in seasons:
        for ms in _poules(matches):
            tab = defaultdict(lambda: [0, 0, 0])
            for m in ms:
                h, a = m["home"]["name"], m["away"]["name"]
                if tab[h][2] >= MIN_AVANT and tab[a][2] >= MIN_AVANT:
                    avg = sum(v[0] for v in tab.values()) / sum(v[2] for v in tab.values())
                    rows.append((*_expected(tab, avg, h, a), m["home"]["score"], m["away"]["score"]))
                for side, o in (("home", "away"), ("away", "home")):
                    r = tab[m[side]["name"]]
                    r[0], r[1], r[2] = r[0] + m[side]["score"], r[1] + m[o]["score"], r[2] + 1
    n = len(rows)
    dom, ext = DOM, EXT
    if n:
        dom = (sum(r[2] for r in rows) / sum(r[0] for r in rows) * n + DOM * N_DOM) / (n + N_DOM)
        ext = (sum(r[3] for r in rows) / sum(r[1] for r in rows) * n + EXT * N_DOM) / (n + N_DOM)
    errs = [(r[2] - r[3]) - (dom * r[0] - ext * r[1]) for r in rows]
    decided = [(dom * r[0] - ext * r[1], r[2] - r[3]) for r in rows if r[2] != r[3]]
    backtest = dict(n=n, vainqueur=round(100 * sum((p > 0) == (a > 0) for p, a in decided) / len(decided)) if decided else None,
                    erreur=round(sum(abs(e) for e in errs) / n, 1) if n else None)
    # qui jouait : chaque feuille confrontée à ce que l'équipe aligne d'habitude (ses autres feuilles)
    obs, memo = [], {}

    def conceded(m, side):   # chaque feuille resservant une vingtaine de fois
        if (id(m), side) not in memo:
            memo[(id(m), side)] = an.keepers_conceded(m, side)
        return memo[(id(m), side)]
    for matches in seasons:
        sheets = defaultdict(list)
        for m in matches:
            for side in ("home", "away"):
                if not m.get("coupe") and (m.get("players") or {}).get(side):
                    sheets[m[side]["name"]].append((m, side, 1.0))
        for ms in _poules(matches):
            tab = defaultdict(lambda: [0, 0, 0])
            for m in ms:
                for side, o in (("home", "away"), ("away", "home")):
                    r = tab[m[side]["name"]]
                    r[0], r[1], r[2] = r[0] + m[side]["score"], r[1] + m[o]["score"], r[2] + 1
            avg = sum(v[0] for v in tab.values()) / max(1, sum(v[2] for v in tab.values()))
            for m in ms:
                for side, o in (("home", "away"), ("away", "home")):
                    t, u = m[side]["name"], m[o]["name"]
                    if not (m.get("players") or {}).get(side) or tab[t][2] <= MIN_AVANT or tab[u][2] <= MIN_AVANT:
                        continue
                    others = [e for e in sheets[t] if e[0] is not m]
                    if len(others) < MIN_FEUILLES:
                        continue
                    # buts attendus sans ce match (ni pour l'une, ni pour l'autre équipe)
                    att = (tab[t][0] - m[side]["score"]) / (tab[t][2] - 1) / avg
                    dfn = (tab[u][1] - m[side]["score"]) / (tab[u][2] - 1) / avg
                    mu = avg * att * dfn * (dom if side == "home" else ext)
                    pi, _ = sheet_presence(team_model(others, conceded=conceded), m, side, conceded=conceded)
                    opp = [e for e in sheets[u] if e[0] is not m]
                    dsr = sheet_presence(team_model(opp, conceded=conceded), m, o, conceded=conceded)[1] if (m.get("players") or {}).get(o) and len(opp) >= MIN_FEUILLES else 0.0
                    obs.append(([(pi - 1) * mu, -dsr * mu], m[side]["score"] - mu))
    (beta, gamma), (beta_sd, gamma_sd) = _solve(obs, (BETA, GAMMA), (BETA_SD, GAMMA_SD))
    return dict(dom=round(dom, 3), ext=round(ext, 3), n_matchs=n, backtest=backtest,
                beta=round(min(1.0, max(0.0, beta)), 3), beta_sd=round(beta_sd, 3),
                gamma=round(min(3.0, max(0.0, gamma)), 3), gamma_sd=round(gamma_sd, 3), n_feuilles=len(obs))


# ---------------------------------------------------------------- avant le match, après le match
def kickoff(m):
    """Le coup d'envoi (« AAAA-MM-JJTHH:MM ») ; horaire à confirmer : le début du jour annoncé."""
    d = m.get("date") or ""
    return d[:16] if len(d) >= 16 and not m.get("provisoire") else d[:10] + "T00:00" if d else None


PROFIL = ("j", "bp_moy", "bc_moy", "arrets_pct", "mt1_bp", "mt1_bc", "mt2_bp", "mt2_bc", "deux_min_moy",
          "jaunes_moy", "forme", "periodes_bp", "periodes_bc")


def snapshot(m, u, e, now, saison):
    """La projection telle qu'on la montre avant le match : nos moyennes, les leurs, le score attendu,
    les tranches à surveiller (leurs buts dans leurs matchs + les nôtres encaissés dans les nôtres) et
    à exploiter (l'inverse), comme l'onglet Adversaires."""
    u, e = u or {}, e or {}
    pour, ecart = m.get("buts_pour"), m.get("ecart")
    out = dict(fige=now, saison=saison, id=str(m["id"]), date=m.get("date"), provisoire=bool(m.get("provisoire")),
               journee=m.get("journee"), coupe=m.get("coupe"), tour=m.get("tour"), adversaire=m["adversaire"],
               domicile=bool(m.get("domicile")), p=m.get("p_victoire"), enjeu=m.get("enjeu"), cle=bool(m.get("cle")),
               pour=pour, contre=round(pour - ecart, 1) if pour is not None and ecart is not None else None, ecart=ecart,
               nous={k: u.get(k) for k in PROFIL}, eux={k: e.get(k) for k in PROFIL}, surveiller=None, exploiter=None)
    if u.get("periodes_bc") and e.get("periodes_bp"):
        risk = [a + b for a, b in zip(u["periodes_bc"], e["periodes_bp"])]
        chance = [a + b for a, b in zip(u["periodes_bp"], e["periodes_bc"])]
        out["surveiller"], out["exploiter"] = risk.index(max(risk)), chance.index(max(chance))
    return out


def _slices(m, side):
    if not m.get("events"):
        return None
    out = [[0] * 6, [0] * 6]
    for ev in m["events"]:
        if ev.get("type") in ("goal", "pen_goal"):
            out[0 if ev.get("side") == side else 1][min(5, int((ev.get("t") or 0) // 600))] += 1
    return out


def _sum(sheet, k):
    return sum(pl.get(k) or 0 for pl in sheet)


def _missing(model, keys, n=3, cles=None):
    """Les meilleurs buteurs habituels (au moins deux matchs) absents de la feuille."""
    if not model:
        return []
    top = sorted((k for k in model["taux"] if model["apps"].get(k, 0) >= 2 and (cles is None or k in cles)),
                 key=lambda k: -model["taux"][k])[:n]
    return [dict(cle=k, nom=model["noms"].get(k), taux=round(model["taux"][k], 1)) for k in top if k not in keys]


def lineup(us, keys, avant, cal, gardiens=frozenset()):
    """L'écart attendu avec cette équipe de notre côté (clés des joueurs), l'adversaire à son habitude : les
    gardiens pèsent leur part habituelle des tirs."""
    keepers = {k: us["part"].get(k, 0.0) for k in keys if k in gardiens or k in us["sr"]}
    pi, dsr = presence(us, [k for k in keys if k not in keepers], keepers)
    pour, contre = adjust(avant["pour"], avant["contre"], cal, (pi, dsr))
    return dict(part=round(100 * pi), gardien=round(100 * dsr, 1), pour=pour, contre=contre, ecart=round(pour - contre, 1))


def reality(m, side, avant, cal, models, keyf, choix=None, cles=None, gardiens=frozenset(), suggestion=None, source=None):
    """Ce que la feuille dit du match, et ce que les présents expliquent de l'écart au pronostic.
    models : (le nôtre, le leur), tels qu'ils étaient avant le match ; choix : la feuille retenue par
    l'entraîneur (clés des joueurs), si elle a été publiée ; cles : les joueurs de l'effectif (seuls
    eux peuvent manquer) ; gardiens : nos gardiens ; suggestion : la feuille que proposait le tableau de
    bord (source : « publication », jointe à la feuille de l'entraîneur, ou « collecte », la dernière
    calculée avant le coup d'envoi)."""
    o = "away" if side == "home" else "home"
    bp, bc = m[side]["score"], m[o]["score"]
    players = m.get("players") or {}
    sheet, theirs = players.get(side) or [], players.get(o) or []
    out = dict(v=V, bp=bp, bc=bc, ecart=bp - bc, res=an.outcome(bp, bc), feuille=bool(sheet),
               mt=[m[side].get("ht"), m[o].get("ht")] if m[side].get("ht") is not None and m[o].get("ht") is not None else None,
               periodes=_slices(m, side))
    if sheet:
        out.update(deux_min=[_sum(sheet, "two_min"), _sum(theirs, "two_min") if theirs else None],
                   jaunes=[_sum(sheet, "yellow"), _sum(theirs, "yellow") if theirs else None],
                   rouges=[_sum(sheet, "red"), _sum(theirs, "red") if theirs else None],
                   arrets=[an.save_pct(_sum(sheet, "saves"), bc), an.save_pct(_sum(theirs, "saves"), bp) if theirs else None])
    us, them = models
    if avant.get("pour") is None or avant.get("contre") is None:
        return out
    pres = {}
    if sheet and us and us["feuilles"] >= MIN_FEUILLES:
        pi, dsr = sheet_presence(us, m, side, keyf)
        keys = {keyf(pl) for pl in sheet}
        pres["nous"] = dict(part=round(100 * pi), gardien=round(100 * dsr, 1), joueurs=len(sheet),
                            absents=[dict(cle=a["cle"], taux=a["taux"]) for a in _missing(us, keys, cles=cles)])
    if theirs and them and them["feuilles"] >= MIN_FEUILLES:
        pi, dsr = sheet_presence(them, m, o)
        keys = {player_key(pl) for pl in theirs}
        pres["eux"] = dict(part=round(100 * pi), gardien=round(100 * dsr, 1), joueurs=len(theirs),
                           absents=[dict(nom=a["nom"], taux=a["taux"]) for a in _missing(them, keys)])
    if pres:
        out["presents"] = pres
        n = pres.get("nous") or {}
        t = pres.get("eux") or {}
        pour, contre = adjust(avant["pour"], avant["contre"], cal, (n.get("part", 100) / 100, n.get("gardien", 0) / 100),
                              (t.get("part", 100) / 100, t.get("gardien", 0) / 100))
        out["corrige"] = dict(pour=pour, contre=contre, ecart=round(pour - contre, 1))
    if not (us and us["feuilles"] >= MIN_FEUILLES):
        return out
    if choix:
        out["retenue"] = lineup(us, choix, avant, cal, gardiens)
    # la proposition du tableau de bord, et l'équipe qui a joué, chiffrées de la même façon : l'écart entre les
    # deux est ce que le modèle pensait des choix de l'entraîneur ; l'écart au score, ce qu'ils ont donné
    played = [keyf(pl) for pl in sheet]
    if played:
        out["jouee"] = lineup(us, played, avant, cal, gardiens)
    coach = choix or played
    if suggestion and coach:
        out["proposee"] = dict(lineup(us, suggestion, avant, cal, gardiens), source=source)
        plus, moins = sorted(set(coach) - set(suggestion)), sorted(set(suggestion) - set(coach))
        goals = {keyf(pl): pl.get("goals") or 0 for pl in sheet if not pl.get("saves")}
        on = [k for k in plus if k in goals]   # ceux qu'il a fait entrer et qui ont joué dans le champ
        out["choix"] = dict(source="publiee" if choix else "feuille", plus=plus, moins=moins,
                            buts_plus=sum(goals[k] for k in on) if sheet else None,
                            attendus_plus=round(sum(us["taux"].get(k, us["moyen"]) for k in on), 1) if sheet else None)
    return out


def entries_of(team, current, past, before, keyf_is_club=False, w_past=0.5, config=None):
    """Les feuilles d'une équipe jouées avant une date : cette saison (poids 1), la saison passée
    (w_past ; même équipe sous une autre écriture)."""
    same = (lambda a: is_club(a, config)) if keyf_is_club else (lambda a: a == team)
    same_past = (lambda a: is_club(a, config)) if keyf_is_club else (lambda a: same_team(a, team))
    out = [(m, s, 1.0) for m in current for s in ("home", "away")
           if same(m[s]["name"]) and (m.get("players") or {}).get(s) and (m.get("date") or "") < before]
    out += [(m, s, w_past) for m in past for s in ("home", "away")
            if same_past(m[s]["name"]) and (m.get("players") or {}).get(s)]
    return out


def record(saison, profiles, club, current, past, cal, config, roster, players, now, season_label, w_past, choix=None,
           archive=None):
    """Garde le pronostic de chaque match du club à venir (le dernier avant le coup d'envoi l'emporte),
    puis, le match joué, ce que la feuille en dit. archive : les feuilles retenues et proposées gardées par
    pipeline/selections.py, {match: entrée}. Renvoie les pronostics de la saison, du plus ancien au plus
    récent, et leur bilan."""
    store = read_json(DATA / NAME, {}) or {}
    kept = dict(store.get("matchs") or {})
    played = {str(m["id"]): m for m in current if m["home"].get("score") is not None and m["away"].get("score") is not None}
    for m in (saison or {}).get("matchs") or []:
        mid, kick = str(m["id"]), kickoff(m)
        if mid in played or (kick and now >= kick):
            continue   # commencé : le pronostic d'avant reste
        kept[mid] = dict(kept.get(mid) or {}, avant=snapshot(m, profiles.get(club), profiles.get(m["adversaire"]), now, season_label))
    keyf = club_key(roster)
    cles = {"R:" + k for k in roster or {}}
    gardiens = frozenset(p["cle"] for p in players if p.get("gardien"))
    for mid, e in kept.items():
        x, avant = played.get(mid), e.get("avant")
        if not x or not avant or (e.get("apres") or {}).get("v") == V and e["apres"].get("feuille"):
            continue
        side = "home" if is_club(x["home"]["name"], config) else "away"
        before = x.get("date") or "9999"
        us = team_model(entries_of(club, current, past, before, True, w_past, config), keyf)
        adv = x["away" if side == "home" else "home"]["name"]
        them = team_model(entries_of(adv, current, past, before, w_past=w_past))
        sel = (archive or {}).get(mid) or {}
        mine = ((choix or {}).get(mid) or {}).get("joueurs") or sel.get("retenue")
        sugg = sel.get("proposee") or sel.get("auto")
        e["apres"] = reality(x, side, avant, cal, (us, them), keyf, mine, cles, gardiens, sugg,
                             "publication" if sel.get("proposee") else "collecte")
    # les plus récents ; un match qui n'a plus lieu (date passée, jamais joué) finit par sortir
    order = sorted(kept, key=lambda k: (kept[k].get("avant") or {}).get("date") or "")
    kept = {k: kept[k] for k in order[-GARDE:]}
    write_json(DATA / NAME, dict(v=1, matchs=kept))
    out = [dict(e["avant"], apres=e.get("apres")) for e in kept.values()
           if e.get("avant") and e["avant"].get("saison") == season_label]
    return out, summary(out)


def summary(items):
    """Bilan des pronostics joués : vainqueur trouvé, erreur moyenne sur l'écart, biais, et la même
    erreur une fois connus les présents."""
    done = [x for x in items if x.get("apres") and x.get("ecart") is not None]
    if not done:
        return dict(n=0)
    err = [x["apres"]["ecart"] - x["ecart"] for x in done]
    hit = [(x["ecart"] > 0) == (x["apres"]["ecart"] > 0) for x in done if x["apres"]["ecart"] != 0 and x["ecart"] != 0]
    known = [x for x in done if x["apres"].get("corrige")]
    return dict(n=len(done), vainqueur=sum(hit), sur=len(hit),
                erreur=round(sum(abs(v) for v in err) / len(err), 1), biais=round(sum(err) / len(err), 1),
                n_presents=len(known),
                erreur_avant=round(sum(abs(x["apres"]["ecart"] - x["ecart"]) for x in known) / len(known), 1) if known else None,
                erreur_presents=round(sum(abs(x["apres"]["ecart"] - x["apres"]["corrige"]["ecart"]) for x in known) / len(known), 1) if known else None)


SD_PRUDENT = 6.0   # buts : l'écart-type d'un écart au score face au modèle, tant que trop peu de matchs le mesurent
SD_MIN = 4.0       # jamais moins, même si les premiers matchs tombent près du pronostic


def _mean(v):
    return round(sum(v) / len(v), 1) if v else None


def influence(items):
    """Les choix de l'entraîneur face aux propositions du tableau de bord, et ce qu'ils ont donné (demande de
    l'auteur, 10/10/2026). Pour chaque match joué dont on connaît les deux : ce que le modèle pensait de ses
    changements avant le match (`valeur` : écart attendu avec son équipe moins écart attendu avec la
    proposition), et ce que l'équipe a fait de plus que prévu une fois connus les présents des deux côtés
    (`residu` : écart au score moins l'écart corrigé). Puis, matchs où il a suivi la proposition contre
    matchs où il s'en est écarté : si ses choix savent ce que le modèle ignore (forme du moment, adversaire,
    vestiaire), l'équipe fait mieux que prévu quand il s'écarte. Une tendance, pas une preuve : `marge` est
    la marge d'erreur à 95 % de la différence (ou du résidu face à zéro si l'un des deux groupes manque)."""
    rows = []
    for x in items:
        a = x.get("apres") or {}
        c, p = a.get("choix"), a.get("proposee")
        if not c or not p:
            continue
        coach = a.get("retenue") if c["source"] == "publiee" else a.get("jouee")
        ref = (a.get("corrige") or a.get("jouee") or {}).get("ecart")
        rows.append(dict(id=x["id"], journee=x.get("journee"), coupe=x.get("coupe"), tour=x.get("tour"),
                         adversaire=x.get("adversaire"), date=x.get("date"), source=c["source"], proposee=p.get("source"),
                         changes=len(c["plus"]), plus=c["plus"], moins=c["moins"], res=a.get("res"), reel=a["ecart"],
                         prevu=x.get("ecart"), avec_proposee=p["ecart"], avec_choix=coach and coach["ecart"],
                         valeur=round(coach["ecart"] - p["ecart"], 1) if coach else None,
                         residu=round(a["ecart"] - ref, 1) if ref is not None else None,
                         buts_plus=c.get("buts_plus"), attendus_plus=c.get("attendus_plus")))
    if not rows:
        return dict(n=0, matchs=[])
    res = [r["residu"] for r in rows if r["residu"] is not None]
    sd = SD_PRUDENT
    if len(res) >= 3:
        mu = sum(res) / len(res)
        sd = max(SD_MIN, math.sqrt(sum((v - mu) ** 2 for v in res) / (len(res) - 1)))

    def group(rs):
        rr = [r["residu"] for r in rs if r["residu"] is not None]
        return dict(n=len(rs), residu=_mean(rr), n_residu=len(rr), valeur=_mean([r["valeur"] for r in rs if r["valeur"] is not None]),
                    resultats={k: sum(1 for r in rs if r["res"] == k) for k in ("V", "N", "D")})
    suivis, ecartes = group([r for r in rows if not r["changes"]]), group([r for r in rows if r["changes"]])
    if suivis["n_residu"] and ecartes["n_residu"]:
        diff = round(ecartes["residu"] - suivis["residu"], 1)
        marge = round(1.96 * sd * math.sqrt(1 / suivis["n_residu"] + 1 / ecartes["n_residu"]), 1)
    else:   # un seul des deux groupes : face au modèle, qui vise zéro
        g = ecartes if ecartes["n_residu"] else suivis
        diff = g["residu"]
        marge = round(1.96 * sd / math.sqrt(g["n_residu"]), 1) if g["n_residu"] else None
    on = [r for r in rows if r["buts_plus"] is not None and r["attendus_plus"] is not None and r["plus"]]
    return dict(n=len(rows), matchs=rows, suivis=suivis, ecartes=ecartes, diff=diff, marge=marge, sd=round(sd, 1),
                changements=round(sum(r["changes"] for r in rows) / len(rows), 1),
                buts_plus=sum(r["buts_plus"] for r in on) if on else None,
                attendus_plus=round(sum(r["attendus_plus"] for r in on), 1) if on else None)


def lineup_inputs(players, club, current, past, config, roster, w_past):
    """Pour la page : le taux de buts de chaque joueur de champ, le % d'arrêts de chaque gardien et sa
    part des tirs, et la force de frappe d'une feuille habituelle du club, pour l'écart attendu d'une
    feuille proposée."""
    model = team_model(entries_of(club, current, past, "9999", True, w_past, config), club_key(roster))
    if not model:
        return None
    for p in players:
        p["taux"] = round(model["taux"].get(p["cle"], model["moyen"]), 2)
        if p.get("gardien"):
            p["sr"] = round(model["sr"].get(p["cle"], model["tr"]), 3) if model["tr"] is not None else None
            p["part_gb"] = round(model["part"].get(p["cle"], 0.0), 3)
    return dict(base=round(model["base"], 2), moyen=round(model["moyen"], 2), six=SIX,
                tr=round(model["tr"], 3) if model["tr"] is not None else None, feuilles=model["feuilles"])

"""Dixon-Coles -malli + joukkuekohtainen kotietu + ottelukohtaiset saadot."""

from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import poisson


def _tau(x, y, lam, mu, rho):
    if x == 0 and y == 0: return 1.0 - lam * mu * rho
    if x == 0 and y == 1: return 1.0 + lam * rho
    if x == 1 and y == 0: return 1.0 + mu * rho
    if x == 1 and y == 1: return 1.0 - rho
    return 1.0


@dataclass
class DixonColesModel:
    attack: dict = field(default_factory=dict)
    defence: dict = field(default_factory=dict)
    home_advantage: float = 0.0           # globaali keskiarvo
    home_advantage_per_team: dict = field(default_factory=dict)  # joukkuekohtainen lisays
    rho: float = -0.1
    teams_: list = field(default_factory=list)
    per_team_home_adv: bool = True        # True = sovita joukkuekohtainen kotietu

    def fit(self, matches, home_team_col="home_team", away_team_col="away_team",
            home_goals_col="home_score", away_goals_col="away_score",
            decay=0.0, date_col=None, l2_per_team=2.0,
            l2_attack_defence=2.0, team_priors=None):
        """
        Sovita malli.

        Parametrit
        ----------
        l2_per_team
            Shrinkkaa joukkuekohtaisia home-advantage-poikkeamia kohti 0:aa
            (estaa overfittingia kun joukkueella on vahan kotipeleja).
        l2_attack_defence
            **Bayes-prior** hyokkays/puolustus-parametreille. Vetaa joukkueiden
            estimaatit kohti liigan keskiarvoa (joka on 0). Vahan dataa ->
            estimaatti pysyy lahempana keskiarvoa, paljon dataa -> data dominoi.

            Ekvivalentti Normal(0, sigma)-priorin MAP-estimoinnille jossa
            sigma = sqrt(1 / (2 * l2_attack_defence)). Suositukset:
              - 0.5 = heikko shrinkage, lahes pure MLE
              - 2.0 = oletus, sopiva 1-2 kauden datalla
              - 5.0 = vahva shrinkage, hyodyllinen kun joukkueella vahan otteluja
              - 0   = ei prioriaa (vanha kayttaytyminen)
        team_priors
            Optionaalinen dict joukkuekohtaisia priorityyppeja:
            ``{joukkue: {"attack": x, "defence": y, "weight": w}}``.
            ``weight`` on shrinkage-vahvuuskerroin (oletus 1.0). Ilman tata
            joukkueiden L2-prior on (0, 0); tama vaihtaa shrinkage-kohteen
            (ja initialisoinnin) mainittuun arvoon. Hyodyllinen promotoiduille
            joukkueille joiden alasarjaestimaatti tunnetaan.
        """
        df = matches.dropna(subset=[home_goals_col, away_goals_col]).copy()
        df[home_goals_col] = df[home_goals_col].astype(int)
        df[away_goals_col] = df[away_goals_col].astype(int)
        teams = sorted(set(df[home_team_col]) | set(df[away_team_col]))
        n = len(teams)
        idx = {t: i for i, t in enumerate(teams)}

        if decay > 0 and date_col is not None:
            t = pd.to_datetime(df[date_col])
            paivaa = (t.max() - t).dt.days.values
            painot = np.exp(-decay * paivaa)
        else:
            painot = np.ones(len(df))

        h_idx = df[home_team_col].map(idx).values
        a_idx = df[away_team_col].map(idx).values
        h_g = df[home_goals_col].values
        a_g = df[away_goals_col].values

        # Rakenna prior-vektorit team_priors:sta. Default: kaikki nollia.
        prior_attack = np.zeros(n)
        prior_defence = np.zeros(n)
        prior_weight = np.ones(n)
        if team_priors:
            for tnimi, p in team_priors.items():
                if tnimi in idx:
                    i = idx[tnimi]
                    prior_attack[i] = float(p.get("attack", 0.0))
                    prior_defence[i] = float(p.get("defence", 0.0))
                    prior_weight[i] = float(p.get("weight", 1.0))

        # Parametrivektori: [attack(n), defence(n), gamma_per_team(n), gamma_global, rho]
        # = 3n + 2 parametria yhteensa
        if self.per_team_home_adv:
            n_per_team = n
        else:
            n_per_team = 0

        def neg_log_lik(params):
            attack = params[:n]
            defence = params[n:2*n]
            if self.per_team_home_adv:
                gamma_team = params[2*n:3*n]
                gamma_global = params[-2]
                rho = params[-1]
                lam = np.exp(attack[h_idx] + defence[a_idx] + gamma_global + gamma_team[h_idx])
            else:
                gamma_team = np.zeros(n)
                gamma_global = params[-2]
                rho = params[-1]
                lam = np.exp(attack[h_idx] + defence[a_idx] + gamma_global)
            mu = np.exp(attack[a_idx] + defence[h_idx])

            log_p = poisson.logpmf(h_g, lam) + poisson.logpmf(a_g, mu)
            # Vektoroitu tau: vain (0,0), (0,1), (1,0), (1,1) -ottelut saavat
            # epatriviaalin korjauskertoimen, muut jaavat 1.0:ksi.
            # Korvaa Python for-loopin -> ~150x nopeampi per fit-kutsu.
            tau_arr = np.ones(len(h_g))
            m_00 = (h_g == 0) & (a_g == 0)
            m_01 = (h_g == 0) & (a_g == 1)
            m_10 = (h_g == 1) & (a_g == 0)
            m_11 = (h_g == 1) & (a_g == 1)
            tau_arr[m_00] = 1.0 - lam[m_00] * mu[m_00] * rho
            tau_arr[m_01] = 1.0 + lam[m_01] * rho
            tau_arr[m_10] = 1.0 + mu[m_10] * rho
            tau_arr[m_11] = 1.0 - rho
            tau_arr = np.clip(tau_arr, 1e-10, None)
            log_p = log_p + np.log(tau_arr)

            nll = -np.sum(painot * log_p)
            # L2-shrinkage: rankaisee joukkuekohtaista poikkeamaa nollasta
            if self.per_team_home_adv:
                nll += l2_per_team * np.sum(gamma_team ** 2)
            # Bayes-prior: vetaa attack/defence -estimaatit kohti prior_attack/
            # prior_defence -arvoja (oletuksena 0 = liigan keskiarvo, mutta
            # team_priors:lla voi vaihtaa esim. alasarjaestimaattiin).
            # prior_weight skaalaa per-joukkue shrinkage-vahvuuden.
            if l2_attack_defence > 0:
                a_diff2 = prior_weight * (attack - prior_attack) ** 2
                d_diff2 = prior_weight * (defence - prior_defence) ** 2
                nll += l2_attack_defence * (np.sum(a_diff2) + np.sum(d_diff2))
            return nll

        # Alustusarvot — priorit annettu joukkueille auttavat konvergoimaan
        if self.per_team_home_adv:
            x0 = np.concatenate([
                prior_attack.copy(),     # attack (oletuksena 0)
                prior_defence.copy(),    # defence (oletuksena 0)
                np.zeros(n),             # gamma_team (joukkuekohtainen)
                [0.25, -0.1],            # gamma_global, rho
            ])
        else:
            x0 = np.concatenate([prior_attack.copy(), prior_defence.copy(), [0.25, -0.1]])

        # Identifioitavuus: attack-summa = 0
        constraints = ({"type": "eq", "fun": lambda p: np.sum(p[:n])},)
        # Lisaa: per-team gamma -summa = 0 jotta gamma_global pysyy keskiarvona
        if self.per_team_home_adv:
            constraints = (
                constraints[0],
                {"type": "eq", "fun": lambda p: np.sum(p[2*n:3*n])},
            )

        result = minimize(neg_log_lik, x0, constraints=constraints,
                          method="SLSQP", options={"maxiter": 300, "disp": False})
        params = result.x
        self.attack = {t: params[i] for t, i in idx.items()}
        self.defence = {t: params[n + i] for t, i in idx.items()}
        if self.per_team_home_adv:
            self.home_advantage_per_team = {t: params[2*n + i] for t, i in idx.items()}
        else:
            self.home_advantage_per_team = {t: 0.0 for t in teams}
        self.home_advantage = params[-2]
        self.rho = params[-1]
        self.teams_ = teams
        return self

    def expected_goals(self, home_team, away_team, adjustments=None):
        if home_team not in self.attack or away_team not in self.attack:
            raise ValueError(f"Tuntematon joukkue: {home_team} tai {away_team}")
        team_gamma = self.home_advantage_per_team.get(home_team, 0.0)
        lam = np.exp(self.attack[home_team] + self.defence[away_team]
                     + self.home_advantage + team_gamma)
        mu = np.exp(self.attack[away_team] + self.defence[home_team])
        if adjustments:
            lam *= float(adjustments.get("home_factor", 1.0))
            mu *= float(adjustments.get("away_factor", 1.0))
        return float(lam), float(mu)

    def score_matrix(self, home_team, away_team, max_goals=10, adjustments=None):
        lam, mu = self.expected_goals(home_team, away_team, adjustments=adjustments)
        h = poisson.pmf(np.arange(max_goals + 1), lam)
        a = poisson.pmf(np.arange(max_goals + 1), mu)
        m = np.outer(h, a)
        for i in range(2):
            for j in range(2):
                m[i, j] *= _tau(i, j, lam, mu, self.rho)
        return m / m.sum()

    def predict_1x2(self, home_team, away_team, adjustments=None):
        m = self.score_matrix(home_team, away_team, adjustments=adjustments)
        return {"home": float(np.tril(m, -1).sum()),
                "draw": float(np.trace(m)),
                "away": float(np.triu(m, 1).sum())}

    def predict_over_under(self, home_team, away_team, line=2.5, adjustments=None):
        m = self.score_matrix(home_team, away_team, adjustments=adjustments)
        n = m.shape[0]
        i_arr = np.arange(n)[:, None]
        j_arr = np.arange(n)[None, :]
        totals = i_arr + j_arr
        over = float(m[totals > line].sum())
        under = float(m[totals < line].sum())
        return {"over": over, "under": under, "push": 1.0 - over - under}

    def predict_btts(self, home_team, away_team, adjustments=None):
        m = self.score_matrix(home_team, away_team, adjustments=adjustments)
        p_h0 = float(m[0, :].sum())
        p_a0 = float(m[:, 0].sum())
        p_00 = float(m[0, 0])
        yes = 1 - p_h0 - p_a0 + p_00
        return {"btts_yes": yes, "btts_no": 1 - yes}

    def todennakoisin_tulos(self, home_team, away_team, top_n=5, adjustments=None):
        m = self.score_matrix(home_team, away_team, adjustments=adjustments)
        rivit = [(f"{i}-{j}", float(m[i, j])) for i in range(m.shape[0]) for j in range(m.shape[1])]
        rivit.sort(key=lambda x: x[1], reverse=True)
        return rivit[:top_n]


def apply_match_adjustments(home_injury_pct=0.0, away_injury_pct=0.0,
                            home_motivation_pct=0.0, away_motivation_pct=0.0,
                            home_rest_advantage_days=0.0, is_derby=False,
                            weather_total_goals_delta=0.0):
    home = 1.0 + home_injury_pct / 100.0
    away = 1.0 + away_injury_pct / 100.0
    home *= 1.0 + home_motivation_pct / 100.0
    away *= 1.0 + away_motivation_pct / 100.0
    home *= 1.0 + 0.015 * home_rest_advantage_days
    away *= 1.0 - 0.015 * home_rest_advantage_days
    if is_derby:
        home *= 1.08
        away *= 1.08
    if weather_total_goals_delta != 0.0:
        wm = 1.0 + weather_total_goals_delta / 3.0
        home *= wm
        away *= wm
    home = max(0.3, min(2.5, home))
    away = max(0.3, min(2.5, away))
    return {"home_factor": home, "away_factor": away}

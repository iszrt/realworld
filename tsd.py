from __future__ import annotations
import math, random
from dataclasses import dataclass
from typing import Callable, List, Tuple, Optional
import numpy as np


@dataclass
class Antibody:
    x: np.ndarray
    aff: float          # affinity = -f (maximize)
    I: float = 0.0      # improvement EWMA
    J: float = 0.0      # novelty score
    tag: int = 0        # short-lived tag counter
    T: int = 0          # age
    S: int = 0          # memory or selection count


class ETFCSA_TSD:
    """
    Event-Triggered FCSA with Temporal Substrate Drift (TSD) and Rac1 forgetting.

    TSD:
      Maintain a substrate vector s in R^d.
      On each accepted improvement with delta dx = x_new - x_old, update s += eta * dx.
      All variation is applied in drifted coordinates: x_adj = x - lambda_s * s, mutate x_adj,
      then map back: x_new = clip(x_adj + lambda_s * s).
      Periodic decay: s *= rho every drift_interval evaluations.

    Rac1:
      Activity A = T / (S + eps) is used to
        1) penalize event score via exp(-gamma_rac1 * max(0, A - c_threshold))
        2) raise a mutation floor when A exceeds c_threshold
        3) reseed stale high-activity untagged individuals each tick

    Extras kept minimal:
      tiny IICO-like spark
      opposition-biased reseed with elementwise min/max bounds
      short coordinate polish at end
    """

    def __init__(
        self,
        func: Callable[[np.ndarray], float],
        bounds: List[Tuple[float, float]],
        N: int = 60,
        n_select: int = 12,
        n_clones: int = 4,
        r: float = 2.0,
        a_frac: float = 0.12,
        seed: Optional[int] = 42,
        max_evals: int = 350_000,
        fire_target: float = 0.2,
        alpha_I: float = 1.0,
        beta_J: float = 0.5,
        threshold_eta: float = 0.05,
        spark_prob: float = 0.04,
        tag_half_life: int = 250,
        clearance_period: float = 0.06,
        budget_per_tick: int = 200,
        c_threshold: float = 3.0,
        gamma_rac1: float = 0.75,
        # TSD params
        eta: float = 0.25,           # substrate learning rate
        lambda_s: float = 0.5,       # strength of coordinate shift
        rho: float = 0.98,           # decay factor for substrate
        drift_interval: int = 2000,  # evals between substrate decay
        progress: Optional[Callable[[int], None]] = None,
    ):
        self.func = func
        self.bounds = np.array(bounds, dtype=float)
        self.dim = self.bounds.shape[0]
        self.N = int(N)
        self.n_select = int(n_select)
        self.n_clones = int(n_clones)
        self.r = float(r)
        self.a_frac = float(a_frac)
        self.max_evals = int(max_evals)

        self.fire_target = float(fire_target)
        self.alpha_I = float(alpha_I)
        self.beta_J = float(beta_J)
        self.threshold_eta = float(threshold_eta)

        self.spark_prob = float(spark_prob)
        self.tag_half_life = int(tag_half_life)
        self.clear_every = max(1, int(clearance_period * self.max_evals))
        self.budget_per_tick = int(budget_per_tick)

        self.c_threshold = float(c_threshold)
        self.gamma_rac1 = float(gamma_rac1)

        self.eta = float(eta)
        self.lambda_s = float(lambda_s)
        self.rho = float(rho)
        self.drift_interval = int(drift_interval)
        # generation cap (number of outer loop iterations)
        # scale with available eval budget to avoid premature stop
        self.max_gens = max(2000, int(math.ceil(self.max_evals / max(1, self.budget_per_tick))))

        self.rng = np.random.default_rng(seed)
        if seed is not None:
            np.random.seed(seed)
            random.seed(seed)

        self.widths = self.bounds[:, 1] - self.bounds[:, 0]
        self.a_vec = self.a_frac * self.widths

        self._progress = progress
        self.evals = 0

        self.pop: List[Antibody] = []
        self.best_x: Optional[np.ndarray] = None
        self.best_f: float = float("inf")
        self.history: List[float] = []
        self.theta = 0.0
        self._grid_idx: List[int] = []
        
        # Support for initial points
        self.init_points: Optional[np.ndarray] = None

        # Temporal Substrate Drift state
        self.s = np.zeros(self.dim, dtype=float)
        self._last_decay_eval = 0

    # evaluation wrapper
    def _objective(self, x: np.ndarray) -> float:
        self.evals += 1
        # do not call per-evaluation progress here; report per-generation instead
        # substrate decay on schedule
        if self.evals - self._last_decay_eval >= self.drift_interval:
            self.s *= self.rho
            self._last_decay_eval = self.evals
        return float(self.func(x))

    # init
    def _init(self):
        self.pop.clear()
        
        # If initial points provided, use them first
        n_init = 0
        if self.init_points is not None and len(self.init_points) > 0:
            n_init = min(len(self.init_points), self.N)
            for i in range(n_init):
                x = self.init_points[i].copy()
                # Clip to bounds
                np.clip(x, self.bounds[:, 0], self.bounds[:, 1], out=x)
                f = self._objective(x)
                ab = Antibody(x=x, aff=-f)
                self.pop.append(ab)
                if f < self.best_f:
                    self.best_f, self.best_x = f, x.copy()
        
        # Fill remaining population with random individuals
        for _ in range(self.N - n_init):
            x = self.bounds[:, 0] + self.rng.random(self.dim) * self.widths
            f = self._objective(x)
            ab = Antibody(x=x, aff=-f)
            self.pop.append(ab)
            if f < self.best_f:
                self.best_f, self.best_x = f, x.copy()
                
        self._grid_idx = list(range(min(self.N, max(8, self.dim))))
        self.s[:] = 0.0
        self._last_decay_eval = self.evals

    # signals
    def _update_signals(self, idx: int, old_aff: float):
        ab = self.pop[idx]
        gain = max(0.0, ab.aff - old_aff)
        ab.I = 0.85 * ab.I + 0.15 * gain
        if self._grid_idx:
            xs = np.stack([self.pop[j].x for j in self._grid_idx], axis=0)
            d = np.linalg.norm(xs - ab.x[None, :], axis=1)
            if d.size:
                ab.J = float(np.min(d) / (np.mean(d) + 1e-12))
        if ab.tag > 0:
            ab.tag -= 1

    # TSD coordinate helpers
    def _to_drifted(self, x: np.ndarray) -> np.ndarray:
        return x - self.lambda_s * self.s

    def _from_drifted(self, x_adj: np.ndarray) -> np.ndarray:
        y = x_adj + self.lambda_s * self.s
        np.clip(y, self.bounds[:, 0], self.bounds[:, 1], out=y)
        return y

    # FCSA mutate with Rac1 floor, performed in drifted coordinates
    def _mutate_fcsa(self, x: np.ndarray, a_norm: float, A: float) -> np.ndarray:
        p_base = math.exp(-self.r * a_norm)
        over = max(0.0, A - self.c_threshold)
        p_floor = min(0.9, 0.2 + 0.15 * over)
        p = max(p_base, p_floor)

        x_adj = self._to_drifted(x)
        mask = self.rng.random(self.dim) < p
        if np.any(mask):
            step = self.rng.uniform(-self.a_vec, self.a_vec)
            x_adj2 = x_adj + mask.astype(float) * step
        else:
            x_adj2 = x_adj
        return self._from_drifted(x_adj2)

    # spark in drifted coordinates
    def _spark(self, x: np.ndarray) -> np.ndarray:
        x_adj = self._to_drifted(x)
        z = self.rng.random(self.dim)
        z = 3.99 * z * (1 - z)
        kick = (z - 0.5) * 0.5 * self.widths
        y_adj = x_adj + kick
        np.clip(y_adj, self.bounds[:, 0] - self.lambda_s * self.s,
                self.bounds[:, 1] - self.lambda_s * self.s, out=y_adj)
        y = self._from_drifted(y_adj)
        opp = self.bounds[:, 0] + self.bounds[:, 1] - y
        mid = 0.5 * (self.bounds[:, 0] + self.bounds[:, 1])
        lo = np.minimum(mid, opp)
        hi = np.maximum(mid, opp)
        y = self.rng.uniform(lo, hi)
        np.clip(y, self.bounds[:, 0], self.bounds[:, 1], out=y)
        return y

    # improvement acceptance with TSD update
    def _accept_if_better(self, ab: Antibody, x_old: np.ndarray, f_new: float, x_new: np.ndarray):
        improved = f_new < (-ab.aff)
        if improved:
            dx = x_new - x_old
            ab.x = x_new
            ab.aff = -f_new
            ab.S = max(1, ab.S + 1)
            ab.T = 0
            ab.tag = max(ab.tag, self.tag_half_life)
            # Temporal Substrate Drift update
            self.s += self.eta * dx
            if f_new < self.best_f:
                self.best_f, self.best_x = f_new, x_new.copy()
        return improved

    # one individual fire
    def _fire_one(self, i: int) -> int:
        ab = self.pop[i]
        old_aff = ab.aff
        A = ab.T / (ab.S + 1e-12)

        if self.rng.random() < self.spark_prob:
            cand = self._spark(ab.x)
        else:
            a_norm = 0.5
            cand = self._mutate_fcsa(ab.x, a_norm, A)

        f = self._objective(cand)
        self._accept_if_better(ab, ab.x.copy(), f, cand)
        self._update_signals(i, old_aff)
        return 1

    # micro cloning on hottest few, with TSD in acceptance
    def _micro_clone(self, hot_indices: List[int], budget: int) -> int:
        if budget <= 0 or not hot_indices:
            return 0
        used = 0
        hot = sorted(hot_indices, key=lambda j: self.pop[j].I, reverse=True)[:min(len(hot_indices), self.n_select)]
        affs = np.array([self.pop[j].aff for j in hot])
        a_min, a_max = float(affs.min()), float(affs.max())
        denom = max(a_max - a_min, 1e-12)

        for j in hot:
            if used >= budget:
                break
            ab = self.pop[j]
            A = ab.T / (ab.S + 1e-12)
            a_norm = (ab.aff - a_min) / denom if denom > 0 else 0.5
            k = max(1, int(round(1 + a_norm * (self.n_clones - 1))))
            for _ in range(k):
                if used >= budget: break
                y = self._mutate_fcsa(ab.x, a_norm, A)
                f = self._objective(y); used += 1
                self._accept_if_better(ab, ab.x.copy(), f, y)
        return used

    # Rac1 reseed of zombies
    def _rac1_reseed(self):
        new_pop: List[Antibody] = []
        for ab in self.pop:
            improving = ab.I > 1e-12
            A = ab.T / (ab.S + 1e-12)
            if (A > self.c_threshold) and (not improving) and (ab.tag == 0):
                if self.best_x is None:
                    y = self.bounds[:, 0] + self.rng.random(self.dim) * self.widths
                else:
                    # opposition near best in drifted sense
                    best_drifted = self._to_drifted(self.best_x)
                    opp = self.bounds[:, 0] + self.bounds[:, 1] - (best_drifted + self.lambda_s * self.s)
                    mid = 0.5 * (self.bounds[:, 0] + self.bounds[:, 1])
                    lo = np.minimum(mid, opp)
                    hi = np.maximum(mid, opp)
                    y = self.rng.uniform(lo, hi)
                np.clip(y, self.bounds[:, 0], self.bounds[:, 1], out=y)
                f = self._objective(y)
                ab = Antibody(x=y, aff=-f, tag=self.tag_half_life, T=0, S=0)
                if f < self.best_f:
                    self.best_f, self.best_x = f, y.copy()
            new_pop.append(ab)
        self.pop = new_pop

    # clearance
    def _clearance(self):
        survivors: List[Antibody] = []
        for ab in self.pop:
            if ab.tag > 0 or ab.I > 1e-12:
                survivors.append(ab)
        need = self.N - len(survivors)
        for _ in range(need):
            if self.best_x is None:
                y = self.bounds[:, 0] + self.rng.random(self.dim) * self.widths
            else:
                opp = self.bounds[:, 0] + self.bounds[:, 1] - self.best_x
                mid = 0.5 * (self.bounds[:, 0] + self.bounds[:, 1])
                lo = np.minimum(mid, opp)
                hi = np.maximum(mid, opp)
                y = self.rng.uniform(lo, hi)
            np.clip(y, self.bounds[:, 0], self.bounds[:, 1], out=y)
            f = self._objective(y)
            survivors.append(Antibody(x=y, aff=-f))
            if f < self.best_f:
                self.best_f, self.best_x = f, y.copy()
        self.pop = survivors

    # scheduler with Rac1 penalty
    def _pick_indices(self) -> List[int]:
        scores = []
        for i, ab in enumerate(self.pop):
            ab.T += 1
            A = ab.T / (ab.S + 1e-12)
            base = self.alpha_I * ab.I + self.beta_J * ab.J
            over = max(0.0, A - self.c_threshold)
            penal = math.exp(-self.gamma_rac1 * over)
            scores.append(base * penal)
        order = np.argsort(scores)[::-1]
        hot = [int(i) for i in order if scores[i] > self.theta]
        if len(hot) < max(2, self.N // 10):
            extra = self.rng.choice(self.N, size=min(self.N // 10, self.N), replace=False)
            hot = list(dict.fromkeys(list(hot) + list(map(int, extra))))
        return hot

    # final polish
    def _polish(self, steps: int = 120):
        if self.best_x is None:
            return
        x = self.best_x.copy()
        f = self.best_f
        lo, hi = self.bounds[:, 0], self.bounds[:, 1]
        step = 0.04 * self.widths
        for t in range(steps):
            d = t % self.dim
            for sgn in (+1.0, -1.0):
                cand = x.copy()
                cand[d] = np.clip(cand[d] + sgn * step[d], lo[d], hi[d])
                fc = self._objective(cand)
                if fc < f:
                    x, f = cand, fc
            step *= 0.985
            if np.max(step) < 1e-12:
                break
        if f < self.best_f:
            self.best_f, self.best_x = f, x.copy()

    # main
    def optimize(self, progress: Callable[..., None] | None = None, init_points: np.ndarray | None = None):
        """
        Run optimization.
        
        Args:
            progress: Optional progress callback
            init_points: Optional initial points as 2D array (n_points, dim)
                        These will be used to seed the initial population
        """
        # allow external progress callback to override constructor arg
        if progress is not None:
            self._progress = progress
        
        # Set initial points if provided
        if init_points is not None:
            self.init_points = init_points

        self._init()

        # ---- emit gen=0 snapshot (initial population) ----
        if self._progress is not None:
            try:
                pop_arr = np.stack([ab.x for ab in self.pop]).astype(float) if self.pop else np.empty((0, self.dim))
                fit_arr = np.array([-ab.aff for ab in self.pop], dtype=float)  # objective values
                self._progress(
                    gen=0,
                    pop=pop_arr,
                    fitness=fit_arr,
                    best_fitness=self.best_f,
                    gbest=self.best_x.copy() if self.best_x is not None else None,
                    evals=self.evals,
                )
            except Exception:
                pass

        last_clear = 0
        gen = 0

        # iterate in ticks (generations); stop when either eval budget exhausted or gen reaches max_gens
        while self.evals < self.max_evals and gen < self.max_gens:
            budget = min(self.budget_per_tick, self.max_evals - self.evals)

            hot = self._pick_indices()
            if not hot:
                self.theta *= 0.9
                # still advance generation counter to keep curves moving
                gen += 1
                continue

            b1 = max(1, budget // 2)
            b2 = budget - b1

            used = 0
            for i in hot:
                if used >= b1:
                    break
                used += self._fire_one(i)

            k = max(1, len(hot) // 3)
            used += self._micro_clone(hot[:k], b2)

            fired_fraction = len(hot) / max(1, self.N)
            self.theta += self.threshold_eta * (fired_fraction - self.fire_target)

            self._rac1_reseed()

            if self.evals - last_clear >= self.clear_every:
                self._clearance()
                last_clear = self.evals

            # track best fitness per generation
            self.history.append(self.best_f)

            # per-generation progress (use gen+1 so it follows the gen=0 snapshot)
            if self._progress is not None:
                try:
                    pop_arr = np.stack([ab.x for ab in self.pop]) if len(self.pop) > 0 else np.empty((0, self.dim))
                    fit_arr = np.array([-ab.aff for ab in self.pop], dtype=float)
                    self._progress(
                        gen=gen + 1,
                        pop=pop_arr,
                        fitness=fit_arr,
                        best_fitness=self.best_f,
                        gbest=self.best_x.copy() if self.best_x is not None else None,
                        evals=self.evals,
                    )
                except Exception:
                    pass

            gen += 1
            if self.evals >= self.max_evals:
                break
            if gen >= self.max_gens:
                break

        self._polish()

        # enforce history length cap
        if len(self.history) > self.max_gens:
            self.history = self.history[: self.max_gens]

        return self.best_x.copy(), self.best_f, {
            "evals_used": self.evals,
            "generations_run": len(self.history),
            "history": self.history,
            "substrate_norm": float(np.linalg.norm(self.s)),
        }



# demo
if __name__ == "__main__":
    def ackley(x: np.ndarray) -> float:
        a, b, c = 20.0, 0.2, 2 * np.pi
        d = x.size
        sum_sq = np.sum(x * x)
        sum_cos = np.sum(np.cos(c * x))
        return -a * np.exp(-b * np.sqrt(sum_sq / d)) - np.exp(sum_cos / d) + a + np.e

    dim = 2
    bounds = [(-5.0, 5.0)] * dim

    opt = ETFCSA_TSD(
        func=ackley,
        bounds=bounds,
        N=60,
        max_evals=50_000,
        seed=123,
        budget_per_tick=150,
        eta=0.25,
        lambda_s=0.5,
        rho=0.985,
        drift_interval=1500
    )
    xbest, fbest, info = opt.optimize()
    print("best f", fbest, "evals", info["evals_used"], "||s||", info["substrate_norm"])

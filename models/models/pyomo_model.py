"""
Pyomo-based optimization model for production planning with learning curves.
"""

import pyomo.environ as pyo
from typing import Any, Dict, List, Sequence


class MakeColorModel:
    """Builds and solves the Make-Color production planning model.

    Parameters
    ----------
    input_data : Any
        An instance of a user-defined ``InputData`` class that exposes the
        required *sets* and *parameters* as dictionaries, e.g.::

            input_data.set  – dict of iterable sets
            input_data.param – dict of scalar / indexed parameters

        The field names must match those referenced inside the model
        (``setL``, ``paramD``, etc.) exactly.
    discount_alpha : float, optional
        Annual discount rate *α* used by ``get_discount_factor``
        (default 0.05 ⇒ 5 %).
    ``kwargs`` are passed straight to the solver in :py:meth:`solve`.
    """

    def __init__(self, input_data: Any, *, discount_alpha: float = 0.05):
        self.data = input_data
        self.alpha = discount_alpha
        self.model: pyo.ConcreteModel | None = None
        self.first_t: int | None = None
        self._prev: Dict[int, int] = {}
        self._build_model()

    # Public API
    def solve(self, solver_name: str = "cplex", tee: bool = True, **solver_kwargs):
        """Solve the Pyomo model and return the solver results."""
        if self.model is None:
            raise RuntimeError("Model not yet built.")
        solver = pyo.SolverFactory(solver_name)
        for k, v in solver_kwargs.items():
            solver.options[k] = v
        results = solver.solve(self.model, tee=tee)
        return results

    def value(self, var: pyo.Component) -> Dict[Any, float]:
        """Return a dictionary of *value(var[index])* for every index."""
        return {idx: pyo.value(var[idx]) for idx in var}

    # Private helpers
    def _get_prev(self, t: int) -> int | None:
        """Return the predecessor of period *t* (or ``None`` if *t* is first)."""
        return self._prev.get(t)

    def _discount(self, t: int) -> float:
        """Calculate discount factor for period t."""
        return 1.0 / (1.0 + self.alpha) ** t

    # Model builder
    def _build_model(self):
        """Build the complete Pyomo ConcreteModel."""
        d = self.data
        m = pyo.ConcreteModel()

        # 1 – Convenience handles
        L: Sequence[str] = d.set["setL"]
        S: Sequence[str] = d.set["setS"]
        T: List[int] = sorted(d.set["setT"])
        BP = sorted(d.set["setBP"])
        Ssame = d.set["setSsame"]
        SP = d.set["setSP"]

        self.first_t = first_t = T[0]
        self._prev = {t: (T[i - 1] if i > 0 else None) for i, t in enumerate(T)}

        # 2 – Sets
        m.L = pyo.Set(initialize=L)
        m.S = pyo.Set(initialize=S)
        m.T = pyo.Set(ordered=True, initialize=T)
        m.BP = pyo.Set(ordered=True, initialize=BP)
        m.Ssame = pyo.Set(initialize=Ssame)
        m.SP = pyo.Set(initialize=SP, dimen=2)

        # 3 – Parameters
        par = d.param
        m.Csetup = pyo.Param(initialize=par["Csetup"])
        m.Plate = pyo.Param(m.S, initialize=par["Plate"])
        m.Rexp = pyo.Param(initialize=par["Rexp"])
        m.bigM = pyo.Param(initialize=par["bigM"])

        # Indexed parameters
        m.D = pyo.Param(m.S, m.T, initialize=par["paramD"], default=0, 
                        within=pyo.NonNegativeReals)
        m.F = pyo.Param(m.S, m.T, initialize=par["paramF"], default=0, 
                        within=pyo.NonNegativeReals)
        m.I0fabric = pyo.Param(m.S, initialize=par["paramI0fabric"])
        m.I0product = pyo.Param(m.S, initialize=par["paramI0product"])
        m.B0 = pyo.Param(m.S, initialize=par["paramB0"])
        m.Tfabprocess = pyo.Param(m.S, initialize=par["paramTfabprocess"])
        m.Tprodfinish = pyo.Param(m.S, initialize=par["paramTprodfinish"])
        m.Y0 = pyo.Param(m.L, m.S, initialize=par["paramY0"], within=pyo.Binary)
        m.Yenable = pyo.Param(m.L, m.S, initialize=par["paramYenable"], 
                             within=pyo.Binary)
        m.N = pyo.Param(m.L, initialize=par["paramN"])
        m.H = pyo.Param(m.L, m.T, initialize=par["paramH"])
        m.SAM = pyo.Param(m.S, initialize=par["paramSAM"])

        # Learning-curve data
        m.Xp = pyo.Param(m.BP, initialize=par["paramXp"])
        m.Fp = pyo.Param(m.BP, initialize=par["paramFp"])
        m.Exp0 = pyo.Param(m.L, initialize=par["paramExp0"])
        m.Lexp = pyo.Param(m.L, m.S, initialize=par["paramLexp"])
        m.MaxExp = pyo.Param(initialize=par["MaxExp"])

        # 4 – Decision variables
        m.P = pyo.Var(m.L, m.S, m.T, domain=pyo.NonNegativeReals)
        m.Ship = pyo.Var(m.S, m.T, domain=pyo.NonNegativeReals)
        m.BegInv_fab = pyo.Var(m.S, m.T, domain=pyo.NonNegativeReals)
        m.EndInv_fab = pyo.Var(m.S, m.T, domain=pyo.NonNegativeReals)
        m.BegInv_prod = pyo.Var(m.S, m.T, domain=pyo.NonNegativeReals)
        m.EndInv_prod = pyo.Var(m.S, m.T, domain=pyo.NonNegativeReals)
        m.B = pyo.Var(m.S, m.T, domain=pyo.NonNegativeReals)
        m.Y = pyo.Var(m.L, m.S, m.T, domain=pyo.Binary)
        m.Z = pyo.Var(m.L, m.SP, m.T, domain=pyo.Binary)
        m.Exp = pyo.Var(m.L, m.T, domain=pyo.NonNegativeReals, bounds=(1, m.MaxExp))
        m.Eff = pyo.Var(m.L, m.T, domain=pyo.NonNegativeReals, bounds=(0, 1))
        m.change = pyo.Var(m.L, m.T, domain=pyo.NonNegativeReals, bounds=(0, 1))
        m.U = pyo.Var(m.L, m.T, domain=pyo.Binary)

        # 5 – Objective components
        def setup_cost_rule(m):
            return sum(
                m.Csetup * m.Z[l, (sp, s), t] * self._discount(t)
                for l in m.L
                for (sp, s) in m.SP
                for t in m.T
            )

        m.setup_cost = pyo.Expression(rule=setup_cost_rule)

        def late_pen_rule(m):
            return sum(
                m.Plate[s] * m.B[s, t] * self._discount(t) 
                for s in m.S 
                for t in m.T
            )

        m.late_pen = pyo.Expression(rule=late_pen_rule)

        def exp_accum_rule(m):
            return sum(m.Rexp * m.Exp[l, t] for l in m.L for t in m.T)

        m.exp_accum = pyo.Expression(rule=exp_accum_rule)

        m.Obj = pyo.Objective(
            expr=m.setup_cost + m.late_pen - m.exp_accum, sense=pyo.minimize
        )

        # 6 – Constraints
        self._build_constraints(m, first_t)

        # Save reference
        self.model = m

    def _build_constraints(self, m, first_t):
        """Build all model constraints."""
        
        # 6.1 Fabric balance & usage limits
        def beg_inv_fab(m, s, t):
            LT = m.Tfabprocess[s]
            beg = m.I0fabric[s] if t == first_t else m.EndInv_fab[s, self._get_prev(t)]
            usable = m.F[s, t - LT] if t > LT else 0
            return m.BegInv_fab[s, t] == beg + usable

        m.beg_inv_fab = pyo.Constraint(m.S, m.T, rule=beg_inv_fab)

        def end_inv_fab(m, s, t):
            return m.EndInv_fab[s, t] == m.BegInv_fab[s, t] - sum(
                m.P[l, s, t] for l in m.L
            )

        m.end_inv_fab = pyo.Constraint(m.S, m.T, rule=end_inv_fab)

        def prod_limit(m, s, t):
            return sum(m.P[l, s, t] for l in m.L) <= m.BegInv_fab[s, t]

        m.prod_limit = pyo.Constraint(m.S, m.T, rule=prod_limit)

        # 6.2 Shipment & product inventory
        def beg_inv_prod(m, s, t):
            LT = m.Tprodfinish[s]
            beg = m.I0product[s] if t == first_t else m.EndInv_prod[s, self._get_prev(t)]
            finished = sum(m.P[l, s, t - LT] for l in m.L) if t > LT else 0
            return m.BegInv_prod[s, t] == beg + finished

        m.beg_inv_prod = pyo.Constraint(m.S, m.T, rule=beg_inv_prod)

        def end_inv_prod(m, s, t):
            return m.EndInv_prod[s, t] == m.BegInv_prod[s, t] - m.Ship[s, t]

        m.end_inv_prod = pyo.Constraint(m.S, m.T, rule=end_inv_prod)

        def ship_limit(m, s, t):
            return m.Ship[s, t] <= m.BegInv_prod[s, t]

        m.ship_limit = pyo.Constraint(m.S, m.T, rule=ship_limit)

        # 6.3 Backlog recursion
        def backlog_bal(m, s, t):
            if t == first_t:
                return m.B[s, t] == m.B0[s] + m.D[s, t] - m.Ship[s, t]
            return m.B[s, t] == m.B[s, self._get_prev(t)] + m.D[s, t] - m.Ship[s, t]

        m.backlog_bal = pyo.Constraint(m.S, m.T, rule=backlog_bal)

        # 6.4 Exactly one style per line-day
        m.one_style = pyo.Constraint(
            m.L, m.T, rule=lambda m, l, t: sum(m.Y[l, s, t] for s in m.S) == 1
        )

        m.line_enable_style = pyo.Constraint(
            m.L,
            m.S,
            m.T,
            rule=lambda m, l, s, t: m.Y[l, s, t] <= m.Yenable[l, s],
        )

        m.bigM_prod = pyo.Constraint(
            m.L, m.S, m.T, rule=lambda m, l, s, t: m.P[l, s, t] <= m.bigM * m.Y[l, s, t]
        )

        # 6.5 Switch identification
        def sw_lb_first(m, l, sp, s):
            t = first_t
            return m.Z[l, (sp, s), t] >= m.Y0[l, sp] + m.Y[l, s, t] - 1

        m.sw_lb_first = pyo.Constraint(m.L, m.SP, rule=sw_lb_first)

        def sw_lb_roll(m, l, sp, s, t):
            if t == first_t:
                return pyo.Constraint.Skip
            return (
                m.Z[l, (sp, s), t] >= m.Y[l, sp, self._get_prev(t)] + m.Y[l, s, t] - 1
            )

        m.sw_lb_roll = pyo.Constraint(m.L, m.SP, m.T, rule=sw_lb_roll)

        m.sw_ub1 = pyo.Constraint(
            m.L, m.SP, m.T, rule=lambda m, l, sp, s, t: m.Z[l, (sp, s), t] <= m.Y[l, s, t]
        )

        def sw_ub2(m, l, sp, s, t):
            if t == first_t:
                return m.Z[l, (sp, s), t] <= m.Y0[l, sp]
            return m.Z[l, (sp, s), t] <= m.Y[l, sp, self._get_prev(t)]

        m.sw_ub2 = pyo.Constraint(m.L, m.SP, m.T, rule=sw_ub2)

        # 6.6 Utilisation / experience logic
        def U_lower(m, l, t):
            if m.H[l, t] == 0:
                return m.U[l, t] == 0
            minutes = sum(m.SAM[s] * m.P[l, s, t] for s in m.S)
            thresh = 0.5 * m.H[l, t] * 60 * m.N[l] * m.Eff[l, t]
            return minutes - thresh + m.bigM * (1 - m.U[l, t]) >= 0

        m.U_lower = pyo.Constraint(m.L, m.T, rule=U_lower)

        def U_upper(m, l, t):
            if m.H[l, t] == 0:
                return m.U[l, t] == 0
            eps = 1e-6
            minutes = sum(m.SAM[s] * m.P[l, s, t] for s in m.S)
            thresh = 0.5 * m.H[l, t] * 60 * m.N[l] * m.Eff[l, t]
            return minutes - thresh - eps <= m.bigM * m.U[l, t]

        m.U_upper = pyo.Constraint(m.L, m.T, rule=U_upper)

        m.Change_constraint = pyo.Constraint(
            m.L,
            m.T,
            rule=lambda m, l, t: m.change[l, t]
            == sum(
                m.Z[l, (sp, s), t]
                for (s, sp) in m.SP
                if (s, sp) not in m.Ssame
            ),
        )

        # Experience recursion
        def exp_init_lo(m, l):
            return m.Exp[l, first_t] >= m.Exp0[l] - m.MaxExp * m.change[l, first_t]

        def exp_init_hi(m, l):
            return m.Exp[l, first_t] <= m.Exp0[l] + m.MaxExp * m.change[l, first_t]

        m.exp_init_lo = pyo.Constraint(m.L, rule=exp_init_lo)
        m.exp_init_hi = pyo.Constraint(m.L, rule=exp_init_hi)

        def exp_rec_lo(m, l, t):
            if t == first_t:
                return pyo.Constraint.Skip
            return (
                m.Exp[l, t]
                >= m.Exp[l, self._get_prev(t)]
                + m.U[l, self._get_prev(t)]
                - m.MaxExp * m.change[l, t]
            )

        def exp_rec_hi(m, l, t):
            if t == first_t:
                return pyo.Constraint.Skip
            return (
                m.Exp[l, t]
                <= m.Exp[l, self._get_prev(t)]
                + m.U[l, self._get_prev(t)]
                + m.MaxExp * m.change[l, t]
            )

        m.exp_rec_lo = pyo.Constraint(m.L, m.T, rule=exp_rec_lo)
        m.exp_rec_hi = pyo.Constraint(m.L, m.T, rule=exp_rec_hi)

        def exp_bounds_lo(m, l, t):
            return (
                m.Exp[l, t]
                >= sum(m.Lexp[l, s] * m.Z[l, (sp, s), t] for (s, sp) in m.SP)
                - m.MaxExp * (1 - m.change[l, t])
            )

        def exp_bounds_hi(m, l, t):
            return (
                m.Exp[l, t]
                <= sum(m.Lexp[l, s] * m.Z[l, (sp, s), t] for (s, sp) in m.SP)
                + m.MaxExp * (1 - m.change[l, t])
            )

        m.exp_bounds_lo = pyo.Constraint(m.L, m.T, rule=exp_bounds_lo)
        m.exp_bounds_hi = pyo.Constraint(m.L, m.T, rule=exp_bounds_hi)

        # Learning curve (piecewise SOS2)
        xp_list = [pyo.value(m.Xp[p]) for p in m.BP]
        fp_list = [pyo.value(m.Fp[p]) for p in m.BP]
        m.LC_PW = pyo.Piecewise(
            m.L,
            m.T,
            m.Eff,
            m.Exp,
            pw_pts=xp_list,
            f_rule=fp_list,
            pw_constr_type="EQ",
            pw_repn="SOS2",
        )

        # Capacity with variable efficiency
        def capacity(m, l, s, t):
            return m.SAM[s] * m.P[l, s, t] <= m.H[l, t] * 60 * m.N[l] * m.Eff[l, t]

        m.capacity = pyo.Constraint(m.L, m.S, m.T, rule=capacity)

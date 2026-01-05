"""
ALNS Operator - Acts as both Solution Evaluator and Repair Operator.
Handles production simulation, inventory, backlog, learning curves,
and intelligent repair (Greedy Insertion) logic.
"""

import copy
from collections import defaultdict
from typing import Dict, Set, Any, List
import random
import numpy as np


class ALNSOperator:
    """
    Acts as a Repair Operator within the heuristic framework.
    It repairs infeasible/missing assignments using Greedy Insertion before evaluation.
    """

    def __init__(
        self, input_data, cap_map: Dict[str, Set[str]], discount_alpha: float
    ):
        """
        Parameters
        ----------
        input_data : InputData
            Problem data
        cap_map : Dict[str, Set[str]]
            Line -> allowed styles mapping
        discount_alpha : float
            Discount rate for time value
        """
        self.input = input_data
        self.cap_map = cap_map
        self.alpha = discount_alpha
        self.precomputed = self._precompute_data()
        
        # Pre-calculate priority of styles based on total demand
        self.style_priority = self._calculate_style_priority()

    def _discount(self, t: int) -> float:
        """Calculate discount factor for period t."""
        return 1.0 / (1.0 + self.alpha) ** t

    def _calculate_style_priority(self) -> List[str]:
        """Rank styles by total demand descending (for Greedy Insertion)."""
        demands = {
            s: sum(self.input.param["paramD"].get((s, t), 0) for t in self.input.set["setT"])
            for s in self.input.set["setS"]
        }
        return sorted(demands, key=demands.get, reverse=True)

    def _is_allowed(self, line: str, style: str) -> bool:
        """Check if line can produce style."""
        return style in self.cap_map[line]

    def _precompute_data(self) -> Dict:
        """Precompute frequently accessed data."""
        precomputed = {"style_sam": {}, "line_capacity": {}}

        for s in self.input.set["setS"]:
            precomputed["style_sam"][s] = self.input.param["paramSAM"][s]

        for l in self.input.set["setL"]:
            precomputed["line_capacity"][l] = [
                self.input.param["paramH"].get((l, t), 0)
                * 60
                * self.input.param["paramN"][l]
                for t in self.input.set["setT"]
            ]

        return precomputed

    def initialize_solution(self) -> Dict:
        """
        Create initial solution using Greedy Insertion strategy.
        Assigns highest priority allowed style to each line.
        """
        solution = {"assignment": {}}
        
        for l in self.input.set["setL"]:
            # Find the highest priority style allowed on this line
            best_style = None
            for s in self.style_priority:
                if self._is_allowed(l, s):
                    best_style = s
                    break
            
            # Fallback if no style from priority list is allowed
            if best_style is None:
                if self.cap_map[l]:
                    best_style = random.choice(list(self.cap_map[l]))

            for t in self.input.set["setT"]:
                if best_style:
                    solution["assignment"][(l, t)] = best_style

        return self.repair_and_evaluate(solution)

    def get_efficiency(self, exp_days: float) -> float:
        """
        Get efficiency from learning curve via linear interpolation.
        """
        curve = [
            (self.input.param["paramXp"][p], self.input.param["paramFp"][p])
            for p in self.input.set["setBP"]
        ]

        if exp_days <= curve[0][0]:
            return curve[0][1]
        if exp_days >= curve[-1][0]:
            return curve[-1][1]

        for i in range(len(curve) - 1):
            x1, y1 = curve[i]
            x2, y2 = curve[i + 1]
            if x1 <= exp_days <= x2:
                return y1 + (y2 - y1) * (exp_days - x1) / (x2 - x1)

        return curve[-1][1]

    def _greedy_repair_move(self, line: str, current_t: int, assignment: Dict) -> str | None:
        """
        ALNS Greedy Insertion Operator for a single slot.
        Prioritizes:
        1. Consistency (same as previous day) to reduce setup.
        2. High demand styles.
        """
        allowed = self.cap_map[line]
        if not allowed:
            return None

        # 1. Try to maintain continuity (Setup cost reduction)
        prev_t = current_t - 1
        if prev_t in self.input.set["setT"]:
            prev_style = assignment.get((line, prev_t))
            if prev_style in allowed:
                # Simple probabilistic check to allow breaking blocks rarely
                if random.random() < 0.8: 
                    return prev_style

        # 2. Greedy by Priority (Backlog reduction)
        for s in self.style_priority:
            if s in allowed:
                return s
        
        return random.choice(list(allowed))

    def repair_and_evaluate(self, solution: Dict) -> Dict:
        """
        Main function:
        1. REPAIR: Fixes infeasible/missing assignments (ALNS Repair).
        2. EVALUATE: Simulates production to compute costs.

        Parameters
        ----------
        solution : Dict
            Solution with 'assignment' key (line, time) -> style

        Returns
        -------
        Dict
            Complete solution with production, costs, backlog, etc.
        """
        assignment = solution.get("assignment", {})
        
        # --- PHASE 1: ALNS REPAIR (Greedy Insertion) ---
        # Fix capability violations or missing values
        for l in self.input.set["setL"]:
            # Sort time to encourage continuity repair
            sorted_t = sorted(self.input.set["setT"])
            for t in sorted_t:
                s = assignment.get((l, t))
                
                # If invalid or missing, apply greedy repair
                if s is None or not self._is_allowed(l, s):
                    repaired_style = self._greedy_repair_move(l, t, assignment)
                    if repaired_style:
                        assignment[(l, t)] = repaired_style

        solution["assignment"] = assignment
        
        # --- PHASE 2: EVALUATION (Simulation) ---
        move_type = solution.get("type")

        # Initialize solution tracking
        solution.update(
            {
                "production": {},
                "shipment": {},
                "changes": {},
                "experience": {},
                "efficiency": {},
            }
        )

        # Initialize inventories and backlog
        inv_fab = defaultdict(
            float, copy.deepcopy(self.input.param["paramI0fabric"])
        )
        inv_prod = defaultdict(
            float, copy.deepcopy(self.input.param["paramI0product"])
        )
        backlog = copy.deepcopy(self.input.param["paramB0"])

        setup_cost = late_cost = exp_reward = 0.0

        # Line states (current style, experience)
        line_states = {
            l: dict(
                current_style=self._get_initial_style(l),
                exp=self.input.param["paramExp0"].get(l, 0),
                up_exp=0,
            )
            for l in self.input.set["setL"]
        }

        # Production history for lead time lookback
        daily_prod_history = defaultdict(lambda: defaultdict(float))

        # Main simulation loop
        for t in sorted(self.input.set["setT"]):
            # Fabric arrivals
            for s in self.input.set["setS"]:
                LT_f = self.input.param["paramTfabprocess"][s]
                inv_fab[s] += self.input.param["paramF"].get(
                    (s, t - LT_f), 0
                )

            # Production decisions
            pot_prod = {s: [] for s in self.input.set["setS"]}

            for l in self.input.set["setL"]:
                st = line_states[l]
                st["exp"] += st["up_exp"]  # Carry over yesterday's update

                new_style = assignment.get((l, t))
                work_day = self.input.param["paramH"].get((l, t), 0) > 0

                if new_style is None: 
                    # If still None (no capabilities), skip
                    st["up_exp"] = 0
                    continue

                # Style change & setup cost
                if st["current_style"] != new_style:
                    solution["changes"][
                        (l, st["current_style"], new_style, t)
                    ] = 1
                    setup_cost += (
                        self.input.param["Csetup"] * self._discount(t)
                    )

                    # Reset experience if not same family
                    if (
                        st["current_style"],
                        new_style,
                    ) not in self.input.set["setSsame"]:
                        st["exp"] = self.input.param["paramLexp"][
                            l, new_style
                        ]

                # Record experience & efficiency
                solution["experience"][(l, t)] = st["exp"]
                eff = self.get_efficiency(st["exp"])
                solution["efficiency"][(l, t)] = eff

                # Experience reward
                exp_reward += st["exp"] * self.input.param["Rexp"]

                # Potential capacity on working day
                if (
                    work_day
                    and self.precomputed["style_sam"].get(new_style, 0) > 0
                ):
                    cap_min = self.precomputed["line_capacity"][l][t - 1]
                    sam = self.precomputed["style_sam"][new_style]
                    max_p = (cap_min * eff) / sam
                    pot_prod[new_style].append({"line": l, "max_p": max_p})
                    st["up_exp"] = 0  # Default, may change
                else:
                    st["up_exp"] = 0

                st["current_style"] = new_style

            # Realize production
            for s, items in pot_prod.items():
                total_cap = sum(i["max_p"] for i in items)
                actual_p = min(total_cap, inv_fab[s])

                daily_prod_history[s][t] = actual_p
                inv_fab[s] -= actual_p

                # Split across lines proportionally
                if total_cap > 0:
                    for i in items:
                        share = actual_p * i["max_p"] / total_cap
                        solution["production"][(i["line"], s, t)] = share

                        # Experience bump if worked enough
                        if share >= 0.5 * i["max_p"]:
                            line_states[i["line"]]["up_exp"] = 1

            # Shipments & backlog
            for s in self.input.set["setS"]:
                LT_p = self.input.param["paramTprodfinish"][s]
                finished = daily_prod_history[s].get(t - LT_p, 0.0)
                inv_prod[s] += finished

                to_ship = backlog[s] + self.input.param["paramD"].get(
                    (s, t), 0
                )
                ship_qty = min(inv_prod[s], to_ship)

                solution["shipment"][(s, t)] = ship_qty
                inv_prod[s] -= ship_qty
                backlog[s] = to_ship - ship_qty

                if backlog[s] > 1e-6:
                    late_cost += (
                        backlog[s]
                        * self.input.param["Plate"][s]
                        * self._discount(t)
                    )

        # Finalize solution
        solution.update(
            {
                "final_backlog": backlog,
                "total_setup": setup_cost,
                "total_late": late_cost,
                "total_exp": exp_reward,
                "total_cost": setup_cost + late_cost - exp_reward,
            }
        )

        if move_type:
            solution["type"] = move_type

        return solution

    def _get_initial_style(self, line: str) -> str | None:
        """Get initial style assignment for a line from paramY0."""
        if "paramY0" in self.input.param:
            for s in self.input.set["setS"]:
                if self.input.param["paramY0"].get((line, s), 0) == 1:
                    return s
        return None

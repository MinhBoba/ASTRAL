import copy
from collections import defaultdict
import random
import numpy as np

class ALNSOperator:
    """
    Acts as the Evaluator and Repairer based on the original logic.
    Encapsulates simulation, cost calculation, and greedy repair.
    """

    def __init__(self, input_data, cap_map, discount_alpha):
        self.input = input_data
        self.cap_map = cap_map
        self.alpha = discount_alpha
        self.precomputed = self._precompute_data()

    def _precompute_data(self):
        precomputed = {'style_sam': {}, 'line_capacity': {}}
        for s in self.input.set['setS']:
            precomputed['style_sam'][s] = self.input.param['paramSAM'][s]
        for l in self.input.set['setL']:
            precomputed['line_capacity'][l] = [
                self.input.param['paramH'].get((l, t), 0) * 60 * self.input.param['paramN'][l]
                for t in self.input.set['setT']
            ]
        return precomputed

    def _discount(self, t: int) -> float:
        return 1.0 / (1.0 + self.alpha) ** t

    def _is_allowed(self, line, style):
        return style in self.cap_map[line]

    def _random_allowed_style(self, line):
        return random.choice(list(self.cap_map[line]))

    def _get_initial_style(self, line):
        if 'paramY0' in self.input.param:
            for s in self.input.set['setS']:
                if self.input.param['paramY0'].get((line, s), 0) == 1:
                    return s
        return None

    def get_efficiency(self, exp_days):
        curve = [(self.input.param['paramXp'][p], self.input.param['paramFp'][p]) 
                 for p in self.input.set['setBP']]
        if exp_days <= curve[0][0]:
            return curve[0][1]
        if exp_days >= curve[-1][0]:
            return curve[-1][1]
        for i in range(len(curve) - 1):
            x1, y1 = curve[i]
            x2, y2 = curve[i+1]
            if x1 <= exp_days <= x2:
                return y1 + (y2 - y1) * (exp_days - x1) / (x2 - x1)
        return curve[-1][1]

    def initialize_solution(self):
        """Creates the initial solution using the logic from the old code."""
        solution = {'assignment': {}}
        for l in self.input.set['setL']:
            allowed = self.cap_map[l]
            # Find style with max total demand allowed on this line
            demands = {
                s: sum(self.input.param['paramD'].get((s, t), 0)
                for t in self.input.set['setT'])
                for s in allowed
            }
            if not demands:
                initial_style = self._random_allowed_style(l)
            else:
                initial_style = max(demands, key=demands.get)
            
            for t in self.input.set['setT']:
                solution['assignment'][(l, t)] = initial_style
        
        return self.repair_and_evaluate(solution)

    def repair_and_evaluate(self, solution):
        """
        The CORE logic from the old code. 
        1. Fixes invalid assignments (Repair).
        2. Simulates production (Evaluate).
        """
        assignment = solution.get('assignment', {})
        
        # --- REPAIR: Fix invalid assignments ---
        for (l, t), s in list(assignment.items()):
            if not self._is_allowed(l, s):
                # print(f'{(l,s)} is not allowed, repairing...')
                assignment[(l, t)] = self._random_allowed_style(l)
        
        solution['assignment'] = assignment

        # --- EVALUATE: Initialize Simulation State ---
        move_type = solution.get("type")
        solution.update({
            "production":  {},
            "shipment":    {},
            "changes":     {},
            "experience":  {},
            "efficiency":  {}
        })

        inv_fab  = defaultdict(float, copy.deepcopy(self.input.param["paramI0fabric"]))
        inv_prod = defaultdict(float, copy.deepcopy(self.input.param["paramI0product"]))
        backlog  = copy.deepcopy(self.input.param["paramB0"])

        setup_cost = late_cost = exp_reward = 0.0

        line_states = {
            l: dict(current_style=self._get_initial_style(l),
                    exp=self.input.param["paramExp0"].get(l, 0),
                    up_exp=0)
            for l in self.input.set["setL"]
        }

        # Keep history of daily production by style so we can look back LT days
        daily_prod_history = defaultdict(lambda: defaultdict(float))

        # --- MAIN SIMULATION LOOP ---
        for t in sorted(self.input.set["setT"]):

            # 1. Fabric Receipts
            for s in self.input.set["setS"]:
                LT_f = self.input.param["paramTfabprocess"][s]
                inv_fab[s] += self.input.param["paramF"].get((s, t - LT_f), 0)

            # 2. Decide Production
            pot_prod = {s: [] for s in self.input.set["setS"]}

            for l in self.input.set["setL"]:
                st = line_states[l]
                st["exp"] += st["up_exp"] # carry-over yesterday’s update
                
                new_style = assignment.get((l, t))
                work_day  = self.input.param["paramH"].get((l, t), 0) > 0
                
                if new_style is None: # Should be fixed by repair, but safety check
                    st["up_exp"] = 0
                    continue

                # Style change & setup cost
                if st["current_style"] != new_style:
                    solution["changes"][(l, st["current_style"], new_style, t)] = 1
                    setup_cost += (self.input.param["Csetup"] * self._discount(t))

                    # Reset experience if styles are not in the same “family”
                    if (st["current_style"], new_style) not in self.input.set["setSsame"]:
                        st["exp"] = self.input.param["paramLexp"].get((l, new_style), 0)

                # Record experience & efficiency
                solution["experience"][(l, t)] = st["exp"]
                eff = self.get_efficiency(st["exp"])
                solution["efficiency"][(l, t)] = eff

                # Experience reward (discounted)
                exp_reward += st["exp"] * self.input.param["Rexp"]

                # Potential capacity on a working day
                if work_day and self.precomputed["style_sam"].get(new_style, 0) > 0:
                    cap_min = self.precomputed["line_capacity"][l][t - 1]
                    sam     = self.precomputed["style_sam"][new_style]
                    max_p   = (cap_min * eff) / sam
                    pot_prod[new_style].append({"line": l, "max_p": max_p})
                    st["up_exp"] = 0 # Default, set to 1 if share is high enough
                else:
                    st["up_exp"] = 0

                st["current_style"] = new_style

            # 3. Realise Production
            for s, items in pot_prod.items():
                total_cap = sum(i["max_p"] for i in items)
                actual_p  = min(total_cap, inv_fab[s])

                daily_prod_history[s][t] = actual_p
                inv_fab[s] -= actual_p

                # Split across lines proportionally
                if total_cap > 0:
                    for i in items:
                        share = actual_p * i["max_p"] / total_cap
                        solution["production"][(i["line"], s, t)] = share
                        # Experience bump if “worked enough”
                        if share >= 0.5 * i["max_p"]:
                            line_states[i["line"]]["up_exp"] = 1

            # 4. Shipments & Backlog
            for s in self.input.set["setS"]:
                LT_p = self.input.param["paramTprodfinish"][s]
                finished = daily_prod_history[s].get(t - LT_p, 0.0)
                inv_prod[s] += finished

                to_ship = backlog[s] + self.input.param["paramD"].get((s, t), 0)
                ship_qty = min(inv_prod[s], to_ship)

                solution["shipment"][(s, t)] = ship_qty
                inv_prod[s] -= ship_qty
                backlog[s]  = to_ship - ship_qty

                if backlog[s] > 1e-6:
                    late_cost += (backlog[s] *
                                self.input.param["Plate"][s] *
                                self._discount(t))

        # --- FINALIZE ---
        solution.update({
            "final_backlog": backlog,
            "total_setup":   setup_cost,
            "total_late":    late_cost,
            "total_exp":     exp_reward,
            "total_cost":    setup_cost + late_cost - exp_reward
        })

        if move_type:
            solution["type"] = move_type
            
        return solution

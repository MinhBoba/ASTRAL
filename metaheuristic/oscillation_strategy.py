import random
import copy

class StrategicOscillationHandler:
    def __init__(self, input_data, evaluator):
        self.input = input_data
        self.evaluator = evaluator
        self.lines = list(self.input.set['setL'])
        self.times = sorted(list(self.input.set['setT']))

    def explore_infeasible_region(self, current_solution):
        """
        [RELAX] Generate a solution that violates constraints.
        Objective: force backlog styles into the production schedule regardless of capability.
        """
        shaken_solution = copy.deepcopy(current_solution)
        assignment = shaken_solution['assignment']
        
        # collect list of backlog styles (convert to IDs)
        backlog_map = current_solution.get('final_backlog', {})
        high_risk_ids = []
        for s_name, qty in backlog_map.items():
            if qty > 0:
                s_id = self.evaluator.style_to_id.get(s_name)
                if s_id is not None:
                    high_risk_ids.append(s_id)
        
        # if no backlog, random perturbation to shake things up
        if not high_risk_ids:
            return self._random_perturbation(shaken_solution)

        # force late styles into random slots (Infeasible Injection)
        # change about 5-8% of total slots
        num_changes = max(5, int(len(self.lines) * len(self.times) * 0.08))
        
        for _ in range(num_changes):
            l = random.choice(self.lines)
            t = random.choice(self.times)
            s_forced = random.choice(high_risk_ids)
            
            # assign directly, skip _is_allowed check
            assignment[(l, t)] = s_forced
            
        return shaken_solution

    def _random_perturbation(self, solution):
        """Randomly shuffle when there is no backlog to break the current structure."""
        assignment = solution['assignment']
        all_style_ids = list(self.evaluator.style_to_id.values())
        
        for _ in range(15):
            l = random.choice(self.lines)
            t = random.choice(self.times)
            s_id = random.choice(all_style_ids)
            assignment[(l, t)] = s_id
        return solution

    def aggressive_repair(self, infeasible_solution):
        """
        [REPAIR] Aggressively repair to restore feasibility.
        Logic: if Line A holds style X (illegal), find Line B (legal) to swap X to,
        even if that means pushing Line B's style Y out.
        """
        repaired_assign = copy.deepcopy(infeasible_solution['assignment'])
        
        # iterate over the entire grid
        for l in self.lines:
            for t in self.times:
                s_id = repaired_assign.get((l, t))
                
                # if we encounter a violation (Line l assigned style s_id not allowed)
                if s_id is not None and not self.evaluator._is_allowed(l, s_id):
                    
                    # find "reinforcements": other lines that can do s_id at time t
                    candidates = [
                        cl for cl in self.lines 
                        if cl != l and self.evaluator._is_allowed(cl, s_id)
                    ]
                    
                    fixed = False
                    if candidates:
                        # randomly pick a reinforcer
                        l_target = random.choice(candidates)
                        s_target_current = repaired_assign.get((l_target, t))
                        
                        # -- SWAP --
                        # 1. move the incorrect item (s_id) to the correct line (l_target)
                        repaired_assign[(l_target, t)] = s_id
                        
                        # 2. handle the displaced style (s_target_current)
                        # if line l can do s_target_current then swap, otherwise random
                        if s_target_current is not None and self.evaluator._is_allowed(l, s_target_current):
                            repaired_assign[(l, t)] = s_target_current
                        else:
                            repaired_assign[(l, t)] = self.evaluator._random_allowed_style_id(l)
                        
                        fixed = True
                    
                    if not fixed:
                        # if no one can rescue, remove violating style and assign a random allowed one
                        repaired_assign[(l, t)] = self.evaluator._random_allowed_style_id(l)

        # recompute cost after structure has been fixed
        return self.evaluator.repair_and_evaluate({'assignment': repaired_assign})

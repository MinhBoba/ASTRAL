"""
Neighbor generation strategies for Tabu Search & ALNS.
v2 includes:
Algorithm optimization use dict istead of deepcopy and add ALNS destroy operators.
"""

import random
from typing import Dict, List, Any, Set, Tuple


class NeighborGenerator:
    """
    Generates neighbors using:
    1. Local Moves (Swap, Reassign)
    2. ALNS Destroy Operators (Random, Worst-Setup, Zone/Shaw)
    """

    def __init__(self, input_data, cap_map: Dict[str, Set[str]]):
        self.input = input_data
        self.cap_map = cap_map
        self.lines = list(self.input.set["setL"])
        self.times = sorted(list(self.input.set["setT"]))

    def _fast_copy_assignment(self, assignment: Dict) -> Dict:
        """
        Optimization: Shallow copy is enough for flat dictionary.
        Much faster than copy.deepcopy().
        """
        return assignment.copy()

    def generate_neighbors(
        self, base_solution: Dict, mo_probability: float, evaluator
    ) -> List[Dict]:
        """
        Master method generating both Local Search moves and ALNS moves.
        """
        neighbors = []

        # 1. Traditional Local Moves (Fast)
        neighbors.extend(self._generate_local_moves(base_solution, evaluator))

        # 2. ALNS Destroy-Repair Moves (Smarter)
        # Only run if probability allows or if local moves found nothing
        if random.random() < mo_probability:
            alns_neighbors = self._generate_alns_moves(base_solution, evaluator)
            neighbors.extend(alns_neighbors)

        return neighbors

    # =========================================================================
    # TRADITIONAL LOCAL MOVES (Optimized)
    # =========================================================================

    def _generate_local_moves(self, base_solution: Dict, evaluator) -> List[Dict]:
        neighbors = []
        base_assign = base_solution["assignment"]
        
        # Limit number of random moves to keep speed high
        num_moves = min(len(self.lines) * len(self.times) // 2, 20)

        for _ in range(num_moves):
            move_type = random.choice(["swap", "reassign_single"])
            new_assign = self._fast_copy_assignment(base_assign)
            l = random.choice(self.lines)

            changed = False
            if move_type == "swap" and len(self.times) >= 2:
                t1, t2 = random.sample(self.times, 2)
                if new_assign.get((l, t1)) != new_assign.get((l, t2)):
                    new_assign[(l, t1)], new_assign[(l, t2)] = (
                        new_assign[(l, t2)],
                        new_assign[(l, t1)],
                    )
                    changed = True

            else:  # reassign_single
                t = random.choice(self.times)
                # Random valid style
                current_s = new_assign.get((l, t))
                allowed = list(self.cap_map[l])
                if len(allowed) > 1:
                    new_s = random.choice(allowed)
                    if new_s != current_s:
                        new_assign[(l, t)] = new_s
                        changed = True

            if changed:
                # Evaluator will fix simple constraints if needed
                neighbors.append(
                    evaluator.repair_and_evaluate({"assignment": new_assign})
                )

        return neighbors

    # =========================================================================
    # ALNS DESTROY OPERATORS
    # =========================================================================

    def _generate_alns_moves(self, base_solution: Dict, evaluator) -> List[Dict]:
        """Apply Destroy operators, then let Evaluator (ALNS Operator) Repair."""
        moves = []
        base_assign = base_solution["assignment"]
        
        # Destroy magnitude (remove 5% to 20% of solution)
        total_slots = len(self.lines) * len(self.times)
        num_remove = random.randint(max(1, int(total_slots * 0.05)), int(total_slots * 0.2))

        # 1. Random Removal
        moves.append(self._destroy_random(base_assign, num_remove, evaluator))

        # 2. Worst Setup Removal (Target changeovers)
        moves.append(self._destroy_worst_setup(base_assign, num_remove, evaluator))

        # 3. Zone Removal (Spatial/Shaw approximation)
        moves.append(self._destroy_zone(base_assign, num_remove, evaluator))

        return [m for m in moves if m is not None]

    def _destroy_random(self, assignment: Dict, n: int, evaluator) -> Dict:
        """Randomly unassign N slots."""
        new_assign = self._fast_copy_assignment(assignment)
        keys = list(new_assign.keys())
        
        # Destroy
        for k in random.sample(keys, min(n, len(keys))):
            new_assign[k] = None  # None triggers Greedy Repair in ALNS_operator
            
        return evaluator.repair_and_evaluate({"assignment": new_assign, "type": "alns_random"})

    def _destroy_worst_setup(self, assignment: Dict, n: int, evaluator) -> Dict:
        """
        Target slots that cause setup changes.
        Removing them allows the repair heuristic to potentially merge segments.
        """
        new_assign = self._fast_copy_assignment(assignment)
        candidates = []

        for l in self.lines:
            for i in range(1, len(self.times)):
                t_prev = self.times[i-1]
                t_curr = self.times[i]
                # If there is a change, mark the current day for potential removal
                if assignment.get((l, t_prev)) != assignment.get((l, t_curr)):
                    candidates.append((l, t_curr))
        
        # If not enough setups, fill with random
        targets = candidates if len(candidates) >= n else candidates + random.sample(list(assignment.keys()), n - len(candidates))
        
        # Destroy
        for k in random.sample(targets, min(len(targets), n)):
            new_assign[k] = None

        return evaluator.repair_and_evaluate({"assignment": new_assign, "type": "alns_worst_setup"})

    def _destroy_zone(self, assignment: Dict, n: int, evaluator) -> Dict:
        """
        Zone/Shaw Removal: Remove a contiguous block (same line, nearby time) 
        or related slots to allow reshuffling a specific area.
        """
        new_assign = self._fast_copy_assignment(assignment)
        
        # Pick a seed "center"
        seed_l = random.choice(self.lines)
        seed_t_idx = random.randint(0, len(self.times) - 1)
        
        # Define a "radius" of destruction around the seed
        # We simulate "Relatedness" by proximity in Time and Line
        removed_count = 0
        
        # Try to remove around the seed on the same line
        start_idx = max(0, seed_t_idx - n // 2)
        end_idx = min(len(self.times), start_idx + n)
        
        for i in range(start_idx, end_idx):
            t = self.times[i]
            if (seed_l, t) in new_assign:
                new_assign[(seed_l, t)] = None
                removed_count += 1
        
        # If we need to remove more, pick a neighbor line
        if removed_count < n and len(self.lines) > 1:
            neighbor_l = random.choice([l for l in self.lines if l != seed_l])
            for i in range(start_idx, end_idx):
                t = self.times[i]
                if (neighbor_l, t) in new_assign:
                    new_assign[(neighbor_l, t)] = None
                    removed_count += 1
                    if removed_count >= n:
                        break

        return evaluator.repair_and_evaluate({"assignment": new_assign, "type": "alns_zone"})

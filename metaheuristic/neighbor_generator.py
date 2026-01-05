import copy
import random

class NeighborGenerator:
    """
    Handles generation of neighbors using strategies from the old code:
    1. Traditional moves (Swap, Reassign)
    2. Multi-Objective moves (Setup Reduction, Late Cost Reduction, Balanced)
    """

    def __init__(self, input_data, cap_map):
        self.input = input_data
        self.cap_map = cap_map
        self.lines = list(self.input.set['setL'])
        self.times = sorted(list(self.input.set['setT']))

    def _is_allowed(self, line, style):
        return style in self.cap_map[line]

    def _random_allowed_style(self, line):
        if not self.cap_map[line]: return None
        return random.choice(list(self.cap_map[line]))

    def generate_neighbors(self, base_solution, mo_probability, evaluator):
        """
        Master method: Generates neighbors using mixed strategies.
        Requires 'evaluator' (ALNSOperator) to calculate costs.
        """
        neighbors = []
        
        # 1. Traditional Neighbors
        traditional = self._generate_traditional_neighbors(base_solution, evaluator)
        neighbors.extend(traditional)
        
        # 2. Multi-Objective Neighbors (Adaptive)
        if random.random() < mo_probability:
            mo_neighbors = self._generate_multi_objective_neighbors(base_solution, evaluator)
            neighbors.extend(mo_neighbors)
            
        return neighbors

    # ----------------------------------------------------------------
    #  Traditional Generation
    # ----------------------------------------------------------------
    def _generate_traditional_neighbors(self, base_solution, evaluator):
        neighbors = []
        # Number of neighbors logic from old code
        num_neighbors = max(len(self.lines) * 2, 10)

        for _ in range(num_neighbors):
            move_type = random.choice(['swap', 'reassign_block', 'reassign_single'])
            new_assign = copy.deepcopy(base_solution['assignment'])
            l = random.choice(self.lines)

            if move_type == 'swap' and len(self.times) >= 2:
                t1, t2 = random.sample(self.times, 2)
                # Swap logic
                new_assign[(l, t1)], new_assign[(l, t2)] = (
                    new_assign[(l, t2)],
                    new_assign[(l, t1)],
                )

            elif move_type == 'reassign_block' and len(self.times) > 5:
                block_size = random.randint(2, max(2, len(self.times) // 4))
                start_t_idx = random.randint(0, len(self.times) - block_size)
                start_t = self.times[start_t_idx]
                
                new_style = self._random_allowed_style(l)
                if new_style:
                    for i in range(block_size):
                        t = self.times[start_t_idx + i]
                        new_assign[(l, t)] = new_style

            else:  # reassign_single
                t = random.choice(self.times)
                new_style = self._random_allowed_style(l)
                if new_style:
                    new_assign[(l, t)] = new_style

            # Add if changed
            if new_assign != base_solution['assignment']:
                neighbors.append(evaluator.repair_and_evaluate({'assignment': new_assign}))

        return neighbors

    # ----------------------------------------------------------------
    #  Multi-Objective Generation (The "Smart" Logic)
    # ----------------------------------------------------------------
    def _generate_multi_objective_neighbors(self, base_solution, evaluator):
        neighbors = []
        
        # 1. Setup Reduction Moves
        neighbors.extend(self._generate_setup_reduction_moves(base_solution, evaluator))
        
        # 2. Late Cost Reduction Moves
        neighbors.extend(self._generate_late_cost_reduction_moves(base_solution, evaluator))
        
        # 3. Balanced Moves
        neighbors.extend(self._generate_balanced_moves(base_solution, evaluator))
        
        return neighbors

    def _generate_setup_reduction_moves(self, base_solution, evaluator):
        moves = []
        current_assign = base_solution['assignment']

        for l in self.lines:
            for segment in self._find_short_segments(l, current_assign):
                if len(segment['periods']) > 3: continue

                dominant = self._get_dominant_neighbor_style(l, segment, current_assign)
                if dominant and self._is_allowed(l, dominant):
                    new_assign = copy.deepcopy(current_assign)
                    for t in segment['periods']:
                        new_assign[(l, t)] = dominant
                    moves.append({'assignment': new_assign, 'type': 'setup_reduction'})
        
        # Evaluate top 5 only (Old Code Logic)
        return [evaluator.repair_and_evaluate(m) for m in moves[:5]]

    def _generate_late_cost_reduction_moves(self, base_solution, evaluator):
        moves = []
        current_assign = base_solution['assignment']
        high_risk = self._identify_high_risk_styles(base_solution)[:3]

        for style in high_risk:
            moves.extend(self._generate_capacity_boost_moves(style, current_assign))

        return [evaluator.repair_and_evaluate(m) for m in moves[:5]]

    def _generate_balanced_moves(self, base_solution, evaluator):
        moves = []
        current_assign = base_solution['assignment']
        
        for l in self.lines:
            if len(self.times) < 2: continue
            t1, t2 = random.sample(self.times, 2)
            
            if current_assign[(l, t1)] != current_assign[(l, t2)]:
                new_assign = copy.deepcopy(current_assign)
                new_assign[(l, t1)], new_assign[(l, t2)] = new_assign[(l, t2)], new_assign[(l, t1)]
                moves.append({'assignment': new_assign, 'type': 'balanced'})
                
        return [evaluator.repair_and_evaluate(move) for move in moves[:3]]

    # --- Helpers for MO Logic ---
    def _find_short_segments(self, line, assignment):
        segments = []
        if not self.times: return segments
        
        current_style = None
        current_segment = []
        
        for t in self.times:
            style = assignment.get((line, t))
            if style != current_style:
                if current_segment:
                    segments.append({'style': current_style, 'periods': current_segment})
                current_style = style
                current_segment = [t]
            else:
                current_segment.append(t)
        if current_segment:
            segments.append({'style': current_style, 'periods': current_segment})
            
        return [s for s in segments if len(s['periods']) <= 3]

    def _get_dominant_neighbor_style(self, line, segment, assignment):
        start_t = min(segment['periods'])
        end_t = max(segment['periods'])
        
        # Logic to find t index to get prev/next
        start_idx = self.times.index(start_t)
        end_idx = self.times.index(end_t)
        
        prev_style = None
        if start_idx > 0:
            prev_style = assignment.get((line, self.times[start_idx-1]))
            
        next_style = None
        if end_idx < len(self.times) - 1:
            next_style = assignment.get((line, self.times[end_idx+1]))
            
        if prev_style and prev_style == next_style:
            return prev_style
        return prev_style or next_style

    def _identify_high_risk_styles(self, solution):
        backlog = solution.get('final_backlog', {})
        if not backlog: return []
        sorted_styles = sorted(backlog.keys(), key=lambda s: backlog[s], reverse=True)
        return [s for s in sorted_styles if backlog[s] > 0]

    def _generate_capacity_boost_moves(self, style_to_boost, assignment):
        moves = []
        potential = [
            (l, t) for l in self.lines for t in self.times
            if self._is_allowed(l, style_to_boost) and assignment.get((l, t)) != style_to_boost
        ]
        
        if potential:
            l, t = random.choice(potential)
            new_assign = copy.deepcopy(assignment)
            new_assign[(l, t)] = style_to_boost
            moves.append({'assignment': new_assign, 'type': 'late_cost_reduction'})
        return moves

import copy
import random

class NeighborGenerator:
    """
    Generate neighbors based on simple adaptive probabilities.
    Compatible with the optimized ALNSOperator (uses IDs instead of strings).
    """

    def __init__(self, input_data, cap_map):
        self.input = input_data
        # cap_map here is only used as a reference for lines/times lists
        self.lines = list(self.input.set['setL'])
        self.times = sorted(list(self.input.set['setT']))

    def generate_neighbors(self, base_solution, mo_probability, evaluator):
        """
        Generate a list of neighboring solutions.

        Parameters
        ----------
        mo_probability : float
            Probability of activating smart multi-objective operators.
        evaluator : ALNSOperator
            Used to check constraints (bitmask) and compute cost (fast fail).
        """
        neighbors = []
        
        # 1. always generate traditional neighbors (swap, reassign)
        traditional = self._generate_traditional_neighbors(base_solution, evaluator)
        neighbors.extend(traditional)
        
        # 2. generate smart (MO) neighbors probabilistically
        if random.random() < mo_probability:
            mo_neighbors = self._generate_multi_objective_neighbors(base_solution, evaluator)
            neighbors.extend(mo_neighbors)
            
        return neighbors

    # =================================================================
    #  TRADITIONAL MOVES
    # =================================================================
    def _generate_traditional_neighbors(self, base_solution, evaluator):
        neighbors = []
        base_assign = base_solution['assignment']
        num_neighbors = max(len(self.lines) * 2, 10) # Logic cũ

        for _ in range(num_neighbors):
            move_type = random.choice(['swap', 'reassign_block', 'reassign_single'])
            
            # shallow copy is fast enough
            new_assign = copy.copy(base_assign)
            l = random.choice(self.lines)

            changed = False
            
            if move_type == 'swap' and len(self.times) >= 2:
                t1, t2 = random.sample(self.times, 2)
                if new_assign[(l, t1)] != new_assign[(l, t2)]:
                    new_assign[(l, t1)], new_assign[(l, t2)] = new_assign[(l, t2)], new_assign[(l, t1)]
                    changed = True

            elif move_type == 'reassign_block' and len(self.times) > 5:
                block_size = random.randint(2, max(2, len(self.times) // 4))
                start_idx = random.randint(0, len(self.times) - block_size)
                
                # ask evaluator for a random allowed style ID (O(1))
                new_style_id = evaluator._random_allowed_style_id(l)
                
                if new_style_id is not None:
                    for i in range(block_size):
                        t = self.times[start_idx + i]
                        if new_assign[(l, t)] != new_style_id:
                            new_assign[(l, t)] = new_style_id
                            changed = True

            else:  # reassign_single
                t = random.choice(self.times)
                new_style_id = evaluator._random_allowed_style_id(l)
                
                if new_style_id is not None and new_style_id != new_assign[(l, t)]:
                    new_assign[(l, t)] = new_style_id
                    changed = True

            if changed:
                # no need to tag origin_operator anymore since RL was removed
                neighbors.append(evaluator.repair_and_evaluate({'assignment': new_assign}))

        return neighbors

    # =================================================================
    #  MULTI-OBJECTIVE MOVES (SMART)
    # =================================================================
    def _generate_multi_objective_neighbors(self, base_solution, evaluator):
        neighbors = []
        
        # 1. reduce setup cost (Setup Reduction)
        neighbors.extend(self._gen_setup_reduction(base_solution, evaluator))
        
        # 2. reduce late penalty (Late Cost Reduction)
        neighbors.extend(self._gen_late_reduction(base_solution, evaluator))
        
        # 3. balance (purposeful swap)
        neighbors.extend(self._gen_balanced(base_solution, evaluator))
        
        # mark as MO so Tabu Search can track stats
        for n in neighbors:
            n['type'] = 'mo_move'
            
        return neighbors

    def _gen_setup_reduction(self, base_solution, evaluator):
        moves = []
        current_assign = base_solution['assignment']
        attempts = 0
        
        for l in self.lines:
            segments = self._find_short_segments(l, current_assign)
            if not segments: continue
            
            # try connecting two random short segments
            for segment in random.sample(segments, min(len(segments), 2)):
                dominant_id = self._get_dominant_neighbor_style(l, segment, current_assign)
                
                # check ID validity using evaluator bitmask
                if dominant_id is not None and evaluator._is_allowed(l, dominant_id):
                    new_assign = copy.copy(current_assign)
                    for t in segment['periods']:
                        new_assign[(l, t)] = dominant_id
                    moves.append(evaluator.repair_and_evaluate({'assignment': new_assign}))
                    attempts += 1
            if attempts >= 5: break
        return moves

    def _gen_late_reduction(self, base_solution, evaluator):
        moves = []
        current_assign = base_solution['assignment']
        
        # find style IDs with backlog
        high_risk_ids = self._identify_high_risk_styles(base_solution)
        if not high_risk_ids: return []

        # take top 3 most delayed styles
        for s_id in high_risk_ids[:3]:
            # find potential slots to insert
            valid_slots = [
                (l, t) for l in self.lines for t in self.times
                if evaluator._is_allowed(l, s_id) and current_assign.get((l, t)) != s_id
            ]
            
            if valid_slots:
                # try inserting into 3 random positions
                for _ in range(min(3, len(valid_slots))):
                    l, t = random.choice(valid_slots)
                    new_assign = copy.copy(current_assign)
                    new_assign[(l, t)] = s_id
                    moves.append(evaluator.repair_and_evaluate({'assignment': new_assign}))
        return moves

    def _gen_balanced(self, base_solution, evaluator):
        moves = []
        current_assign = base_solution['assignment']
        
        for _ in range(5): # attempt 5 strategic swaps
            l = random.choice(self.lines)
            if len(self.times) < 2: continue
            t1, t2 = random.sample(self.times, 2)
            
            # only swap if different
            if current_assign[(l, t1)] != current_assign[(l, t2)]:
                new_assign = copy.copy(current_assign)
                new_assign[(l, t1)], new_assign[(l, t2)] = new_assign[(l, t2)], new_assign[(l, t1)]
                moves.append(evaluator.repair_and_evaluate({'assignment': new_assign}))
        return moves

    # --- HELPERS ---
    def _find_short_segments(self, line, assignment):
        segments = []
        current_style = None
        current_segment = []
        
        for t in self.times:
            style = assignment.get((line, t))
            if style != current_style:
                if current_segment: segments.append({'style': current_style, 'periods': current_segment})
                current_style = style
                current_segment = [t]
            else:
                current_segment.append(t)
        if current_segment: segments.append({'style': current_style, 'periods': current_segment})
        # filter segments of length <= 3 days
        return [s for s in segments if len(s['periods']) <= 3]

    def _get_dominant_neighbor_style(self, line, segment, assignment):
        start_t = min(segment['periods'])
        end_t = max(segment['periods'])
        try:
            start_idx = self.times.index(start_t)
            end_idx = self.times.index(end_t)
        except ValueError: return None

        prev = assignment.get((line, self.times[start_idx-1])) if start_idx > 0 else None
        nxt = assignment.get((line, self.times[end_idx+1])) if end_idx < len(self.times) - 1 else None
        
        if prev is not None and prev == nxt: return prev
        return prev if prev is not None else nxt

    def _identify_high_risk_styles(self, solution):
        # return list of style IDs
        backlog = solution.get('final_backlog', {})
        if not backlog: return []
        # sort backlog descending
        sorted_ids = sorted(backlog.keys(), key=lambda s: backlog[s], reverse=True)
        return [s for s in sorted_ids if backlog[s] > 0]

import copy
import random

class NeighborGenerator:
    """
    Sinh láng giềng dựa trên xác suất thích nghi (Simple Adaptive).
    Tương thích với ALNSOperator tối ưu (dùng ID thay vì String).
    """

    def __init__(self, input_data, cap_map):
        self.input = input_data
        # cap_map ở đây chỉ dùng để tham chiếu list lines/times
        self.lines = list(self.input.set['setL'])
        self.times = sorted(list(self.input.set['setT']))

    def generate_neighbors(self, base_solution, mo_probability, evaluator):
        """
        Sinh danh sách các giải pháp láng giềng.
        
        Parameters
        ----------
        mo_probability : float
            Xác suất để kích hoạt các toán tử Multi-Objective (thông minh).
        evaluator : ALNSOperator
            Dùng để kiểm tra ràng buộc (bitmask) và tính toán chi phí (fast fail).
        """
        neighbors = []
        
        # 1. Luôn sinh các láng giềng truyền thống (Swap, Reassign)
        traditional = self._generate_traditional_neighbors(base_solution, evaluator)
        neighbors.extend(traditional)
        
        # 2. Sinh láng giềng thông minh (MO) dựa trên xác suất
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
            
            # Shallow copy là đủ nhanh
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
                
                # Gọi evaluator để lấy random ID hợp lệ (O(1))
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
                # Không cần tag origin_operator nữa vì đã bỏ RL
                neighbors.append(evaluator.repair_and_evaluate({'assignment': new_assign}))

        return neighbors

    # =================================================================
    #  MULTI-OBJECTIVE MOVES (SMART)
    # =================================================================
    def _generate_multi_objective_neighbors(self, base_solution, evaluator):
        neighbors = []
        
        # 1. Giảm chi phí chuyển đổi (Setup Reduction)
        neighbors.extend(self._gen_setup_reduction(base_solution, evaluator))
        
        # 2. Giảm phạt trễ (Late Cost Reduction)
        neighbors.extend(self._gen_late_reduction(base_solution, evaluator))
        
        # 3. Cân bằng (Balanced - Swap có chủ đích)
        neighbors.extend(self._gen_balanced(base_solution, evaluator))
        
        # Đánh dấu là MO để Tabu Search biết đường thống kê
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
            
            # Thử nối 2 segment ngắn ngẫu nhiên
            for segment in random.sample(segments, min(len(segments), 2)):
                dominant_id = self._get_dominant_neighbor_style(l, segment, current_assign)
                
                # Check ID hợp lệ bằng bitmask của evaluator
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
        
        # Tìm style (ID) bị backlog
        high_risk_ids = self._identify_high_risk_styles(base_solution)
        if not high_risk_ids: return []

        # Lấy top 3 style trễ nhất
        for s_id in high_risk_ids[:3]:
            # Tìm các vị trí khả dĩ để chèn
            valid_slots = [
                (l, t) for l in self.lines for t in self.times
                if evaluator._is_allowed(l, s_id) and current_assign.get((l, t)) != s_id
            ]
            
            if valid_slots:
                # Chèn thử vào 3 vị trí ngẫu nhiên
                for _ in range(min(3, len(valid_slots))):
                    l, t = random.choice(valid_slots)
                    new_assign = copy.copy(current_assign)
                    new_assign[(l, t)] = s_id
                    moves.append(evaluator.repair_and_evaluate({'assignment': new_assign}))
        return moves

    def _gen_balanced(self, base_solution, evaluator):
        moves = []
        current_assign = base_solution['assignment']
        
        for _ in range(5): # Thử 5 lần swap chiến lược
            l = random.choice(self.lines)
            if len(self.times) < 2: continue
            t1, t2 = random.sample(self.times, 2)
            
            # Chỉ swap nếu khác nhau
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
        # Lọc các đoạn ngắn <= 3 ngày
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
        # Trả về list ID style
        backlog = solution.get('final_backlog', {})
        if not backlog: return []
        # Sắp xếp giảm dần backlog
        sorted_ids = sorted(backlog.keys(), key=lambda s: backlog[s], reverse=True)
        return [s for s in sorted_ids if backlog[s] > 0]

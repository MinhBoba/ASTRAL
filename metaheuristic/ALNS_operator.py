import copy
from collections import defaultdict
import random
import numpy as np
import math

class ALNSOperator:
    """
    Evaluator & Repairer tối ưu hóa:
    1. Integer ID Mapping: Tối ưu hiệu năng.
    2. Efficiency Lookup Table: Tra bảng thay vì tính toán O(1).
    3. Strict Material Logic: Xử lý triệt để Trailing Zero & Idle Switch.
    """

    def __init__(self, input_data, cap_map, discount_alpha):
        self.input = input_data
        self.alpha = discount_alpha
        
        # --- 1. Map String <-> Integer ID ---
        all_styles = sorted(list(self.input.set['setS']))
        self.style_to_id = {name: i for i, name in enumerate(all_styles)}
        self.id_to_style = {i: name for i, name in enumerate(all_styles)}
        
        # --- 2. Cache Capability ---
        self.line_allowed_sets = {} 
        self.line_allowed_lists = {}
        for l in self.input.set['setL']:
            ids = [self.style_to_id[s] for s in cap_map[l] if s in self.style_to_id]
            self.line_allowed_sets[l] = set(ids)
            self.line_allowed_lists[l] = ids

        # --- 3. Efficiency Lookup Table (Tạo bảng tra cứu) ---
        self.max_lookup_day = 2000 # Đủ lớn cho số ngày kinh nghiệm
        self.efficiency_table = self._build_efficiency_lookup()

        # --- 4. Setup Fast Fail & Precompute ---
        self.pruning_cutoff = float('inf')
        self.precomputed = self._precompute_data()

    def set_pruning_best(self, best_cost):
        if best_cost == float('inf'):
            self.pruning_cutoff = float('inf')
        else:
            self.pruning_cutoff = best_cost * 1.2

    def _build_efficiency_lookup(self):
        """Tính trước Efficiency cho mọi mức kinh nghiệm."""
        table = {}
        breakpoints = sorted(self.input.set['setBP'])
        if not breakpoints: return {i: 1.0 for i in range(self.max_lookup_day + 1)}
            
        curve = [(self.input.param['paramXp'][p], self.input.param['paramFp'][p]) for p in breakpoints]
        
        def calc_eff(exp_days):
            if exp_days <= curve[0][0]: return curve[0][1]
            if exp_days >= curve[-1][0]: return curve[-1][1]
            for i in range(len(curve) - 1):
                x1, y1 = curve[i]
                x2, y2 = curve[i+1]
                if x1 <= exp_days <= x2:
                    return y1 + (y2 - y1) * (exp_days - x1) / (x2 - x1)
            return curve[-1][1]

        for day in range(self.max_lookup_day + 1):
            table[day] = calc_eff(day)
        return table

    def get_efficiency(self, exp_days):
        """Tra cứu O(1)"""
        day_idx = int(exp_days)
        if day_idx >= self.max_lookup_day: return self.efficiency_table[self.max_lookup_day]
        if day_idx < 0: return self.efficiency_table[0]
        return self.efficiency_table[day_idx]

    def _precompute_data(self):
        precomputed = {'style_sam': {}, 'line_capacity': {}}
        for s_name, s_id in self.style_to_id.items():
            precomputed['style_sam'][s_id] = self.input.param['paramSAM'][s_name]
            
        for l in self.input.set['setL']:
            precomputed['line_capacity'][l] = [
                self.input.param['paramH'].get((l, t), 0) * 60 * self.input.param['paramN'][l]
                for t in self.input.set['setT']
            ]
        return precomputed

    def _discount(self, t: int) -> float:
        return 1.0 / (1.0 + self.alpha) ** t

    def _is_allowed(self, line, style_id):
        return style_id in self.line_allowed_sets[line]

    def _random_allowed_style_id(self, line):
        options = self.line_allowed_lists.get(line)
        if not options: return None
        return random.choice(options)

    def _get_initial_style_id(self, line):
        if 'paramY0' in self.input.param:
            for s_name, s_id in self.style_to_id.items():
                if self.input.param['paramY0'].get((line, s_name), 0) == 1:
                    return s_id
        return None

    def initialize_solution(self):
        # (Giữ nguyên logic khởi tạo như cũ)
        solution = {'assignment': {}}
        demand_by_id_time = {}
        for (s_name, t), val in self.input.param['paramD'].items():
            if s_name in self.style_to_id:
                demand_by_id_time[(self.style_to_id[s_name], t)] = val

        for l in self.input.set['setL']:
            allowed_ids = self.line_allowed_lists[l]
            demands = {
                s_id: sum(demand_by_id_time.get((s_id, t), 0) for t in self.input.set['setT'])
                for s_id in allowed_ids
            }
            if not demands: initial_style_id = self._random_allowed_style_id(l)
            else: initial_style_id = max(demands, key=demands.get)
            
            for t in self.input.set['setT']:
                solution['assignment'][(l, t)] = initial_style_id
        
        return self.repair_and_evaluate(solution)

    def repair_and_evaluate(self, solution):
        """
        Vòng lặp mô phỏng chính với Logic kiểm tra tồn kho chặt chẽ.
        """
        assignment = solution.get('assignment', {})
        
        # --- REPAIR ID ---
        for (l, t), s_id in list(assignment.items()):
            if isinstance(s_id, str): s_id = self.style_to_id.get(s_id)
            if s_id is None or not self._is_allowed(l, s_id):
                assignment[(l, t)] = self._random_allowed_style_id(l)
        solution['assignment'] = assignment

        # --- INIT SIMULATION VARS ---
        move_type = solution.get("type")
        solution.update({"production": {}, "shipment": {}, "changes": {}, "experience": {}, "efficiency": {}})

        inv_fab = defaultdict(float)
        inv_prod = defaultdict(float)
        backlog = defaultdict(float)
        
        # Init inventory from params
        for s_name, val in self.input.param["paramI0fabric"].items():
            if s_name in self.style_to_id: inv_fab[self.style_to_id[s_name]] = val
        for s_name, val in self.input.param["paramI0product"].items():
            if s_name in self.style_to_id: inv_prod[self.style_to_id[s_name]] = val
        for s_name, val in self.input.param["paramB0"].items():
            if s_name in self.style_to_id: backlog[self.style_to_id[s_name]] = val

        setup_cost = late_cost = exp_reward = 0.0

        line_states = {
            l: dict(current_style=self._get_initial_style_id(l),
                    exp=self.input.param["paramExp0"].get(l, 0),
                    up_exp=0)
            for l in self.input.set["setL"]
        }
        daily_prod_history = defaultdict(lambda: defaultdict(float))

        # Cache Lookups
        get_sam = self.precomputed["style_sam"].get
        get_line_cap = self.precomputed["line_capacity"]
        param_h = self.input.param["paramH"]
        param_csetup = self.input.param["Csetup"]
        param_rexp = self.input.param["Rexp"]
        param_lexp = {(l, self.style_to_id[s]): v for (l, s), v in self.input.param["paramLexp"].items() if s in self.style_to_id}
        param_plate = {self.style_to_id[s]: v for s, v in self.input.param["Plate"].items() if s in self.style_to_id}
        param_tfab = {self.style_to_id[s]: v for s, v in self.input.param["paramTfabprocess"].items() if s in self.style_to_id}
        param_tprod = {self.style_to_id[s]: v for s, v in self.input.param["paramTprodfinish"].items() if s in self.style_to_id}
        
        # Optimize loops
        all_style_ids = list(self.style_to_id.values())
        set_l = self.input.set["setL"]
        sorted_times = sorted(self.input.set["setT"])
        t_index_map = {t: i for i, t in enumerate(sorted_times)}
        set_ssame = set((self.style_to_id[s1], self.style_to_id[s2]) for s1, s2 in self.input.set["setSsame"] if s1 in self.style_to_id and s2 in self.style_to_id)
        
        # Precompute Param D & F for speed
        param_F_local = defaultdict(float)
        for (s_name, t), val in self.input.param["paramF"].items():
             if s_name in self.style_to_id: param_F_local[(self.style_to_id[s_name], t)] = val
        
        param_D_local = defaultdict(float)
        for (s_name, t), val in self.input.param["paramD"].items():
             if s_name in self.style_to_id: param_D_local[(self.style_to_id[s_name], t)] = val

        # --- TIME LOOP ---
        for t in sorted_times:
            # Fast fail check
            if setup_cost + late_cost - exp_reward > self.pruning_cutoff:
                solution['total_cost'] = float('inf'); return solution

            disc_factor = self._discount(t)

            # 1. Fabric Receipts
            for s_id in all_style_ids:
                LT_f = param_tfab.get(s_id, 0)
                inv_fab[s_id] += param_F_local.get((s_id, t - LT_f), 0)

            # 2. Decide Production
            pot_prod = {s_id: [] for s_id in all_style_ids}

            for l in set_l:
                st = line_states[l]
                st["exp"] += st["up_exp"] # Update Exp
                
                proposed_style = assignment.get((l, t))
                work_day = param_h.get((l, t), 0) > 0
                
                if proposed_style is None:
                    st["up_exp"] = 0
                    continue

                # ==========================================================
                # [CORE LOGIC] MATERIAL AVAILABILITY CHECK
                # ==========================================================
                
                has_material = inv_fab[proposed_style] > 1e-6
                
                # Biến cờ: Có phải là ngồi chờ hợp lệ (Bridging) không?
                is_valid_bridge = False
                
                if not has_material:
                    # Kiểm tra xem có phải đang chờ nguyên liệu không
                    # Điều kiện chờ: Style giống hôm qua VÀ Style giống ngày mai
                    # (Nghĩa là kẹp giữa 2 ngày làm việc cùng 1 mã)
                    prev_is_same = (st["current_style"] == proposed_style)
                    
                    next_is_same = False
                    current_t_idx = t_index_map[t]
                    if current_t_idx < len(sorted_times) - 1:
                        next_t = sorted_times[current_t_idx + 1]
                        if assignment.get((l, next_t)) == proposed_style:
                            next_is_same = True
                    
                    # Chỉ cho phép Qty=0 nếu là Bridging (Prev=Same & Next=Same)
                    if prev_is_same and next_is_same:
                        is_valid_bridge = True

                # XỬ LÝ QUYẾT ĐỊNH
                final_style = proposed_style
                
                if not has_material and not is_valid_bridge:
                    # VI PHẠM: Hết hàng nhưng không phải Bridging -> PHẢI ĐỔI MÃ
                    # (Đây là fix cho Trailing Zero và Idle Switch)
                    
                    # 1. Ưu tiên: Giữ mã cũ (nếu có hàng) để tránh Setup
                    if st["current_style"] is not None and inv_fab[st["current_style"]] > 1e-6:
                         final_style = st["current_style"]
                    else:
                        # 2. Tìm bất kỳ mã nào khác có hàng trong danh sách cho phép
                        candidates = self.line_allowed_lists[l]
                        # Shuffle để tránh thiên vị
                        candidates_shuffled = list(candidates)
                        random.shuffle(candidates_shuffled)
                        
                        found_alt = False
                        for cand_id in candidates_shuffled:
                            if inv_fab[cand_id] > 1e-6:
                                final_style = cand_id
                                found_alt = True
                                break
                        
                        # Nếu cùng đường (không mã nào có hàng), đành chấp nhận Qty=0 trên mã cũ
                        if not found_alt and st["current_style"] is not None:
                             final_style = st["current_style"]

                    # Update Assignment để Look-ahead các ngày sau thấy sự thay đổi này
                    assignment[(l, t)] = final_style

                # ==========================================================
                # END CORE LOGIC
                # ==========================================================

                # Calculate Setup Cost
                if st["current_style"] != final_style:
                    solution["changes"][(l, st["current_style"], final_style, t)] = 1
                    setup_cost += (param_csetup * disc_factor)
                    if (st["current_style"], final_style) not in set_ssame:
                        st["exp"] = param_lexp.get((l, final_style), 0)

                solution["experience"][(l, t)] = st["exp"]
                
                # Lookup Efficiency (Fast)
                eff = self.get_efficiency(st["exp"])
                solution["efficiency"][(l, t)] = eff
                
                exp_reward += st["exp"] * param_rexp

                if work_day:
                    sam = get_sam(final_style, 0)
                    if sam > 0:
                        cap_min = get_line_cap[l][t - 1]
                        max_p = (cap_min * eff) / sam
                        pot_prod[final_style].append({"line": l, "max_p": max_p})
                        st["up_exp"] = 0 
                    else:
                        st["up_exp"] = 0
                else:
                    st["up_exp"] = 0

                st["current_style"] = final_style

            # 3. Realise Production
            for s_id, items in pot_prod.items():
                if not items: continue
                total_cap = sum(i["max_p"] for i in items)
                actual_p = min(total_cap, inv_fab[s_id])

                daily_prod_history[s_id][t] = actual_p
                inv_fab[s_id] -= actual_p

                if total_cap > 0:
                    for i in items:
                        share = actual_p * i["max_p"] / total_cap
                        solution["production"][(i["line"], s_id, t)] = share
                        # Exp Gain Rule: Làm > 50% năng lực mới được cộng exp
                        if share >= 0.5 * i["max_p"]:
                            line_states[i["line"]]["up_exp"] = 1

            # 4. Shipments
            for s_id in all_style_ids:
                LT_p = param_tprod.get(s_id, 0)
                finished = daily_prod_history[s_id].get(t - LT_p, 0.0)
                inv_prod[s_id] += finished
                
                demand_t = param_D_local.get((s_id, t), 0)
                to_ship = backlog[s_id] + demand_t
                ship_qty = min(inv_prod[s_id], to_ship)

                solution["shipment"][(s_id, t)] = ship_qty
                inv_prod[s_id] -= ship_qty
                backlog[s_id] = to_ship - ship_qty

                if backlog[s_id] > 1e-6:
                    late_cost += (backlog[s_id] * param_plate.get(s_id, 0) * disc_factor)

        # Finalize
        final_backlog_str = {self.id_to_style[k]: v for k, v in backlog.items() if k is not None}
        solution.update({
            "final_backlog": final_backlog_str,
            "total_setup": setup_cost,
            "total_late": late_cost,
            "total_exp": exp_reward,
            "total_cost": setup_cost + late_cost - exp_reward
        })
        if move_type: solution["type"] = move_type
        return solution

    def convert_solution_to_string_keys(self, solution):
        new_sol = copy.deepcopy(solution)
        new_assign = {(l, t): self.id_to_style.get(s_id) for (l, t), s_id in new_sol['assignment'].items()}
        new_prod = {(l, self.id_to_style.get(s_id), t): v for (l, s_id, t), v in new_sol['production'].items()}
        new_sol['assignment'] = new_assign
        new_sol['production'] = new_prod
        return new_sol
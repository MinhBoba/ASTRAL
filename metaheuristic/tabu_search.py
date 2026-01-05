import time
import copy
from collections import deque, defaultdict
from .neighbor_generator import NeighborGenerator
from .ALNS_operator import ALNSOperator

class TabuSearchSolver:
    def __init__(self, input_data, discount_alpha=0.05, initial_line_df=None, max_iter=1000, 
                 tabu_tenure=10, max_time=1200, min_tenure=5, max_tenure=30, 
                 increase_threshold=50, decrease_threshold=10, verbose=True):
        
        self.input = input_data
        self.alpha = discount_alpha
        self.max_iter = max_iter
        self.max_time = max_time
        
        # Tabu parameters
        self.current_tenure = tabu_tenure
        self.min_tenure = min_tenure
        self.max_tenure = max_tenure
        self.increase_threshold = increase_threshold
        self.decrease_threshold = decrease_threshold
        self.no_improvement_counter = 0
        self.consecutive_improvements_counter = 0
        self.verbose = verbose
        
        # Adaptive Strategy Parameters
        self.mo_probability = 0.6
        self.mo_moves_attempted = 0
        self.mo_moves_accepted_as_best = 0

        # Restart Strategy Parameter
        # Kích hoạt restart nếu không cải thiện trong thời gian dài (gấp 3 lần ngưỡng tăng tenure)
        self.restart_threshold = self.increase_threshold * 3

        # Build Capability Map
        param_enable = self.input.param.get("paramYenable", {})
        self.cap_map = defaultdict(set)
        for (l, s), val in param_enable.items():
            if val: self.cap_map[l].add(s)

        for l in self.input.set['setL']:
            if not self.cap_map[l]:
                raise ValueError(f"Line {l} has no enabled styles.")

        # Initialize Modular Components
        self.evaluator = ALNSOperator(input_data, self.cap_map, discount_alpha)
        self.neighbor_gen = NeighborGenerator(input_data, self.cap_map)

        # Initialize Solution
        self.current_solution = self.evaluator.initialize_solution()
        self.best_solution = copy.deepcopy(self.current_solution)
        self.best_cost = self.current_solution['total_cost']
        self.tabu_list = deque(maxlen=self.current_tenure)
        self.costs = [self.best_cost]
        self.start_time = time.time()

    def solve(self):
        print(f"Bắt đầu tối ưu hóa. Chi phí ban đầu: {self.best_cost:,.2f}")
        print(f"Nhiệm kỳ Tabu ban đầu: {self.current_tenure}. Phạm vi động: [{self.min_tenure}, {self.max_tenure}]")
        print(f"Ngưỡng kích hoạt Restart: {self.restart_threshold} vòng lặp không cải thiện.")
        
        last_iter = self.max_iter
        
        for i in range(self.max_iter):
            if time.time() - self.start_time > self.max_time:
                print(f"\nĐã đạt giới hạn thời gian {self.max_time}s ở vòng lặp {i}.")
                last_iter = i
                break

            # 1. Generate Neighbors
            # Lưu ý: Evaluator có khả năng Fast Fail, nhưng cần neighbor generator truyền best_cost vào (nếu có update).
            # Ở đây ta gọi mặc định, việc tối ưu Fast Fail trong neighbor_generator có thể làm ở bước sau.
            neighbors = self.neighbor_gen.generate_neighbors(
                self.current_solution, 
                self.mo_probability, 
                self.evaluator
            )
            
            if not neighbors: continue

            # 2. Select Best Move
            neighbors.sort(key=lambda s: s['total_cost'])
            best_neighbor_found = False
            improvement_this_iteration = False
            chosen_move_is_mo = False

            for neighbor in neighbors:
                move = self._get_move_signature(self.current_solution['assignment'], neighbor['assignment'])
                is_best_ever = neighbor['total_cost'] < self.best_cost
                is_not_tabu = move not in self.tabu_list
                
                if is_best_ever or is_not_tabu:
                    self.current_solution = neighbor
                    chosen_move_is_mo = 'type' in neighbor
                    self.tabu_list.append(move)
                    
                    if is_best_ever:
                        self.best_solution = copy.deepcopy(neighbor)
                        self.best_cost = neighbor['total_cost']
                        improvement_this_iteration = True
                        print(f"Vòng lặp {i}: Tìm thấy giải pháp tốt hơn! Chi phí mới: {self.best_cost:,.2f}")
                    
                    best_neighbor_found = True
                    break

            if not best_neighbor_found:
                self.current_solution = neighbors[0]
                chosen_move_is_mo = 'type' in self.current_solution

            self.costs.append(self.current_solution['total_cost'])

            # 3. Update Adaptive Strategies
            self._update_mo_strategy(chosen_move_is_mo, improvement_this_iteration)
            self._update_tenure(improvement_this_iteration)

            # --- NEW: Restart Strategy Logic ---
            if improvement_this_iteration:
                self.no_improvement_counter = 0 # Reset counter
            else:
                self.no_improvement_counter += 1
                
                # Kiểm tra điều kiện Restart
                if self.no_improvement_counter >= self.restart_threshold:
                    if self.verbose:
                        print(f"  -> [RESTART] Đã kẹt {self.no_improvement_counter} vòng. Xáo trộn giải pháp tốt nhất để tìm hướng mới.")
                    
                    # Lấy giải pháp tốt nhất hiện có, làm nhiễu nó 30%
                    self.current_solution = self.evaluator.perturb_solution(self.best_solution, perturbation_rate=0.3)
                    
                    # Xóa Tabu list để cho phép đi lại các nước cũ nếu cần
                    self.tabu_list.clear()
                    
                    # Reset lại bộ đếm để không restart liên tục
                    self.no_improvement_counter = 0

            # Progress logging
            if i % 100 == 0 and i > 0:
                print(f"Vòng lặp {i}: Chi phí hiện tại = {self.current_solution['total_cost']:,.2f}, "
                      f"Tốt nhất = {self.best_cost:,.2f}, Xác suất MO = {self.mo_probability:.2f}")

        # Final Wrap-up
        print("\n" + "="*50)
        print("TỐI ƯU HÓA HOÀN TẤT")
        print(f"Chi phí cuối cùng tốt nhất: {self.best_cost:,.2f}")
        print(f"Tổng số vòng lặp: {last_iter}")
        print(f"Thời gian chạy: {time.time() - self.start_time:.2f} giây")
        print("="*50)
        
        self.best_solution['is_final_check'] = True
        self.best_solution = self.evaluator.repair_and_evaluate(self.best_solution)
        return self.best_solution

    def _get_move_signature(self, old_assign, new_assign):
        """Creates a tuple representing what changed."""
        return tuple(sorted([
            (k, old_assign[k], new_assign[k]) 
            for k in old_assign if old_assign[k] != new_assign[k]
        ]))

    def _update_tabu_list_capacity(self):
        if self.tabu_list.maxlen != self.current_tenure:
            self.tabu_list = deque(self.tabu_list, maxlen=self.current_tenure)

    def _update_mo_strategy(self, move_was_mo, move_led_to_improvement):
        if move_was_mo:
            self.mo_moves_attempted += 1
            if move_led_to_improvement:
                self.mo_moves_accepted_as_best += 1
        
        if self.mo_moves_attempted > 20:
            success_rate = self.mo_moves_accepted_as_best / self.mo_moves_attempted
            if success_rate > 0.1:
                self.mo_probability = min(0.95, self.mo_probability + 0.05)
            else:
                self.mo_probability = max(0.2, self.mo_probability - 0.05)
            
            if self.mo_moves_attempted > 100:
                self.mo_moves_attempted = 0
                self.mo_moves_accepted_as_best = 0

    def _update_tenure(self, improvement_this_iteration):
        if improvement_this_iteration:
            self.consecutive_improvements_counter += 1
            # Note: no_improvement_counter is handled in the main loop for Restart logic
            if self.consecutive_improvements_counter >= self.decrease_threshold:
                if self.current_tenure > self.min_tenure:
                    self.current_tenure = max(self.min_tenure, self.current_tenure - 1)
                    self._update_tabu_list_capacity()
                    if self.verbose: print(f"  -> Cải thiện liên tục. Nhiệm kỳ giảm xuống: {self.current_tenure}")
                self.consecutive_improvements_counter = 0
        else:
            self.consecutive_improvements_counter = 0
            # Logic tăng tenure khi không cải thiện (nhỏ hơn logic restart)
            # Dùng ngưỡng increase_threshold riêng, không reset no_improvement_counter ở đây 
            # để logic Restart hoạt động đúng.
            if self.no_improvement_counter > 0 and self.no_improvement_counter % self.increase_threshold == 0:
                if self.current_tenure < self.max_tenure:
                    self.current_tenure = min(self.max_tenure, self.current_tenure + 2)
                    self._update_tabu_list_capacity()
                    if self.verbose: print(f"  -> Không cải thiện. Nhiệm kỳ tăng lên: {self.current_tenure}")

    def print_solution_summary(self, solution=None):
        sol = solution or self.best_solution
        if not sol: print("No solution."); return
        setup_cost = len(sol.get('changes', {})) * self.input.param['Csetup']
        print(f"Tổng chi phí: {sol['total_cost']:,.2f}")
        print(f"Setup Cost: {setup_cost:,.2f}")

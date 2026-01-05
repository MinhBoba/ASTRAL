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

        # Build Capability Map (Logic check from old code)
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
        
        last_iter = self.max_iter
        
        for i in range(self.max_iter):
            if time.time() - self.start_time > self.max_time:
                print(f"\nĐã đạt giới hạn thời gian {self.max_time}s ở vòng lặp {i}.")
                last_iter = i
                break

            # --- OPTIMIZATION: Set Fast Fail Threshold ---
            # Cập nhật chi phí tốt nhất cho Evaluator để nó biết đường cắt tỉa nhánh tồi
            self.evaluator.set_pruning_best(self.best_cost)

            # 1. Generate Neighbors
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
        # Đặt lại ngưỡng về vô cực để lần kiểm tra cuối cùng không bị cắt tỉa nhầm
        self.evaluator.set_pruning_best(float('inf'))
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
            self.no_improvement_counter = 0
            if self.consecutive_improvements_counter >= self.decrease_threshold:
                if self.current_tenure > self.min_tenure:
                    self.current_tenure = max(self.min_tenure, self.current_tenure - 1)
                    self._update_tabu_list_capacity()
                    if self.verbose: print(f"  -> Cải thiện liên tục. Nhiệm kỳ giảm xuống: {self.current_tenure}")
                self.consecutive_improvements_counter = 0
        else:
            self.no_improvement_counter += 1
            self.consecutive_improvements_counter = 0
            if self.no_improvement_counter >= self.increase_threshold:
                if self.current_tenure < self.max_tenure:
                    self.current_tenure = min(self.max_tenure, self.current_tenure + 2)
                    self._update_tabu_list_capacity()
                    if self.verbose: print(f"  -> Không cải thiện. Nhiệm kỳ tăng lên: {self.current_tenure}")
                self.no_improvement_counter = 0

    def print_solution_summary(self, solution=None):
        sol = solution or self.best_solution
        if not sol: print("No solution."); return
        setup_cost = len(sol.get('changes', {})) * self.input.param['Csetup']
        print(f"Tổng chi phí: {sol['total_cost']:,.2f}")
        print(f"Setup Cost: {setup_cost:,.2f}")

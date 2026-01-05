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
        # Khởi tạo NeighborGenerator (RL Agent)
        self.neighbor_gen = NeighborGenerator(input_data, self.cap_map)

        # Initialize Solution
        self.current_solution = self.evaluator.initialize_solution()
        self.best_solution = copy.deepcopy(self.current_solution)
        self.best_cost = self.current_solution['total_cost']
        self.tabu_list = deque(maxlen=self.current_tenure)
        self.costs = [self.best_cost]
        self.start_time = time.time()

    def solve(self):
        print(f"Bắt đầu tối ưu hóa (RL-Adaptive). Chi phí ban đầu: {self.best_cost:,.2f}")
        
        last_iter = self.max_iter
        
        for i in range(self.max_iter):
            if time.time() - self.start_time > self.max_time:
                print(f"\nĐã đạt giới hạn thời gian {self.max_time}s ở vòng lặp {i}.")
                last_iter = i
                break

            # 1. Generate Neighbors (RL Agent tự chọn chiến lược)
            neighbors = self.neighbor_gen.generate_neighbors(
                self.current_solution, 
                self.evaluator
            )
            
            if not neighbors: continue

            # 2. Select Best Move
            neighbors.sort(key=lambda s: s['total_cost'])
            best_neighbor_found = False
            improvement_this_iteration = False
            
            # Biến lưu thông tin để feedback cho RL
            chosen_op = None
            improvement_value = 0.0

            for neighbor in neighbors:
                move = self._get_move_signature(self.current_solution['assignment'], neighbor['assignment'])
                is_best_ever = neighbor['total_cost'] < self.best_cost
                is_not_tabu = move not in self.tabu_list
                
                if is_best_ever or is_not_tabu:
                    # Tính độ cải thiện so với giải pháp HIỆN TẠI (để làm reward)
                    improvement_value = self.current_solution['total_cost'] - neighbor['total_cost']
                    
                    self.current_solution = neighbor
                    chosen_op = neighbor.get('origin_operator') # Lấy tên toán tử đã sinh ra nó
                    self.tabu_list.append(move)
                    
                    if is_best_ever:
                        self.best_solution = copy.deepcopy(neighbor)
                        self.best_cost = neighbor['total_cost']
                        improvement_this_iteration = True
                        print(f"Vòng lặp {i}: Tìm thấy giải pháp tốt hơn! Chi phí mới: {self.best_cost:,.2f} (Op: {chosen_op})")
                    
                    best_neighbor_found = True
                    break

            if not best_neighbor_found:
                # Nếu tất cả đều Tabu, chọn cái tốt nhất trong số đó (Aspiration Criteria dạng yếu)
                # Hoặc chỉ đơn giản lấy cái đầu tiên
                best_neighbor = neighbors[0]
                improvement_value = self.current_solution['total_cost'] - best_neighbor['total_cost']
                self.current_solution = best_neighbor
                chosen_op = best_neighbor.get('origin_operator')

            self.costs.append(self.current_solution['total_cost'])

            # 3. RL FEEDBACK LOOP (Quan trọng!)
            if chosen_op:
                # Nếu improvement > 0 nghĩa là giảm chi phí (Tốt)
                # Nếu improvement < 0 nghĩa là tăng chi phí (Xấu - leo dốc)
                self.neighbor_gen.update_reward(chosen_op, improvement_value)

            # 4. Update Tenure (Adaptive Tenure)
            self._update_tenure(improvement_this_iteration)

            if i % 100 == 0 and i > 0:
                # In ra để xem RL đang ưu tiên cái gì
                best_op_stats = max(self.neighbor_gen.q_values.items(), key=lambda x: x[1])
                print(f"Vòng lặp {i}: Cost={self.current_solution['total_cost']:,.0f}. "
                      f"Best Op: {best_op_stats[0]} (Q={best_op_stats[1]:.2f}). "
                      f"Epsilon: {self.neighbor_gen.epsilon:.3f}")

        # Final Wrap-up
        print("\n" + "="*50)
        print("TỐI ƯU HÓA HOÀN TẤT")
        print(f"Chi phí cuối cùng tốt nhất: {self.best_cost:,.2f}")
        
        self.best_solution['is_final_check'] = True
        self.best_solution = self.evaluator.repair_and_evaluate(self.best_solution)
        return self.best_solution

    def _get_move_signature(self, old_assign, new_assign):
        return tuple(sorted([
            (k, old_assign[k], new_assign[k]) 
            for k in old_assign if old_assign[k] != new_assign[k]
        ]))

    def _update_tabu_list_capacity(self):
        if self.tabu_list.maxlen != self.current_tenure:
            self.tabu_list = deque(self.tabu_list, maxlen=self.current_tenure)

    def _update_tenure(self, improvement_this_iteration):
        if improvement_this_iteration:
            self.consecutive_improvements_counter += 1
            self.no_improvement_counter = 0
            if self.consecutive_improvements_counter >= self.decrease_threshold:
                if self.current_tenure > self.min_tenure:
                    self.current_tenure = max(self.min_tenure, self.current_tenure - 1)
                    self._update_tabu_list_capacity()
                self.consecutive_improvements_counter = 0
        else:
            self.no_improvement_counter += 1
            self.consecutive_improvements_counter = 0
            if self.no_improvement_counter >= self.increase_threshold:
                if self.current_tenure < self.max_tenure:
                    self.current_tenure = min(self.max_tenure, self.current_tenure + 2)
                    self._update_tabu_list_capacity()
                self.no_improvement_counter = 0

    def print_solution_summary(self, solution=None):
        sol = solution or self.best_solution
        if not sol: print("No solution."); return
        setup_cost = len(sol.get('changes', {})) * self.input.param['Csetup']
        print(f"Tổng chi phí: {sol['total_cost']:,.2f}")
        print(f"Setup Cost: {setup_cost:,.2f}")

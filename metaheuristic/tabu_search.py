"""
Tabu Search solver for production planning optimization.
Main orchestrator that coordinates neighbor generation, ALNS repair, and search.
"""

import time
import copy
from collections import deque, defaultdict
from typing import Dict, Any

from .neighbor_generator import NeighborGenerator
from .ALNS_operator import ALNSOperator
from .visualizer import SolutionVisualizer


class TabuSearchSolver:
    """
    Adaptive Tabu Search with ALNS-based repair operators.
    """

    def __init__(
        self,
        input_data,
        discount_alpha: float = 0.05,
        initial_line_df=None,
        max_iter: int = 20000,
        tabu_tenure: int = 10,
        max_time: float = 1200,
        min_tenure: int = 5,
        max_tenure: int = 30,
        increase_threshold: int = 50,
        decrease_threshold: int = 10,
        verbose: bool = True,
    ):
        """
        Parameters
        ----------
        input_data : InputData
            Problem data with sets and parameters
        discount_alpha : float
            Discount rate for time value of money
        max_iter : int
            Maximum iterations
        tabu_tenure : int
            Initial tabu list size
        max_time : float
            Maximum runtime in seconds
        min_tenure : int
            Minimum tabu tenure (adaptive)
        max_tenure : int
            Maximum tabu tenure (adaptive)
        increase_threshold : int
            Iterations without improvement before increasing tenure
        decrease_threshold : int
            Consecutive improvements before decreasing tenure
        verbose : bool
            Print progress messages
        """
        self.input = input_data
        self.alpha = discount_alpha
        self.initial_line_df = initial_line_df
        self.max_iter = max_iter
        self.max_time = max_time
        self.initial_tenure = tabu_tenure
        self.current_tenure = tabu_tenure
        self.min_tenure = min_tenure
        self.max_tenure = max_tenure
        self.increase_threshold = increase_threshold
        self.decrease_threshold = decrease_threshold
        self.no_improvement_counter = 0
        self.consecutive_improvements_counter = 0
        self.verbose = verbose

        # Adaptive strategy parameters
        self.mo_probability = 0.6
        self.mo_moves_attempted = 0
        self.mo_moves_accepted_as_best = 0

        # Build capability map from paramYenable
        param_enable = self.input.param.get("paramYenable", {})
        self.cap_map = defaultdict(set)

        for (l, s), val in param_enable.items():
            if val:
                self.cap_map[l].add(s)

        # Guard-rail: every line must have allowed styles
        for l in self.input.set["setL"]:
            if not self.cap_map[l]:
                raise ValueError(
                    f"Line {l} has no enabled styles in paramYenable"
                )

        # Initialize components - Using ALNSOperator instead of simple evaluator
        self.evaluator = ALNSOperator(
            input_data, self.cap_map, discount_alpha
        )
        self.neighbor_gen = NeighborGenerator(input_data, self.cap_map)
        
        # Initialize solution
        self.current_solution = self.evaluator.initialize_solution()
        self.best_solution = copy.deepcopy(self.current_solution)
        self.best_cost = self.current_solution["total_cost"]
        self.tabu_list = deque(maxlen=self.current_tenure)
        self.costs = [self.best_cost]
        self.start_time = time.time()

        # Create visualizer
        self.visualizer = SolutionVisualizer(
            input_data, self.evaluator.precomputed
        )

    def solve(self) -> Dict:
        """
        Main Tabu Search loop.
        
        Returns
        -------
        Dict
            Best solution found
        """
        print(f"Bắt đầu tối ưu hóa. Chi phí ban đầu: {self.best_cost:,.2f}")
        print(
            f"Nhiệm kỳ Tabu ban đầu: {self.current_tenure}. "
            f"Phạm vi động: [{self.min_tenure}, {self.max_tenure}]"
        )

        last_iter = self.max_iter

        for i in range(self.max_iter):
            # Check time limit
            if time.time() - self.start_time > self.max_time:
                print(
                    f"\nĐã đạt giới hạn thời gian {self.max_time}s "
                    f"ở vòng lặp {i}."
                )
                last_iter = i
                break

            # Generate neighbors (passes the ALNSOperator as evaluator)
            neighbors = self.neighbor_gen.generate_neighbors(
                self.current_solution, self.mo_probability, self.evaluator
            )

            if not neighbors:
                continue

            # Sort by cost
            neighbors.sort(key=lambda s: s["total_cost"])

            best_neighbor_found = False
            improvement_this_iteration = False
            chosen_move_is_mo = False

            # Find best admissible neighbor
            for neighbor in neighbors:
                move = self._get_move_signature(
                    self.current_solution["assignment"],
                    neighbor["assignment"],
                )
                is_best_ever = neighbor["total_cost"] < self.best_cost
                is_not_tabu = move not in self.tabu_list

                if is_best_ever or is_not_tabu:
                    self.current_solution = neighbor
                    chosen_move_is_mo = "type" in neighbor
                    self.tabu_list.append(move)

                    if is_best_ever:
                        self.best_solution = copy.deepcopy(neighbor)
                        self.best_cost = neighbor["total_cost"]
                        improvement_this_iteration = True
                        print(
                            f"Vòng lặp {i}: Tìm thấy giải pháp tốt hơn! "
                            f"Chi phí mới: {self.best_cost:,.2f}"
                        )

                    best_neighbor_found = True
                    break

            # If all neighbors are tabu, take best one anyway
            if not best_neighbor_found:
                self.current_solution = neighbors[0]
                chosen_move_is_mo = "type" in self.current_solution

            self.costs.append(self.current_solution["total_cost"])

            # Update adaptive strategy
            self._update_mo_strategy(
                chosen_move_is_mo, improvement_this_iteration
            )

            # Adaptive tenure management
            if improvement_this_iteration:
                self.consecutive_improvements_counter += 1
                self.no_improvement_counter = 0

                if (
                    self.consecutive_improvements_counter
                    >= self.decrease_threshold
                ):
                    if self.current_tenure > self.min_tenure:
                        self.current_tenure = max(
                            self.min_tenure, self.current_tenure - 1
                        )
                        self._update_tabu_list_capacity()
                        if self.verbose:
                            print(
                                f"  -> Cải thiện liên tục. "
                                f"Nhiệm kỳ giảm xuống: "
                                f"{self.current_tenure}"
                            )
                    self.consecutive_improvements_counter = 0
            else:
                self.no_improvement_counter += 1
                self.consecutive_improvements_counter = 0

                if (
                    self.no_improvement_counter
                    >= self.increase_threshold
                ):
                    if self.current_tenure < self.max_tenure:
                        self.current_tenure = min(
                            self.max_tenure, self.current_tenure + 2
                        )
                        self._update_tabu_list_capacity()
                        if self.verbose:
                            print(
                                f"  -> Không cải thiện. "
                                f"Nhiệm kỳ tăng lên: "
                                f"{self.current_tenure}"
                            )
                    self.no_improvement_counter = 0

            # Progress report
            if i % 100 == 0 and i > 0:
                print(
                    f"Vòng lặp {i}: Chi phí hiện tại = "
                    f"{self.current_solution['total_cost']:,.2f}, "
                    f"Tốt nhất = {self.best_cost:,.2f}, "
                    f"Xác suất MO = {self.mo_probability:.2f}"
                )

        # Final summary
        print("\n" + "=" * 50)
        print("TỐI ƯU HÓA HOÀN TẤT")
        print(f"Chi phí cuối cùng tốt nhất: {self.best_cost:,.2f}")
        print(f"Tổng số vòng lặp: {last_iter}")
        print(f"Thời gian chạy: {time.time() - self.start_time:.2f} giây")
        print("=" * 50)

        # Final repair
        self.best_solution["is_final_check"] = True
        self.best_solution = self.evaluator.repair_and_evaluate(
            self.best_solution
        )

        return self.best_solution

    def _get_move_signature(
        self, old_assign: Dict, new_assign: Dict
    ) -> tuple:
        """Create unique signature for a move (for tabu list)."""
        return tuple(
            sorted(
                [
                    (k, old_assign[k], new_assign[k])
                    for k in old_assign
                    if old_assign[k] != new_assign[k]
                ]
            )
        )

    def _update_tabu_list_capacity(self):
        """Update tabu list size when tenure changes."""
        if self.tabu_list.maxlen != self.current_tenure:
            self.tabu_list = deque(
                self.tabu_list, maxlen=self.current_tenure
            )

    def _update_mo_strategy(
        self, move_was_mo: bool, move_led_to_improvement: bool
    ):
        """
        Update multi-objective strategy based on recent success.
        Increases MO probability if successful, decreases otherwise.
        """
        if move_was_mo:
            self.mo_moves_attempted += 1
            if move_led_to_improvement:
                self.mo_moves_accepted_as_best += 1

        # Adjust MO probability after burn-in period
        if self.mo_moves_attempted > 20:
            success_rate = (
                self.mo_moves_accepted_as_best / self.mo_moves_attempted
            )

            # Successful MO moves -> increase usage
            if success_rate > 0.1:
                self.mo_probability = min(0.95, self.mo_probability + 0.05)
            # Unsuccessful -> decrease usage
            else:
                self.mo_probability = max(0.2, self.mo_probability - 0.05)

            # Periodic reset to adapt to different search phases
            if self.mo_moves_attempted > 100:
                self.mo_moves_attempted = 0
                self.mo_moves_accepted_as_best = 0

    # Convenience methods for reporting
    def print_solution_summary(self, solution=None):
        """Print summary of solution."""
        sol = solution or self.best_solution
        self.visualizer.print_solution_summary(sol)

    def plot_cost_progress(self):
        """Plot cost evolution."""
        self.visualizer.plot_cost_progress(self.costs)

    def visualize_schedule(self, solution=None):
        """Visualize schedule."""
        sol = solution or self.best_solution
        self.visualizer.visualize_schedule(sol)

    def print_detailed_reports(self, solution=None, order_df=None):
        """Generate detailed reports."""
        sol = solution or self.best_solution
        self.visualizer.print_detailed_reports(sol, order_df)

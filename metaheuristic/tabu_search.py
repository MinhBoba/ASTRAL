import time
import copy
from collections import deque, defaultdict
import random

# import internal modules
from .neighbor_generator import NeighborGenerator
from .ALNS_operator import ALNSOperator
from .oscillation_strategy import StrategicOscillationHandler

class TabuSearchSolver:
    def __init__(self, input_data, discount_alpha=0.05, initial_line_df=None, max_iter=1000, 
                 tabu_tenure=15, max_time=1200, min_tenure=5, max_tenure=40, 
                 increase_threshold=50, decrease_threshold=10, verbose=True):
        
        self.input = input_data
        self.alpha = discount_alpha
        self.max_iter = max_iter
        self.max_time = max_time
        self.verbose = verbose
        
        # --- TABU PARAMETERS ---
        self.current_tenure = tabu_tenure
        self.min_tenure = min_tenure
        self.max_tenure = max_tenure
        self.increase_threshold = increase_threshold
        self.decrease_threshold = decrease_threshold
        self.tabu_list = deque(maxlen=self.current_tenure)
        
        # --- ADAPTIVE TRACKING ---
        self.no_improvement_counter = 0
        self.consecutive_improvements_counter = 0
        self.mo_probability = 0.5  # probability of running a multi-objective move
        self.mo_moves_attempted = 0
        self.mo_moves_accepted_as_best = 0

        # --- SETUP CAPABILITY MAP ---
        # map used by NeighborGenerator to know which line can process which styles
        param_enable = self.input.param.get("paramYenable", {})
        self.cap_map = defaultdict(set)
        for (l, s), val in param_enable.items():
            if val: self.cap_map[l].add(s)

        # check basic input data
        for l in self.input.set['setL']:
            if not self.cap_map[l]:
                print(f"WARNING: Line {l} has no allowable styles (paramYenable all zeros).")

        # --- INITIALIZE COMPONENTS ---
        # 1. Evaluator
        self.evaluator = ALNSOperator(input_data, self.cap_map, discount_alpha)
        
        # 2. Generator
        self.neighbor_gen = NeighborGenerator(input_data, self.cap_map)
        
        # 3. Oscillation
        self.oscillation_handler = StrategicOscillationHandler(input_data, self.evaluator)

        # --- INITIAL SOLUTION ---
        print("Creating initial solution...")
        self.current_solution = self.evaluator.initialize_solution()
        self.best_solution = copy.deepcopy(self.current_solution)
        self.best_cost = self.current_solution['total_cost']
        self.costs = [self.best_cost]
        self.start_time = time.time()

    def solve(self):
        print(f"\n--- STARTING OPTIMIZATION ---")
        print(f"Initial cost: {self.best_cost:,.2f}")
        print(f"Tham số: Max Iter={self.max_iter}, Max Time={self.max_time}s")
        print("-" * 60)
        
        last_iter = 0
        
        for i in range(1, self.max_iter + 1):
            last_iter = i
            
            # 1. check elapsed time
            if time.time() - self.start_time > self.max_time:
                print(f"\n[STOP] reached time limit at iteration {i}.")
                break

            # 2. Cập nhật Fast Fail cho Evaluator
            self.evaluator.set_pruning_best(self.best_cost)

            # A. STRATEGIC OSCILLATION
            # trigger when stagnated (no_improve > 150) or periodically (every 250 iterations)
            oscillation_triggered = False
            if i > 50 and (self.no_improvement_counter > 150 or i % 250 == 0):
                oscillation_triggered = self._perform_oscillation(i)
            
            # if oscillation found a new path and reset counters,
            # we can skip the regular neighbor search this iteration to save time
            if oscillation_triggered and self.no_improvement_counter == 0:
                continue

            # B. NEIGHBORHOOD SEARCH

            neighbors = self.neighbor_gen.generate_neighbors(
                self.current_solution, 
                self.mo_probability, 
                self.evaluator
            )
            
            if not neighbors:
                continue

            # sort to prioritize good solutions (Best Improvement strategy)
            # normally Tabu Search would scan all; sorting makes aspiration checks easier
            neighbors.sort(key=lambda s: s['total_cost'])
            
            best_neighbor = None
            found_valid_move = False
            chosen_move_is_mo = False

            # iterate through neighbors
            for neighbor in neighbors:
                move_signature = self._get_move_signature(self.current_solution['assignment'], neighbor['assignment'])
                cost = neighbor['total_cost']
                
                # Aspiration Criteria: if better than Best Global -> ignore Tabu
                is_aspiration = cost < self.best_cost
                is_tabu = move_signature in self.tabu_list
                
                if is_aspiration or not is_tabu:
                    best_neighbor = neighbor
                    found_valid_move = True
                    chosen_move_is_mo = (neighbor.get('type') == 'mo_move')
                    
                    # Cập nhật Tabu List
                    self.tabu_list.append(move_signature)
                    
                    # update Best Global if needed
                    if is_aspiration:
                        self.best_solution = copy.deepcopy(neighbor)
                        self.best_cost = cost
                        self._on_improvement(i, cost, source="TabuSearch")
                    else:
                        self._on_no_improvement()
                    
                    break # chosen the best feasible move so stop (Best Fit)

            # Cập nhật Current Solution
            if found_valid_move:
                self.current_solution = best_neighbor
            else:
                # if all moves are tabu (rare), pick the best anyway to avoid deadlock
                # to prevent the algorithm from getting stuck
                best_neighbor = neighbors[0]
                self.current_solution = best_neighbor
                # still count as no global improvement
                self._on_no_improvement()

            self.costs.append(self.current_solution['total_cost'])

            # ==========================================================
            # C. ADAPTIVE STRATEGY
            # ==========================================================
            self._update_mo_strategy(chosen_move_is_mo, found_valid_move and best_neighbor['total_cost'] < self.costs[-2] if len(self.costs)>1 else False)
            self._update_tenure()

            # Logging
            if i % 100 == 0:
                print(f"Iter {i:5d} | Current: {self.current_solution['total_cost']:12,.0f} | Best: {self.best_cost:12,.0f} | Tenure: {self.current_tenure:2d} | MO Prob: {self.mo_probability:.2f}")

        # --- FINISH ---
        return self._finalize_solution(last_iter)

    #  HELPER METHODS

    def _perform_oscillation(self, iter_idx):
        """Perform strategic oscillation logic: Relax -> Repair."""
        if self.verbose:
            print(f"  >> [Oscillation] triggered at iteration {iter_idx}. exploring infeasible region...")

        # 1. Relax: generate infeasible solution
        relaxed_sol = self.oscillation_handler.explore_infeasible_region(self.best_solution)
        
        # 2. Repair: aggressive correction
        feasible_sol = self.oscillation_handler.aggressive_repair(relaxed_sol)
        
        cost_new = feasible_sol['total_cost']
        improved = False
        
        # 3. evaluate
        if cost_new < self.best_cost:
            # found new record thanks to oscillation
            self.best_solution = copy.deepcopy(feasible_sol)
            self.best_cost = cost_new
            self.current_solution = feasible_sol
            self._on_improvement(iter_idx, cost_new, source="Oscillation")
            
            # reset Tabu List to freely explore this new region
            self.tabu_list.clear()
            improved = True
            
        elif self.no_improvement_counter > 200:
            # "Desperation" mode: if stuck too long, accept an oscillation solution
            # even if it's not better than global best, as long as it's different to escape the hole.
            # (here we require it not be too much worse than current)
            if cost_new < self.current_solution['total_cost'] * 1.1:
                if self.verbose:
                    print(f"  >> [Oscillation] accepting alternative solution to escape stagnation (Cost: {cost_new:,.0f}).")
                self.current_solution = feasible_sol
                self.tabu_list.clear()
                self.no_improvement_counter = 50 # Reset một phần
                improved = True # return True to signal main loop to skip neighbor search this iteration

        return improved

    def _on_improvement(self, iter_idx, new_cost, source="Tabu"):
        """Handle event when a better solution is found."""
        print(f"[{source}] Iter {iter_idx}: new record! Cost: {new_cost:,.2f}")
        self.consecutive_improvements_counter += 1
        self.no_improvement_counter = 0

    def _on_no_improvement(self):
        """Handle event when no global improvement occurs."""
        self.no_improvement_counter += 1
        self.consecutive_improvements_counter = 0

    def _update_tenure(self):
        """Adjust tabu list length (Tabu Tenure) dynamically."""
        if self.consecutive_improvements_counter >= self.decrease_threshold:
            # doing well -> decrease tenure to intensify search
            if self.current_tenure > self.min_tenure:
                self.current_tenure -= 1
                self.tabu_list = deque(self.tabu_list, maxlen=self.current_tenure)
            self.consecutive_improvements_counter = 0
            
        elif self.no_improvement_counter >= self.increase_threshold:
            # stuck -> increase tenure to diversify search
            if self.current_tenure < self.max_tenure:
                self.current_tenure += 2
                self.tabu_list = deque(self.tabu_list, maxlen=self.current_tenure)
            self.no_improvement_counter = 0 # reset to avoid rapidly increasing again

    def _update_mo_strategy(self, move_was_mo, move_was_improvement):
        """Adjust probability of using multi-objective moves."""
        if move_was_mo:
            self.mo_moves_attempted += 1
            if move_was_improvement:
                self.mo_moves_accepted_as_best += 1
        
        # adjust every 50 attempts
        if self.mo_moves_attempted > 50:
            rate = self.mo_moves_accepted_as_best / self.mo_moves_attempted
            if rate > 0.15: # if reasonably effective
                self.mo_probability = min(0.9, self.mo_probability + 0.05)
            else:
                self.mo_probability = max(0.2, self.mo_probability - 0.05)
            
            # Reset
            self.mo_moves_attempted = 0
            self.mo_moves_accepted_as_best = 0

    def _get_move_signature(self, old_assign, new_assign):
        """Create a signature for a move to store in the Tabu list.
        The signature is a tuple of changes: ((line, date, old_style, new_style), ...)
        """
        changes = []
        for key, val in old_assign.items():
            if new_assign[key] != val:
                changes.append((key, val, new_assign[key]))
        # sort to ensure tuple consistency
        return tuple(sorted(changes))

    def _finalize_solution(self, iterations_run):
        print("\n" + "="*50)
        print("OPTIMIZATION COMPLETE")
        print(f"Best cost: {self.best_cost:,.2f}")
        print(f"Total iterations: {iterations_run}")
        print(f"Elapsed time: {time.time() - self.start_time:.2f}s")
        print("="*50)
        
        # disable pruning to compute final metrics accurately
        self.evaluator.set_pruning_best(float('inf'))
        
        # 1. recompute all statistics
        final_sol_id = self.evaluator.repair_and_evaluate(self.best_solution)
        
        # 2. convert ID -> string (important for Excel export)
        final_sol_str = self.evaluator.convert_solution_to_string_keys(final_sol_id)
        
        return final_sol_str

    def print_solution_summary(self, solution=None):
        sol = solution or self.best_solution  # solution should have string keys (after finalizing)
        if not sol:
            print("No solution available.")
            return

        # note: if called before finalize the solution may still use IDs
        # perform safety checks
        total = sol.get('total_cost', 0)
        setup = sol.get('total_setup', 0)
        late = sol.get('total_late', 0)
        exp = sol.get('total_exp', 0)
        
        print(f"Total cost: {total:,.2f}")
        print(f"  - Setup cost: {setup:,.2f}")
        print(f"  - Late penalty: {late:,.2f}")
        print(f"  - Experience reward: {exp:,.2f}")

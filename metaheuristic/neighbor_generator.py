"""
Neighbor generation strategies for Tabu Search.
Includes traditional random moves and multi-objective moves.
"""

import random
import copy
from typing import Dict, List, Any, Set


class NeighborGenerator:
    """Generates neighbor solutions using various strategies."""

    def __init__(self, input_data, cap_map: Dict[str, Set[str]]):
        """
        Parameters
        ----------
        input_data : InputData
            Problem data including sets and parameters
        cap_map : Dict[str, Set[str]]
            Mapping of line -> allowed styles
        """
        self.input = input_data
        self.cap_map = cap_map

    def _random_allowed_style(self, line: str, rng=random) -> str:
        """Get a random allowed style for a given line."""
        return rng.choice(list(self.cap_map[line]))

    def _is_allowed(self, line: str, style: str) -> bool:
        """Check if a line can produce a style."""
        return style in self.cap_map[line]

    def generate_neighbors(
        self, base_solution: Dict, mo_probability: float, evaluator
    ) -> List[Dict]:
        """
        Master neighbor generation method with adaptive mix of strategies.

        Parameters
        ----------
        base_solution : Dict
            Current solution with 'assignment' key
        mo_probability : float
            Probability of generating multi-objective moves
        evaluator : ALNSOperator
            Evaluator instance to repair and evaluate solutions

        Returns
        -------
        List[Dict]
            List of neighbor solutions
        """
        neighbors = []

        # Always generate traditional random moves
        traditional = self._generate_traditional_neighbors(
            base_solution, evaluator
        )
        neighbors.extend(traditional)

        # With certain probability, add smarter multi-objective moves
        if random.random() < mo_probability:
            mo_neighbors = self.generate_multi_objective_neighbors(
                base_solution, evaluator
            )
            neighbors.extend(mo_neighbors)

        return neighbors

    def _generate_traditional_neighbors(
        self, base_solution: Dict, evaluator
    ) -> List[Dict]:
        """
        Generate traditional random moves: swap, block reassign, single reassign.
        All moves respect line-style capability constraints.
        """
        neighbors = []
        num_neighbors = max(len(self.input.set["setL"]) * 2, 10)

        for _ in range(num_neighbors):
            move_type = random.choice(
                ["swap", "reassign_block", "reassign_single"]
            )
            new_assignment = copy.deepcopy(base_solution["assignment"])
            l = random.choice(self.input.set["setL"])

            if move_type == "swap" and len(self.input.set["setT"]) >= 2:
                t1, t2 = random.sample(self.input.set["setT"], 2)
                new_assignment[(l, t1)], new_assignment[(l, t2)] = (
                    new_assignment[(l, t2)],
                    new_assignment[(l, t1)],
                )

            elif (
                move_type == "reassign_block"
                and len(self.input.set["setT"]) > 5
            ):
                block_size = random.randint(
                    2, max(2, len(self.input.set["setT"]) // 4)
                )
                start_t = random.randint(
                    min(self.input.set["setT"]),
                    max(self.input.set["setT"]) - block_size,
                )
                # Randomize a new style (might be suboptimal, ALNSOperator will evaluate)
                new_style = self._random_allowed_style(l)
                for t_offset in range(block_size):
                    t = start_t + t_offset
                    if t in self.input.set["setT"]:
                        new_assignment[(l, t)] = new_style

            else:  # reassign_single
                t = random.choice(self.input.set["setT"])
                new_style = self._random_allowed_style(l)
                new_assignment[(l, t)] = new_style

            # Only accept if something changed
            if new_assignment != base_solution["assignment"]:
                neighbors.append(
                    evaluator.repair_and_evaluate(
                        {"assignment": new_assignment}
                    )
                )

        return neighbors

    def generate_multi_objective_neighbors(
        self, base_solution: Dict, evaluator
    ) -> List[Dict]:
        """
        Generate intelligent neighbors focusing on:
        1. Reducing setup costs (merge short segments)
        2. Reducing late costs (boost capacity for risky styles)
        3. Balanced moves
        """
        neighbors = []

        # 1. Setup reduction moves
        setup_moves = self._generate_setup_reduction_moves(
            base_solution, evaluator
        )
        neighbors.extend(setup_moves)

        # 2. Late cost reduction moves
        late_moves = self._generate_late_cost_reduction_moves(
            base_solution, evaluator
        )
        neighbors.extend(late_moves)

        # 3. Balanced moves
        balanced = self._generate_balanced_moves(base_solution, evaluator)
        neighbors.extend(balanced)

        return neighbors

    def _generate_setup_reduction_moves(
        self, base_solution: Dict, evaluator
    ) -> List[Dict]:
        """Merge short segments into adjacent dominant style."""
        moves = []
        current_assign = base_solution["assignment"]

        for l in self.input.set["setL"]:
            segments = self._find_short_segments(l, current_assign)
            for segment in segments:
                if len(segment["periods"]) > 3:
                    continue

                dominant = self._get_dominant_neighbor_style(
                    l, segment, current_assign
                )
                if dominant and self._is_allowed(l, dominant):
                    new_assign = copy.deepcopy(current_assign)
                    for t in segment["periods"]:
                        new_assign[(l, t)] = dominant
                    moves.append(
                        {
                            "assignment": new_assign,
                            "type": "setup_reduction",
                        }
                    )

        # Evaluate top moves only
        return [evaluator.repair_and_evaluate(m) for m in moves[:5]]

    def _generate_late_cost_reduction_moves(
        self, base_solution: Dict, evaluator
    ) -> List[Dict]:
        """Boost production for styles at risk of being late."""
        moves = []
        current_assign = base_solution["assignment"]

        # Identify high-risk styles
        high_risk = self._identify_high_risk_styles(base_solution)[:3]

        for style in high_risk:
            capacity_moves = self._generate_capacity_boost_moves(
                style, current_assign
            )
            moves.extend(capacity_moves)

        return [evaluator.repair_and_evaluate(m) for m in moves[:5]]

    def _generate_balanced_moves(
        self, base_solution: Dict, evaluator
    ) -> List[Dict]:
        """Strategic swaps attempting to balance setup and late costs."""
        moves = []
        current_assign = base_solution["assignment"]

        for l in self.input.set["setL"]:
            if len(self.input.set["setT"]) < 2:
                continue

            t1, t2 = random.sample(self.input.set["setT"], 2)

            # Only swap if styles are different
            if current_assign.get((l, t1)) != current_assign.get((l, t2)):
                new_assign = copy.deepcopy(current_assign)
                new_assign[(l, t1)], new_assign[(l, t2)] = (
                    new_assign[(l, t2)],
                    new_assign[(l, t1)],
                )
                moves.append({"assignment": new_assign, "type": "balanced"})

        return [evaluator.repair_and_evaluate(move) for move in moves[:3]]

    def _find_short_segments(
        self, line: str, assignment: Dict
    ) -> List[Dict]:
        """Find short consecutive blocks of the same style."""
        segments = []
        if not self.input.set["setT"]:
            return segments

        sorted_days = sorted(self.input.set["setT"])
        current_style = None
        current_segment = []

        for t in sorted_days:
            style = assignment.get((line, t))
            if style != current_style:
                if current_segment:
                    segments.append(
                        {"style": current_style, "periods": current_segment}
                    )
                current_style = style
                current_segment = [t]
            else:
                current_segment.append(t)

        if current_segment:
            segments.append(
                {"style": current_style, "periods": current_segment}
            )

        # Return only short segments
        return [s for s in segments if len(s["periods"]) <= 3]

    def _get_dominant_neighbor_style(
        self, line: str, segment: Dict, assignment: Dict
    ) -> str | None:
        """Get the style of blocks surrounding a segment."""
        start_t = min(segment["periods"])
        end_t = max(segment["periods"])

        prev_t = start_t - 1
        next_t = end_t + 1

        prev_style = assignment.get((line, prev_t))
        next_style = assignment.get((line, next_t))

        # Best case: merge into larger block
        if prev_style and prev_style == next_style:
            return prev_style

        # Otherwise pick one neighbor
        return prev_style or next_style

    def _identify_high_risk_styles(self, solution: Dict) -> List[str]:
        """Identify styles with highest final backlog."""
        backlog = solution.get("final_backlog", {})
        if not backlog:
            return []

        sorted_styles = sorted(
            backlog.keys(), key=lambda s: backlog[s], reverse=True
        )
        return [s for s in sorted_styles if backlog[s] > 0]

    def _generate_capacity_boost_moves(
        self, style_to_boost: str, assignment: Dict
    ) -> List[Dict]:
        """Assign risky style to idle slots on capable lines."""
        moves = []

        # Find potential slots
        potential = [
            (l, t)
            for l in self.input.set["setL"]
            for t in self.input.set["setT"]
            if self._is_allowed(l, style_to_boost)
            and assignment.get((l, t)) != style_to_boost
        ]

        if potential:
            l, t = random.choice(potential)
            new_assign = copy.deepcopy(assignment)
            new_assign[(l, t)] = style_to_boost
            moves.append(
                {"assignment": new_assign, "type": "late_cost_reduction"}
            )

        return moves

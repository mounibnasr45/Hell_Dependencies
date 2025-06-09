# dependency_resolver_agent/agent_core/heuristic_calculator.py
from typing import FrozenSet
from dependency_resolver_agent.data_models.requirement import Requirement
from dependency_resolver_agent.data_models.conflict_info import ConflictInfo

class HeuristicCalculator:
    def calculate_h_score(
        self,
        current_requirements: FrozenSet[Requirement], # pylint: disable=unused-argument
        conflict_info: ConflictInfo,
        original_direct_reqs: FrozenSet[Requirement] # pylint: disable=unused-argument
    ) -> float:
        if not conflict_info.is_conflict:
            return 0.0

        num_involved = len(conflict_info.involved_direct_packages)
        
        # Base heuristic: number of direct dependencies involved, or 1 if unknown but conflict exists
        h_val = float(num_involved) if num_involved > 0 else 1.0

        # Slightly higher heuristic if a specific sub-dependency is identified as a multi-package problem
        if conflict_info.sub_dependency_culprit and num_involved > 1:
            h_val += 0.5
        
        # If all original direct dependencies are involved, it might be a more complex conflict
        if num_involved == len(original_direct_reqs) and num_involved > 1:
            h_val += 0.2 # Small bump if all are involved

        return h_val
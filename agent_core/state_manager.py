# dependency_resolver_agent/agent_core/state_manager.py
from dataclasses import dataclass, field
from typing import FrozenSet, Optional, List, Tuple

from dependency_resolver_agent.data_models.requirement import Requirement

@dataclass
class AStarNode:
    requirements: FrozenSet[Requirement]
    g_score: float = float('inf')
    h_score: float = float('inf')
    parent: Optional['AStarNode'] = None
    last_action: str = "Initial state" # Description of the action that led to this node

    @property
    def f_score(self) -> float:
        return self.g_score + self.h_score

    # For heapq priority queue
    def __lt__(self, other: 'AStarNode'):
        if self.f_score != other.f_score:
            return self.f_score < other.f_score
        # Tie-breaking: prefer lower g_score (closer to start with same f_score)
        if self.g_score != other.g_score:
            return self.g_score < other.g_score
        # Further tie-breaking: prefer fewer requirements (simpler state)
        return len(self.requirements) < len(other.requirements)

    # For using in sets/dictionary keys (processed_node_g_scores)
    def __hash__(self):
        return hash(self.requirements)

    def __eq__(self, other):
        if not isinstance(other, AStarNode):
            return False
        return self.requirements == other.requirements

def reconstruct_path(node: AStarNode) -> List[Tuple[str, FrozenSet[Requirement]]]:
    path = []
    current = node
    while current:
        path.append((current.last_action, current.requirements))
        current = current.parent
    return path[::-1] # Return from start to goal
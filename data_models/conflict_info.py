# dependency_resolver_agent/data_models/conflict_info.py
from dataclasses import dataclass, field
from typing import Set, Optional, Tuple

@dataclass
class ConflictInfo:
    is_conflict: bool
    error_message: str = ""
    involved_direct_packages: Set[str] = field(default_factory=set)
    # (package_name, specifier_hint_from_error_str)
    sub_dependency_culprit: Optional[Tuple[str, str]] = None
    # Could add more structured fields if LLM provides them, e.g.:
    # conflicting_transitive_constraints: Dict[str, List[str]]
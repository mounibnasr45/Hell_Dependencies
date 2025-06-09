# dependency_resolver_agent/utils/cache_manager.py
from typing import Dict, FrozenSet, Optional

from dependency_resolver_agent.data_models import Requirement, ConflictInfo
# Forward declaration for type hint, actual import handled by type checker
if False: # TYPE_CHECKING
    from dependency_resolver_agent.data_models.requirement import Requirement
    from dependency_resolver_agent.data_models.conflict_info import ConflictInfo


# Cache for pip-compile results: Keyed by FrozenSet[Requirement], Value: ConflictInfo
PIP_COMPILE_CACHE: Dict[FrozenSet['Requirement'], 'ConflictInfo'] = {}

# Cache for full pip-compile evaluation (raw output + ConflictInfo)
# Key: FrozenSet[Requirement], Value: Tuple[bool_success, str_stdout, str_stderr, ConflictInfo]
# This helps avoid re-parsing if only raw output was needed before, but now ConflictInfo is
FULL_EVAL_CACHE: Dict[FrozenSet['Requirement'], tuple[bool, str, str, 'ConflictInfo']] = {}


def get_cached_pip_compile_result(requirements_set: FrozenSet['Requirement']) -> Optional['ConflictInfo']:
    return PIP_COMPILE_CACHE.get(requirements_set)

def store_pip_compile_result(requirements_set: FrozenSet['Requirement'], result: 'ConflictInfo'):
    PIP_COMPILE_CACHE[requirements_set] = result

def clear_pip_compile_cache():
    PIP_COMPILE_CACHE.clear()
    FULL_EVAL_CACHE.clear()

def get_cached_full_eval(requirements_set: FrozenSet['Requirement']) -> Optional[tuple[bool, str, str, 'ConflictInfo']]:
    return FULL_EVAL_CACHE.get(requirements_set)

def store_cached_full_eval(requirements_set: FrozenSet['Requirement'], data: tuple[bool, str, str, 'ConflictInfo']):
    FULL_EVAL_CACHE[requirements_set] = data
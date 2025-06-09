# dependency_resolver_agent/agent_core/action_generator.py
import re
from typing import List, Tuple, FrozenSet, Optional, Set

from dependency_resolver_agent.data_models.requirement import Requirement, Version, PACKAGING_AVAILABLE, SpecifierSet, InvalidVersion, InvalidSpecifier
from dependency_resolver_agent.data_models.conflict_info import ConflictInfo
from dependency_resolver_agent.tooling.pypi_service import PyPIService
from dependency_resolver_agent.utils.logger import log_verbose
from dependency_resolver_agent.agent_core.state_manager import AStarNode


class ActionGenerator:
    def __init__(self, pypi_service: PyPIService):
        self.pypi_service = pypi_service

    def get_cost_of_action(self, action_desc: str, req_before: Optional[Requirement], req_after: Optional[Requirement]) -> float:
        base_cost = 1.0

        if "Changed" in action_desc and req_before is not None and req_after is not None:
            if not PACKAGING_AVAILABLE:
                return base_cost + 0.5 # Generic penalty

            try:
                # Both exact versions
                if req_before.is_exact() and req_after.is_exact():
                    v_before = req_before.get_version_obj()
                    v_after = req_after.get_version_obj()
                    if v_before and v_after:
                        if v_before.major != v_after.major: return base_cost + 2.0
                        if v_before.minor != v_after.minor: return base_cost + 1.0
                        if v_before.micro != v_after.micro: return base_cost + 0.5
                        return base_cost + 0.25 # Smaller changes (epoch, pre/post release)
                # Changing from non-exact to exact
                elif not req_before.is_exact() and req_after.is_exact() and req_before.specifier:
                    old_spec_set = SpecifierSet(req_before.specifier)
                    new_version = req_after.get_version_obj()
                    if new_version and new_version in old_spec_set:
                        return base_cost + 0.1 # Low cost for pinning within allowed range
                    else:
                        return base_cost + 1.7 # Pinning outside original loose spec
                return base_cost + 1.5 # Other changes
            except (InvalidVersion, InvalidSpecifier, TypeError, AttributeError):
                return base_cost + 1.2 # Fallback

        elif "Loosened" in action_desc:
            return base_cost + 1.2 # Higher than patch, lower than minor

        elif "Pinned transitive" in action_desc:
            return base_cost + 3.0 # Relatively high cost

        elif "Removed direct" in action_desc:
            return base_cost + 5.0 # Very high cost

        return base_cost

    def get_neighbors(
        self,
        current_node: AStarNode,
        original_direct_reqs: FrozenSet[Requirement], # Names of original requirements
        conflict_info: ConflictInfo
        ) -> List[Tuple[FrozenSet[Requirement], str, float]]:

        neighbors: List[Tuple[FrozenSet[Requirement], str, float]] = []
        current_reqs_map = {r.name: r for r in current_node.requirements}

        # Determine which packages to focus modifications on
        # If conflict_info gives specific packages, use them. Otherwise, consider all originals.
        pkgs_to_target_for_modification_names: Set[str] = conflict_info.involved_direct_packages
        if not pkgs_to_target_for_modification_names and conflict_info.is_conflict:
            # If conflict exists but no specific packages identified, target all *current* direct dependencies
            # that were also part of the *original* set.
            original_direct_req_names = {r.name for r in original_direct_reqs}
            pkgs_to_target_for_modification_names = {
                r.name for r in current_node.requirements if r.name in original_direct_req_names
            }
            log_verbose("    [Neighbors] Conflict, but no specific pkgs. Targeting all current original direct dependencies.")
        elif not conflict_info.is_conflict: # Should not happen if called correctly
            log_verbose("    [Neighbors] No conflict, no neighbors generated via modification.")
            return []


        log_verbose(f"    [Neighbors] Packages targeted for modification based on conflict: {pkgs_to_target_for_modification_names or 'None'}")

        # Strategy 1: Change version of a direct dependency
        for pkg_name_to_modify in pkgs_to_target_for_modification_names:
            current_req_obj = current_reqs_map.get(pkg_name_to_modify)
            if not current_req_obj:
                log_verbose(f"    [Neighbors] Warning: Targeted package '{pkg_name_to_modify}' not in current node's requirements. Skipping version change for it.")
                continue

            log_verbose(f"      [Neighbors] Considering version changes for '{pkg_name_to_modify}' (current: {current_req_obj.specifier})")
            versions_to_try = self.pypi_service.get_versions_to_try(pkg_name_to_modify, current_req_obj)
            log_verbose(f"        [Neighbors] Versions to try for '{pkg_name_to_modify}': {versions_to_try[:5]}{'...' if len(versions_to_try)>5 else ''}")

            for v_str_to_try in versions_to_try:
                new_spec = f"=={v_str_to_try}"
                if new_spec == current_req_obj.specifier:
                    continue

                new_req_for_pkg = Requirement(name=pkg_name_to_modify, specifier=new_spec)
                
                temp_new_reqs_list = [r for r in current_node.requirements if r.name != pkg_name_to_modify]
                temp_new_reqs_list.append(new_req_for_pkg)
                new_requirements_set = frozenset(temp_new_reqs_list)

                action_desc = f"Changed {pkg_name_to_modify} from '{current_req_obj.specifier}' to '{new_spec}'"
                action_cost = self.get_cost_of_action(action_desc, current_req_obj, new_req_for_pkg)
                neighbors.append((new_requirements_set, action_desc, action_cost))
                log_verbose(f"          [Neighbors] Generated (Version Change): {action_desc}, cost={action_cost:.2f}")

        # Strategy 2: Loosen constraint (e.g., from ==X.Y.Z to ~=X.Y)
        if PACKAGING_AVAILABLE: # This strategy relies heavily on 'packaging'
            for pkg_name_to_loosen in pkgs_to_target_for_modification_names:
                current_req_obj = current_reqs_map.get(pkg_name_to_loosen)
                if not current_req_obj or not current_req_obj.is_exact():
                    continue # Only loosen exact constraints

                current_version_obj = current_req_obj.get_version_obj()
                if not current_version_obj or not hasattr(current_version_obj, 'release') or len(current_version_obj.release) < 2:
                    continue # Cannot determine major.minor

                major, minor = current_version_obj.release[0], current_version_obj.release[1]
                new_loose_spec = f"~={major}.{minor}"

                if new_loose_spec == current_req_obj.specifier: # Should not happen if it was exact
                    continue
                
                # Avoid re-loosening if already compatible, e.g. ==1.2.3 to ~=1.2, then later considering ==1.2.0 to ~=1.2
                # This check is subtle. If already loose, this strategy shouldn't apply.
                # But if it was ==1.2.0 and we generate ~=1.2, it's valid.
                # The main guard is `current_req_obj.is_exact()`

                loosened_req = Requirement(name=pkg_name_to_loosen, specifier=new_loose_spec)
                
                temp_new_reqs_list = [r for r in current_node.requirements if r.name != pkg_name_to_loosen]
                temp_new_reqs_list.append(loosened_req)
                new_requirements_set = frozenset(temp_new_reqs_list)

                action_desc = f"Loosened {pkg_name_to_loosen} from '{current_req_obj.specifier}' to '{new_loose_spec}'"
                action_cost = self.get_cost_of_action(action_desc, current_req_obj, loosened_req)
                neighbors.append((new_requirements_set, action_desc, action_cost))
                log_verbose(f"          [Neighbors] Generated (Loosen): {action_desc}, cost={action_cost:.2f}")

        # Strategy 3: Pin problematic transitive dependency
        if conflict_info.sub_dependency_culprit:
            sub_dep_name, sub_dep_spec_hint = conflict_info.sub_dependency_culprit
            log_verbose(f"      [Neighbors] Considering pinning transitive dependency '{sub_dep_name}' (hint: '{sub_dep_spec_hint}')")
            
            # Check if this sub_dep is already a direct requirement (pinned)
            if sub_dep_name in current_reqs_map:
                log_verbose(f"        [Neighbors] Transitive dependency '{sub_dep_name}' is already a direct requirement. Skipping re-pinning for now.")
            else:
                versions_to_try_for_subdep = self.pypi_service.get_versions_to_try(
                    sub_dep_name,
                    sub_dep_specifier_hint=sub_dep_spec_hint # Pass hint to pypi_service
                )
                log_verbose(f"        [Neighbors] Versions to try for pinning '{sub_dep_name}': {versions_to_try_for_subdep[:3]}{'...' if len(versions_to_try_for_subdep)>3 else ''}")

                for v_str_pin in versions_to_try_for_subdep[:2]: # Try pinning to a couple of top suggested versions
                    pinned_spec = f"=={v_str_pin}"
                    pinned_req = Requirement(name=sub_dep_name, specifier=pinned_spec)
                    
                    new_requirements_set = frozenset(list(current_node.requirements) + [pinned_req])

                    action_desc = f"Pinned transitive {sub_dep_name} to '{pinned_spec}'"
                    # req_before is None as we are adding a new req, req_after is the new pinned_req
                    action_cost = self.get_cost_of_action(action_desc, None, pinned_req)
                    neighbors.append((new_requirements_set, action_desc, action_cost))
                    log_verbose(f"          [Neighbors] Generated (Pin Transitive): {action_desc}, cost={action_cost:.2f}")

        # Strategy 4: Remove a direct dependency (as a last resort)
        # Only remove dependencies that were part of the original set and are implicated
        original_direct_req_names = {r.name for r in original_direct_reqs}
        for pkg_name_to_remove in pkgs_to_target_for_modification_names:
            if pkg_name_to_remove not in original_direct_req_names:
                continue # Don't remove something that was pinned transitively earlier

            current_req_obj = current_reqs_map.get(pkg_name_to_remove)
            if not current_req_obj:
                continue # Should not happen

            log_verbose(f"      [Neighbors] Considering removing direct dependency '{pkg_name_to_remove}'")
            
            new_requirements_set = frozenset([r for r in current_node.requirements if r.name != pkg_name_to_remove])
            
            # Ensure we don't generate an empty set of requirements if we remove the last one
            if not new_requirements_set and len(current_node.requirements) == 1:
                log_verbose(f"        [Neighbors] Skipping removal of '{pkg_name_to_remove}' as it's the last requirement.")
                continue

            action_desc = f"Removed direct {pkg_name_to_remove}"
            # req_before is the removed one, req_after is None
            action_cost = self.get_cost_of_action(action_desc, current_req_obj, None)
            neighbors.append((new_requirements_set, action_desc, action_cost))
            log_verbose(f"          [Neighbors] Generated (Remove Direct): {action_desc}, cost={action_cost:.2f}")


        if not neighbors and conflict_info.is_conflict:
            log_verbose(f"    [Neighbors] WARNING: No neighbors generated for conflicting node with reqs: {self._reqs_to_str_summary(current_node.requirements)}")
        return neighbors

    def _reqs_to_str_summary(self, reqs: FrozenSet[Requirement], limit: int = 3) -> str:
        sorted_reqs = sorted(str(r) for r in reqs)
        if len(sorted_reqs) > limit:
            return ", ".join(sorted_reqs[:limit]) + f"... (+{len(sorted_reqs) - limit} more)"
        return ", ".join(sorted_reqs)
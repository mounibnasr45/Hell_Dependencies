# dependency_resolver_agent/tooling/pypi_service.py
from typing import List, Dict, Optional, Set as TypingSet

from dependency_resolver_agent.data_models.requirement import Requirement, Version, SpecifierSet, PACKAGING_AVAILABLE, InvalidVersion, InvalidSpecifier
from dependency_resolver_agent.utils.logger import log_verbose

# This would ideally come from config_manager or be more dynamic
SIMULATED_PYPI_VERSIONS: Dict[str, List[str]] = {
    "sphinx":     ["4.3.2", "5.0.0", "5.3.0", "6.0.0", "6.1.3", "6.2.1", "7.0.0", "7.1.0"],
    "docutils":   ["0.16", "0.17", "0.17.1", "0.18", "0.18.1", "0.19", "0.20", "0.20.1", "0.21.0"],
    "requests":   ["2.22.0", "2.25.1", "2.28.1", "2.29.0", "2.31.0", "2.32.0"],
    "urllib3":    ["1.25.11", "1.26.5", "1.26.15", "2.0.0", "2.0.7", "2.1.0", "2.2.0", "2.2.1"],
    "tensorflow": ["2.3.0", "2.5.0", "2.6.0", "2.8.0", "2.9.0", "2.10.0", "2.13.0", "2.15.0"],
    "numpy":      ["1.17.0", "1.18.5", "1.19.5", "1.20.3", "1.21.6", "1.22.0", "1.22.4", "1.23.5", "1.24.0", "1.24.4", "1.26.0", "1.26.3"],
    "flask":      ["1.1.0", "1.1.4", "2.0.0", "2.0.3", "2.1.0", "2.2.0", "2.3.0", "3.0.0"],
    "werkzeug":   ["0.16.0", "1.0.1", "2.0.0", "2.0.3", "2.1.0", "2.2.0", "2.3.0", "3.0.0"],
    "jinja2":     ["2.11.3", "3.0.0", "3.1.0", "3.1.2", "3.1.3"], # Often a conflict point with Flask
    "common-http-util": ["1.0", "1.4", "1.7", "2.0"], # Example package from prompt
    "anotherpackage": ["1.0.0", "1.1.0", "2.0.0"], # For testing pinning
    "subdep":         ["0.5.0", "0.6.0", "1.0.0", "1.0.1", "1.2.0"], # For testing pinning
}

class PyPIService:
    def __init__(self, simulated_versions: Optional[Dict[str, List[str]]] = None):
        self.versions_db = simulated_versions if simulated_versions is not None else SIMULATED_PYPI_VERSIONS

    def get_available_versions(self, package_name: str) -> List[str]:
        """Returns available versions, newest first, if packaging lib is available."""
        raw_versions = self.versions_db.get(package_name, [])
        if not raw_versions:
            return []
        if PACKAGING_AVAILABLE:
            try:
                return sorted(raw_versions, key=Version, reverse=True)
            except InvalidVersion: # Should not happen if SIMULATED_PYPI_VERSIONS is clean
                log_verbose(f"[PyPIService] Warning: Invalid version in DB for {package_name}")
                return sorted(raw_versions, reverse=True) # Fallback string sort
        return sorted(raw_versions, reverse=True)


    def get_versions_to_try(
        self,
        package_name: str,
        current_requirement: Optional[Requirement] = None,
        num_around=2,
        num_latest=3,
        num_within_spec=2,
        sub_dep_specifier_hint: Optional[str] = None # For pinning transitive
        ) -> List[str]:

        all_versions_str = self.get_available_versions(package_name) # Already sorted newest first
        if not all_versions_str: return []

        if not PACKAGING_AVAILABLE: # Simplified fallback
            return all_versions_str[:num_latest + num_around * 2]

        try:
            all_versions_obj = [Version(v) for v in all_versions_str] # Already sorted
        except InvalidVersion:
            log_verbose(f"Warning: Invalid version format for {package_name} during get_versions_to_try. Using unsorted subset.")
            return all_versions_str[:num_latest + num_around * 2]

        versions_to_try_set: TypingSet[Version] = set()

        # 0. If a sub_dep_specifier_hint is provided (for pinning transitive)
        hint_spec_set: Optional[SpecifierSet] = None
        if sub_dep_specifier_hint:
            try:
                hint_spec_set = SpecifierSet(sub_dep_specifier_hint)
                # Try to get versions satisfying this hint
                versions_satisfying_hint = sorted(
                    [v for v in all_versions_obj if v in hint_spec_set],
                    reverse=True
                )
                for i in range(min(len(versions_satisfying_hint), num_latest)): # take a few latest satisfying hint
                    versions_to_try_set.add(versions_satisfying_hint[i])
                # If no versions found satisfying hint, this path might not add any initially
            except InvalidSpecifier:
                log_verbose(f"[PyPIService] Invalid specifier hint '{sub_dep_specifier_hint}' for {package_name}")


        # 1. Add a few latest overall versions (especially if no hint or hint yielded few)
        for i in range(min(len(all_versions_obj), num_latest)):
            versions_to_try_set.add(all_versions_obj[i])

        current_version_obj: Optional[Version] = None
        current_specifier_set: Optional[SpecifierSet] = None

        if current_requirement and current_requirement.specifier:
            try:
                current_specifier_set = SpecifierSet(current_requirement.specifier)
                if current_requirement.is_exact():
                    exact_ver_str = current_requirement.get_exact_version_str()
                    if exact_ver_str:
                        current_version_obj = Version(exact_ver_str)
            except (InvalidSpecifier, InvalidVersion):
                pass

        # 2. If current requirement has a specifier, try versions within that specifier
        if current_specifier_set:
            versions_within_spec = sorted(
                [v for v in all_versions_obj if v in current_specifier_set],
                reverse=True
            )
            for i in range(min(len(versions_within_spec), num_within_spec)):
                versions_to_try_set.add(versions_within_spec[i])
            if versions_within_spec: # Also add the absolute latest that satisfies the spec
                 versions_to_try_set.add(versions_within_spec[0])


        # 3. If current version is known (exact), try versions around it
        if current_version_obj:
            try:
                # Find index of current_version_obj in all_versions_obj (which is sorted newest to oldest)
                current_idx = -1
                for idx, v_obj in enumerate(all_versions_obj):
                    if v_obj == current_version_obj:
                        current_idx = idx
                        break
                
                if current_idx != -1:
                    # Older versions (index increases)
                    for i in range(1, num_around + 1):
                        if current_idx + i < len(all_versions_obj):
                            versions_to_try_set.add(all_versions_obj[current_idx + i])
                    # Newer versions (index decreases)
                    for i in range(1, num_around + 1):
                        if current_idx - i >= 0:
                            versions_to_try_set.add(all_versions_obj[current_idx - i])
            except ValueError:
                pass # current_version_obj not in all_versions_obj

        # Convert to string and sort newest first
        return sorted([str(v) for v in versions_to_try_set], key=Version, reverse=True)
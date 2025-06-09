# dependency_resolver_agent/tooling/regex_conflict_parser.py
import re
from typing import Set, Optional, Tuple, FrozenSet

from dependency_resolver_agent.data_models.requirement import Requirement
from dependency_resolver_agent.data_models.conflict_info import ConflictInfo

class RegexConflictParser:
    def parse(self, stdout: str, stderr: str, direct_requirements: FrozenSet[Requirement]) -> ConflictInfo:
        full_output = f"STDOUT:\n{stdout}\nSTDERR:\n{stderr}"
        involved_direct_names = set()
        sub_dep_culprit: Optional[Tuple[str, str]] = None
        
        direct_req_name_map = {r.name.lower(): r.name for r in direct_requirements}

        # Look for direct dependencies mentioned in error context
        # This needs to be fairly general.
        # Common patterns:
        # - "package_a depends on sub_package_x" (where package_a is direct)
        # - Lines starting with "  direct_package_name ..." in resolution lists
        # - "Cannot install direct_package_name"
        for req_name_orig_case in direct_req_name_map.values():
            # Regex to find the package name, possibly followed by specifiers or version numbers
            # This tries to capture mentions of the direct package in various contexts
            # Adjusted to be less strict about "==" immediately following
            pattern = r"(\b" + re.escape(req_name_orig_case) + r"\b)" + \
                      r"(\s*(?:[<>=!~]=?|is)\s*[\w.,*+-]+(?:,\s*[<>=!~]=?\s*[\w.,*+-]+)*)?" # Optional specifier/version part
            if re.search(pattern, full_output, re.IGNORECASE):
                involved_direct_names.add(req_name_orig_case)

        # Attempt to find "The conflict is caused by:" block
        # Example:
        # ERROR: Cannot install -r requirements.in (line 3) and requests==2.29.0 because these package versions have conflicting dependencies.
        # The conflict is caused by:
        #     requests 2.29.0 depends on urllib3<2.0 and >=1.25.0
        #     root depends on urllib3==2.0.0
        #
        # To fix this you could try to:
        # 1. loosen the range of package versions you've specified
        # 2. remove package versions to allow pip attempt to solve the dependency conflict
        conflict_block_match = re.search(
            r"The conflict is caused by:(.*?)(?:\n\nTo fix this|Because no versions of|(?:\n\s*pip freeze output:)|(?:\n\s*ERROR:)|(?:\n\s*During handling of the above exception)|\Z)",
            full_output, re.DOTALL | re.IGNORECASE
        )
        if conflict_block_match:
            conflict_text = conflict_block_match.group(1).strip()
            # Find lines like: "    package_a x.y.z depends on conflictingpackage==A"
            # Or "    conflictingpackage A is required by package_b x.y.z"
            dep_lines_depends_on = re.findall(
                r"^\s*([\w.-]+)\s+(?:[\w.?*-]+|\(any\))\s+depends on\s+([\w.-]+)\s*([<>=!~]=?[\w.,*+-]+(?:,\s*[<>=!~]=?[\w.,*+-]+)*)?",
                conflict_text, re.MULTILINE | re.IGNORECASE
            )
            dep_lines_required_by = re.findall(
                r"^\s*([\w.-]+)\s+([<>=!~]=?[\w.,*+-]+(?:,\s*[<>=!~]=?[\w.,*+-]+)*)?\s+is required by\s+([\w.-]+)",
                conflict_text, re.MULTILINE | re.IGNORECASE
            )

            potential_culprits_specs: dict[str, Set[str]] = {} # {sub_dep_name: {spec1, spec2}}

            for dependant, dep_name, dep_spec in dep_lines_depends_on:
                dep_spec_cleaned = (dep_spec or "").strip()
                # Only consider it a sub-dependency if the 'dependant' is not one of our direct_requirements
                # OR if the 'dep_name' itself is not a direct requirement (it's the one being depended upon)
                if dep_name.lower() not in direct_req_name_map:
                    potential_culprits_specs.setdefault(dep_name, set()).add(dep_spec_cleaned)
                # Also, if a direct dependency depends on something that *becomes* a conflict point
                elif dep_name.lower() in direct_req_name_map and dependant.lower() not in direct_req_name_map : # e.g. transitive depends on a direct
                     potential_culprits_specs.setdefault(dep_name, set()).add(dep_spec_cleaned)


            for dep_name, dep_spec, _requirer in dep_lines_required_by:
                dep_spec_cleaned = (dep_spec or "").strip()
                if dep_name.lower() not in direct_req_name_map:
                    potential_culprits_specs.setdefault(dep_name, set()).add(dep_spec_cleaned)

            for culprit_name, specs_set in potential_culprits_specs.items():
                # A good candidate for sub_dependency_culprit is a non-direct package
                # that has multiple *different* specifiers mentioned for it, or at least one specific one.
                # Filter out empty strings from specs_set if they occurred
                valid_specs = {s for s in specs_set if s}
                if len(valid_specs) > 0 : #  len(valid_specs) > 1 or (len(valid_specs) == 1 and next(iter(valid_specs))):
                    # Join multiple specifiers with "; "
                    sub_dep_culprit = (culprit_name, "; ".join(sorted(list(valid_specs))))
                    # If this sub_dep_culprit is mentioned, try to add the direct_reqs that caused it
                    # This is harder without full dependency graph parsing.
                    # For now, if sub_dep_culprit, assume all direct reqs are involved.
                    if not involved_direct_names : # If we haven't found any yet
                        involved_direct_names.update(direct_req_name_map.values())
                    break # Take the first one

        # Fallback: if parsing failed to identify specifics but it's a clear resolution error
        if not involved_direct_names and ("ResolutionImpossible" in full_output or "Could not find a version that satisfies the requirement" in full_output):
            involved_direct_names = set(direct_req_name_map.values()) # Blame all direct ones

        return ConflictInfo(
            is_conflict=True, # This parser is only called on conflict
            error_message=full_output,
            involved_direct_packages=involved_direct_names,
            sub_dependency_culprit=sub_dep_culprit
        )
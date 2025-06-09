# dependency_resolver_agent/agent_core/orchestrator.py
import heapq
import re
from typing import List, Tuple, Dict, Optional, FrozenSet, Set

from dependency_resolver_agent.data_models.requirement import Requirement
from dependency_resolver_agent.data_models.conflict_info import ConflictInfo
from dependency_resolver_agent.agent_core.state_manager import AStarNode, reconstruct_path
from dependency_resolver_agent.agent_core.action_generator import ActionGenerator
from dependency_resolver_agent.agent_core.heuristic_calculator import HeuristicCalculator
from dependency_resolver_agent.tooling.pip_compiler_service import PipCompilerService
from dependency_resolver_agent.tooling.regex_conflict_parser import RegexConflictParser
from dependency_resolver_agent.llm_services.conflict_parser_llm import LLMConflictParser # Now for real
from dependency_resolver_agent.utils.logger import log_verbose
from dependency_resolver_agent.utils import cache_manager
from dependency_resolver_agent.utils import config_manager as config


class Orchestrator:
    def __init__(self,
                 action_generator: ActionGenerator,
                 heuristic_calc: HeuristicCalculator,
                 pip_compiler: PipCompilerService,
                 regex_conflict_parser: RegexConflictParser, # Fallback
                 llm_conflict_parser: Optional[LLMConflictParser] = None # Primary if USE_LLM_PARSER
                 ):
        self.action_generator = action_generator
        self.heuristic_calc = heuristic_calc
        self.pip_compiler = pip_compiler
        self.regex_conflict_parser = regex_conflict_parser
        self.llm_conflict_parser = llm_conflict_parser

        if config.USE_LLM_PARSER and self.llm_conflict_parser is None:
            log_verbose("[Orchestrator] Warning: USE_LLM_PARSER is True, but no LLMConflictParser provided. LLM parsing will not be used.")
        elif config.USE_LLM_PARSER and self.llm_conflict_parser and self.llm_conflict_parser.llm is None:
            log_verbose("[Orchestrator] Warning: LLMConflictParser provided, but its LLM is not initialized (e.g. API key issue). LLM parsing may fallback.")


    def _parse_initial_requirements(self, content: str) -> FrozenSet[Requirement]:
        # ... (same as before, no changes needed here)
        parsed: Set[Requirement] = set()
        for line_num, line in enumerate(content.strip().split('\n'), 1):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            match = re.match(r"^\s*([a-zA-Z0-9_.-]+)\s*((?:[<>=!~]=?|[<>=!~])\s*[\w.,*+-]+(?:\s*,\s*[<>=!~]=?\s*[\w.,*+-]+)*)?\s*(?:#.*)?$", line)
            if match:
                name = match.group(1).strip()
                spec = (match.group(2) or "").strip()
                try:
                    parsed.add(Requirement(name=name, specifier=spec))
                except ValueError as ve:
                    log_verbose(f"Warning: Skipping malformed initial requirement on line {line_num} ('{line}'): {ve}")
            elif line:
                log_verbose(f"Warning: Skipping malformed initial requirement line {line_num}: '{line}' (no regex match).")
        return frozenset(parsed)

    def _get_conflict_info_for_node(self, requirements_set: FrozenSet[Requirement], direct_reqs_for_parser: FrozenSet[Requirement]) -> ConflictInfo:
        cached_eval = cache_manager.get_cached_full_eval(requirements_set)
        if cached_eval:
            _success, _stdout, _stderr, conflict_info_obj = cached_eval
            log_verbose(f"  [Orchestrator Cache] Full eval hit for: {self._reqs_to_str_summary(requirements_set)}")
            return conflict_info_obj

        success, stdout_str, stderr_str = self.pip_compiler.run_compile(requirements_set)
        full_pip_output = f"STDOUT:\n{stdout_str}\nSTDERR:\n{stderr_str}" # For regex parser if LLM fails

        conflict_info_obj: Optional[ConflictInfo] = None

        if success:
            conflict_info_obj = ConflictInfo(is_conflict=False, error_message=stdout_str)
        else:
            parsed_with_llm = False
            if config.USE_LLM_PARSER and self.llm_conflict_parser and self.llm_conflict_parser.llm:
                log_verbose("  [Orchestrator] Attempting conflict parsing with LLM...")
                try:
                    conflict_info_obj = self.llm_conflict_parser.parse(stdout_str, stderr_str, direct_reqs_for_parser)
                    if conflict_info_obj:
                        log_verbose("  [Orchestrator] LLM parsing successful.")
                        parsed_with_llm = True
                    else:
                        log_verbose("  [Orchestrator] LLM parsing returned None, falling back to regex.")
                except Exception as e_llm: # Catch any exception from LLM parsing attempt
                    log_verbose(f"  [Orchestrator] Exception during LLM parsing: {e_llm}. Falling back to regex.")
            
            if not parsed_with_llm: # Fallback to regex if LLM not used, not available, or failed
                log_verbose("  [Orchestrator] Using regex conflict parser.")
                conflict_info_obj = self.regex_conflict_parser.parse(stdout_str, stderr_str, direct_reqs_for_parser)
                # Regex parser always sets is_conflict=True if called, ensure error message is set
                if conflict_info_obj and not conflict_info_obj.error_message:
                     conflict_info_obj.error_message = full_pip_output


        if conflict_info_obj is None: # Should not happen if regex parser is a true fallback
            log_verbose("  [Orchestrator] CRITICAL: No conflict info could be generated. Defaulting to generic conflict.")
            conflict_info_obj = ConflictInfo(
                is_conflict=not success, # Base on pip-compile success
                error_message=full_pip_output,
                involved_direct_packages={r.name for r in direct_reqs_for_parser} if not success else set(),
                sub_dependency_culprit=None
            )
        
        cache_manager.store_cached_full_eval(requirements_set, (success, stdout_str, stderr_str, conflict_info_obj))
        # Also update the simpler cache for direct ConflictInfo lookup if needed elsewhere
        cache_manager.store_pip_compile_result(requirements_set, conflict_info_obj)
        return conflict_info_obj


    def solve(self, initial_requirements_str: str, max_iterations: int = config.MAX_ASTAR_ITERATIONS) -> \
            Optional[Tuple[FrozenSet[Requirement], List[Tuple[str, FrozenSet[Requirement]]]]]:
        # ... (Initialization of start_node, open_set_pq, processed_node_g_scores is THE SAME)
        # ... (Main A* loop structure is THE SAME)
        # The only change is how _get_conflict_info_for_node is called and its internal logic.
        # All other parts of the solve method remain identical to the previous version.

        log_verbose("Parsing initial requirements...")
        original_direct_reqs = self._parse_initial_requirements(initial_requirements_str)
        if not original_direct_reqs:
            print("ERROR: No valid requirements parsed from initial input.")
            return None
        log_verbose(f"Initial direct requirements: {self._reqs_to_str_summary(original_direct_reqs)}")

        log_verbose("Performing initial evaluation for start_node...")
        initial_conflict_info = self._get_conflict_info_for_node(original_direct_reqs, original_direct_reqs)
        initial_h_score = self.heuristic_calc.calculate_h_score(original_direct_reqs, initial_conflict_info, original_direct_reqs)

        start_node = AStarNode(
            requirements=original_direct_reqs,
            g_score=0.0,
            h_score=initial_h_score
        )

        open_set_pq: List[AStarNode] = [start_node]
        processed_node_g_scores: Dict[FrozenSet[Requirement], float] = {}

        print(f"Starting A* search. Max iterations: {max_iterations}. Python: {self.pip_compiler.python_executable}")
        log_verbose(f"Initial node: f={start_node.f_score:.2f} (g=0, h={initial_h_score:.2f}), reqs: {self._reqs_to_str_summary(start_node.requirements)}")
        if initial_conflict_info.is_conflict:
            log_verbose(f"  Initial conflict involves: {initial_conflict_info.involved_direct_packages or 'unknown'}")
            if initial_conflict_info.sub_dependency_culprit:
                log_verbose(f"  Sub-dependency hint: {initial_conflict_info.sub_dependency_culprit}")

        iteration_count = 0
        while open_set_pq and iteration_count < max_iterations:
            iteration_count += 1
            current_node = heapq.heappop(open_set_pq)

            log_verbose(f"\n--- Iteration {iteration_count}/{max_iterations} ---")
            log_verbose(f"  Expanding node: f={current_node.f_score:.2f} (g={current_node.g_score:.2f}, h={current_node.h_score:.2f})")
            log_verbose(f"  Action to this node: '{current_node.last_action}'")
            log_verbose(f"  Node reqs: {self._reqs_to_str_summary(current_node.requirements)}")

            if current_node.requirements in processed_node_g_scores and \
               current_node.g_score >= processed_node_g_scores[current_node.requirements]:
                log_verbose("  (Skipping: already processed this state via an equal or better path)")
                continue
            processed_node_g_scores[current_node.requirements] = current_node.g_score

            current_node_conflict_info = self._get_conflict_info_for_node(current_node.requirements, original_direct_reqs)

            if not current_node_conflict_info.is_conflict:
                print(f"\n>>> SUCCESS: Solution Found after {iteration_count} iterations! <<<")
                solution_path = reconstruct_path(current_node)
                return current_node.requirements, solution_path

            log_verbose(f"  Conflict persists. Involved: {current_node_conflict_info.involved_direct_packages or 'unknown'}. Sub-dep: {current_node_conflict_info.sub_dependency_culprit}")
            # Limit error message display length
            error_msg_sample = current_node_conflict_info.error_message.replace('\n', ' ').replace('\r', '')
            log_verbose(f"  Error sample: {error_msg_sample[:300]}...")


            for neighbor_reqs_set, action_desc, action_cost in self.action_generator.get_neighbors(
                                                                    current_node,
                                                                    original_direct_reqs,
                                                                    current_node_conflict_info):
                tentative_g_score = current_node.g_score + action_cost

                if neighbor_reqs_set in processed_node_g_scores and \
                   tentative_g_score >= processed_node_g_scores[neighbor_reqs_set]:
                    # log_verbose(f"    Skipping neighbor (already processed better): {self._reqs_to_str_summary(neighbor_reqs_set)}")
                    continue
                
                neighbor_h_score = self.heuristic_calc.calculate_h_score(neighbor_reqs_set, current_node_conflict_info, original_direct_reqs)
                
                neighbor_node = AStarNode(
                    requirements=neighbor_reqs_set,
                    g_score=tentative_g_score,
                    h_score=neighbor_h_score,
                    parent=current_node,
                    last_action=action_desc
                )
                heapq.heappush(open_set_pq, neighbor_node)
                log_verbose(f"    Added neighbor to OPEN: f={neighbor_node.f_score:.2f}, g={neighbor_node.g_score:.2f}, h={neighbor_node.h_score:.2f} | Action: '{action_desc}' | Reqs: {self._reqs_to_str_summary(neighbor_node.requirements)}")

        print(f"\n>>> FAILURE: No solution found after {iteration_count} iterations (max: {max_iterations}). <<<")
        if open_set_pq:
            log_verbose(f"  Open set still has {len(open_set_pq)} nodes. Lowest f_score: {open_set_pq[0].f_score:.2f}")
        else:
            log_verbose("  Open set is empty.")
        return None

    def _reqs_to_str_summary(self, reqs: FrozenSet[Requirement], limit: int = 5) -> str:
        sorted_reqs = sorted(str(r) for r in reqs)
        if len(sorted_reqs) > limit:
            return ", ".join(sorted_reqs[:limit]) + f"... (+{len(sorted_reqs) - limit} more)"
        return ", ".join(sorted_reqs)
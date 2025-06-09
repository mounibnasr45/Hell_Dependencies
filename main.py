# dependency_resolver_agent/main.py
import time
import shutil
import subprocess
import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from dependency_resolver_agent.utils import logger, cache_manager, config_manager
from dependency_resolver_agent.tooling.pypi_service import PyPIService
from dependency_resolver_agent.tooling.pip_compiler_service import PipCompilerService
from dependency_resolver_agent.tooling.regex_conflict_parser import RegexConflictParser
from dependency_resolver_agent.llm_services.conflict_parser_llm import LLMConflictParser # Import LLM parser
from dependency_resolver_agent.agent_core.action_generator import ActionGenerator
from dependency_resolver_agent.agent_core.heuristic_calculator import HeuristicCalculator
from dependency_resolver_agent.agent_core.orchestrator import Orchestrator
from dependency_resolver_agent.data_models.requirement import PACKAGING_AVAILABLE


def run_tests():
    current_python_interpreter = config_manager.DEFAULT_PYTHON_EXECUTABLE
    print(f"Script is running under Python interpreter: {current_python_interpreter}")
    # ... (pip-compile check remains the same) ...
    pip_compile_exe_path_check = shutil.which("pip-compile")
    if not pip_compile_exe_path_check:
        print("CRITICAL ERROR: 'pip-compile' command not found in PATH.")
        # ... (rest of the check)
        sys.exit(1) # Simplified exit for brevity
    else:
        try:
            # ... (version check)
            pass
        except:
            pass # Simplified for brevity


    if not PACKAGING_AVAILABLE:
        print("Reminder: 'packaging' library not found. Functionality will be limited.")

    print(f"LLM Parser Usage Enabled: {config_manager.USE_LLM_PARSER}")
    if config_manager.USE_LLM_PARSER:
        if not config_manager.OPENROUTER_API_KEY or config_manager.OPENROUTER_API_KEY == "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":
            print("WARNING: USE_LLM_PARSER is True, but OPENROUTER_API_KEY is not set or is the default example. LLM will likely fail.")
        print(f"LLM Model for Parsing: {config_manager.LLM_MODEL_FOR_CONFLICT_PARSING}")


    # Initialize services
    pypi_svc = PyPIService()
    pip_compiler_svc = PipCompilerService(python_executable=current_python_interpreter)
    regex_parser = RegexConflictParser()
    
    llm_parser_instance = None
    if config_manager.USE_LLM_PARSER:
        llm_parser_instance = LLMConflictParser() # Instantiated here

    action_gen = ActionGenerator(pypi_service=pypi_svc)
    heuristic_calc = HeuristicCalculator()

    orchestrator = Orchestrator(
        action_generator=action_gen,
        heuristic_calc=heuristic_calc,
        pip_compiler=pip_compiler_svc,
        regex_conflict_parser=regex_parser, # Always provide regex as fallback
        llm_conflict_parser=llm_parser_instance if config_manager.USE_LLM_PARSER else None
    )

    # ... (Test cases remain the same as the previous full build)
    test_cases = {
        "Sphinx 5.0 & Docutils 0.17 (Conflict)": """
sphinx==5.0.0
docutils==0.17.0
""",
        "Requests 2.29.0 & Urllib3 2.0.0 (Conflict)": """
requests==2.29.0
urllib3==2.0.0
""",
        "Flask 1.1.0 & Werkzeug 3.0.0 (Major Conflict)": """
flask==1.1.0
werkzeug==3.0.0
""",
        "No Conflict (Already Solvable)": """
requests==2.31.0
urllib3==2.0.7
""",
        "Complex Case (Flask 2.0, Jinja2 3.1 - Needs Jinja2 Downgrade)": """
flask==2.0.0
jinja2==3.1.0
""", # Flask 2.0.0 requires jinja2<3.1,>=2.10.1. Jinja2==3.1.0 is incompatible.
    }
    pypi_svc.versions_db.setdefault("jinja2", ["2.11.3", "3.0.0", "3.0.3", "3.1.0", "3.1.2", "3.1.3"])


    for test_name, initial_reqs_content in test_cases.items():
        print(f"\n\n===== Running Test Case: {test_name} =====")
        print(f"Initial requirements:\n{initial_reqs_content.strip()}\n")

        # Enable verbose for harder cases or if LLM is used
        if config_manager.USE_LLM_PARSER or "Complex" in test_name or "Requests 2.29" in test_name or "Flask 1.1" in test_name:
             logger.set_verbose_logging(True)
        else:
             logger.set_verbose_logging(False)

        cache_manager.clear_pip_compile_cache()
        start_time = time.time()

        result_tuple = orchestrator.solve(
            initial_reqs_content,
            max_iterations=config_manager.MAX_ASTAR_ITERATIONS
        )
        end_time = time.time()
        # logger.set_verbose_logging(False) # Keep it on if it was for LLM

        if result_tuple:
            final_requirements, path = result_tuple
            print("\n--- Final Solution Found ---")
            print("Solved Requirements (sorted):")
            for req_obj in sorted(list(final_requirements), key=lambda r: r.name):
                print(f"  {req_obj}")
            print("\nPath to solution (Actions taken):")
            for i, (action, req_set_in_path) in enumerate(path):
                req_summary = ", ".join(sorted(str(r) for r in req_set_in_path)[:5])
                if len(req_set_in_path) > 5: req_summary += "..."
                print(f"  Step {i}: {action} -> Reqs: {req_summary}")
        else:
            print("\n--- No Solution Found for this test case ---")

        print(f"\nTotal time for {test_name}: {end_time - start_time:.3f} seconds")
        print(f"Cache size for {test_name}: {len(cache_manager.PIP_COMPILE_CACHE) + len(cache_manager.FULL_EVAL_CACHE)} entries.")
        print("=========================================")

if __name__ == "__main__":
    run_tests()
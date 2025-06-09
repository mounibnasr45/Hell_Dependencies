# dependency_resolver_agent/tooling/pip_compiler_service.py
import subprocess
import tempfile
import os
import shutil
from typing import FrozenSet, Tuple

from dependency_resolver_agent.data_models.requirement import Requirement
from dependency_resolver_agent.utils.logger import log_verbose
from dependency_resolver_agent.utils import config_manager as config

class PipCompilerService:
    def __init__(self, python_executable: str = config.DEFAULT_PYTHON_EXECUTABLE):
        self.python_executable = python_executable
        self.pip_compile_exe = shutil.which("pip-compile") or "pip-compile"
        if not shutil.which(self.pip_compile_exe):
            msg = f"CRITICAL: pip-compile command '{self.pip_compile_exe}' not found."
            print(msg)
            # In a real app, you might raise a specific setup error
            # For now, we let it fail later if called.

    def run_compile(self, requirements_set: FrozenSet[Requirement]) -> Tuple[bool, str, str]:
        """
        Runs pip-compile.
        Returns: (success_status: bool, stdout: str, stderr: str)
        """
        log_verbose(f"  [PipCompilerService] Compiling: {self._reqs_to_str_summary(requirements_set)}")
        temp_dir = ""
        try:
            temp_dir = tempfile.mkdtemp(prefix="pip_resolve_")
            requirements_in_content = "\n".join(sorted(str(r) for r in requirements_set))
            in_file_path = os.path.join(temp_dir, "requirements.in")
            out_file_path = os.path.join(temp_dir, "requirements.txt")

            with open(in_file_path, "w") as f: f.write(requirements_in_content)

            cmd = [
                self.pip_compile_exe,
                "--resolver=backtracking", # pip-tools default, but explicit
                "--verbose",               # For better error messages
                "--output-file", out_file_path,
                # "--allow-unsafe", # Consider if needed; can mask real issues
                in_file_path
            ]
            log_verbose(f"    Executing: {' '.join(cmd)}")
            process = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                shell=False, # Important for security and correctness
                check=False, # We handle return code manually
                timeout=config.PIP_COMPILE_TIMEOUT_SECONDS
            )

            success = process.returncode == 0
            # Even on success, pip-compile might print concerning things to stderr (e.g. deprecation warnings)
            # But for conflict resolution, RC is the primary indicator.
            # Some "INFO" level things from pip-tools go to stderr.
            if success and ("ERROR:" in process.stderr or "ResolutionImpossible" in process.stderr):
                log_verbose(f"    pip-compile RC=0 but error pattern found in stderr. Considering it a failure.")
                success = False # Treat as failure for our purposes

            log_verbose(f"    pip-compile {'SUCCESS' if success else 'FAILED'} (RC={process.returncode})")
            return success, process.stdout, process.stderr

        except subprocess.TimeoutExpired:
            log_verbose(f"    pip-compile timed out after {config.PIP_COMPILE_TIMEOUT_SECONDS}s")
            return False, "", "Error: pip-compile timed out."
        except FileNotFoundError: # Should be caught by __init__ but as a safeguard
            msg = f"CRITICAL: pip-compile command '{self.pip_compile_exe}' not found during execution."
            print(msg) # Should not happen if __init__ check passes
            return False, "", msg # Or raise
        except Exception as e:
            err_msg = f"Unexpected pip-compile error: {type(e).__name__}: {e}"
            log_verbose(f"    {err_msg}")
            return False, "", err_msg
        finally:
            if temp_dir and os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)

    def _reqs_to_str_summary(self, reqs: FrozenSet[Requirement], limit: int = 3) -> str:
        sorted_reqs = sorted(str(r) for r in reqs)
        if len(sorted_reqs) > limit:
            return ", ".join(sorted_reqs[:limit]) + f"... (+{len(sorted_reqs) - limit} more)"
        return ", ".join(sorted_reqs)
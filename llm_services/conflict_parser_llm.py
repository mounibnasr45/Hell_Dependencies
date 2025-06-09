# dependency_resolver_agent/llm_services/conflict_parser_llm.py
import json
from typing import FrozenSet, Optional, List
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.output_parsers import PydanticOutputParser # For structured output # <- CORRECT
from pydantic import BaseModel, Field

from dependency_resolver_agent.data_models.requirement import Requirement
from dependency_resolver_agent.data_models.conflict_info import ConflictInfo
from dependency_resolver_agent.llm_services.client import get_llm_for_conflict_parsing
from dependency_resolver_agent.utils.logger import log_verbose
from dependency_resolver_agent.utils import config_manager as config


# Define Pydantic model for structured LLM output
class LLMConflictAnalysis(BaseModel):
    involved_direct_packages: List[str] = Field(description="List of direct package names (from user's original list) involved in the conflict.")
    sub_dependency_culprit_name: Optional[str] = Field(None, description="Name of the primary transitive sub-dependency causing the conflict, if one is clearly identifiable.")
    sub_dependency_culprit_specs: Optional[str] = Field(None, description="Conflicting version specifiers for the sub-dependency culprit (e.g., '<1.0; >=1.5').")


PROMPT_TEMPLATE = """
You are an expert Python dependency analysis tool. Your task is to analyze the provided pip-compile error output and identify the root causes of any dependency conflicts.

The user's original direct dependencies were:
{direct_dependencies_list_str}

Pip-compile output:
---STDOUT---
{stdout}
---END STDOUT---

---STDERR---
{stderr}
---END STDERR---

Carefully review the stdout and stderr from pip-compile.
Based *only* on the information in the pip-compile output and the list of original direct dependencies:

1.  Identify which of the *original direct dependencies* (from the list: {direct_dependencies_list_str}) are involved in or are causing the conflict.
2.  If a specific *transitive sub-dependency* (a package not in the original direct list) is clearly the main point of contention because different packages require incompatible versions of it, please identify:
    a.  The name of this transitive sub-dependency.
    b.  A string summarizing the conflicting version specifiers mentioned for it in the error output (e.g., "requires <2.0; another requires >=2.1.0").

If the pip-compile output indicates success (no conflict), all fields in your response related to conflicts should be empty or null.
If there's a conflict but no specific transitive sub-dependency is clearly the sole culprit, leave those fields (sub_dependency_culprit_name, sub_dependency_culprit_specs) null.

{format_instructions}
"""

class LLMConflictParser:
    def __init__(self):
        self.llm = None
        if config.OPENROUTER_API_KEY and config.OPENROUTER_API_KEY != "YOUR_OPENROUTER_API_KEY_HERE" and config.OPENROUTER_API_KEY != "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": # Check if a real key is likely set
            try:
                self.llm = get_llm_for_conflict_parsing()
                log_verbose("[LLMConflictParser] LLM initialized successfully.")
            except Exception as e:
                log_verbose(f"[LLMConflictParser] CRITICAL: Failed to initialize LLM: {e}. Will fallback to regex.")
                self.llm = None
        else:
            log_verbose("[LLMConflictParser] LLM not initialized due to missing or default API key.")

        self.pydantic_parser = PydanticOutputParser(pydantic_object=LLMConflictAnalysis)


    def parse(self, stdout: str, stderr: str, direct_requirements: FrozenSet[Requirement]) -> Optional[ConflictInfo]:
        if not self.llm:
            log_verbose("[LLMConflictParser] LLM not available, parse() returning None.")
            return None # Fallback will be handled by orchestrator

        direct_deps_str_list = sorted([req.name for req in direct_requirements])
        direct_deps_display_str = ", ".join(direct_deps_str_list)

        prompt = ChatPromptTemplate.from_template(
            template=PROMPT_TEMPLATE,
            partial_variables={"format_instructions": self.pydantic_parser.get_format_instructions()}
        )
        
        chain = prompt | self.llm | self.pydantic_parser

        full_pip_output_for_llm = f"STDOUT:\n{stdout}\nSTDERR:\n{stderr}"
        log_verbose(f"[LLMConflictParser] Querying LLM for conflict analysis. Direct deps: {direct_deps_display_str}")
        # log_verbose(f"[LLMConflictParser] Full pip output for LLM:\n{full_pip_output_for_llm[:1000]}...") # Log sample of input to LLM

        try:
            llm_response_structured: LLMConflictAnalysis = chain.invoke({
                "direct_dependencies_list_str": direct_deps_display_str,
                "stdout": stdout,
                "stderr": stderr
            })
            log_verbose(f"[LLMConflictParser] LLM Raw Response (structured): {llm_response_structured}")

            # Ensure involved_direct_packages only contains names from the original list
            valid_involved_direct = {
                pkg_name for pkg_name in llm_response_structured.involved_direct_packages
                if pkg_name in direct_deps_str_list
            }
            if len(valid_involved_direct) != len(llm_response_structured.involved_direct_packages):
                log_verbose(f"[LLMConflictParser] Warning: LLM returned direct packages not in original list. Filtered.")


            sub_dep_culprit = None
            if llm_response_structured.sub_dependency_culprit_name and ll_m_response_structured.sub_dependency_culprit_specs:
                sub_dep_culprit = (
                    llm_response_structured.sub_dependency_culprit_name,
                    llm_response_structured.sub_dependency_culprit_specs
                )
            elif llm_response_structured.sub_dependency_culprit_name: # Name but no specs
                 sub_dep_culprit = (llm_response_structured.sub_dependency_culprit_name, "")


            # If LLM says no direct packages involved but there was an error, it might be a parsing failure or a non-dependency error
            is_conflict_according_to_llm = bool(valid_involved_direct) or bool(sub_dep_culprit)
            
            # The 'is_conflict' field of ConflictInfo should be based on pip-compile's exit code primarily.
            # The LLM's job is to detail the conflict IF one exists.
            # So, this method is called when a conflict IS known.
            return ConflictInfo(
                is_conflict=True, # Assume conflict as this parser is called on failure
                error_message=full_pip_output_for_llm, # Store the full input given to LLM
                involved_direct_packages=valid_involved_direct,
                sub_dependency_culprit=sub_dep_culprit
            )

        except Exception as e:
            log_verbose(f"[LLMConflictParser] Error during LLM invocation or parsing: {type(e).__name__} - {e}")
            # Optionally, could try a simpler StrOutputParser if Pydantic fails, then regex the string.
            # For now, signal failure by returning None.
            return None
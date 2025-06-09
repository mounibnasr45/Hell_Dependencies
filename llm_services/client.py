# dependency_resolver_agent/llm_services/client.py
from langchain_openai import ChatOpenAI
from dependency_resolver_agent.utils import config_manager as config
from dependency_resolver_agent.utils.logger import log_verbose

def get_openaicompatible_llm(
    model_name: str,
    api_key: str,
    base_url: str,
    temperature: float = 0.1,
    max_tokens: int = 1024,
    request_timeout: int = 60
):
    """
    Returns a LangChain ChatOpenAI LLM instance configured for an OpenAI-compatible API.
    """
    log_verbose(f"[LLM Client] Initializing LLM: Model={model_name}, BaseURL={base_url}, Temp={temperature}, MaxTokens={max_tokens}")
    return ChatOpenAI(
        model=model_name,
        openai_api_key=api_key,
        openai_api_base=base_url,
        temperature=temperature,
        max_tokens=max_tokens,
        request_timeout=request_timeout,
        default_headers={
            "HTTP-Referer": "http://localhost:8000/dep-resolver", # Example, adapt if deployed
            "X-Title": "Python Dependency Resolver Agent"
        }
    )

def get_llm_for_conflict_parsing(
    model_name: str = None,
    temperature: float = None,
    max_tokens: int = None,
    request_timeout: int = None
):
    """
    Factory function to get an LLM instance specifically for conflict parsing, using OpenRouter.
    """
    model_to_use = model_name or config.LLM_MODEL_FOR_CONFLICT_PARSING
    temp_to_use = temperature if temperature is not None else config.LLM_TEMPERATURE
    tokens_to_use = max_tokens if max_tokens is not None else config.LLM_MAX_TOKENS
    timeout_to_use = request_timeout if request_timeout is not None else config.LLM_REQUEST_TIMEOUT

    if not config.OPENROUTER_API_KEY or config.OPENROUTER_API_KEY == "YOUR_OPENROUTER_API_KEY_HERE":
        log_verbose("[LLM Client] CRITICAL: OpenRouter API Key not configured. LLM will not function.")
        # raise ValueError("OpenRouter API Key not configured.") # Or handle more gracefully

    return get_openaicompatible_llm(
        model_name=model_to_use,
        api_key=config.OPENROUTER_API_KEY,
        base_url="https://openrouter.ai/api/v1",
        temperature=temp_to_use,
        max_tokens=tokens_to_use,
        request_timeout=timeout_to_use
    )

# Note: The direct_query_openrouter_llm function is not directly used by the
# ConflictParserLLM as we prefer LangChain's interface, but it's good for reference.
# If needed, it could be adapted and placed here or in a separate utility.
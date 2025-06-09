# dependency_resolver_agent/utils/config_manager.py
import sys
import os # For environment variables

# Basic configuration, can be expanded (e.g., load from .env using python-dotenv)
DEFAULT_PYTHON_EXECUTABLE = sys.executable
PIP_COMPILE_TIMEOUT_SECONDS = 120
MAX_ASTAR_ITERATIONS = 50

# PyPI service
SIMULATED_PYPI_VERSIONS_CONFIG_KEY = "SIMULATED_PYPI_VERSIONS"

# --- LLM Configuration ---
# Replace with your actual OpenRouter API Key or set as environment variable
# IMPORTANT: DO NOT COMMIT YOUR API KEY DIRECTLY INTO CODE FOR PUBLIC REPOSITORIES
# Use environment variables or a .env file with python-dotenv in real projects.
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "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") # Default for testing
# Recommended model for parsing, good at instruction following and JSON output
LLM_MODEL_FOR_CONFLICT_PARSING = os.getenv("LLM_MODEL_FOR_CONFLICT_PARSING", "mistralai/mistral-7b-instruct:free") # Example: "mistralai/mistral-7b-instruct" or a paid one
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.1"))
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "1024"))
LLM_REQUEST_TIMEOUT = int(os.getenv("LLM_REQUEST_TIMEOUT", "60")) # Seconds for LLM API call


# --- Feature Flags ---
# Set to True to use LLM parser. If False or LLM fails, RegexParser will be used as fallback.
USE_LLM_PARSER = True
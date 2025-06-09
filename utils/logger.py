# dependency_resolver_agent/utils/logger.py
ENABLE_VERBOSE_LOGGING = False

def log_verbose(message: str):
    if ENABLE_VERBOSE_LOGGING:
        print(message)

def set_verbose_logging(enable: bool):
    global ENABLE_VERBOSE_LOGGING
    ENABLE_VERBOSE_LOGGING = enable
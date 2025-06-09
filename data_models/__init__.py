# dependency_resolver_agent/data_models/__init__.py

# Expose the key data models at the package level
from .requirement import Requirement, PACKAGING_AVAILABLE, Version, SpecifierSet, InvalidSpecifier, InvalidVersion
from .conflict_info import ConflictInfo

__all__ = [
    "Requirement",
    "ConflictInfo",
    "PACKAGING_AVAILABLE",
    "Version",
    "SpecifierSet",
    "InvalidSpecifier",
    "InvalidVersion"
]
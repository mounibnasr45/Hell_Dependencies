# dependency_resolver_agent/data_models/requirement.py
from dataclasses import dataclass, field
from typing import Optional

# --- Packaging Library (Optional but Recommended) ---
try:
    from packaging.specifiers import SpecifierSet, InvalidSpecifier
    from packaging.version import Version, InvalidVersion
    PACKAGING_AVAILABLE = True
except ImportError:
    PACKAGING_AVAILABLE = False
    # Dummy classes if 'packaging' is not available (copied from original script)
    class Version:
        def __init__(self, v_str):
            self.v_str = str(v_str)
            try:
                parts = [int(p) for p in self.v_str.split('.')[:3]]
                self.major = parts[0] if len(parts) > 0 else 0
                self.minor = parts[1] if len(parts) > 1 else 0
                self.micro = parts[2] if len(parts) > 2 else 0
            except ValueError: self.major, self.minor, self.micro = 0,0,0
            self.public = self.v_str
        def __str__(self): return self.v_str
        def __lt__(self, other): return self.v_str < other.v_str
        def __eq__(self, other): return self.v_str == other.v_str
        def __hash__(self): return hash(self.v_str)
        @property
        def release(self): return tuple(int(p) for p in self.v_str.split('.')[:2]) # Simplified major.minor

    class SpecifierSet:
        def __init__(self, s_str=""): self.s_str = str(s_str) if s_str else ""
        def __contains__(self, version_obj: Version) -> bool:
            if not self.s_str: return True
            if self.s_str.startswith("=="): return version_obj.v_str == self.s_str[2:]
            return True
        def __str__(self): return self.s_str
        def filter(self, versions_iterable): return versions_iterable
    class InvalidSpecifier(Exception): pass
    class InvalidVersion(Exception): pass

if not PACKAGING_AVAILABLE:
    print("CRITICAL WARNING: 'packaging' library not found. Install with: pip install packaging")
    print("                 Version comparison and specifier validation will be limited.")


@dataclass(frozen=True, order=True)
class Requirement:
    name: str
    specifier: str = field(default="") # Can be empty for "any version"

    def __post_init__(self):
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("Requirement name must be a non-empty string.")
        if not isinstance(self.specifier, str):
            raise ValueError("Requirement specifier must be a string (can be empty).")
        if PACKAGING_AVAILABLE and self.specifier:
            try:
                SpecifierSet(self.specifier)
            except InvalidSpecifier as e:
                raise ValueError(f"Invalid specifier '{self.specifier}' for package '{self.name}': {e}")

    def __str__(self):
        return f"{self.name}{self.specifier}" if self.specifier else self.name

    def is_exact(self) -> bool:
        return self.specifier.startswith("==")

    def get_exact_version_str(self) -> Optional[str]:
        if self.is_exact():
            version_part = self.specifier[2:]
            if PACKAGING_AVAILABLE:
                try:
                    return str(Version(version_part).public)
                except InvalidVersion:
                    return None # Or return version_part if malformed but still want to use?
            return version_part # Fallback if packaging not available
        return None

    def get_version_obj(self) -> Optional[Version]:
        if self.is_exact() and PACKAGING_AVAILABLE:
            try:
                return Version(self.specifier[2:])
            except InvalidVersion:
                return None
        elif self.is_exact(): # PACKAGING_AVAILABLE is False
             try:
                return Version(self.specifier[2:]) # Use dummy Version
             except: # Catch any error during dummy parsing
                return None
        return None
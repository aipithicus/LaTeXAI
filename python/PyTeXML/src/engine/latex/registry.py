"""One immutable name index for the supported Python format adaptations."""
from types import MappingProxyType
from . import declarations, lookahead, files


def _profiles(*families):
    profiles = {}
    for family in families:
        for name, profile in family.PROFILES.items():
            if name in profiles:
                raise ValueError(f'Duplicate format routine: {name}')
            profiles[name] = profile
    return MappingProxyType(profiles)


PROFILES = _profiles(declarations, lookahead, files)

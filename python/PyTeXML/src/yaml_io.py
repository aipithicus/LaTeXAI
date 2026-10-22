"""Strict YAML loading and resource identities; domain schemas stay with their owners."""
from __future__ import annotations
from pathlib import Path
from typing import Any
import yaml


class _UniqueLoader(yaml.SafeLoader):
    def __init__(self, stream, error_type: type[ValueError]):
        self.error_type = error_type
        super().__init__(stream)


def _mapping(loader: _UniqueLoader, node: yaml.MappingNode, deep: bool = False) -> dict:
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            if key in result:
                raise loader.error_type(f"Duplicate YAML key {key!r} at {key_node.start_mark}")
            result[key] = loader.construct_object(value_node, deep=deep)
        except TypeError as error:
            raise loader.error_type(f"Invalid YAML mapping key at {key_node.start_mark}") from error
    return result


_UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def load_mapping(path: Path, *, error_type: type[ValueError] = ValueError) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as stream:
            loader = _UniqueLoader(stream, error_type)
            try:
                data = loader.get_single_data()
            finally:
                loader.dispose()
    except yaml.YAMLError as error:
        raise error_type(f"{path}: {error}") from error
    if not isinstance(data, dict):
        raise error_type(f"{path}: expected a YAML mapping")
    return data


def validate_resource_identity(data: dict[str, Any], path: Path, *, key: str = "name",
                               error_type: type[ValueError] = ValueError) -> str:
    """Require one resource's declared local identity to equal its filename stem.

    The caller supplies the schema's identity field and owns the namespace.
    This validates already loaded data; it performs no additional file I/O and
    does not constrain names of entries inside aggregate registries.
    """
    identity = data.get("identity")
    if not isinstance(identity, dict):
        raise error_type(f"{path}: identity must be a mapping")
    name = identity.get(key)
    if not isinstance(name, str) or not name:
        raise error_type(f"{path}: identity.{key} must be a nonempty string")
    if name != path.stem:
        raise error_type(f"{path}: identity.{key} {name!r} must match filename stem {path.stem!r}")
    return name

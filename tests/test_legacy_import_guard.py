import importlib

import pytest


def test_legacy_package_is_removed() -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("sena.legacy")

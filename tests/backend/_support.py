import sys
from types import ModuleType, SimpleNamespace
from typing import Any


def install_config_module(monkeypatch: Any, config: SimpleNamespace) -> None:
    plugins = ModuleType("plugins")
    plugins.__path__ = []
    memory = ModuleType("plugins.memory")
    memory.__path__ = []
    honcho = ModuleType("plugins.memory.honcho")
    honcho.__path__ = []
    client = ModuleType("plugins.memory.honcho.client")

    class HonchoClientConfig:
        @classmethod
        def from_global_config(cls) -> SimpleNamespace:
            return config

    setattr(client, "HonchoClientConfig", HonchoClientConfig)
    monkeypatch.setitem(sys.modules, "plugins", plugins)
    monkeypatch.setitem(sys.modules, "plugins.memory", memory)
    monkeypatch.setitem(sys.modules, "plugins.memory.honcho", honcho)
    monkeypatch.setitem(sys.modules, "plugins.memory.honcho.client", client)

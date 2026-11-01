"""依 [guards.*] 設定組出 GuardPipeline（可插拔：[guards] python = ["pkg.mod"]）。"""
import importlib

from aicam.core.guards import STAGES, GuardPipeline
from aicam.plugins.registry import ConfigError

from .builtin import BUILTIN


def build_pipeline(settings, on_hit=None) -> GuardPipeline:
    gc = settings.section("guards")
    registry = dict(BUILTIN)
    for mod in gc.get("python", []):                 # 可插拔：模組需提供 GUARDS = {name: class}
        registry.update(importlib.import_module(mod).GUARDS)
    confs = gc.get("conf", {})
    chains = {}
    for st in STAGES:
        names = gc.get(st, {}).get("chain", [])
        unknown = [n for n in names if n not in registry]
        if unknown:
            raise ConfigError(f"[guards.{st}] 含未知 guard：{unknown}")
        chains[st] = [registry[n](confs.get(n, {})) for n in names]
    return GuardPipeline(chains, on_hit)

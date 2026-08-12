"""Adapters: snapshots, optional Cynober RPC, public space weather."""

from __future__ import annotations

from adapters.snapshot_store import SnapshotStore, load_snapshot_into_map

__all__ = [
    "SnapshotStore",
    "load_snapshot_into_map",
    "CynoberRpcBridge",
    "client_available",
    "rpc_status_dict",
    "get_space_weather",
    "SpaceWeatherSnapshot",
]


def __getattr__(name: str):
    # Soft export — avoid importing cynober_client at package import time
    if name in ("CynoberRpcBridge", "client_available", "rpc_status_dict"):
        from adapters import cynober_rpc as _rpc

        return getattr(_rpc, name)
    if name in ("get_space_weather", "SpaceWeatherSnapshot"):
        from adapters import space_weather as _wx

        return getattr(_wx, name)
    raise AttributeError(name)
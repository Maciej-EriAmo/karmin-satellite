"""Adapters: snapshots + optional Cynober RPC.

Solar weather lives in ``engine.solar`` (shims under adapters.space_weather).
"""

from __future__ import annotations

from adapters.snapshot_store import SnapshotStore, load_snapshot_into_map

__all__ = [
    "SnapshotStore",
    "load_snapshot_into_map",
    "CynoberRpcBridge",
    "client_available",
    "rpc_status_dict",
]


def __getattr__(name: str):
    # Soft export — avoid importing cynober_client at package import time
    if name in ("CynoberRpcBridge", "client_available", "rpc_status_dict"):
        from adapters import cynober_rpc as _rpc

        return getattr(_rpc, name)
    raise AttributeError(name)
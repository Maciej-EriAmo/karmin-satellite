"""Adapters: persistence bridges (local snapshots; optional Cynober later)."""

from __future__ import annotations

from adapters.snapshot_store import SnapshotStore, load_snapshot_into_map

__all__ = ["SnapshotStore", "load_snapshot_into_map"]

#!/usr/bin/env python3
"""
Optional Cynober DB RPC bridge for Studio snapshots (S1b remote).

Local JSON store remains primary. This module pushes/pulls the same
``cynober-studio-snapshot-v1`` payload over Cynober-Secure (KarminQL + KAFS media).

Config (env):
  CYNOBER_HOST / CYNOBER_PORT     — direct endpoint (default 127.0.0.1:8080)
  CYNOBER_PROFILE                — ~/.karmazyn_client.json profile name
  CYNOBER_WORLD                  — optional WYBIERZ ŚWIAT after connect
  CYNOBER_DB / DBASE_PATH        — extra sys.path for cynober_client (dev tree)
  CYNOBER_RPC=0                  — force-disable even if client is importable

Does NOT hard-depend on DBase at import time — soft import on connect.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("cynober.studio.rpc")

# Atom / media id prefix in Cynober worlds
ATOM_PREFIX = "studio:snap:"
BUBBLE_CATALOG = "CynoberStudioSnapshots"
MIME_SNAPSHOT = "application/vnd.cynober.studio.snapshot+json"


class CynoberRpcError(RuntimeError):
    """Bridge / transport error (optional path — never crash Studio core)."""


def _env_truthy(name: str, default: str = "") -> bool:
    v = os.environ.get(name, default).strip().lower()
    return v in ("1", "true", "yes", "on")


def ensure_cynober_on_path() -> Optional[Path]:
    """Add DBase / Cynober tree to sys.path if needed. Returns path used or None."""
    candidates: List[Path] = []
    for key in ("CYNOBER_DB", "DBASE_PATH"):
        raw = os.environ.get(key, "").strip()
        if raw:
            candidates.append(Path(raw))
    # sibling / known local trees
    home = Path.home()
    candidates.extend(
        [
            home / "DBase",
            Path(r"C:\Users\drwis\DBase"),
            Path(__file__).resolve().parents[2] / "DBase",
        ]
    )
    for p in candidates:
        if p.is_dir() and (p / "cynober_client.py").is_file():
            sp = str(p)
            if sp not in sys.path:
                sys.path.insert(0, sp)
            return p
    return None


def client_available() -> bool:
    """True if cynober_client can be imported (RPC disabled via CYNOBER_RPC=0)."""
    if os.environ.get("CYNOBER_RPC", "1").strip() in ("0", "false", "no", "off"):
        return False
    ensure_cynober_on_path()
    try:
        import cynober_client  # noqa: F401

        return True
    except Exception:
        return False


def atom_id_for(snapshot_id: str) -> str:
    sid = str(snapshot_id).strip()
    if sid.startswith(ATOM_PREFIX):
        return sid
    return f"{ATOM_PREFIX}{sid}"


def slim_payload_for_rpc(
    payload: dict,
    *,
    include_sats: bool = False,
    max_sats: int = 0,
) -> dict:
    """
    Remote-safe copy: density + meta (SLA: scale with cells, not N sats).

    Full TLE catalog stays on local disk snapshots unless include_sats=True.
    """
    out = {
        "format": payload.get("format") or "cynober-studio-snapshot-v1",
        "snapshot_id": payload.get("snapshot_id"),
        "created_at": payload.get("created_at"),
        "src": payload.get("src"),
        "using": payload.get("using"),
        "grid_deg": payload.get("grid_deg"),
        "hot_only": payload.get("hot_only"),
        "prop": payload.get("prop"),
        "version": payload.get("version"),
        "shells": payload.get("shells") or {},
        "summary": payload.get("summary") or {},
        "density": payload.get("density") or [],
        "catalog_hash": payload.get("catalog_hash"),
        "rpc": {
            "include_sats": bool(include_sats),
            "transport": "cynober-media-kafs",
        },
    }
    if include_sats:
        sats = list(payload.get("sats") or [])
        if max_sats and max_sats > 0:
            sats = sats[: int(max_sats)]
        out["sats"] = sats
    else:
        out["sats"] = []
        out["sats_omitted"] = int(
            payload.get("using")
            or len(payload.get("sats") or [])
            or 0
        )
    return out


@dataclass
class RpcPushResult:
    snapshot_id: str
    atom_id: str
    bytes_sent: int
    cells: int
    world: Optional[str] = None
    remote: Optional[dict] = None

    def as_dict(self) -> dict:
        return {
            "snapshot_id": self.snapshot_id,
            "atom_id": self.atom_id,
            "bytes_sent": self.bytes_sent,
            "cells": self.cells,
            "world": self.world,
            "remote": self.remote,
        }


class CynoberRpcBridge:
    """
    Thin adapter over cynober_client.Connect.

    Usage:
      with CynoberRpcBridge.from_env() as br:
          br.health()
          br.push_payload(payload)
    """

    def __init__(
        self,
        client: Any,
        *,
        world: Optional[str] = None,
        owned_client: bool = True,
    ):
        self.client = client
        self.world = world
        self._owned = owned_client
        self._world_selected = False

    @classmethod
    def from_env(
        cls,
        *,
        host: Optional[str] = None,
        port: Optional[int] = None,
        profile: Optional[str] = None,
        world: Optional[str] = None,
        timeout: float = 30.0,
    ) -> "CynoberRpcBridge":
        if not client_available():
            raise CynoberRpcError(
                "cynober_client unavailable — install cynober-db or set CYNOBER_DB"
            )
        ensure_cynober_on_path()
        from cynober_client import connect

        host = host if host is not None else os.environ.get("CYNOBER_HOST") or None
        port_raw = os.environ.get("CYNOBER_PORT", "").strip()
        if port is None and port_raw:
            port = int(port_raw)
        profile = profile if profile is not None else (
            os.environ.get("CYNOBER_PROFILE") or None
        )
        world = world if world is not None else (
            os.environ.get("CYNOBER_WORLD") or None
        )

        if host and port:
            client = connect(host, int(port), timeout=timeout)
        elif host and not port:
            client = connect(host, 8080, timeout=timeout)
        elif profile:
            client = connect(profile=profile, timeout=timeout)
        else:
            # active profile / defaults
            client = connect(timeout=timeout)

        br = cls(client, world=world or None, owned_client=True)
        if br.world:
            br.select_world(br.world)
        return br

    def select_world(self, world: str, *, create: bool = False) -> dict:
        w = _esc(world)
        if create:
            row = self.client.query_line(f'UTWÓRZ ŚWIAT "{w}"')
            if row.get("status") not in ("ok", None) and "istnieje" not in str(
                row.get("message") or ""
            ).lower():
                # try select anyway
                pass
        row = self.client.query_line(f'WYBIERZ ŚWIAT "{w}"')
        st = str((row or {}).get("status") or "").lower()
        if st and st not in ("ok", "none"):
            raise CynoberRpcError(f'WYBIERZ ŚWIAT "{w}" failed: {row}')
        self.world = world
        self._world_selected = True
        return row

    def health(self) -> dict:
        row = self.client.query_line("ZDROWIE")
        info = {}
        try:
            if hasattr(self.client, "session_info"):
                info = self.client.session_info()
        except Exception:
            info = {}
        return {
            "status": row.get("status") or "unknown",
            "health": row,
            "session": info,
            "world": self.world,
            "kafs": bool(getattr(self.client, "kafs_enabled", False)),
        }

    def push_payload(
        self,
        payload: dict,
        *,
        snapshot_id: Optional[str] = None,
        include_sats: bool = False,
        max_sats: int = 0,
        register_catalog: bool = True,
    ) -> RpcPushResult:
        sid = str(
            snapshot_id
            or payload.get("snapshot_id")
            or f"snap_{int(__import__('time').time())}"
        )
        slim = slim_payload_for_rpc(
            {**payload, "snapshot_id": sid},
            include_sats=include_sats,
            max_sats=max_sats,
        )
        raw = json.dumps(slim, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        aid = atom_id_for(sid)

        if not getattr(self.client, "kafs_enabled", False):
            # Fallback: store density JSON as string feature on catalog atom
            return self._push_via_karminql(slim, sid, aid, raw, register_catalog)

        if register_catalog:
            self._ensure_catalog_meta(sid, aid, slim, len(raw))
        remote = self.client.put_media(
            aid,
            raw,
            mime=MIME_SNAPSHOT,
            bubble=BUBBLE_CATALOG if register_catalog else "",
            binding=sid if register_catalog else "",
        )
        return RpcPushResult(
            snapshot_id=sid,
            atom_id=aid,
            bytes_sent=len(raw),
            cells=len(slim.get("density") or []),
            world=self.world,
            remote=remote if isinstance(remote, dict) else {"raw": remote},
        )

    def _push_via_karminql(
        self,
        slim: dict,
        sid: str,
        aid: str,
        raw: bytes,
        register_catalog: bool,
    ) -> RpcPushResult:
        """When KAFS unavailable: UTRWAL + WSTRZYKNIJ JSON (size-limited)."""
        if len(raw) > 400_000:
            raise CynoberRpcError(
                f"payload {len(raw)} B too large for KarminQL fallback "
                f"(need KAFS / kafs-stream); cells={len(slim.get('density') or [])}"
            )
        # escape for KarminQL string literal
        body = raw.decode("utf-8").replace("\\", "\\\\").replace('"', '\\"')
        bubble = _esc(BUBBLE_CATALOG)
        self.client.query_line(f'UTRWAL "{bubble}"')
        self.client.query_line(
            f'WSTRZYKNIJ "{_esc(sid)}" = "{body[:200000]}" DO "{bubble}"'
        )
        self.client.query_line(
            f'WSTRZYKNIJ "{_esc(sid + ":atom")}" = "{_esc(aid)}" DO "{bubble}"'
        )
        self.client.query_line(
            f'WSTRZYKNIJ "{_esc(sid + ":cells")}" = {len(slim.get("density") or [])} DO "{bubble}"'
        )
        return RpcPushResult(
            snapshot_id=sid,
            atom_id=aid,
            bytes_sent=len(raw),
            cells=len(slim.get("density") or []),
            world=self.world,
            remote={"transport": "karminql-json", "kafs": False},
        )

    def _ensure_catalog_meta(
        self, sid: str, aid: str, slim: dict, nbytes: int
    ) -> None:
        bubble = _esc(BUBBLE_CATALOG)
        try:
            self.client.query_line(f'UTRWAL "{bubble}"')
            self.client.query_line(
                f'WSTRZYKNIJ "{_esc(sid + ":meta")}" = '
                f'{{"atom_id":"{_esc(aid)}","cells":{len(slim.get("density") or [])},'
                f'"bytes":{nbytes},"version":{int(slim.get("version") or 0)}}} '
                f'DO "{bubble}"'
            )
        except Exception as e:
            log.debug("catalog meta skip: %s", e)

    def pull_payload(self, snapshot_id: str) -> dict:
        aid = atom_id_for(snapshot_id)
        if getattr(self.client, "kafs_enabled", False):
            try:
                data, mime, meta = self.client.get_media(aid)
                payload = json.loads(data.decode("utf-8"))
                payload.setdefault("snapshot_id", snapshot_id)
                payload["_rpc"] = {"atom_id": aid, "mime": mime, "meta": meta}
                return payload
            except Exception as e:
                log.info("get_media failed (%s), trying KarminQL fallback", e)

        # KarminQL fallback: feature on catalog bubble
        bubble = _esc(BUBBLE_CATALOG)
        row = self.client.query_line(
            f'WYPISZ "{_esc(snapshot_id)}" GDZIE "BĄBEL" = "{bubble}"'
        )
        # Various response shapes — try common fields
        text = None
        if isinstance(row, dict):
            data = row.get("data") or row.get("row") or row
            if isinstance(data, dict):
                text = data.get(snapshot_id) or data.get("value") or data.get("V")
            if text is None:
                text = row.get(snapshot_id) or row.get("value")
        if not text:
            # try SHOW bubble
            show = self.client.query_line(f'POKAŻ "{bubble}"')
            props = (show.get("data") or show).get("properties") if isinstance(
                show.get("data") or show, dict
            ) else None
            if isinstance(props, dict):
                text = props.get(snapshot_id)
        if not text:
            raise CynoberRpcError(f"snapshot not found on RPC: {snapshot_id}")
        if isinstance(text, dict):
            return text
        return json.loads(str(text))

    def push_from_local_store(
        self,
        local_store: Any,
        snapshot_id: str,
        **kwargs: Any,
    ) -> RpcPushResult:
        payload = local_store.load_raw(snapshot_id)
        return self.push_payload(payload, snapshot_id=snapshot_id, **kwargs)

    def close(self) -> None:
        if self._owned and self.client is not None:
            try:
                self.client.close()
            except Exception:
                pass
            self.client = None

    def __enter__(self) -> "CynoberRpcBridge":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


def _esc(name: str) -> str:
    return str(name).replace("\\", "\\\\").replace('"', '\\"')


def rpc_status_dict() -> Dict[str, Any]:
    """Machine-readable availability for /api/rpc/status (no connect)."""
    path = ensure_cynober_on_path()
    avail = client_available()
    return {
        "available": avail,
        "enabled_env": os.environ.get("CYNOBER_RPC", "1"),
        "cynober_db_path": str(path) if path else None,
        "host": os.environ.get("CYNOBER_HOST") or None,
        "port": os.environ.get("CYNOBER_PORT") or None,
        "profile": os.environ.get("CYNOBER_PROFILE") or None,
        "world": os.environ.get("CYNOBER_WORLD") or None,
        "atom_prefix": ATOM_PREFIX,
        "note_en": "Optional remote bridge; local out/snapshots remains primary.",
        "note_pl": "Opcjonalny most zdalny; lokalne out/snapshots zostaje primary.",
    }

"""Unit tests for optional Cynober RPC bridge (mocked client — no server)."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "substrate"))
sys.path.insert(0, str(ROOT))


class _FakeClient:
    def __init__(self, *, kafs: bool = True, accept_login: bool = True):
        self.kafs_enabled = kafs
        self.media: Dict[str, bytes] = {}
        self.queries: List[str] = []
        self.closed = False
        self.accept_login = accept_login
        self.logged_in: Optional[str] = None

    def query_line(self, text: str) -> dict:
        self.queries.append(text)
        u = text.strip().upper()
        if u.startswith("ZALOGUJ"):
            if not self.accept_login:
                return {"status": "error", "message": "bad token"}
            # Keep last quoted name as logged-in user for tests.
            import re

            m = re.search(r'ZALOGUJ\s+"([^"]+)"', text, re.I)
            self.logged_in = m.group(1) if m else "user"
            return {"status": "ok", "action": "LOGIN", "user": self.logged_in}
        if u.startswith("ZDROWIE"):
            return {"status": "ok", "data": {"server_version": "test"}}
        if u.startswith("WYBIERZ"):
            return {"status": "ok", "action": "SELECT_WORLD"}
        if u.startswith("UTRWAL"):
            return {"status": "ok"}
        if "MEDIA PUT" in u:
            return {"status": "ok"}
        return {"status": "ok"}

    def put_media(
        self,
        atom_id: str,
        data: bytes,
        *,
        mime: str = "application/octet-stream",
        bubble: str = "",
        binding: str = "",
        chunk_size: int = 0,
    ) -> dict:
        self.media[atom_id] = bytes(data)
        return {
            "status": "ok",
            "atom_id": atom_id,
            "size": len(data),
            "mime": mime,
            "bubble": bubble,
            "binding": binding,
        }

    def get_media(self, atom_id: str, **kwargs: Any):
        if atom_id not in self.media:
            raise RuntimeError(f"missing {atom_id}")
        return self.media[atom_id], "application/json", {"id": atom_id}

    def session_info(self) -> dict:
        return {"host": "fake", "port": 0, "connected": True, "kafs_enabled": self.kafs_enabled}

    def close(self) -> None:
        self.closed = True


class TestSlimPayload(unittest.TestCase):
    def test_slim_strips_sats_by_default(self):
        from adapters.cynober_rpc import slim_payload_for_rpc

        payload = {
            "format": "cynober-studio-snapshot-v1",
            "snapshot_id": "snap_test",
            "density": [{"ilat": 1, "ilon": 2, "count": 9}],
            "shells": {"shell:53": 3},
            "sats": [{"norad": 1, "tle1": "x", "tle2": "y"}] * 5,
            "using": 5,
            "version": 2,
        }
        slim = slim_payload_for_rpc(payload)
        self.assertEqual(slim["sats"], [])
        self.assertEqual(slim["sats_omitted"], 5)
        self.assertEqual(len(slim["density"]), 1)
        slim2 = slim_payload_for_rpc(payload, include_sats=True, max_sats=2)
        self.assertEqual(len(slim2["sats"]), 2)


class TestBridgeMock(unittest.TestCase):
    def test_push_pull_kafs(self):
        from adapters.cynober_rpc import CynoberRpcBridge, atom_id_for

        client = _FakeClient(kafs=True)
        br = CynoberRpcBridge(client, world="studio_test", owned_client=True)
        payload = {
            "snapshot_id": "demo1",
            "density": [{"ilat": 10, "ilon": 20, "count": 4}],
            "shells": {},
            "summary": {"sats": 0},
            "version": 1,
            "using": 0,
        }
        res = br.push_payload(payload)
        self.assertEqual(res.snapshot_id, "demo1")
        self.assertEqual(res.atom_id, atom_id_for("demo1"))
        self.assertGreater(res.bytes_sent, 20)
        self.assertEqual(res.cells, 1)
        self.assertIn(res.atom_id, client.media)

        got = br.pull_payload("demo1")
        self.assertEqual(got["snapshot_id"], "demo1")
        self.assertEqual(got["density"][0]["count"], 4)
        br.close()
        self.assertTrue(client.closed)

    def test_push_karminql_fallback(self):
        from adapters.cynober_rpc import CynoberRpcBridge

        client = _FakeClient(kafs=False)
        br = CynoberRpcBridge(client, owned_client=False)
        payload = {
            "snapshot_id": "ql1",
            "density": [{"ilat": 0, "ilon": 0, "count": 1}],
            "using": 0,
        }
        res = br.push_payload(payload)
        self.assertEqual(res.remote.get("transport"), "karminql-json")
        self.assertTrue(any("UTRWAL" in q for q in client.queries))

    def test_rpc_status_dict(self):
        from adapters.cynober_rpc import rpc_status_dict

        d = rpc_status_dict()
        self.assertIn("available", d)
        self.assertIn("atom_prefix", d)
        self.assertIn("note_en", d)
        self.assertEqual(d.get("min_cynober_db"), "8.2.5")
        self.assertIn("auth_configured", d)

    def test_login_ok(self):
        from adapters.cynober_rpc import CynoberRpcBridge

        client = _FakeClient()
        br = CynoberRpcBridge(client, owned_client=False)
        row = br.login("admin", "secret")
        self.assertEqual(row.get("status"), "ok")
        self.assertEqual(br._auth_user, "admin")
        self.assertTrue(any(q.upper().startswith("ZALOGUJ") for q in client.queries))
        h = br.health()
        self.assertEqual(h.get("auth_user"), "admin")

    def test_login_fail(self):
        from adapters.cynober_rpc import CynoberRpcBridge, CynoberRpcError

        client = _FakeClient(accept_login=False)
        br = CynoberRpcBridge(client, owned_client=False)
        with self.assertRaises(CynoberRpcError):
            br.login("admin", "wrong")


class TestStudioRpcStatusApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import threading
        import urllib.request
        from http.server import ThreadingHTTPServer

        from engine.starlink_atoms import build_map
        from ui.app import StudioState, create_handler

        store, amap, use, src = build_map(
            limit=12,
            hot_only=True,
            offline_demo=True,
            backend="python",
            cache="out/starlink_tle_cache.txt",
        )
        cls.state = StudioState(
            amap=amap,
            catalog=list(use),
            src=src,
            using=len(use),
            offline_demo=True,
        )
        handler = create_handler(cls.state)
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.port = cls.httpd.server_address[1]
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.urllib = urllib.request

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def test_api_rpc_status(self):
        with self.urllib.urlopen(self.base + "/api/rpc/status", timeout=5) as r:
            j = json.loads(r.read().decode("utf-8"))
        self.assertEqual(j["status"], "ok")
        self.assertIn("available", j["data"])


if __name__ == "__main__":
    unittest.main()

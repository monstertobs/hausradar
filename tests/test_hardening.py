"""Security-Hardening Tests (Phase 7).

Abgedeckte Findings:
  HR-SEC-001 – X-API-Key Middleware
  HR-SEC-002 – simulate/motion in Production deaktiviert
  HR-SEC-005 – Body-Size-Limit
  HR-SEC-006 – XSS: esc()-Funktion in api.js vorhanden
  HR-SEC-007 – Security-HTTP-Header in Responses
  HR-SEC-008 – WebSocket Origin-Prüfung
  HR-SEC-009 – Max 3 Targets
  HR-SEC-012 – WebSocket Verbindungslimit
  HR-SEC-015 – analytics.py Spaltenname-Whitelist
"""
import json
import sys
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))

from fastapi.testclient import TestClient
from app.main import app, _origin_allowed
from app import database as db
from app import live_state
from app.analytics import _where
from app.websocket_service import ConnectionManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clean_state():
    live_state.clear()
    db._reset_for_tests()
    yield
    live_state.clear()
    db._reset_for_tests()


@pytest.fixture()
def client():
    with TestClient(app) as c:
        db._clear_tables_for_tests(app.state.db_path)
        db._reset_for_tests()
        live_state.clear()
        yield c


BASE_PAYLOAD = {
    "sensor_id":    "radar_wohnzimmer",
    "room_id":      "wohnzimmer",
    "timestamp_ms": 1_710_000_000_000,
    "target_count": 0,
    "targets":      [],
}


# ---------------------------------------------------------------------------
# HR-SEC-002 – simulate/motion in Production deaktiviert
# ---------------------------------------------------------------------------

class TestSimulateProductionMode:
    def test_simulate_active_in_development(self, client):
        """Im Development-Modus (Standard) muss simulate/motion 200 zurückgeben."""
        app.state.settings["environment"] = "development"
        res = client.post("/api/simulate/motion", json=BASE_PAYLOAD)
        assert res.status_code == 200

    def test_simulate_disabled_in_production(self, client):
        """Im Production-Modus muss simulate/motion 404 zurückgeben."""
        app.state.settings["environment"] = "production"
        try:
            res = client.post("/api/simulate/motion", json=BASE_PAYLOAD)
            assert res.status_code == 404
        finally:
            app.state.settings["environment"] = "development"

    def test_live_endpoint_active_in_production(self, client):
        """GET /api/live muss auch im Production-Modus verfügbar sein."""
        app.state.settings["environment"] = "production"
        try:
            res = client.get("/api/live")
            assert res.status_code == 200
        finally:
            app.state.settings["environment"] = "development"


# ---------------------------------------------------------------------------
# HR-SEC-009 – Max 3 Targets
# ---------------------------------------------------------------------------

class TestMaxTargets:
    def _target(self, tid: int):
        return {"id": tid, "x_mm": 1000.0, "y_mm": 500.0, "speed_mm_s": 0.0, "distance_mm": 0.0}

    def test_three_targets_accepted(self, client):
        targets = [self._target(i) for i in range(3)]
        payload = {**BASE_PAYLOAD, "target_count": 3, "targets": targets}
        res = client.post("/api/simulate/motion", json=payload)
        assert res.status_code == 200

    def test_four_targets_rejected(self, client):
        targets = [self._target(i) for i in range(4)]
        payload = {**BASE_PAYLOAD, "target_count": 4, "targets": targets}
        res = client.post("/api/simulate/motion", json=payload)
        assert res.status_code == 422

    def test_zero_targets_accepted(self, client):
        res = client.post("/api/simulate/motion", json=BASE_PAYLOAD)
        assert res.status_code == 200


# ---------------------------------------------------------------------------
# HR-SEC-007 – Security-HTTP-Header
# ---------------------------------------------------------------------------

class TestSecurityHeaders:
    def test_x_frame_options_present(self, client):
        res = client.get("/api/health")
        assert res.headers.get("x-frame-options") == "DENY"

    def test_x_content_type_options_present(self, client):
        res = client.get("/api/health")
        assert res.headers.get("x-content-type-options") == "nosniff"

    def test_referrer_policy_present(self, client):
        res = client.get("/api/health")
        assert res.headers.get("referrer-policy") == "no-referrer"

    def test_permissions_policy_present(self, client):
        res = client.get("/api/health")
        assert "permissions-policy" in res.headers

    def test_csp_present(self, client):
        res = client.get("/api/health")
        csp = res.headers.get("content-security-policy", "")
        assert "default-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp

    def test_headers_on_post_endpoint(self, client):
        """Security-Header müssen auch auf POST-Responses vorhanden sein."""
        res = client.post("/api/simulate/motion", json=BASE_PAYLOAD)
        assert res.headers.get("x-frame-options") == "DENY"


# ---------------------------------------------------------------------------
# HR-SEC-001 – X-API-Key Middleware
# ---------------------------------------------------------------------------

class TestApiKeyAuth:
    def test_no_key_configured_allows_all(self, client):
        """Ohne api_key in settings ist kein Auth erforderlich."""
        app.state.settings.setdefault("server", {})["api_key"] = ""
        from app import main as main_module
        original = main_module._API_KEY
        main_module._API_KEY = None
        try:
            res = client.get("/api/health")
            assert res.status_code == 200
        finally:
            main_module._API_KEY = original

    def test_wrong_key_returns_401(self, client):
        """Mit falschem API-Key muss 401 zurückgegeben werden."""
        from app import main as main_module
        original = main_module._API_KEY
        main_module._API_KEY = "geheimespasswort"
        try:
            res = client.get("/api/live", headers={"X-API-Key": "falscher-key"})
            assert res.status_code == 401
        finally:
            main_module._API_KEY = original

    def test_correct_key_returns_200(self, client):
        """Mit korrektem API-Key muss die Anfrage durchgehen."""
        from app import main as main_module
        original = main_module._API_KEY
        main_module._API_KEY = "geheimespasswort"
        try:
            res = client.get("/api/live", headers={"X-API-Key": "geheimespasswort"})
            assert res.status_code == 200
        finally:
            main_module._API_KEY = original

    def test_health_exempt_from_key(self, client):
        """/api/health ist vom API-Key-Zwang ausgenommen."""
        from app import main as main_module
        original = main_module._API_KEY
        main_module._API_KEY = "geheimespasswort"
        try:
            res = client.get("/api/health")
            assert res.status_code == 200
        finally:
            main_module._API_KEY = original

    def test_missing_key_returns_401(self, client):
        """Ohne X-API-Key Header muss 401 zurückgegeben werden."""
        from app import main as main_module
        original = main_module._API_KEY
        main_module._API_KEY = "geheimespasswort"
        try:
            res = client.get("/api/rooms")
            assert res.status_code == 401
        finally:
            main_module._API_KEY = original


# ---------------------------------------------------------------------------
# HR-SEC-005 – Body-Size-Limit
# ---------------------------------------------------------------------------

class TestBodySizeLimit:
    def test_large_body_rejected(self, client):
        """Body > 64 KB muss mit 413 abgelehnt werden."""
        # Erzeuge einen Payload weit über 64 KB
        huge_payload = {
            "sensor_id":    "radar_wohnzimmer",
            "room_id":      "wohnzimmer",
            "timestamp_ms": 1_710_000_000_000,
            "target_count": 0,
            "targets":      [],
            "padding":      "x" * 100_000,
        }
        res = client.post(
            "/api/simulate/motion",
            content=json.dumps(huge_payload),
            headers={"Content-Type": "application/json"},
        )
        assert res.status_code == 413

    def test_normal_payload_accepted(self, client):
        """Normaler Payload muss weiterhin akzeptiert werden."""
        res = client.post("/api/simulate/motion", json=BASE_PAYLOAD)
        assert res.status_code == 200


# ---------------------------------------------------------------------------
# HR-SEC-008 – WebSocket Origin-Prüfung
# ---------------------------------------------------------------------------

class TestOriginCheck:
    def test_no_allowed_origins_permits_all(self):
        """Leere allowed_origins-Liste → Origin-Prüfung deaktiviert (kein Check)."""
        assert _origin_allowed("http://evil.example.com", []) is True
        assert _origin_allowed(None, []) is True

    def test_allowed_origin_accepted(self):
        allowed = ["http://192.168.1.100:8000"]
        assert _origin_allowed("http://192.168.1.100:8000", allowed) is True

    def test_unknown_origin_rejected(self):
        allowed = ["http://192.168.1.100:8000"]
        assert _origin_allowed("http://192.168.1.200:8000", allowed) is False

    def test_none_origin_rejected_when_list_set(self):
        """Kein Origin-Header → abgelehnt wenn Whitelist konfiguriert."""
        allowed = ["http://192.168.1.100:8000"]
        assert _origin_allowed(None, allowed) is False


# ---------------------------------------------------------------------------
# HR-SEC-012 – WebSocket Verbindungslimit
# ---------------------------------------------------------------------------

class TestWebSocketConnectionLimit:
    def test_set_max_connections(self):
        mgr = ConnectionManager()
        mgr.set_max_connections(5)
        assert mgr._max_connections == 5

    def test_default_max_connections(self):
        mgr = ConnectionManager()
        assert mgr._max_connections == 20


# ---------------------------------------------------------------------------
# HR-SEC-015 – analytics.py Spaltenname-Whitelist
# ---------------------------------------------------------------------------

class TestAnalyticsColumnWhitelist:
    def test_allowed_column_accepted(self):
        where, params = _where(["timestamp_ms >= ?"], {"room_id": "wohnzimmer"})
        assert "room_id = ?" in where
        assert "wohnzimmer" in params

    def test_disallowed_column_raises(self):
        with pytest.raises(ValueError, match="Ungültiger Filterparameter"):
            _where(["timestamp_ms >= ?"], {"'; DROP TABLE target_positions; --": "x"})

    def test_unknown_column_raises(self):
        with pytest.raises(ValueError, match="Ungültiger Filterparameter"):
            _where(["timestamp_ms >= ?"], {"unknown_col": "value"})

    def test_sensor_id_allowed(self):
        where, _ = _where(["timestamp_ms >= ?"], {"sensor_id": "radar_wohnzimmer"})
        assert "sensor_id = ?" in where

    def test_zone_id_allowed(self):
        where, _ = _where(["timestamp_ms >= ?"], {"zone_id": "sofa"})
        assert "zone_id = ?" in where


# ---------------------------------------------------------------------------
# HR-SEC-006 – XSS: esc() in api.js vorhanden
# ---------------------------------------------------------------------------

class TestEscFunctionInJs:
    def test_esc_function_defined_in_api_js(self):
        """api.js muss die globale esc()-Funktion definieren."""
        api_js = Path(__file__).resolve().parent.parent / "web" / "api.js"
        content = api_js.read_text(encoding="utf-8")
        assert "function esc(" in content

    def test_esc_used_in_app_js(self):
        """app.js muss esc() für Raum- und Sensornamen verwenden."""
        app_js = Path(__file__).resolve().parent.parent / "web" / "app.js"
        content = app_js.read_text(encoding="utf-8")
        assert "esc(r.name)" in content
        assert "esc(s.name)" in content

    def test_esc_used_in_settings_js(self):
        """settings.js muss esc() für Raum- und Sensornamen verwenden."""
        settings_js = Path(__file__).resolve().parent.parent / "web" / "settings.js"
        content = settings_js.read_text(encoding="utf-8")
        assert "esc(r.name)" in content
        assert "esc(s.name)" in content

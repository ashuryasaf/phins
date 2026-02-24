import threading

import services.community_messaging_service as community_module
import services.foundation_service as foundation_module
from services.actuarial_service import ActuarialIntegrations


class _StubFoundationService:
    def __init__(self):
        self._members = {
            "MEM-1": {"status": "active"},
            "MEM-2": {"status": "active"},
            "MEM-3": {"status": "pending"},
        }

    def list_foundations(self, limit=50, offset=0, member_id=None, status=None):
        return [
            {"id": "FND-1", "status": "active"},
            {"id": "FND-2", "status": "draft"},
        ]


class _StubCommunityService:
    def __init__(self):
        self._lock = threading.Lock()
        self._threads = {
            "THR-1": {"foundation_id": "FND-1", "status": "open"},
            "THR-2": {"foundation_id": "FND-1", "status": "closed"},
            "THR-3": {"foundation_id": "FND-2", "status": "open"},
        }
        self._messages = {
            "MSG-1": {"thread_id": "THR-1"},
            "MSG-2": {"thread_id": "THR-1"},
            "MSG-3": {"thread_id": "THR-2"},
            "MSG-4": {"thread_id": "THR-3"},
        }


def test_get_community_data_summary_returns_live_metrics(monkeypatch):
    foundation_service = _StubFoundationService()
    community_service = _StubCommunityService()

    monkeypatch.setattr(
        foundation_module,
        "get_foundation_service",
        lambda **kwargs: foundation_service,
    )
    monkeypatch.setattr(
        community_module,
        "get_community_messaging_service",
        lambda **kwargs: community_service,
    )

    summary = ActuarialIntegrations.get_community_data_summary()

    assert summary["total_foundations"] == 2
    assert summary["active_foundations"] == 1
    assert summary["total_members"] == 3
    assert summary["active_members"] == 2
    assert summary["total_threads"] == 3
    assert summary["open_threads"] == 2
    assert summary["closed_threads"] == 1
    assert summary["foundations_with_threads"] == 2
    assert summary["total_messages"] == 4
    assert summary["avg_messages_per_thread"] == 1.33


def test_get_community_data_summary_returns_not_available_on_error(monkeypatch):
    def _fail_get_foundation_service(**kwargs):
        raise RuntimeError("service unavailable")

    monkeypatch.setattr(
        foundation_module,
        "get_foundation_service",
        _fail_get_foundation_service,
    )

    summary = ActuarialIntegrations.get_community_data_summary()
    assert summary == {"status": "not_available", "reason": "community_data_not_loaded"}

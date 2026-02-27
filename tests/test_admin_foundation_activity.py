import web_portal.api_extensions as api_extensions


def test_handle_admin_foundation_activity_aggregates_and_sorts(monkeypatch):
    monkeypatch.setattr(api_extensions, "FOUNDATION_SERVICE_AVAILABLE", True)

    activity_map = {
        "FND-1": [
            {
                "id": "ACT-1",
                "foundation_id": "FND-1",
                "activity_type": "foundation_created",
                "actor_id": "founder_1",
                "timestamp": "2026-01-01T00:00:00+00:00",
                "details": {},
            },
            {
                "id": "ACT-3",
                "foundation_id": "FND-1",
                "activity_type": "foundation_activated",
                "actor_id": "admin_1",
                "timestamp": "2026-01-03T00:00:00+00:00",
                "details": {},
            },
        ],
        "FND-2": [
            {
                "id": "ACT-2",
                "foundation_id": "FND-2",
                "activity_type": "foundation_created",
                "actor_id": "founder_2",
                "timestamp": "2026-01-02T00:00:00+00:00",
                "details": {},
            }
        ],
    }

    class _FakeService:
        @staticmethod
        def list_foundations(limit=1000):
            assert limit == 1000
            return [
                {"id": "FND-1", "name": "Alpha Foundation"},
                {"id": "FND-2", "name": "Beta Foundation"},
            ]

        @staticmethod
        def get_foundation_activities(foundation_id, limit=20):
            assert limit == 20
            return [dict(item) for item in activity_map[foundation_id]]

    monkeypatch.setattr(api_extensions, "get_foundation_service", lambda: _FakeService())

    status, payload = api_extensions.handle_admin_foundation_activity({"role": "admin"})

    assert status == 200
    assert payload["total"] == 3
    assert [item["id"] for item in payload["items"]] == ["ACT-3", "ACT-2", "ACT-1"]
    assert payload["items"][0]["foundation_name"] == "Alpha Foundation"
    assert payload["items"][1]["foundation_name"] == "Beta Foundation"


def test_handle_admin_foundation_activity_honors_default_and_explicit_limit(monkeypatch):
    monkeypatch.setattr(api_extensions, "FOUNDATION_SERVICE_AVAILABLE", True)

    class _FakeService:
        @staticmethod
        def list_foundations(limit=1000):
            return [{"id": "FND-1", "name": "Alpha Foundation"}]

        @staticmethod
        def get_foundation_activities(foundation_id, limit=20):
            assert foundation_id == "FND-1"
            return [
                {
                    "id": f"ACT-{idx:03d}",
                    "foundation_id": "FND-1",
                    "activity_type": "event",
                    "actor_id": "admin_1",
                    "timestamp": f"2026-01-{idx:02d}T00:00:00+00:00",
                    "details": {},
                }
                for idx in range(1, 61)
            ]

    monkeypatch.setattr(api_extensions, "get_foundation_service", lambda: _FakeService())

    default_status, default_payload = api_extensions.handle_admin_foundation_activity({"role": "admin"})
    explicit_status, explicit_payload = api_extensions.handle_admin_foundation_activity(
        {"role": "admin"},
        {"limit": ["10"]},
    )

    assert default_status == 200
    assert default_payload["total"] == 50
    assert explicit_status == 200
    assert explicit_payload["total"] == 10


def test_handle_admin_foundation_activity_requires_admin(monkeypatch):
    monkeypatch.setattr(api_extensions, "FOUNDATION_SERVICE_AVAILABLE", True)

    status, payload = api_extensions.handle_admin_foundation_activity({"role": "customer"})

    assert status == 403
    assert payload == {"error": "Admin access required"}

"""
Supplier offer media uploads through health wallet AI search.

Validates that:
- A supplier can attach photos and videos to a freshly created offer.
- Media is persisted on the offer with integrity metadata (sha256, size).
- Customers see the media (and can search by alt_text) via
  /api/marketplace/offerings (the data feed used by the dashboard
  Health Wallet AI search).
- Removing a media item updates the offer atomically.
"""

import base64
import hashlib
import json
import os
import threading
import time
from http.server import HTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import web_portal.server as portal


PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02"
    b"\xfe\xa75\x81\x84\x00\x00\x00\x00IEND\xaeB`\x82"
)
WEBM_BYTES = b"\x1aE\xdf\xa3PHINS-tiny-fake-webm-payload-for-test"


class _ServerThread(threading.Thread):
    def __init__(self, port: int):
        super().__init__(daemon=True)
        self.port = port
        self.httpd = HTTPServer(("127.0.0.1", port), portal.PortalHandler)

    def run(self):
        self.httpd.serve_forever()

    def stop(self):
        self.httpd.shutdown()


def _post(url: str, payload: dict, token: str | None = None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers)
    try:
        with urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8")), resp.status
    except HTTPError as e:
        body_txt = e.read().decode("utf-8", errors="ignore")
        e.body_txt = body_txt  # type: ignore[attr-defined]
        raise


def _get(url: str, token: str | None = None):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(url, headers=headers)
    with urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8")), resp.status


def _reset_state():
    with portal.STATE_LOCK:
        portal.SUPPLIERS.clear()
        portal.SUPPLIER_OFFERS.clear()
        portal.SUPPLIER_INVITATIONS.clear()
        portal.SUPPLY_CHAIN_LEDGER.clear()
    if getattr(portal, "supply_chain_service", None):
        portal.supply_chain_service.orders.clear()
        portal.supply_chain_service.pending_settlements.clear()
        portal.supply_chain_service.settlement_history.clear()
        portal.supply_chain_service.ledger_chain.clear()


def _bootstrap_supplier_with_offer(base: str):
    admin_login, status = _post(
        f"{base}/api/login",
        {"username": "admin", "password": "admin123"},
    )
    assert status == 200
    admin_token = admin_login["token"]

    invitation, status = _post(
        f"{base}/api/supply-chain/invitations",
        {
            "supplier_type": "clinic",
            "max_uses": 1,
            "expires_days": 30,
            "notes": "media + AI search test",
        },
        token=admin_token,
    )
    assert status == 201
    invitation_code = (invitation.get("invitation") or {}).get("code")
    assert invitation_code

    supplier_reg, status = _post(
        f"{base}/api/supply-chain/register",
        {
            "invitation_code": invitation_code,
            "company_name": "Visual Wellness Clinic",
            "contact_email": "visual-wellness@example.com",
            "contact_name": "Visual Wellness Contact",
            "supplier_type": "clinic",
            "password": "VisualWellness123!",
        },
    )
    assert status == 201
    supplier_id = supplier_reg.get("supplier_id")
    assert supplier_id

    _, status = _post(
        f"{base}/api/supply-chain/suppliers/{supplier_id}/approve",
        {"notes": "Approved for media + AI search test"},
        token=admin_token,
    )
    assert status == 200

    supplier_login, status = _post(
        f"{base}/api/supplier/login",
        {"email": "visual-wellness@example.com", "password": "VisualWellness123!"},
    )
    assert status == 200
    supplier_token = supplier_login["token"]

    offer_res, status = _post(
        f"{base}/api/supplier/offers/upsert",
        {
            "name": "Posture Therapy Session",
            "description": "Wellness service for posture correction",
            "item_type": "service",
            "category": "wellness",
            "price": 120.0,
            "currency": "USD",
            "wallet_compatible": ["health"],
        },
        token=supplier_token,
    )
    assert status in (200, 201)
    offer_id = offer_res.get("id")
    assert offer_id

    return supplier_id, supplier_token, admin_token, offer_id


def test_supplier_can_upload_photo_video_and_health_wallet_ai_search_exposes_them():
    _reset_state()

    port = 8175
    srv = _ServerThread(port)
    srv.start()
    time.sleep(0.5)
    base = f"http://127.0.0.1:{port}"

    try:
        supplier_id, supplier_token, admin_token, offer_id = _bootstrap_supplier_with_offer(base)

        photo_b64 = base64.b64encode(PNG_BYTES).decode("ascii")
        photo_sha = hashlib.sha256(PNG_BYTES).hexdigest()
        photo_resp, status = _post(
            f"{base}/api/supplier/offers/media/upload",
            {
                "offer_id": offer_id,
                "filename": "posture-room.png",
                "content_type": "image/png",
                "alt_text": "calm therapy room with ergonomic chair",
                "data": photo_b64,
            },
            token=supplier_token,
        )
        assert status == 201
        assert photo_resp["success"] is True
        photo_media = photo_resp["media"]
        assert photo_media["type"] == "image"
        assert photo_media["sha256"] == photo_sha
        assert photo_media["size_bytes"] == len(PNG_BYTES)
        assert photo_media["alt_text"] == "calm therapy room with ergonomic chair"
        assert photo_media["url"].startswith(f"/media-files/supplier-offers/{offer_id}/")

        # On-disk integrity: stored file's sha256 matches advertised one.
        rel_disk = photo_media["url"][len("/media-files/"):]
        disk_path = os.path.join(portal.MEDIA_STORAGE_DIR, rel_disk)
        assert os.path.isfile(disk_path)
        with open(disk_path, "rb") as fh:
            assert hashlib.sha256(fh.read()).hexdigest() == photo_sha

        # Idempotency: identical bytes are rejected with 409 (no duplicate writes).
        try:
            _post(
                f"{base}/api/supplier/offers/media/upload",
                {
                    "offer_id": offer_id,
                    "filename": "posture-room-copy.png",
                    "content_type": "image/png",
                    "data": photo_b64,
                },
                token=supplier_token,
            )
            raise AssertionError("Expected duplicate upload to be rejected")
        except HTTPError as e:
            assert e.code == 409

        video_b64 = base64.b64encode(WEBM_BYTES).decode("ascii")
        video_resp, status = _post(
            f"{base}/api/supplier/offers/media/upload",
            {
                "offer_id": offer_id,
                "filename": "posture-demo.webm",
                "content_type": "video/webm",
                "alt_text": "30 second demo of guided posture exercises",
                "data": video_b64,
            },
            token=supplier_token,
        )
        assert status == 201
        assert video_resp["media"]["type"] == "video"
        assert video_resp["media"]["sha256"] == hashlib.sha256(WEBM_BYTES).hexdigest()

        # Owner-side: supplier sees both media items on the offer.
        owner_view, status = _get(f"{base}/api/supplier/offers", token=supplier_token)
        assert status == 200
        owner_offer = next(o for o in owner_view["items"] if o["id"] == offer_id)
        assert isinstance(owner_offer.get("media"), list)
        assert len(owner_offer["media"]) == 2
        assert owner_offer["image_url"] == photo_media["url"]

        # Customer-side AI search feed: media is exposed and indexable.
        offerings, status = _get(
            f"{base}/api/marketplace/offerings?wallet=health",
        )
        assert status == 200
        item = next(i for i in offerings["items"] if i["id"] == offer_id)
        assert item["has_image"] is True
        assert item["has_video"] is True
        assert item["image_url"] == photo_media["url"]
        assert len(item["media"]) == 2
        media_ids = {m["id"] for m in item["media"]}
        assert photo_media["id"] in media_ids
        assert video_resp["media"]["id"] in media_ids

        # AI search alt_text indexing: searching by a phrase that lives ONLY in
        # the alt text should still return the offer.
        alt_results, status = _get(
            f"{base}/api/marketplace/offerings?wallet=health&search=ergonomic",
        )
        assert status == 200
        assert any(i["id"] == offer_id for i in alt_results["items"])

        # Audit / ledger trace: media uploads recorded as non-financial events.
        media_events = [
            tx for tx in portal.TRANSACTION_LEDGER.values()
            if (tx.get("type") or tx.get("tx_type")) == "supplier_offer_media_upload"
            and (tx.get("metadata") or {}).get("offer_id") == offer_id
        ]
        assert len(media_events) == 2

        # Removing one media item updates state atomically without disturbing
        # the surviving item.
        del_resp, status = _post(
            f"{base}/api/supplier/offers/media/delete",
            {"offer_id": offer_id, "media_id": video_resp["media"]["id"]},
            token=supplier_token,
        )
        assert status == 200
        assert del_resp["media_count"] == 1

        offerings_after, _ = _get(
            f"{base}/api/marketplace/offerings?wallet=health",
        )
        item_after = next(i for i in offerings_after["items"] if i["id"] == offer_id)
        assert item_after["has_video"] is False
        assert item_after["has_image"] is True
        assert len(item_after["media"]) == 1
        assert item_after["image_url"] == photo_media["url"]

        # Cross-supplier security: a different supplier may not upload media to
        # someone else's offer.
        invitation2, _ = _post(
            f"{base}/api/supply-chain/invitations",
            {"supplier_type": "clinic", "max_uses": 1, "expires_days": 30},
            token=admin_token,
        )
        invitation_code2 = (invitation2.get("invitation") or {}).get("code")
        supplier_reg2, _ = _post(
            f"{base}/api/supply-chain/register",
            {
                "invitation_code": invitation_code2,
                "company_name": "Other Clinic",
                "contact_email": "other-clinic@example.com",
                "contact_name": "Other Contact",
                "supplier_type": "clinic",
                "password": "OtherClinic123!",
            },
        )
        other_supplier_id = supplier_reg2.get("supplier_id")
        _post(
            f"{base}/api/supply-chain/suppliers/{other_supplier_id}/approve",
            {"notes": "Approved second supplier"},
            token=admin_token,
        )
        other_login, _ = _post(
            f"{base}/api/supplier/login",
            {"email": "other-clinic@example.com", "password": "OtherClinic123!"},
        )
        other_token = other_login["token"]

        try:
            _post(
                f"{base}/api/supplier/offers/media/upload",
                {
                    "offer_id": offer_id,
                    "filename": "intruder.png",
                    "content_type": "image/png",
                    "data": base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"intruder").decode("ascii"),
                },
                token=other_token,
            )
            raise AssertionError("Expected cross-supplier upload to be forbidden")
        except HTTPError as e:
            assert e.code == 403

    except HTTPError as e:
        body = getattr(e, "body_txt", None) or e.read().decode("utf-8", errors="ignore")
        raise AssertionError(f"Unexpected HTTPError {e.code}: {body}") from e
    finally:
        srv.stop()


def test_supplier_offer_media_rejects_unsupported_and_oversized_files():
    _reset_state()

    port = 8176
    srv = _ServerThread(port)
    srv.start()
    time.sleep(0.5)
    base = f"http://127.0.0.1:{port}"

    try:
        _, supplier_token, _, offer_id = _bootstrap_supplier_with_offer(base)

        # Unsupported extension is rejected with 400.
        bad_b64 = base64.b64encode(b"%PDF-1.4 fake").decode("ascii")
        try:
            _post(
                f"{base}/api/supplier/offers/media/upload",
                {
                    "offer_id": offer_id,
                    "filename": "doc.pdf",
                    "content_type": "application/pdf",
                    "data": bad_b64,
                },
                token=supplier_token,
            )
            raise AssertionError("Expected unsupported file type to be rejected")
        except HTTPError as e:
            assert e.code == 400

        # Oversized image is rejected. Either the global request-size guard or
        # the per-media-type guard returns 413; both responses close the
        # connection mid-upload, which can surface as URLError on the client.
        oversized = b"\x89PNG\r\n\x1a\n" + b"\0" * (11 * 1024 * 1024)
        rejected = False
        try:
            _post(
                f"{base}/api/supplier/offers/media/upload",
                {
                    "offer_id": offer_id,
                    "filename": "huge.png",
                    "content_type": "image/png",
                    "data": base64.b64encode(oversized).decode("ascii"),
                },
                token=supplier_token,
            )
        except HTTPError as e:
            assert e.code == 413
            rejected = True
        except (URLError, ConnectionError, OSError):
            rejected = True
        assert rejected, "Expected oversized image to be rejected"

        # Offer was not mutated by the failed uploads.
        owner_view, _ = _get(f"{base}/api/supplier/offers", token=supplier_token)
        owner_offer = next(o for o in owner_view["items"] if o["id"] == offer_id)
        assert owner_offer.get("media") in (None, [])
        assert not owner_offer.get("image_url")

    except HTTPError as e:
        body = getattr(e, "body_txt", None) or e.read().decode("utf-8", errors="ignore")
        raise AssertionError(f"Unexpected HTTPError {e.code}: {body}") from e
    finally:
        srv.stop()

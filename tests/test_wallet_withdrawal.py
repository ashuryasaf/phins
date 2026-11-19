"""Health-wallet withdrawal: chat intake, hold, sealed document, retention desk."""

import base64
import copy
import io
import json
import os
from datetime import timedelta
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from PIL import Image, ImageDraw

import web_portal.server as portal
from services import id_photo_crop
from services import wallet_withdrawal_service as withdrawals
from services.cashflow_unified_report import unified_cashflow_report
from services.wallet_withdrawal_service import WithdrawalError

CUSTOMER = "CUST-WDR-1"
OTHER = "CUST-WDR-2"
IBAN = "GB82 WEST 1234 5698 7654 32"


def _id_card(face_x=210):
    """A landscape card: photo panel with a face on the left, text on the right."""
    image = Image.new("RGB", (1000, 630), (232, 238, 246))
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 0, 1000, 90], fill=(11, 31, 58))
    for line in range(7):
        draw.rectangle([430, 150 + line * 45, 900, 165 + line * 45], fill=(60, 70, 90))
    draw.rectangle([face_x - 130, 130, face_x + 130, 470], fill=(205, 214, 226))
    draw.rectangle([face_x - 110, 350, face_x + 110, 470], fill=(40, 60, 110))
    draw.ellipse([face_x - 70, 160, face_x + 70, 340], fill=(224, 172, 140))
    draw.ellipse([face_x - 80, 140, face_x + 80, 210], fill=(52, 38, 30))
    return image


def _jpeg(image):
    out = io.BytesIO()
    image.save(out, "JPEG", quality=90)
    return out.getvalue()


def _png(image):
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


def _b64(blob):
    return base64.b64encode(blob).decode("ascii")


def _signature_url():
    image = Image.new("RGBA", (420, 140), (255, 255, 255, 0))
    draw = ImageDraw.Draw(image)
    draw.line([(20, 100), (120, 30), (200, 110), (300, 40), (400, 90)], fill=(10, 20, 60, 255), width=4)
    return "data:image/png;base64," + _b64(_png(image))


def _bank_document():
    image = Image.new("RGB", (600, 300), (255, 255, 255))
    ImageDraw.Draw(image).rectangle([40, 40, 560, 90], fill=(20, 40, 90))
    return _png(image)


@pytest.fixture
def books():
    portal.CUSTOMERS[CUSTOMER] = {
        "id": CUSTOMER, "name": "Dana Levi", "email": "dana@example.test",
        "phone": "+972500000001", "address": "1 Harbor Road, Haifa",
    }
    portal.CUSTOMERS[OTHER] = {"id": OTHER, "name": "Omer Katz", "email": "omer@example.test"}
    portal.HEALTH_WALLETS[CUSTOMER] = {
        "customer_id": CUSTOMER, "balance": 1000.00, "monthly_deposit": 0, "transactions": [],
    }
    portal.HEALTH_WALLETS[OTHER] = {
        "customer_id": OTHER, "balance": 50.00, "monthly_deposit": 0, "transactions": [],
    }
    yield
    portal.WALLET_WITHDRAWALS.clear()


def _complete_draft(amount=400.00, holder="Dana Levi"):
    view = withdrawals.open_request(CUSTOMER)
    wid = view["id"]
    withdrawals.answer(CUSTOMER, wid, "details", {"confirm": True})
    withdrawals.answer(CUSTOMER, wid, "amount", amount)
    withdrawals.answer(CUSTOMER, wid, "reason", {"code": "need_cash", "note": "A family expense"})
    withdrawals.answer(CUSTOMER, wid, "bank", {
        "holder": holder, "bank_name": "West Bank", "country": "GB", "account": IBAN, "swift": "WESTGB2L",
    })
    withdrawals.attach_document(CUSTOMER, wid, "id_document", "image/jpeg", _b64(_jpeg(_id_card())))
    source = withdrawals.photo_source(CUSTOMER, wid)
    withdrawals.confirm_photo(CUSTOMER, wid, source["box"])
    withdrawals.attach_document(CUSTOMER, wid, "bank_document", "image/png", _b64(_bank_document()))
    view = withdrawals.sign(CUSTOMER, wid, "Dana Levi", _signature_url())
    assert view["step"]["id"] == "review"
    return wid


def _filed(amount=400.00):
    wid = _complete_draft(amount)
    view = withdrawals.file_request(CUSTOMER, wid, client_ip="127.0.0.1")
    assert view["status"] == "held"
    return wid


def _nft_kinds(wid):
    """NFT types minted for one request. The NFT ledger is shared across tests."""
    return [
        token["transaction_type"] for token in portal.NFT_LEDGER.values()
        if (token.get("metadata") or {}).get("withdrawal_id") == wid
    ]


def _after_window(monkeypatch, days=5):
    real = withdrawals._now
    monkeypatch.setattr(withdrawals, "_now", lambda: real() + timedelta(days=days))


# --- portrait from an identity document ------------------------------------

def test_portrait_box_is_found_on_the_face_of_an_identity_card():
    image = id_photo_crop.load_image(_jpeg(_id_card()), "image/jpeg")
    proposal = id_photo_crop.propose_portrait_box(image)
    assert proposal["method"] == "skin_region"
    left, top, width, height = proposal["box"]
    face_x, face_y = 210 / 1000, 250 / 630
    assert left < face_x < left + width
    assert top < face_y < top + height
    assert left + width < 0.45
    jpeg, used = id_photo_crop.crop_portrait(image, proposal["box"])
    portrait = Image.open(io.BytesIO(jpeg))
    assert portrait.size == id_photo_crop.PORTRAIT_SIZE and portrait.format == "JPEG"
    red, green, blue = portrait.convert("RGB").getpixel((180, 200))
    assert red > 180 and red > blue + 40


def test_portrait_follows_the_face_to_the_other_side_of_the_card():
    image = id_photo_crop.load_image(_jpeg(_id_card(face_x=800).crop((380, 0, 1000, 630))), "image/jpeg")
    proposal = id_photo_crop.propose_portrait_box(image)
    assert proposal["method"] == "skin_region"
    assert proposal["box"][0] > 0.35


def test_a_card_photographed_on_a_wooden_desk_still_yields_the_holder_photo():
    # Wood passes a skin-tone test and surrounds the card, and the face runs
    # on into a neck. The box must stay on the head, inside the printed photo.
    card = _id_card()
    ImageDraw.Draw(card).rectangle([175, 330, 245, 420], fill=(224, 172, 140))
    desk = Image.new("RGB", (1400, 900), (120, 96, 74))
    desk.paste(card.rotate(2, expand=True, fillcolor=(120, 96, 74)), (180, 120))
    image = id_photo_crop.load_image(_jpeg(desk), "image/jpeg")
    proposal = id_photo_crop.propose_portrait_box(image)
    assert proposal["method"] == "skin_region"
    left, top, width, height = (proposal["box"][0] * 1400, proposal["box"][1] * 900,
                                proposal["box"][2] * 1400, proposal["box"][3] * 900)
    # The photo panel is 260 x 340 px at about (260..520, 250..600) on the desk.
    assert 240 <= left and left + width <= 545
    assert 235 <= top and top + height <= 640
    assert width < 300 and abs(width / height - id_photo_crop.PORTRAIT_ASPECT) < 0.02
    assert left < 390 < left + width and top < 370 < top + height


def test_a_document_with_no_face_gets_the_usual_card_position():
    blank = Image.new("RGB", (900, 600), (240, 240, 255))
    proposal = id_photo_crop.propose_portrait_box(blank)
    assert proposal["method"] == "default"
    left, top, width, height = proposal["box"]
    assert 0 <= left and left + width <= 1 and 0 <= top and top + height <= 1


def test_crop_box_is_validated():
    image = id_photo_crop.load_image(_jpeg(_id_card()), "image/jpeg")
    for bad in ([0, 0, 0.01, 0.5], [0, 0, 1], "box", [0, 0, float("nan"), 0.5]):
        with pytest.raises(id_photo_crop.PhotoCropError):
            id_photo_crop.crop_portrait(image, bad)
    _jpeg_bytes, used = id_photo_crop.crop_portrait(image, [0.9, 0.9, 0.5, 0.5])
    assert used[0] + used[2] <= 1.0001 and used[1] + used[3] <= 1.0001
    with pytest.raises(id_photo_crop.PhotoCropError):
        id_photo_crop.load_image(b"not an image", "image/jpeg")


# --- chat intake -------------------------------------------------------------

def test_chat_starts_from_the_customer_record_and_walks_every_step(books):
    view = withdrawals.open_request(CUSTOMER)
    assert view["status"] == "draft"
    assert view["step"]["id"] == "details"
    assert view["step"]["input"]["details"]["name"] == "Dana Levi"
    assert view["step"]["input"]["details"]["email"] == "dana@example.test"
    assert withdrawals.open_request(CUSTOMER)["id"] == view["id"]
    wid = view["id"]

    with pytest.raises(WithdrawalError) as err:
        withdrawals.answer(CUSTOMER, wid, "amount", 100)
    assert err.value.code == "step_out_of_order"

    view = withdrawals.answer(CUSTOMER, wid, "details", {"confirm": True})
    assert view["step"]["id"] == "amount" and view["step"]["input"]["max"] == 1000.00
    with pytest.raises(WithdrawalError) as err:
        withdrawals.answer(CUSTOMER, wid, "amount", 1000.01)
    assert err.value.code == "amount_exceeds_balance"
    view = withdrawals.answer(CUSTOMER, wid, "amount", 400)
    assert view["step"]["id"] == "reason"
    view = withdrawals.answer(CUSTOMER, wid, "reason", {"code": "need_cash"})
    assert view["step"]["id"] == "bank"

    with pytest.raises(WithdrawalError) as err:
        withdrawals.answer(CUSTOMER, wid, "bank", {
            "holder": "Dana Levi", "bank_name": "West Bank", "country": "GB", "account": "GB82WEST12345698765431",
        })
    assert err.value.code == "bank_account_invalid"
    view = withdrawals.answer(CUSTOMER, wid, "bank", {
        "holder": "Dana Levi", "bank_name": "West Bank", "country": "GB", "account": IBAN,
    })
    assert view["bank"]["account_last4"] == "5432" and view["bank"]["account_kind"] == "iban"
    assert "third_party_account" not in view["flags"]
    assert view["step"]["id"] == "id_document"

    with pytest.raises(WithdrawalError) as err:
        withdrawals.attach_document(CUSTOMER, wid, "id_document", "image/jpeg", _b64(b"GIF89a not allowed"))
    assert err.value.code == "file_type_refused"
    view = withdrawals.attach_document(CUSTOMER, wid, "id_document", "image/jpeg", _b64(_jpeg(_id_card())))
    assert view["step"]["id"] == "photo" and view["step"]["input"]["type"] == "photo_crop"

    source = withdrawals.photo_source(CUSTOMER, wid)
    assert source["preview"].startswith("data:image/jpeg;base64,") and source["method"] == "skin_region"
    view = withdrawals.confirm_photo(CUSTOMER, wid, source["box"])
    portrait = view["documents"]["portrait"]
    assert portrait["method"] == "skin_region"
    assert portrait["source"]["sha256"] == view["documents"]["id_document"]["sha256"]
    assert view["step"]["id"] == "bank_document"

    view = withdrawals.attach_document(CUSTOMER, wid, "bank_document", "image/png", _b64(_bank_document()))
    assert view["step"]["id"] == "signature"
    with pytest.raises(WithdrawalError) as err:
        blank = Image.new("RGBA", (300, 100), (255, 255, 255, 0))
        withdrawals.sign(CUSTOMER, wid, "Dana Levi", "data:image/png;base64," + _b64(_png(blank)))
    assert err.value.code == "signature_invalid"
    view = withdrawals.sign(CUSTOMER, wid, "Dana Levi", _signature_url())
    assert view["step"]["id"] == "review" and view["signature"]["signer_name"] == "Dana Levi"

    # Changing an answer after signing asks for the signature again.
    view = withdrawals.answer(CUSTOMER, wid, "amount", 300)
    assert view["step"]["id"] == "signature" and view["signature"] is None
    assert portal.HEALTH_WALLETS[CUSTOMER]["balance"] == 1000.00
    assert portal.CUSTOMERS[CUSTOMER]["name"] == "Dana Levi"


def test_a_customer_adjusted_box_and_a_second_document_are_both_accepted(books):
    view = withdrawals.open_request(CUSTOMER)
    wid = view["id"]
    withdrawals.answer(CUSTOMER, wid, "details", True)
    withdrawals.answer(CUSTOMER, wid, "amount", 50)
    withdrawals.answer(CUSTOMER, wid, "reason", "other")
    withdrawals.answer(CUSTOMER, wid, "bank", {
        "holder": "Dana Levi", "bank_name": "Local Bank", "country": "IL", "account": "123456", "branch": "701",
    })
    pdf = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
    view = withdrawals.attach_document(CUSTOMER, wid, "id_document", "application/pdf", _b64(pdf))
    if view["step"]["input"]["type"] == "upload":
        # No PDF renderer here: the chat asks for a picture of another document.
        assert view["step"]["input"]["kind"] == "photo_source"
        with pytest.raises(WithdrawalError) as err:
            withdrawals.photo_source(CUSTOMER, wid)
        assert err.value.code == "photo_source_missing"
        view = withdrawals.attach_document(CUSTOMER, wid, "photo_source", "image/jpeg", _b64(_jpeg(_id_card())))
        assert view["step"]["input"]["type"] == "photo_crop"
    view = withdrawals.confirm_photo(CUSTOMER, wid, [0.05, 0.2, 0.3, 0.6])
    assert view["documents"]["portrait"]["method"] == "customer_box"
    assert view["documents"]["portrait"]["box"] == [0.05, 0.2, 0.3, 0.6]


def test_another_holder_name_is_flagged_and_the_account_number_stays_in_the_vault(books):
    wid = _complete_draft(holder="Someone Else")
    record = portal.WALLET_WITHDRAWALS[wid]
    assert "third_party_account" in record["flags"]
    stored = json.dumps({key: value for key, value in record.items() if key != "bank_vault"}, default=str)
    account = IBAN.replace(" ", "")
    assert account not in stored
    assert account not in record["bank_vault"]
    assert withdrawals.decrypt_bank_account(record) == account
    assert account not in json.dumps(withdrawals.customer_view(record), default=str)
    assert account not in json.dumps(withdrawals.staff_view(record), default=str)


# --- filing ------------------------------------------------------------------

def test_filing_holds_the_money_anchors_the_signature_and_mints_the_wallet_nft(books):
    wid = _filed(400.00)
    record = portal.WALLET_WITHDRAWALS[wid]
    wallet = portal.HEALTH_WALLETS[CUSTOMER]
    assert wallet["balance"] == 600.00
    hold = wallet["transactions"][-1]
    assert hold["type"] == "withdrawal_hold" and hold["amount"] == 400.00 and hold["withdrawal_id"] == wid

    seal = record["seal"]
    assert withdrawals.seal_intact(record)
    token = portal.NFT_LEDGER[seal["nft_token_id"]]
    assert token["transaction_type"] == "wallet_withdrawal_request"
    assert token["owner_id"] == CUSTOMER
    assert token["metadata"]["withdrawal_id"] == wid
    assert token["metadata"]["record_sha256"] == seal["record_sha256"]
    assert token["metadata"]["portrait_sha256"] == record["documents"]["portrait"]["sha256"]
    assert hold["nft_token_id"] == seal["nft_token_id"]

    anchors = portal._legal_doc_signatures_for(seal["legal_doc_instance"])
    assert len(anchors) == 1
    assert anchors[0]["document_hash"] == seal["record_sha256"]
    assert anchors[0]["signer_name"] == "Dana Levi"

    assert record["retention"]["flag"] is True
    assert record["retention"]["window_days"] == withdrawals.retention_days() == 3
    sealed = record["sealed"]
    assert sealed["wallet"] == {"balance_before": 1000.00, "balance_after": 600.00}
    assert "national_id" not in sealed["holder"]
    with pytest.raises(WithdrawalError) as err:
        withdrawals.answer(CUSTOMER, wid, "amount", 10)
    assert err.value.code == "already_filed"
    with pytest.raises(WithdrawalError) as err:
        withdrawals.open_request(OTHER) and withdrawals.get_request(OTHER, wid)
    assert err.value.status == 404


def test_the_unified_document_carries_the_details_the_portrait_and_the_signature(books):
    wid = _filed(400.00)
    record = portal.WALLET_WITHDRAWALS[wid]
    document = withdrawals.render_document_for_customer(CUSTOMER, wid)
    assert "phins-doc-banner" in document
    assert "Dana Levi" in document and "$400.00" in document and "West Bank" in document
    assert "•••• 5432" in document and IBAN.replace(" ", "") not in document
    assert record["seal"]["nft_token_id"] in document
    assert record["seal"]["record_sha256"] in document
    portrait = withdrawals._read_file(record["documents"]["portrait"])
    assert base64.b64encode(portrait).decode("ascii") in document
    signature = withdrawals._read_file({
        "document_id": record["signature"]["document_id"], "sha256": record["signature"]["sha256"],
    })
    assert base64.b64encode(signature).decode("ascii") in document
    assert "A family expense" in document
    # An IBAN carries no branch on this request; an empty row is left out.
    assert "<th>SWIFT</th>" in document and "<th>Branch</th>" not in document
    with pytest.raises(WithdrawalError):
        withdrawals.render_document_for_customer(OTHER, wid)


def test_a_changed_answer_is_said_as_a_change_and_asks_for_a_new_signature(books):
    wid = _complete_draft(400.00)
    view = withdrawals.answer(CUSTOMER, wid, "amount", {"amount": 250})
    assert view["amount"] == 250.00
    assert view["messages"][-2] == {**view["messages"][-2], "from": "user", "text": "Changed the amount: $250.00"}
    assert view["messages"][-1]["text"].startswith("Updated. ")
    assert view["step"]["id"] == "signature" and view["signature"] is None
    with pytest.raises(WithdrawalError):
        withdrawals.file_request(CUSTOMER, wid, client_ip="127.0.0.1")


def test_the_return_bar_is_hidden_inside_a_frame():
    # The chat and the retention bar show the document in a frame with their
    # own Close button; the document's bar sets display and must yield.
    root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web_portal", "static")
    rule = ".phins-doc-return[hidden]"
    with open(os.path.join(root, "phins-document.css"), encoding="utf-8") as handle:
        assert rule in handle.read()
    with open(os.path.join(root, "phins-doc-return.js"), encoding="utf-8") as handle:
        assert rule in handle.read()


def test_the_pages_carry_the_withdrawal_entry_points():
    root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web_portal", "static")

    def page(name):
        with open(os.path.join(root, name), encoding="utf-8") as handle:
            return handle.read()

    assert 'href="/wallet-withdraw-chat.html"' in page("dashboard.html")
    assert '<script src="/wallet-withdraw-chat.js"></script>' in page("wallet-withdraw-chat.html")
    management = page("customer-management.html")
    assert 'id="withdrawal-retention-bar"' in management
    assert '<script src="/withdrawal-retention-bar.js"></script>' in management
    from security import access_hierarchy

    assert "/wallet-withdraw-chat.html" in access_hierarchy.CUSTOMER_PRIVATE_PAGES


def test_a_changed_record_is_withheld_and_cannot_be_paid(books, monkeypatch):
    wid = _filed(400.00)
    record = portal.WALLET_WITHDRAWALS[wid]
    record["sealed"]["amount"] = 4000.00
    with pytest.raises(WithdrawalError) as err:
        withdrawals.render_document(wid)
    assert err.value.code == "seal_mismatch"
    _after_window(monkeypatch)
    with pytest.raises(WithdrawalError) as err:
        withdrawals.release(wid, actor="admin", role="admin")
    assert err.value.code == "seal_mismatch"
    with pytest.raises(WithdrawalError) as err:
        withdrawals.cancel(CUSTOMER, wid)
    assert err.value.code == "seal_mismatch"
    assert portal.HEALTH_WALLETS[CUSTOMER]["balance"] == 600.00
    assert record["status"] == "held"


def test_a_failed_seal_returns_the_hold(books, monkeypatch):
    wid = _complete_draft(400.00)
    ledger_before = set(portal.NFT_LEDGER)

    def refuse(*_args, **_kwargs):
        raise RuntimeError("ledger offline")

    monkeypatch.setattr(portal, "record_transaction", refuse)
    with pytest.raises(WithdrawalError) as err:
        withdrawals.file_request(CUSTOMER, wid)
    assert err.value.status == 503
    record = portal.WALLET_WITHDRAWALS[wid]
    wallet = portal.HEALTH_WALLETS[CUSTOMER]
    assert wallet["balance"] == 1000.00
    assert not [row for row in wallet["transactions"] if row["type"] == "withdrawal_hold"]
    assert record["status"] == "draft" and "seal" not in record
    assert set(portal.NFT_LEDGER) == ledger_before
    monkeypatch.undo()
    assert withdrawals.file_request(CUSTOMER, wid)["status"] == "held"
    assert wallet["balance"] == 600.00


def test_filing_is_refused_when_the_wallet_no_longer_covers_the_amount(books):
    wid = _complete_draft(400.00)
    portal.HEALTH_WALLETS[CUSTOMER]["balance"] = 100.00
    with pytest.raises(WithdrawalError) as err:
        withdrawals.file_request(CUSTOMER, wid)
    assert err.value.code == "amount_exceeds_balance"
    assert portal.HEALTH_WALLETS[CUSTOMER]["balance"] == 100.00
    assert portal.WALLET_WITHDRAWALS[wid]["status"] == "draft"


# --- reversal and the retention desk ----------------------------------------

def test_the_customer_cancels_and_the_whole_hold_returns(books):
    wid = _filed(400.00)
    view = withdrawals.cancel(CUSTOMER, wid, "Changed my mind")
    assert view["status"] == "reversed"
    wallet = portal.HEALTH_WALLETS[CUSTOMER]
    assert wallet["balance"] == 1000.00
    assert wallet["transactions"][-1]["type"] == "withdrawal_reversal"
    kinds = _nft_kinds(wid)
    assert kinds.count("wallet_withdrawal_request") == 1 and kinds.count("wallet_withdrawal_reversed") == 1
    with pytest.raises(WithdrawalError):
        withdrawals.cancel(CUSTOMER, wid)
    assert wallet["balance"] == 1000.00
    assert withdrawals.open_request(CUSTOMER)["id"] != wid


def test_retention_methods_are_recorded_and_only_the_customer_moves_money(books, monkeypatch):
    wid = _filed(400.00)
    board = withdrawals.retention_board()
    assert board["flagged"] == 1 and board["held_amount"] == 400.00
    assert {method["id"] for method in board["methods"]} >= {
        "outreach_call", "outreach_message", "offer_keep_in_wallet", "offer_partial",
        "offer_move_to_savings", "offer_premium_credit", "extend_hold", "escalate",
    }
    row = board["items"][0]
    assert row["customer_name"] == "Dana Levi" and row["reason"]["code"] == "need_cash"
    assert row["suggested_method"] == "offer_partial"

    with pytest.raises(WithdrawalError) as err:
        withdrawals.record_retention(wid, actor="rel", role="claims", method="outreach_call")
    assert err.value.code == "note_required"
    withdrawals.record_retention(wid, actor="rel", role="claims", method="outreach_call", note="Left a voicemail.")
    with pytest.raises(WithdrawalError) as err:
        withdrawals.record_retention(wid, actor="rel", role="claims", method="offer_partial", keep_amount=400)
    assert err.value.code == "keep_amount_invalid"
    view = withdrawals.record_retention(
        wid, actor="rel", role="claims", method="offer_partial", keep_amount=250,
        message="Keep $250 for next month's pharmacy order?",
    )
    assert view["retention"]["offer"]["status"] == "open"
    offered = view["retention"]["attempts"][-1]
    assert offered["outcome"] == "offered" and offered["keep_amount"] == 250
    assert offered["note"] == "Keep $250 for next month's pharmacy order?"
    assert portal.HEALTH_WALLETS[CUSTOMER]["balance"] == 600.00
    with pytest.raises(WithdrawalError) as err:
        withdrawals.record_retention(wid, actor="rel", role="claims", method="offer_keep_in_wallet")
    assert err.value.code == "offer_open"

    customer = withdrawals.get_request(CUSTOMER, wid)
    assert customer["offer"]["keep_amount"] == 250.00
    assert "retention" not in customer
    with pytest.raises(WithdrawalError):
        withdrawals.accept_offer(OTHER, wid, customer["offer"]["offer_id"])
    accepted = withdrawals.accept_offer(CUSTOMER, wid, customer["offer"]["offer_id"])
    assert accepted["status"] == "held" and accepted["amount"] == 150.00
    assert accepted["amendments"][-1]["kind"] == "reduced"
    assert portal.HEALTH_WALLETS[CUSTOMER]["balance"] == 850.00
    reduced = withdrawals.render_document(wid)
    assert '<div class="wdr-amount">$150.00 USD</div>' in reduced
    assert "Filed and signed for <strong>$400.00</strong>" in reduced

    view = withdrawals.record_retention(wid, actor="rel", role="claims", method="extend_hold", days=2, note="Customer asked for time")
    assert view["window"]["extended"] is True
    with pytest.raises(WithdrawalError) as err:
        withdrawals.record_retention(wid, actor="rel", role="claims", method="extend_hold", days=1, note="again")
    assert err.value.code == "already_extended"
    staff = withdrawals.get_for_staff(wid)
    assert [item["method"] for item in staff["retention"]["attempts"]] == [
        "outreach_call", "offer_partial", "offer_partial", "extend_hold",
    ]
    assert staff["retention"]["trail_intact"] is True

    with pytest.raises(WithdrawalError) as err:
        withdrawals.release(wid, actor="acct", role="accountant")
    assert err.value.code == "window_open"
    _after_window(monkeypatch, days=6)
    paid = withdrawals.release(wid, actor="acct", role="accountant", reference="WIRE-77")
    assert paid["status"] == "paid_out" and paid["amount"] == 150.00
    assert portal.HEALTH_WALLETS[CUSTOMER]["balance"] == 850.00
    kinds = _nft_kinds(wid)
    assert kinds.count("wallet_withdrawal_reduced") == 1 and kinds.count("wallet_withdrawal_paid") == 1
    with pytest.raises(WithdrawalError):
        withdrawals.release(wid, actor="acct", role="accountant")
    document = withdrawals.render_document(wid)
    assert "Paid out" in document and "$250.00 returned to the wallet" in document

    report = unified_cashflow_report(
        wallets=portal.HEALTH_WALLETS, withdrawals=list(portal.WALLET_WITHDRAWALS.values()),
    )
    assert report["withdrawals"]["paid_out"] == 150.00
    assert report["withdrawals"]["returned_to_wallet"] == 250.00
    check = next(row for row in report["integrity"]["checks"] if row["id"] == "withdrawals_tie")
    assert check["ok"] is True


def test_keep_in_wallet_offer_reverses_the_request_when_accepted(books):
    wid = _filed(400.00)
    view = withdrawals.record_retention(wid, actor="rel", role="admin", method="offer_move_to_savings",
                                        message="Savings earn on this balance.")
    offer_id = view["retention"]["offer"]["offer_id"]
    declined = withdrawals.decline_offer(CUSTOMER, wid, offer_id)
    assert declined["offer"] is None and declined["status"] == "held"
    view = withdrawals.record_retention(wid, actor="rel", role="admin", method="offer_keep_in_wallet")
    accepted = withdrawals.accept_offer(CUSTOMER, wid, view["retention"]["offer"]["offer_id"])
    assert accepted["status"] == "reversed"
    assert portal.HEALTH_WALLETS[CUSTOMER]["balance"] == 1000.00
    assert withdrawals.retention_board()["flagged"] == 0


def test_staff_decline_returns_the_hold_to_the_same_wallet(books):
    wid = _filed(400.00)
    with pytest.raises(WithdrawalError):
        withdrawals.decline(wid, actor="acct", role="accountant", reason="")
    view = withdrawals.decline(wid, actor="acct", role="accountant", reason="Bank document is not in the customer's name")
    assert view["status"] == "declined"
    assert portal.HEALTH_WALLETS[CUSTOMER]["balance"] == 1000.00
    assert portal.HEALTH_WALLETS[OTHER]["balance"] == 50.00


def test_a_withdrawal_is_not_read_as_missing_savings(books, monkeypatch):
    before = portal._premium_savings_already_landed(CUSTOMER)
    assert before == 1000.00
    wid = _filed(400.00)
    assert portal._premium_savings_already_landed(CUSTOMER) == before
    _after_window(monkeypatch)
    withdrawals.release(wid, actor="admin", role="admin")
    assert portal._premium_savings_already_landed(CUSTOMER) == before
    monitoring = portal.build_cashflow_monitoring()
    row = next(item for item in monitoring["customers"] if item["customer_id"] == CUSTOMER)
    assert row["live"]["withdrawn"] == 400.00 and row["live"]["health_wallet"] == 600.00


def test_withdrawals_survive_the_ledger_snapshot(books):
    wid = _filed(400.00)
    snapshot = copy.deepcopy(portal.WALLET_WITHDRAWALS[wid])
    assert json.loads(json.dumps(snapshot, default=str))["seal"]["record_sha256"] == snapshot["seal"]["record_sha256"]
    restored = json.loads(json.dumps(snapshot, default=str))
    assert withdrawals.seal_intact(restored)
    assert withdrawals._attempts_intact(restored) and withdrawals._amendments_intact(restored)


# --- HTTP surface ------------------------------------------------------------

def _http(method, path, token, body=None):
    base = os.environ.get("TEST_BASE_URL", "http://127.0.0.1:8000")
    data = json.dumps(body or {}).encode("utf-8") if method == "POST" else None
    request = Request(
        base + path, data=data, method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8") or "{}")


@pytest.fixture
def sessions(books):
    init_set = getattr(portal, "_TEST_PORTS_INITIALIZED", None)
    if isinstance(init_set, set):
        init_set.add(int(os.environ.get("TEST_PORT", "8000")))
    tokens = {
        "phins_wdr-cust": {"username": "dana@example.test", "role": "customer", "customer_id": CUSTOMER},
        "phins_wdr-other": {"username": "omer@example.test", "role": "customer", "customer_id": OTHER},
        "phins_wdr-claims": {"username": "claims_adjuster", "role": "claims"},
        "phins_wdr-acct": {"username": "accountant", "role": "accountant"},
        "phins_wdr-admin": {"username": "admin", "role": "admin"},
    }
    for token, session in tokens.items():
        portal.SESSIONS[token] = dict(session, expires="2099-01-01T00:00:00")
    yield
    for token in tokens:
        portal.SESSIONS.pop(token, None)


def test_http_chat_files_a_withdrawal_and_the_desk_works_it(sessions, monkeypatch):
    base = "/api/customer/wallet-withdrawals"
    status, body = _http("POST", base, "phins_wdr-cust")
    assert status == 200, body
    wid = body["withdrawal"]["id"]
    steps = [
        ("answer", {"step": "details", "value": {"confirm": True}}),
        ("answer", {"step": "amount", "value": 400}),
        ("answer", {"step": "reason", "value": {"code": "not_using"}}),
        ("answer", {"step": "bank", "value": {
            "holder": "Dana Levi", "bank_name": "West Bank", "country": "GB", "account": IBAN}}),
        ("upload", {"kind": "id_document", "mime_type": "image/jpeg", "data": _b64(_jpeg(_id_card()))}),
    ]
    for action, payload in steps:
        status, body = _http("POST", f"{base}/{wid}/{action}", "phins_wdr-cust", payload)
        assert status == 200, body
    status, source = _http("GET", f"{base}/{wid}/photo-source", "phins_wdr-cust")
    assert status == 200 and source["method"] == "skin_region"
    for action, payload in [
        ("photo", {"box": source["box"]}),
        ("upload", {"kind": "bank_document", "mime_type": "image/png", "data": _b64(_bank_document())}),
        ("sign", {"signer_name": "Dana Levi", "image_data": _signature_url()}),
    ]:
        status, body = _http("POST", f"{base}/{wid}/{action}", "phins_wdr-cust", payload)
        assert status == 200, body
    status, body = _http("POST", f"{base}/{wid}/file", "phins_wdr-cust", {})
    assert status == 400 and body["code"] == "confirm_required"
    status, body = _http("POST", f"{base}/{wid}/file", "phins_wdr-cust", {"confirm": True})
    assert status == 200 and body["withdrawal"]["status"] == "held", body
    assert body["withdrawal"]["nft_token_id"]
    assert portal.HEALTH_WALLETS[CUSTOMER]["balance"] == 600.00

    status, body = _http("GET", f"{base}/{wid}/document", "phins_wdr-cust")
    assert status == 200 and "Health wallet withdrawal" in body["html"]
    status, body = _http("GET", base, "phins_wdr-cust")
    assert status == 200 and body["open"]["id"] == wid

    # Another customer cannot see it, and staff cannot act as the customer.
    assert _http("GET", f"{base}/{wid}", "phins_wdr-other")[0] == 404
    assert _http("GET", f"{base}/{wid}/document", "phins_wdr-other")[0] == 404
    assert _http("POST", f"{base}/{wid}/cancel", "phins_wdr-other")[0] == 404
    assert _http("POST", f"{base}/{wid}/cancel", "phins_wdr-admin")[0] == 403
    assert _http("POST", base, "phins_wdr-claims")[0] == 403
    assert portal.HEALTH_WALLETS[CUSTOMER]["balance"] == 600.00

    desk = "/api/admin/wallet-withdrawals"
    assert _http("GET", desk, "phins_wdr-cust")[0] == 403
    status, board = _http("GET", desk, "phins_wdr-claims")
    assert status == 200 and board["flagged"] == 1 and board["can_pay_out"] is False
    assert board["items"][0]["id"] == wid
    status, body = _http("POST", f"{desk}/{wid}/retention", "phins_wdr-claims",
                         {"method": "offer_partial", "keep_amount": 100, "message": "Keep $100 for prescriptions?"})
    assert status == 200 and body["withdrawal"]["retention"]["offer"]["status"] == "open", body
    assert _http("POST", f"{desk}/{wid}/retention", "phins_wdr-cust", {"method": "note", "note": "x"})[0] == 403
    assert _http("POST", f"{desk}/{wid}/release", "phins_wdr-claims")[0] == 403
    assert _http("GET", f"{desk}/{wid}/bank", "phins_wdr-claims")[0] == 403
    status, bank = _http("GET", f"{desk}/{wid}/bank", "phins_wdr-acct")
    assert status == 200 and bank["bank"]["account"] == IBAN.replace(" ", "")
    status, body = _http("POST", f"{desk}/{wid}/release", "phins_wdr-acct")
    assert status == 409 and body["code"] == "window_open"

    status, body = _http("GET", f"{base}/{wid}", "phins_wdr-cust")
    offer_id = body["withdrawal"]["offer"]["offer_id"]
    status, body = _http("POST", f"{base}/{wid}/offer", "phins_wdr-cust", {"offer_id": offer_id, "decision": "accept"})
    assert status == 200 and body["withdrawal"]["amount"] == 300.00
    assert portal.HEALTH_WALLETS[CUSTOMER]["balance"] == 700.00

    _after_window(monkeypatch)
    status, body = _http("POST", f"{desk}/{wid}/release", "phins_wdr-acct", {"reference": "WIRE-1"})
    assert status == 200 and body["withdrawal"]["status"] == "paid_out", body
    status, body = _http("GET", f"{desk}/{wid}/document", "phins_wdr-claims")
    assert status == 200 and "Paid out" in body["html"]
    status, body = _http("GET", "/api/admin/cashflow/unified-report", "phins_wdr-admin")
    assert status == 200 and body["report"]["withdrawals"]["paid_out"] == 300.00
    assert next(c for c in body["report"]["integrity"]["checks"] if c["id"] == "withdrawals_tie")["ok"] is True


def test_http_requires_a_session(books):
    init_set = getattr(portal, "_TEST_PORTS_INITIALIZED", None)
    if isinstance(init_set, set):
        init_set.add(int(os.environ.get("TEST_PORT", "8000")))
    for method, path in (
        ("GET", "/api/customer/wallet-withdrawals"),
        ("POST", "/api/customer/wallet-withdrawals"),
        ("GET", "/api/admin/wallet-withdrawals"),
    ):
        status, body = _http(method, path, "phins_not-a-session")
        assert status in (401, 403) and "error" in body

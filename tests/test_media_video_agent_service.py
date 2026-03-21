#!/usr/bin/env python3
"""Tests for the media video/avatar agent service."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.media_video_agent_service import MediaVideoAgentService


def _sample_media_assets():
    return {
        "media-img-1": {
            "id": "media-img-1",
            "name": "welcome-avatar.png",
            "type": "image",
            "format": "image/png",
            "url": "https://cdn.phins.ai/assets/welcome-avatar.png",
            "uploaded_at": "2026-03-20T10:00:00Z",
            "source": "upload",
        }
    }


def _sample_campaign():
    return {
        "campaign": {
            "campaign_id": "MKT-20260320120000",
            "scope": {
                "vertical": "insurance",
                "objective": "growth",
                "persona": "families",
                "region": "global",
            },
            "value_messaging": {
                "headline": "AI + BI growth engine for insurance teams",
                "subheadline": "Turn campaign data into disciplined media execution",
            },
            "ai_video_blueprints": [
                {"title": "Welcome to PHINS", "format": "Vertical short video"},
                {"title": "Underwriting Agent Demo", "format": "Interview + motion graphics"},
            ],
        },
        "integrity": {
            "algorithm": "hmac-sha256",
            "signature": "placeholder",
            "verified": True,
        },
    }


def test_generate_photo_to_video_packet_is_signed_and_uses_campaign_context():
    svc = MediaVideoAgentService(secret_key="unit-test-secret")
    state = svc.ensure_state({})
    latest_campaign = _sample_campaign()

    generated = svc.generate_job(
        state=state,
        media_assets=_sample_media_assets(),
        latest_campaign=latest_campaign,
        campaign_verified=True,
        provider="kling_official",
        generation_mode="photo_to_video",
        agent_role="welcome",
        source_image_asset_id="media-img-1",
        audio_url="",
        aspect_ratio="16:9",
        duration=5,
        language="en",
        company_name="PHINS",
        tagline="Personal Health Insurance & Savings",
        custom_instructions="Keep it premium and reassuring.",
        cta="Visit phins.ai to explore the platform.",
        generated_by="tester",
    )

    assert generated["integrity"]["verified"] is True
    packet = generated["packet"]
    assert packet["campaign_context"]["campaign_id"] == "MKT-20260320120000"
    assert packet["source_media"]["source_image"]["id"] == "media-img-1"
    assert packet["provider_request"]["dispatch_ready"] is True
    assert "Welcome to PHINS" in packet["script_bundle"]["voiceover_script"]


def test_avatar_packet_blocks_dispatch_when_audio_missing_for_aimlapi():
    svc = MediaVideoAgentService(secret_key="unit-test-secret")
    state = svc.ensure_state({})

    generated = svc.generate_job(
        state=state,
        media_assets=_sample_media_assets(),
        latest_campaign=_sample_campaign(),
        campaign_verified=True,
        provider="aimlapi_kling",
        generation_mode="avatar",
        agent_role="marketing_sales_helper",
        source_image_asset_id="media-img-1",
        audio_url="",
        aspect_ratio="9:16",
        duration=6,
        language="en",
        company_name="PHINS",
        tagline="Personal Health Insurance & Savings",
        custom_instructions="Optimize for AI + BI Marketing & Sales Agent style.",
        cta="Book a guided PHINS walkthrough.",
        generated_by="tester",
    )

    provider_request = generated["packet"]["provider_request"]
    assert provider_request["dispatch_ready"] is False
    assert "audio URL" in provider_request["readiness_note"]


def test_build_prompt_assets_returns_text_and_json_assets():
    svc = MediaVideoAgentService(secret_key="unit-test-secret")
    state = svc.ensure_state({})
    generated = svc.generate_job(
        state=state,
        media_assets=_sample_media_assets(),
        latest_campaign=_sample_campaign(),
        campaign_verified=True,
        provider="kling_official",
        generation_mode="photo_to_video",
        agent_role="underwriting_claims",
        source_image_asset_id="media-img-1",
        audio_url="",
        aspect_ratio="16:9",
        duration=5,
        language="en",
        company_name="PHINS",
        tagline="Personal Health Insurance & Savings",
        custom_instructions="Explain underwriting and claims clearly.",
        cta="See how PHINS improves underwriting control.",
        generated_by="tester",
    )

    assets = svc.build_prompt_assets(generated)
    assert len(assets) == 2
    brief_types = {item["brief_type"] for item in assets}
    assert "video_agent_prompt" in brief_types
    assert "video_agent_payload" in brief_types


def test_submit_job_rejects_invalid_signature_before_dispatch():
    svc = MediaVideoAgentService(secret_key="unit-test-secret")
    state = svc.ensure_state({})
    generated = svc.generate_job(
        state=state,
        media_assets=_sample_media_assets(),
        latest_campaign=_sample_campaign(),
        campaign_verified=True,
        provider="kling_official",
        generation_mode="photo_to_video",
        agent_role="product_services",
        source_image_asset_id="media-img-1",
        audio_url="",
        aspect_ratio="16:9",
        duration=5,
        language="en",
        company_name="PHINS",
        tagline="Personal Health Insurance & Savings",
        custom_instructions="Stay product-focused.",
        cta="Discover PHINS products and services.",
        generated_by="tester",
    )

    result = svc.submit_job(packet=generated["packet"], signature="tampered-signature")
    assert result["success"] is False
    assert result["submitted"] is False
    assert "signature" in result["error"].lower()

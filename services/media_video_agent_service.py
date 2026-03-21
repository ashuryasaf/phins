#!/usr/bin/env python3
"""Signed video and avatar agent workflow for PHINS media generation."""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _safe_text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class MediaVideoAgentService:
    """Builds signed prompt packs and provider requests for media AI engines."""

    _SUPPORTED_AGENT_ROLES: Dict[str, Dict[str, Any]] = {
        "welcome": {
            "label": "Welcome to PHINS",
            "headline": "Welcome to PHINS",
            "intent": "Introduce PHINS, its mission, and why the platform exists.",
            "voice_style": "Warm, premium, confident, and reassuring",
            "storyboard": [
                "Open with the PHINS brand and a calm premium avatar welcome.",
                "Explain PHINS as AI plus BI infrastructure for insurance, health, savings, and service orchestration.",
                "Show trust signals, data integrity controls, and product clarity.",
                "Close with a simple invitation to explore the platform.",
            ],
        },
        "product_services": {
            "label": "Product & Services Explainer",
            "headline": "PHINS Products and Services",
            "intent": "Explain the platform's insurance, health, claims, savings, and support capabilities.",
            "voice_style": "Clear, structured, evidence-based",
            "storyboard": [
                "Start with one customer need and show how PHINS unifies protection and services.",
                "Walk through underwriting, health wallet, care support, and claims orchestration.",
                "Highlight decision support, automation, and advisor visibility.",
                "End with a concise value summary and action prompt.",
            ],
        },
        "underwriting_claims": {
            "label": "Underwriting & Claims Agent",
            "headline": "PHINS Underwriting and Claims Agent",
            "intent": "Explain how PHINS supports underwriting accuracy and transparent claims routing.",
            "voice_style": "Professional, precise, trusted operations tone",
            "storyboard": [
                "Frame the problem: slow underwriting and inconsistent claims workflows.",
                "Show PHINS ingesting structured inputs and decision evidence.",
                "Explain claim triage, audit trail, and human-review checkpoints.",
                "Close with why disciplined automation improves both customer experience and insurer control.",
            ],
        },
        "marketing_sales_helper": {
            "label": "Marketing & Sales Helper",
            "headline": "PHINS Marketing and Sales Helper",
            "intent": "Explain how PHINS uses AI plus BI to improve sales conversations and campaign precision.",
            "voice_style": "Energetic, commercial, intelligent",
            "storyboard": [
                "Open on wasted acquisition spend and fragmented campaign decisions.",
                "Show PHINS translating BI signals into sales playbooks and video-ready stories.",
                "Highlight tailored personas, campaign discipline, and reusable content agents.",
                "End with a call to deploy the PHINS growth copilot.",
            ],
        },
    }

    _PROVIDER_PRESETS: Dict[str, Dict[str, Any]] = {
        "kling_official": {
            "label": "Kling Official",
            "supports": ["photo_to_video"],
            "base_url": "https://klingapi.com",
            "image_to_video_path": "/v1/videos/image2video",
            "avatar_path": "",
            "api_key_env": "KLING_API_KEY",
            "model": "pro-image-to-video",
            "avatar_model": "",
        },
        "aimlapi_kling": {
            "label": "Kling via AIMLAPI",
            "supports": ["photo_to_video", "avatar"],
            "base_url": "https://api.aimlapi.com",
            "image_to_video_path": "/v2/video/generations",
            "avatar_path": "/v2/video/generations",
            "api_key_env": "AIMLAPI_API_KEY",
            "model": "kling-video/v2.1/pro/image-to-video",
            "avatar_model": "klingai/avatar-pro",
        },
        "custom": {
            "label": "Custom Provider",
            "supports": ["photo_to_video", "avatar"],
            "base_url": "",
            "image_to_video_path": "",
            "avatar_path": "",
            "api_key_env": "",
            "model": "",
            "avatar_model": "",
        },
    }

    def __init__(self, secret_key: Optional[str] = None):
        self._secret_key = secret_key or os.getenv("SECRET_KEY", "phins-media-agent-secret")

    def provider_presets(self) -> Dict[str, Dict[str, Any]]:
        return copy.deepcopy(self._PROVIDER_PRESETS)

    def role_catalog(self) -> List[Dict[str, str]]:
        return [
            {"id": role_id, "label": config["label"]}
            for role_id, config in self._SUPPORTED_AGENT_ROLES.items()
        ]

    def ensure_state(self, state: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        source = state if isinstance(state, dict) else {}
        providers = {}
        incoming_providers = source.get("providers", {})
        if not isinstance(incoming_providers, dict):
            incoming_providers = {}

        for provider_id, preset in self._PROVIDER_PRESETS.items():
            provider_state = incoming_providers.get(provider_id, {})
            if not isinstance(provider_state, dict):
                provider_state = {}
            merged = copy.deepcopy(preset)
            for key in [
                "base_url",
                "image_to_video_path",
                "avatar_path",
                "api_key_env",
                "model",
                "avatar_model",
            ]:
                if key in provider_state:
                    merged[key] = _safe_text(provider_state.get(key), merged.get(key, ""))
            providers[provider_id] = merged

        jobs = source.get("jobs", [])
        if not isinstance(jobs, list):
            jobs = []

        latest_job = source.get("latest_job")
        if latest_job is not None and not isinstance(latest_job, dict):
            latest_job = None

        defaults = source.get("defaults", {})
        if not isinstance(defaults, dict):
            defaults = {}

        return {
            "selected_provider": _safe_text(source.get("selected_provider"), "kling_official") or "kling_official",
            "defaults": {
                "generation_mode": _safe_text(defaults.get("generation_mode"), "photo_to_video") or "photo_to_video",
                "agent_role": _safe_text(defaults.get("agent_role"), "welcome") or "welcome",
                "aspect_ratio": _safe_text(defaults.get("aspect_ratio"), "16:9") or "16:9",
                "duration": _safe_int(defaults.get("duration"), 5) or 5,
                "language": _safe_text(defaults.get("language"), "en") or "en",
                "create_media_assets": bool(defaults.get("create_media_assets", True)),
                "use_latest_campaign": bool(defaults.get("use_latest_campaign", True)),
            },
            "providers": providers,
            "jobs": jobs[-40:],
            "latest_job": latest_job or (jobs[-1] if jobs else None),
            "updated_at": _safe_text(source.get("updated_at")),
            "updated_by": _safe_text(source.get("updated_by")),
        }

    def merge_state_update(
        self,
        current_state: Optional[Dict[str, Any]],
        incoming_state: Dict[str, Any],
        updated_by: str,
    ) -> Dict[str, Any]:
        merged = self.ensure_state(current_state)
        incoming = incoming_state if isinstance(incoming_state, dict) else {}

        selected_provider = _safe_text(incoming.get("selected_provider"), merged["selected_provider"])
        if selected_provider in self._PROVIDER_PRESETS:
            merged["selected_provider"] = selected_provider

        defaults = incoming.get("defaults", {})
        if isinstance(defaults, dict):
            for key in ["generation_mode", "agent_role", "aspect_ratio", "language"]:
                if key in defaults:
                    merged["defaults"][key] = _safe_text(defaults.get(key), merged["defaults"].get(key, ""))
            if "duration" in defaults:
                merged["defaults"]["duration"] = max(3, min(15, _safe_int(defaults.get("duration"), 5)))
            for key in ["create_media_assets", "use_latest_campaign"]:
                if key in defaults:
                    merged["defaults"][key] = bool(defaults.get(key))

        providers = incoming.get("providers", {})
        if isinstance(providers, dict):
            for provider_id, values in providers.items():
                if provider_id not in merged["providers"] or not isinstance(values, dict):
                    continue
                for key in [
                    "base_url",
                    "image_to_video_path",
                    "avatar_path",
                    "api_key_env",
                    "model",
                    "avatar_model",
                ]:
                    if key in values:
                        merged["providers"][provider_id][key] = _safe_text(
                            values.get(key), merged["providers"][provider_id].get(key, "")
                        )

        merged["updated_at"] = datetime.now(timezone.utc).isoformat()
        merged["updated_by"] = updated_by or "admin"
        return merged

    def _payload_signature(self, payload: Dict[str, Any]) -> str:
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hmac.new(
            self._secret_key.encode("utf-8"),
            serialized.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def verify_payload(self, payload: Dict[str, Any], signature: str) -> bool:
        expected = self._payload_signature(payload)
        return hmac.compare_digest(expected, _safe_text(signature))

    def _resolve_media_asset(self, media_assets: Dict[str, Dict[str, Any]], asset_id: str) -> Dict[str, Any]:
        if not asset_id:
            return {}
        asset = media_assets.get(asset_id)
        if not isinstance(asset, dict):
            return {}
        return {
            "id": asset.get("id", asset_id),
            "name": asset.get("name", ""),
            "type": asset.get("type", ""),
            "format": asset.get("format", ""),
            "url": asset.get("url") or asset.get("data") or "",
            "thumbnail": asset.get("thumbnail", ""),
            "uploaded_at": asset.get("uploaded_at", ""),
            "source": asset.get("source", ""),
        }

    def _campaign_context(
        self,
        latest_campaign: Optional[Dict[str, Any]],
        campaign_verified: bool,
    ) -> Dict[str, Any]:
        if not isinstance(latest_campaign, dict):
            return {
                "used_latest_campaign": False,
                "campaign_id": "",
                "verified": False,
                "headline": "",
                "vertical": "",
                "objective": "",
                "persona": "",
                "region": "",
                "sample_video_titles": [],
            }

        campaign = latest_campaign.get("campaign", {})
        scope = campaign.get("scope", {}) if isinstance(campaign, dict) else {}
        value_messaging = campaign.get("value_messaging", {}) if isinstance(campaign, dict) else {}
        blueprints = campaign.get("ai_video_blueprints", []) if isinstance(campaign, dict) else []
        if not isinstance(blueprints, list):
            blueprints = []
        return {
            "used_latest_campaign": True,
            "campaign_id": _safe_text(campaign.get("campaign_id")),
            "verified": bool(campaign_verified),
            "headline": _safe_text(value_messaging.get("headline")),
            "subheadline": _safe_text(value_messaging.get("subheadline")),
            "vertical": _safe_text(scope.get("vertical")),
            "objective": _safe_text(scope.get("objective")),
            "persona": _safe_text(scope.get("persona")),
            "region": _safe_text(scope.get("region")),
            "sample_video_titles": [
                _safe_text(item.get("title"))
                for item in blueprints[:3]
                if isinstance(item, dict) and _safe_text(item.get("title"))
            ],
        }

    def _build_script_bundle(
        self,
        *,
        agent_role: str,
        generation_mode: str,
        campaign_context: Dict[str, Any],
        company_name: str,
        tagline: str,
        aspect_ratio: str,
        duration: int,
        language: str,
        custom_instructions: str,
        cta: str,
    ) -> Dict[str, Any]:
        role = self._SUPPORTED_AGENT_ROLES.get(agent_role) or self._SUPPORTED_AGENT_ROLES["welcome"]
        company_label = _safe_text(company_name, "PHINS") or "PHINS"
        tagline_text = _safe_text(tagline, "Personal Health Insurance & Savings")
        vertical = campaign_context.get("vertical") or "insurance"
        region = campaign_context.get("region") or "global"
        persona = campaign_context.get("persona") or "families"
        campaign_hint = campaign_context.get("headline") or f"{company_label} AI + BI growth narrative"
        call_to_action = _safe_text(cta, "Visit phins.ai and request a guided walkthrough.")
        motion_frame = "photo-to-video" if generation_mode == "photo_to_video" else "avatar-led explainer"

        voiceover_script = (
            f"Welcome to {company_label}. {tagline_text}. "
            f"This {motion_frame} introduces the {role['label']} for {persona} audiences in {region}. "
            f"The core message is simple: {role['intent']} "
            f"Campaign optimization cue: {campaign_hint}. "
            f"PHINS combines underwriting discipline, claims transparency, and AI plus BI orchestration. "
            f"{call_to_action}"
        )

        on_screen_text = [
            role["headline"],
            campaign_hint,
            "AI + BI orchestration",
            "Underwriting, claims, service, and growth agents",
            call_to_action,
        ]

        prompt = (
            f"Create a premium {duration}-second {aspect_ratio} {motion_frame} video for {company_label}. "
            f"Agent role: {role['label']}. Tone: {role['voice_style']}. "
            f"Audience: {persona}. Vertical: {vertical}. Region: {region}. Language: {language}. "
            f"Visual objective: trustworthy insurance-tech presentation with clean motion, modern healthcare-finance design, "
            f"legible typography, and premium lighting. "
            f"Storyboard priority: {' | '.join(role['storyboard'])}. "
            f"Voiceover script: {voiceover_script} "
            f"CTA: {call_to_action}. "
            f"Additional instructions: {custom_instructions or 'Preserve data-integrity and compliance-first tone.'}"
        )

        negative_prompt = (
            "No fabricated statistics, no unreadable text, no extra brand logos, no distorted hands or faces, "
            "no medical gore, no chaotic transitions, no compliance-breaking promises, no low-resolution artifacts."
        )

        return {
            "title": role["headline"],
            "role_label": role["label"],
            "voice_style": role["voice_style"],
            "language": language,
            "duration_seconds": duration,
            "aspect_ratio": aspect_ratio,
            "voiceover_script": voiceover_script,
            "on_screen_text": on_screen_text,
            "storyboard": role["storyboard"],
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "call_to_action": call_to_action,
        }

    def _provider_request(
        self,
        *,
        state: Dict[str, Any],
        provider: str,
        generation_mode: str,
        script_bundle: Dict[str, Any],
        source_image: Dict[str, Any],
        audio_url: str,
    ) -> Dict[str, Any]:
        providers = state.get("providers", {})
        provider_config = providers.get(provider, {})
        provider_label = provider_config.get("label", provider)
        supports = provider_config.get("supports", [])
        image_url = _safe_text(source_image.get("url"))
        dispatch_ready = True
        readiness_note = ""

        if generation_mode not in supports:
            dispatch_ready = False
            readiness_note = f"{provider_label} is not configured for {generation_mode} dispatch."

        if generation_mode == "photo_to_video" and not image_url:
            dispatch_ready = False
            readiness_note = "Photo-to-video requires a source image asset with a usable URL or stored data."

        if generation_mode == "avatar" and provider == "kling_official":
            dispatch_ready = False
            readiness_note = "Official Kling preset is currently configured only for image-to-video. Use AIMLAPI Kling or custom provider for avatar dispatch."

        payload: Dict[str, Any]
        endpoint_path = ""
        if provider == "kling_official":
            endpoint_path = _safe_text(provider_config.get("image_to_video_path"))
            payload = {
                "prompt": script_bundle["prompt"],
                "image": image_url,
                "duration": script_bundle["duration_seconds"],
                "aspect_ratio": script_bundle["aspect_ratio"],
                "negative_prompt": script_bundle["negative_prompt"],
            }
        elif provider == "aimlapi_kling":
            if generation_mode == "avatar":
                endpoint_path = _safe_text(provider_config.get("avatar_path"))
                payload = {
                    "model": _safe_text(provider_config.get("avatar_model"), "klingai/avatar-pro"),
                    "image_url": image_url,
                    "prompt": script_bundle["prompt"],
                    "audio_url": _safe_text(audio_url),
                }
                if not payload["audio_url"]:
                    dispatch_ready = False
                    readiness_note = "Avatar dispatch requires an audio URL for the AIMLAPI Kling preset."
            else:
                endpoint_path = _safe_text(provider_config.get("image_to_video_path"))
                payload = {
                    "model": _safe_text(provider_config.get("model"), "kling-video/v2.1/pro/image-to-video"),
                    "image_url": image_url,
                    "prompt": script_bundle["prompt"],
                    "negative_prompt": script_bundle["negative_prompt"],
                    "duration": script_bundle["duration_seconds"],
                    "aspect_ratio": script_bundle["aspect_ratio"],
                }
        else:
            endpoint_path = _safe_text(
                provider_config.get(
                    "avatar_path" if generation_mode == "avatar" else "image_to_video_path"
                )
            )
            payload = {
                "mode": generation_mode,
                "prompt": script_bundle["prompt"],
                "negative_prompt": script_bundle["negative_prompt"],
                "image_url": image_url,
                "audio_url": _safe_text(audio_url),
                "duration": script_bundle["duration_seconds"],
                "aspect_ratio": script_bundle["aspect_ratio"],
                "title": script_bundle["title"],
            }
            if not endpoint_path:
                dispatch_ready = False
                readiness_note = "Custom provider requires an endpoint path before dispatch."

        if not _safe_text(provider_config.get("base_url")):
            dispatch_ready = False
            readiness_note = readiness_note or f"{provider_label} has no base URL configured."

        return {
            "provider": provider,
            "provider_label": provider_label,
            "generation_mode": generation_mode,
            "base_url": _safe_text(provider_config.get("base_url")),
            "endpoint_path": endpoint_path,
            "api_key_env": _safe_text(provider_config.get("api_key_env")),
            "dispatch_ready": dispatch_ready,
            "readiness_note": readiness_note,
            "payload": payload,
        }

    def generate_job(
        self,
        *,
        state: Dict[str, Any],
        media_assets: Dict[str, Dict[str, Any]],
        latest_campaign: Optional[Dict[str, Any]],
        campaign_verified: bool,
        provider: str,
        generation_mode: str,
        agent_role: str,
        source_image_asset_id: str,
        audio_url: str,
        aspect_ratio: str,
        duration: int,
        language: str,
        company_name: str,
        tagline: str,
        custom_instructions: str,
        cta: str,
        generated_by: str,
    ) -> Dict[str, Any]:
        generation_mode = _safe_text(generation_mode, "photo_to_video") or "photo_to_video"
        provider = _safe_text(provider, state.get("selected_provider", "kling_official")) or "kling_official"
        agent_role = _safe_text(agent_role, "welcome") or "welcome"
        aspect_ratio = _safe_text(aspect_ratio, "16:9") or "16:9"
        duration = max(3, min(15, _safe_int(duration, 5)))
        language = _safe_text(language, "en") or "en"

        source_image = self._resolve_media_asset(media_assets, _safe_text(source_image_asset_id))
        campaign_context = self._campaign_context(latest_campaign, campaign_verified)
        packet_id = f"VAG-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"

        script_bundle = self._build_script_bundle(
            agent_role=agent_role,
            generation_mode=generation_mode,
            campaign_context=campaign_context,
            company_name=company_name,
            tagline=tagline,
            aspect_ratio=aspect_ratio,
            duration=duration,
            language=language,
            custom_instructions=custom_instructions,
            cta=cta,
        )
        provider_request = self._provider_request(
            state=state,
            provider=provider,
            generation_mode=generation_mode,
            script_bundle=script_bundle,
            source_image=source_image,
            audio_url=audio_url,
        )

        payload = {
            "packet_id": packet_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "generated_by": generated_by or "admin",
            "agent_role": agent_role,
            "generation_mode": generation_mode,
            "brand_context": {
                "company_name": _safe_text(company_name, "PHINS") or "PHINS",
                "tagline": _safe_text(tagline, "Personal Health Insurance & Savings"),
            },
            "campaign_context": campaign_context,
            "source_media": {
                "source_image": source_image,
                "audio_url": _safe_text(audio_url),
            },
            "script_bundle": script_bundle,
            "provider_request": provider_request,
            "data_integrity": {
                "campaign_signature_verified": bool(campaign_verified),
                "source_image_asset_id": source_image.get("id", ""),
                "provider_payload_generated": True,
                "notes": [
                    "Prompt packet is HMAC signed before submission.",
                    "Provider dispatch is blocked when required source media or env credentials are missing.",
                    "Latest AI + BI campaign context is referenced but not mutated.",
                ],
            },
        }
        signature = self._payload_signature(payload)
        return {
            "packet": payload,
            "integrity": {
                "algorithm": "hmac-sha256",
                "signature": signature,
                "verified": self.verify_payload(payload, signature),
            },
        }

    def build_prompt_assets(self, packet: Dict[str, Any]) -> List[Dict[str, Any]]:
        payload = packet.get("packet", {}) if "packet" in packet else packet
        packet_id = _safe_text(payload.get("packet_id"), "VAG-UNKNOWN")
        script_bundle = payload.get("script_bundle", {}) if isinstance(payload, dict) else {}
        provider_request = payload.get("provider_request", {}) if isinstance(payload, dict) else {}
        storyboard = script_bundle.get("storyboard", [])
        storyboard_text = "\n".join(f"- {item}" for item in storyboard)
        prompt_text = (
            f"Packet: {packet_id}\n"
            f"Agent Role: {_safe_text(payload.get('agent_role'))}\n"
            f"Generation Mode: {_safe_text(payload.get('generation_mode'))}\n"
            f"Title: {_safe_text(script_bundle.get('title'))}\n"
            f"Voice Style: {_safe_text(script_bundle.get('voice_style'))}\n"
            f"Voiceover Script:\n{_safe_text(script_bundle.get('voiceover_script'))}\n\n"
            f"Prompt:\n{_safe_text(script_bundle.get('prompt'))}\n\n"
            f"Negative Prompt:\n{_safe_text(script_bundle.get('negative_prompt'))}\n\n"
            f"Storyboard:\n{storyboard_text}\n"
        )
        payload_json = json.dumps(provider_request.get("payload", {}), indent=2, ensure_ascii=True)
        return [
            {
                "name": f"{packet_id} Prompt Pack.txt",
                "content": prompt_text,
                "brief_type": "video_agent_prompt",
                "format": "text/plain",
            },
            {
                "name": f"{packet_id} Provider Payload.json",
                "content": payload_json,
                "brief_type": "video_agent_payload",
                "format": "application/json",
            },
        ]

    def store_job(
        self,
        state: Optional[Dict[str, Any]],
        *,
        packet_envelope: Dict[str, Any],
        submission: Optional[Dict[str, Any]] = None,
        generated_media_asset_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Persist a generated or submitted job in state."""
        normalized = self.ensure_state(state)
        packet = packet_envelope.get("packet", {}) if isinstance(packet_envelope, dict) else {}
        integrity = packet_envelope.get("integrity", {}) if isinstance(packet_envelope, dict) else {}
        job_entry = {
            "packet": packet,
            "integrity": integrity,
            "submission": submission or {},
            "generated_media_asset_ids": list(generated_media_asset_ids or []),
            "generated_media_asset_id": (generated_media_asset_ids or [""])[0] if generated_media_asset_ids else "",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        jobs = list(normalized.get("jobs", []))
        packet_id = _safe_text(packet.get("packet_id"))
        if packet_id:
            jobs = [
                existing for existing in jobs
                if _safe_text((existing or {}).get("packet", {}).get("packet_id")) != packet_id
            ]
        jobs.append(job_entry)
        normalized["jobs"] = jobs[-40:]
        normalized["latest_job"] = job_entry
        return normalized

    def submit_job(self, *, packet: Dict[str, Any], signature: str) -> Dict[str, Any]:
        if not self.verify_payload(packet, signature):
            return {
                "success": False,
                "error": "Packet signature verification failed.",
                "submitted": False,
            }

        provider_request = packet.get("provider_request", {})
        if not isinstance(provider_request, dict):
            return {
                "success": False,
                "error": "Provider request payload missing.",
                "submitted": False,
            }

        if not provider_request.get("dispatch_ready"):
            return {
                "success": False,
                "error": provider_request.get("readiness_note") or "Provider request is not dispatch-ready.",
                "submitted": False,
            }

        base_url = _safe_text(provider_request.get("base_url"))
        endpoint_path = _safe_text(provider_request.get("endpoint_path"))
        api_key_env = _safe_text(provider_request.get("api_key_env"))
        api_key = os.getenv(api_key_env) if api_key_env else ""

        if not api_key:
            return {
                "success": False,
                "error": f"Missing provider credential. Set environment variable {api_key_env or 'API_KEY_ENV'}.",
                "submitted": False,
            }

        if not base_url or not endpoint_path:
            return {
                "success": False,
                "error": "Provider base URL or endpoint path is missing.",
                "submitted": False,
            }

        request_url = urllib.parse.urljoin(base_url.rstrip("/") + "/", endpoint_path.lstrip("/"))
        encoded_payload = json.dumps(provider_request.get("payload", {}), ensure_ascii=True).encode("utf-8")
        request = urllib.request.Request(
            request_url,
            data=encoded_payload,
            method="POST",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )

        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                raw = response.read().decode("utf-8", errors="replace")
                parsed = json.loads(raw) if raw else {}
                return {
                    "success": True,
                    "submitted": True,
                    "submitted_at": datetime.now(timezone.utc).isoformat(),
                    "provider": provider_request.get("provider"),
                    "provider_label": provider_request.get("provider_label"),
                    "endpoint": request_url,
                    "provider_response": parsed,
                    "provider_job_id": self._extract_job_id(parsed),
                    "output_url": self._extract_output_url(parsed),
                }
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            return {
                "success": False,
                "submitted": False,
                "provider": provider_request.get("provider"),
                "endpoint": request_url,
                "status_code": exc.code,
                "error": body or str(exc),
            }
        except urllib.error.URLError as exc:
            return {
                "success": False,
                "submitted": False,
                "provider": provider_request.get("provider"),
                "endpoint": request_url,
                "error": str(exc.reason),
            }

    def _extract_job_id(self, payload: Any) -> str:
        if not isinstance(payload, dict):
            return ""
        for key in ["job_id", "task_id", "id", "request_id"]:
            value = payload.get(key)
            if value:
                return _safe_text(value)
        data = payload.get("data")
        if isinstance(data, dict):
            for key in ["job_id", "task_id", "id", "request_id"]:
                value = data.get(key)
                if value:
                    return _safe_text(value)
        return ""

    def _extract_output_url(self, payload: Any) -> str:
        if not isinstance(payload, dict):
            return ""
        for key in ["video_url", "output_url", "url"]:
            value = payload.get(key)
            if value:
                return _safe_text(value)
        data = payload.get("data")
        if isinstance(data, dict):
            for key in ["video_url", "output_url", "url"]:
                value = data.get(key)
                if value:
                    return _safe_text(value)
        if isinstance(data, list) and data:
            first = data[0]
            if isinstance(first, dict):
                for key in ["video_url", "output_url", "url"]:
                    value = first.get(key)
                    if value:
                        return _safe_text(value)
        return ""


_media_video_agent_service: Optional[MediaVideoAgentService] = None


def get_media_video_agent_service(secret_key: Optional[str] = None) -> MediaVideoAgentService:
    """Get or create singleton media video agent service."""
    global _media_video_agent_service
    if _media_video_agent_service is None:
        _media_video_agent_service = MediaVideoAgentService(secret_key=secret_key)
    return _media_video_agent_service

import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional


@dataclass
class DeliveryConnectorResult:
    success: bool
    provider: str
    status: str
    shipment_id: Optional[str] = None
    tracking_number: Optional[str] = None
    tracking_url: Optional[str] = None
    eta_days: Optional[int] = None
    details: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "provider": self.provider,
            "status": self.status,
            "shipment_id": self.shipment_id,
            "tracking_number": self.tracking_number,
            "tracking_url": self.tracking_url,
            "eta_days": self.eta_days,
            "details": self.details or {},
            "error": self.error,
        }


class BaseDeliveryConnector:
    provider_name = "generic"
    required_env_var = ""
    tracking_base_url = ""

    def is_configured(self) -> bool:
        return bool(self.required_env_var and os.environ.get(self.required_env_var))

    def create_shipment(self, payload: Dict[str, Any]) -> DeliveryConnectorResult:
        if not self.is_configured():
            return DeliveryConnectorResult(
                success=False,
                provider=self.provider_name,
                status="unconfigured",
                error=f"{self.provider_name} connector is not configured",
                details={"required_env_var": self.required_env_var},
            )

        now = datetime.now(timezone.utc)
        shipment_id = f"{self.provider_name.upper()}-SHIP-{now.strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(3).upper()}"
        tracking_number = f"{self.provider_name.upper()}-{secrets.token_hex(5).upper()}"
        tracking_url = f"{self.tracking_base_url}{tracking_number}" if self.tracking_base_url else None
        eta_days = int(payload.get("eta_days") or 1)
        return DeliveryConnectorResult(
            success=True,
            provider=self.provider_name,
            status="shipment_created",
            shipment_id=shipment_id,
            tracking_number=tracking_number,
            tracking_url=tracking_url,
            eta_days=max(0, eta_days),
            details={
                "mode": payload.get("delivery_method"),
                "destination_city": ((payload.get("delivery_location") or {}).get("city")),
                "created_at": now.isoformat(),
            },
        )


class WoltDeliveryConnector(BaseDeliveryConnector):
    provider_name = "wolt"
    required_env_var = "WOLT_API_KEY"
    tracking_base_url = "https://track.wolt.example/order/"


class UPSDeliveryConnector(BaseDeliveryConnector):
    provider_name = "ups"
    required_env_var = "UPS_API_KEY"
    tracking_base_url = "https://www.ups.com/track?tracknum="


class FedExDeliveryConnector(BaseDeliveryConnector):
    provider_name = "fedex"
    required_env_var = "FEDEX_API_KEY"
    tracking_base_url = "https://www.fedex.com/fedextrack/?trknbr="


class DeliveryProviderConnectorError(ValueError):
    """Raised when a requested delivery provider is unsupported."""


def get_delivery_connector(provider: str) -> BaseDeliveryConnector:
    normalized = str(provider or "").strip().lower()
    mapping = {
        "wolt": WoltDeliveryConnector,
        "ups": UPSDeliveryConnector,
        "fedex": FedExDeliveryConnector,
    }
    connector_cls = mapping.get(normalized)
    if not connector_cls:
        raise DeliveryProviderConnectorError(f"Unsupported delivery provider: {provider}")
    return connector_cls()


def create_delivery_provider_connector(provider: str) -> BaseDeliveryConnector:
    """Backward-compatible factory name used by the supply-chain service."""
    return get_delivery_connector(provider)

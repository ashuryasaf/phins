"""Connector stubs for external authority validations.

These are minimal, test-friendly connector classes that simulate
interactions with external authorities (national insurance, credit card
issuers, health authorities). They are intentionally simple: each exposes
`validate(...)` which returns a dict with `status` and `details`.

In production these would be implemented to call real APIs with secure
credentials, retries, rate-limiting, logging, and error handling.
"""
from dataclasses import dataclass
from typing import Dict
import time


@dataclass
class ValidationResult:
    status: str
    details: Dict


class BaseConnector:
    """Base class with a common interface."""
    def validate(self, **kwargs) -> ValidationResult:
        raise NotImplementedError()


class NationalInsuranceConnector(BaseConnector):
    def validate(self, national_id: str, dob: str = None) -> ValidationResult:
        # Simulate network latency
        time.sleep(0.1)
        # Demo rules: valid if length between 6 and 14 and starts with numeric
        ok = national_id and national_id[0].isdigit() and 6 <= len(national_id) <= 14
        return ValidationResult(status='valid' if ok else 'invalid', details={'national_id': national_id})


class CreditCardIssuerConnector(BaseConnector):
    def validate(self, card_number: str, expiry: str = None) -> ValidationResult:
        time.sleep(0.08)
        # Very simple Luhn-like check (not real): sum of digits mod 10 == 0
        digits = [int(c) for c in card_number if c.isdigit()]
        ok = len(digits) >= 12 and sum(digits) % 10 == 0
        return ValidationResult(status='valid' if ok else 'invalid', details={'card_number_masked': ('*' * (len(digits)-4)) + ''.join(str(d) for d in digits[-4:]) if digits else None})


class HealthAuthorityConnector(BaseConnector):
    def validate(self, patient_id: str, name: str = None) -> ValidationResult:
        time.sleep(0.12)
        # Demo: treat IDs starting with 'H' as valid
        ok = patient_id and patient_id.upper().startswith('H')
        return ValidationResult(status='valid' if ok else 'invalid', details={'patient_id': patient_id, 'name': name})


def demo_validators():
    nis = NationalInsuranceConnector()
    cci = CreditCardIssuerConnector()
    ha = HealthAuthorityConnector()
    return {
        'ni': nis.validate(national_id='123456789'),
        'card': cci.validate(card_number='4111111111111111'),
        'health': ha.validate(patient_id='H-00123', name='Jane Doe'),
    }

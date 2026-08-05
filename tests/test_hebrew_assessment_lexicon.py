"""
Unit tests for the Hebrew assessment lexicon.

Pins longest-match, negation handling, language detection, structured-field
extraction, and the Hebrew → English canonical mapping that feeds the shared
risk scoring / decision-loop pipeline.
"""

from __future__ import annotations

import pytest

from services.hebrew_assessment_lexicon import (
    contains_hebrew,
    detect_document_language,
    extract_hebrew_matches,
    hebrew_ratio,
    smoking_status_from_hebrew,
    is_truthy_smoking_hebrew,
)


class TestLanguageDetection:
    def test_contains_hebrew(self):
        assert contains_hebrew("Diagnosis: סוכרת") is True
        assert contains_hebrew("diabetes only") is False
        assert contains_hebrew("") is False

    def test_hebrew_ratio_and_detect(self):
        he_doc = "אבחנה: סוכרת. תרופה: מטפורמין. פרמיה: ₪1,250"
        assert hebrew_ratio(he_doc) > 0.5
        assert detect_document_language(he_doc) == "he"

        mixed = "Customer John. אבחנה: סוכרת. Premium 100 USD."
        assert detect_document_language(mixed) in ("he", "mixed")

        assert detect_document_language("diabetes hypertension asthma") == "en"


class TestMedicalExtraction:
    def test_diabetes_and_hypertension(self):
        text = "אבחנות: סוכרת סוג 2, יתר לחץ דם. תרופות: מטפורמין, אמלודיפין."
        matches = extract_hebrew_matches(text)
        by_type = {}
        for m in matches:
            by_type.setdefault(m.fact_type, set()).add(m.canonical)
        assert "diabetes" in by_type["medical_condition"]
        assert "hypertension" in by_type["medical_condition"]
        assert "metformin" in by_type["medication"]
        assert "amlodipine" in by_type["medication"]
        # Canonical English — not the Hebrew surface form.
        diabetes = next(m for m in matches if m.canonical == "diabetes")
        assert diabetes.metadata["lang"] == "he"
        assert "סוכרת" in diabetes.raw_match

    def test_longest_match_prefers_specific_phrase(self):
        text = "המטופל סובל מיתר לחץ דם כרוני."
        matches = extract_hebrew_matches(text)
        medical = [m.canonical for m in matches if m.fact_type == "medical_condition"]
        assert "hypertension" in medical
        # Must not also invent a bare unrelated condition from a substring.
        assert medical.count("hypertension") == 1

    def test_negation_skips_clinical_match(self):
        text = "אין סוכרת. ללא אסתמה. שלילי ל-HIV."
        matches = extract_hebrew_matches(text)
        medical = {m.canonical for m in matches if m.fact_type == "medical_condition"}
        assert "diabetes" not in medical
        assert "asthma" not in medical
        assert "hiv" not in medical
        assert "aids" not in medical

    def test_positive_still_extracted_alongside_negation(self):
        text = "אין אסתמה. אבחנה: סוכרת."
        matches = extract_hebrew_matches(text)
        medical = {m.canonical for m in matches if m.fact_type == "medical_condition"}
        assert "diabetes" in medical
        assert "asthma" not in medical


class TestInsuranceAndSavings:
    def test_structured_premium_and_sum_insured(self):
        text = (
            "מספר פוליסה: 12345678\n"
            "פרמיה חודשית: ₪1,250.50\n"
            "סכום ביטוח: ₪1,000,000\n"
            "חברה: מגדל"
        )
        matches = extract_hebrew_matches(text)
        by_label = {m.canonical: m for m in matches if m.fact_type == "insurance"}
        assert "policy_number" in by_label
        assert by_label["policy_number"].metadata.get("policy_number") == "12345678"
        assert by_label["premium"].amount == pytest.approx(1250.50)
        assert by_label["sum insured"].amount == pytest.approx(1000000.0)
        assert by_label["provider"].metadata.get("provider") == "מגדל"

    def test_pension_and_balance(self):
        text = "קרן פנסיה מנורה. יתרה: ₪85,000. צבירה: 120000"
        matches = extract_hebrew_matches(text)
        savings = {m.canonical: m for m in matches if m.fact_type == "savings"}
        assert "pension" in savings
        assert savings["balance"].amount == pytest.approx(85000.0)


class TestRiskSmokingVitals:
    def test_high_risk_and_smoker(self):
        text = "הערכת סיכון: סיכון גבוה. סטטוס עישון: מעשן."
        matches = extract_hebrew_matches(text)
        risk = {m.canonical for m in matches if m.fact_type == "risk_indicator"}
        assert "high risk" in risk
        assert "smoker" in risk

    def test_smoking_status_helpers(self):
        assert smoking_status_from_hebrew("המטופל מעשן") == "current"
        assert smoking_status_from_hebrew("מעשן לשעבר") == "former"
        assert smoking_status_from_hebrew("לא מעשן") == "never"
        assert is_truthy_smoking_hebrew("מעשנת") is True
        assert is_truthy_smoking_hebrew("לא מעשן") is False

    def test_bmi_and_blood_pressure_hebrew_labels(self):
        text = "מדד מסת גוף: 36.5. לחץ דם: 150/95."
        matches = extract_hebrew_matches(text)
        vitals = {m.canonical: m.amount for m in matches if m.fact_type == "vital_sign"}
        assert vitals["bmi"] == pytest.approx(36.5)
        assert vitals["blood_pressure_systolic"] == pytest.approx(150.0)
        assert vitals["blood_pressure_diastolic"] == pytest.approx(95.0)

    def test_disability_percentage(self):
        text = "אחוזי נכות: 60%"
        matches = extract_hebrew_matches(text)
        disability = [
            m for m in matches
            if m.fact_type == "vital_sign" and m.canonical == "disability_percentage"
        ]
        assert disability and disability[0].amount == pytest.approx(60.0)


class TestEmptyAndEnglishOnly:
    def test_english_only_returns_empty(self):
        assert extract_hebrew_matches("Patient has diabetes and hypertension.") == []

    def test_empty_text(self):
        assert extract_hebrew_matches("") == []
        assert extract_hebrew_matches(None) == []  # type: ignore[arg-type]

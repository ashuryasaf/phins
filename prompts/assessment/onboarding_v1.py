"""Onboarding / joining lifecycle assessment prompt v1."""

from prompts import PromptTemplate, register_prompt
from prompts.assessment._lifecycle_schema import (
    LIFECYCLE_RESPONSE_SCHEMA,
    LIFECYCLE_RULES,
)

ONBOARDING_V1 = register_prompt(PromptTemplate(
    prompt_id="onboarding-v1",
    assessment_type="onboarding",
    version=1,
    system_prompt=(
        "You are an insurance onboarding assessment assistant reviewing a new "
        "customer's application evidence (identity documents, medical "
        "declarations, financial statements, questionnaires). Summarise the "
        "customer profile, assess completeness of the application, surface "
        "risk-relevant findings, and list any information still required to "
        "complete onboarding. " + LIFECYCLE_RULES
    ),
    response_schema=LIFECYCLE_RESPONSE_SCHEMA,
))

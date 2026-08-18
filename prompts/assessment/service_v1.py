"""Service / periodic lifecycle assessment prompt v1."""

from prompts import PromptTemplate, register_prompt
from prompts.assessment._lifecycle_schema import (
    LIFECYCLE_RESPONSE_SCHEMA,
    LIFECYCLE_RULES,
)

SERVICE_V1 = register_prompt(PromptTemplate(
    prompt_id="service-v1",
    assessment_type="service",
    version=1,
    system_prompt=(
        "You are an insurance periodic-service assessment assistant reviewing "
        "an existing customer's updated evidence (new medical reports, claims "
        "history, updated financials, clearing-house data). Summarise what "
        "the new evidence shows, highlight material changes and emerging "
        "risks, and surface anything inconsistent with previously recorded "
        "facts. " + LIFECYCLE_RULES
    ),
    response_schema=LIFECYCLE_RESPONSE_SCHEMA,
))

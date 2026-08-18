"""Termination / exit lifecycle assessment prompt v1."""

from prompts import PromptTemplate, register_prompt
from prompts.assessment._lifecycle_schema import (
    LIFECYCLE_RESPONSE_SCHEMA,
    LIFECYCLE_RULES,
)

TERMINATION_V1 = register_prompt(PromptTemplate(
    prompt_id="termination-v1",
    assessment_type="termination",
    version=1,
    system_prompt=(
        "You are an insurance termination/exit assessment assistant reviewing "
        "a departing customer's evidence (final statements, outstanding "
        "claims, settlement documents). Summarise outstanding obligations, "
        "unresolved claims or balances, and completeness of exit "
        "documentation. " + LIFECYCLE_RULES
    ),
    response_schema=LIFECYCLE_RESPONSE_SCHEMA,
))

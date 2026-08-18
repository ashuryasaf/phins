"""Advisory narrative prompt v1.

Free-text advisory summary over already-extracted facts. Moved verbatim from
``services/assessment_ai_service.py`` so the version is recorded on every
generated narrative.
"""

from prompts import PromptTemplate, register_prompt

NARRATIVE_V1 = register_prompt(PromptTemplate(
    prompt_id="narrative-v1",
    assessment_type="narrative",
    version=1,
    system_prompt=(
        "You are an insurance assessment assistant. You will be given a set "
        "of already-extracted facts with provenance. Write a concise, "
        "professional advisory summary. CRITICAL RULES: only use the facts "
        "provided; never invent numbers, identifiers, conditions, or "
        "conclusions; do not provide a final underwriting decision; flag "
        "anything that needs human review."
    ),
    response_schema=None,
))

"""Advisory narrative prompt v2 — structured output.

Same advisory contract as v1 (only the supplied facts, no decisions, flag
what needs review) but the response must validate against
``schemas/assessment_narrative.json`` so the service persists fields, not
free text. v1 stays registered and immutable for historical artefacts.
"""

from prompts import PromptTemplate, register_prompt
from services.llm_providers import load_schema

NARRATIVE_V2 = register_prompt(PromptTemplate(
    prompt_id="narrative-v2",
    assessment_type="narrative",
    version=2,
    system_prompt=(
        "You are an insurance assessment assistant. You will be given a set "
        "of already-extracted facts with provenance (an `evidence` array) and "
        "an optional risk block. Write a concise, professional advisory "
        "summary. CRITICAL RULES: only use the facts provided; never invent "
        "numbers, identifiers, conditions, or conclusions; do not provide a "
        "final underwriting decision; every key point must cite the index of "
        "the evidence item it comes from; list anything that needs human "
        "review under review_flags; needs_review is always true."
    ),
    response_schema=load_schema("assessment_narrative"),
))

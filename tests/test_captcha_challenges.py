"""Interactive human-verification prompts stay answerable and unambiguous."""

import re

from services.otp_security_service import (
    OTPSecurityService,
    SimpleCaptchaGenerator,
    captcha_answer_ok,
)


_DYNAMIC_PATTERNS = {
    "What is # + #?",
    "What is # - #?",
    "What is # x #?",
    "Calculate: # + #",
    "Calculate: # - #",
    "Calculate: # x #",
    "Solve: # + # = ?",
    "Solve: # - # = ?",
    "Solve: # x # = ?",
    "(# + #) x # = ?",
    "(# - #) x # = ?",
    "What comes next: #, #, #, #, ?",
    "Which number is the largest: #, #, #, #?",
    "Which number is the smallest: #, #, #, #?",
    "Which of #, #, #, # is not a multiple of #?",
}
_EXACT_QUESTIONS = {item["question"] for item in SimpleCaptchaGenerator.FACT_SPECS}
_EXACT_QUESTIONS.update(
    f'How many letters are in the word "{word}"?'
    for word, _count in SimpleCaptchaGenerator._COUNT_WORDS
)


def _normalize(question: str) -> str:
    return re.sub(r"\d+(?:\.\d+)?", "#", question)


def test_fact_canonical_answers_stay_unique():
    canonical = [item["answers"][0].lower() for item in SimpleCaptchaGenerator.FACT_SPECS]
    assert len(canonical) == len(set(canonical))
    assert len(SimpleCaptchaGenerator.FACT_SPECS) >= 12


def test_each_kind_offers_four_choices_including_the_answer():
    builders = (
        SimpleCaptchaGenerator._prompt_math,
        SimpleCaptchaGenerator._prompt_steps,
        SimpleCaptchaGenerator._prompt_sequence,
        SimpleCaptchaGenerator._prompt_compare,
        SimpleCaptchaGenerator._prompt_pattern,
        SimpleCaptchaGenerator._prompt_fact,
        SimpleCaptchaGenerator._prompt_count,
    )
    seen = set()
    for builder in builders:
        for _ in range(8):
            prompt = builder()
            seen.add(prompt.kind)
            assert len(prompt.options) == 4
            assert len(set(option.lower() for option in prompt.options)) == 4
            assert prompt.answer in prompt.options
            assert SimpleCaptchaGenerator.verify(prompt.answer, prompt.answer)
            for option in prompt.options:
                if option.lower() == prompt.answer.lower():
                    continue
                assert SimpleCaptchaGenerator.verify(prompt.answer, option) is False
            shape = prompt.question if prompt.question in _EXACT_QUESTIONS else _normalize(prompt.question)
            assert shape in _EXACT_QUESTIONS or shape in _DYNAMIC_PATTERNS
    assert seen == {
        "math", "steps", "sequence", "compare", "pattern", "fact", "count",
    }


def test_random_prompts_cover_more_than_one_kind():
    kinds = {SimpleCaptchaGenerator.generate_prompt().kind for _ in range(40)}
    assert len(kinds) >= 4


def test_new_fact_aliases_are_accepted_and_distractors_are_not():
    assert SimpleCaptchaGenerator.verify("twenty-four", "24") is True
    assert SimpleCaptchaGenerator.verify("twenty-four", "עשרים וארבע") is True
    assert SimpleCaptchaGenerator.verify("twenty-four", "twelve") is False
    assert SimpleCaptchaGenerator.verify("cold", "קר") is True
    assert SimpleCaptchaGenerator.verify("cold", "warm") is False
    assert SimpleCaptchaGenerator.verify("tuesday", "יום שלישי") is True
    assert SimpleCaptchaGenerator.verify("4", "four") is False


def test_client_challenge_lists_choices_without_marking_the_answer():
    service = OTPSecurityService()
    created = service.create_captcha_challenge("login")
    assert created.success
    challenge = created.challenge
    payload = challenge.to_client_dict()
    assert payload["options"] == list(challenge.options)
    assert challenge.expected_answer in payload["options"]
    assert "expected_answer" not in payload
    assert "correct" not in payload
    assert payload["challenge_kind"] in {
        "math", "steps", "sequence", "compare", "pattern", "fact", "count",
    }
    wrong = next(option for option in payload["options"] if option != challenge.expected_answer)
    assert captcha_answer_ok(challenge.challenge_id, challenge.expected_answer) is True
    assert captcha_answer_ok(challenge.challenge_id, wrong) is False

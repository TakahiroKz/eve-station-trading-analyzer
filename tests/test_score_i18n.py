"""Los códigos que el backend envía en la explicación del puntaje tienen texto en los cinco idiomas del frontend."""
import re
from pathlib import Path

import pytest

from analytics.opportunity import FILTER_CODES, REASON_CODES, OpportunityConfig, OpportunityContext, assess_opportunity
from analytics.scoring import (
    CAP_CODES,
    NOTE_CODES,
    WEIGHT_KEYS,
    ScoreConfig,
    ScoreInputs,
    score_opportunity,
)

I18N = Path(__file__).resolve().parent.parent / "frontend" / "app" / "src" / "i18n"
LANGS = ("en", "es", "de", "fr", "it")


def keys_of(lang: str) -> set[str]:
    return set(re.findall(r'^\s*"([^"]+)":', (I18N / f"{lang}.ts").read_text(encoding="utf-8"), flags=re.MULTILINE))


def required_keys() -> set[str]:
    keys = {f"score.note.{c}" for c in NOTE_CODES} | {f"score.cap.{c}" for c in CAP_CODES}
    keys |= {f"score.code.{c}" for c in FILTER_CODES + REASON_CODES}
    keys |= {f"score.factor.{k}" for k in WEIGHT_KEYS}
    keys |= {f"class.{c}" for c in ("EXCELLENT", "HIGH", "MODERATE", "LOW", "DISCARDED")}
    keys |= {f"elig.{c}" for c in ("RECOMMENDED", "ELIGIBLE", "NO_ELIGIBLE")}
    keys |= {f"action.{c}" for c in ("BUY_CANDIDATE", "WAIT", "REJECT")}
    keys |= {"sort.score", "score.col", "score.title", "filters.minScore", "filters.eligibility",
             "score.value.bookDepth", "detail.bookDepth", "detail.bookDepthValue"}
    return keys


@pytest.mark.parametrize("lang", LANGS)
def test_every_score_code_has_a_text_in_each_language(lang):
    missing = required_keys() - keys_of(lang)
    assert not missing, f"{lang}.ts no tiene: {sorted(missing)}"


def test_the_codes_the_engine_emits_are_all_declared():
    inputs = ScoreInputs(roi=1.8, best_buy=1000.0, volume_7d=100.0, volume_30d=100.0, ops_7d=3.0, buy_orders=1,
                         sell_orders=1, status="POTENCIAL", price_cv=None)
    emitted_notes, emitted_caps, emitted_filters, emitted_reasons = set(), set(), set(), set()
    scenarios = [
        inputs,
        ScoreInputs(roi=0.3, best_buy=1000.0, volume_7d=5e6, volume_30d=5e6, ops_7d=120, buy_orders=40,
                    sell_orders=40, status="POTENCIAL", price_cv=0.03),
        ScoreInputs(roi=0.03, best_buy=1000.0, volume_7d=0.0, volume_30d=5e6, ops_7d=1, buy_orders=40,
                    sell_orders=40, status="DESCARTADO", price_cv=0.9),
        ScoreInputs(roi=0.7, best_buy=0.0, volume_7d=5e6, volume_30d=5e6, ops_7d=120, buy_orders=0, sell_orders=0,
                    status="DESCARTADO", price_cv=0.03),
    ]
    for item in scenarios:
        result = score_opportunity(item, ScoreConfig())
        emitted_notes |= {f.code for f in result.factors}
        emitted_caps |= {c["code"] for c in result.caps}
        for context in (OpportunityContext(250.0, True, 2.0), OpportunityContext(-1.0, False, 99.0)):
            out = assess_opportunity(item, context, result, ScoreConfig(), OpportunityConfig())
            emitted_filters |= set(out["eligibility"]["failed_filters"])
            emitted_reasons |= set(out["recommendation"]["reason_codes"]) - set(out["eligibility"]["failed_filters"])
            emitted_reasons |= {c["code"] for c in out["recommendation"]["to_change"]} - set(FILTER_CODES)

    assert emitted_notes <= set(NOTE_CODES)
    assert emitted_caps <= set(CAP_CODES)
    assert emitted_filters <= set(FILTER_CODES)
    assert emitted_reasons <= set(REASON_CODES)


def test_every_factor_carries_a_code_and_its_measurements():
    result = score_opportunity(ScoreInputs(roi=0.3, best_buy=1000.0, volume_7d=5e6, volume_30d=5e6, ops_7d=120,
                                           buy_orders=40, sell_orders=40, status="POTENCIAL", price_cv=0.03))

    for factor in result.factors:
        assert factor.code in NOTE_CODES and factor.metrics
    dumped = result.to_dict()["factors"]
    assert all({"code", "metrics"} <= set(f) for f in dumped)
    assert dumped[0]["metrics"] == {"roi": 0.3}

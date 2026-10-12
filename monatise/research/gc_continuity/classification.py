"""Evidence-based labels; absence and transport completion never prove no trade."""
from monatise.research.gc_continuity import CLASS_NAMES


def classify(*, session_state, raw_present, admitted_present, trade_count,
             independently_complete_trades=False, record_validation_passed=True):
    if session_state == "CLOSED":
        code,reason = "A","REVIEWED_STATUS_EXCLUDES_TRADING"
    elif session_state != "FULLY_OPEN":
        code,reason = "E","PARTIAL_OR_UNREVIEWED_SESSION_NOT_A_FULLY_OPEN_MISSING_BAR"
    elif raw_present and not admitted_present and record_validation_passed:
        code,reason = "D","VALID_NATIVE_RECORD_PRESENT_BUT_OMITTED"
    elif not raw_present and trade_count is not None and trade_count > 0:
        code,reason = "C","EXECUTED_ACTIVITY_CONTRADICTS_ABSENT_REQUIRED_OBSERVATION"
    elif not raw_present and trade_count == 0 and independently_complete_trades is True:
        code,reason = "B","INDEPENDENT_COMPLETE_TRADE_EVIDENCE_ESTABLISHES_NO_TRADES"
    else:
        code,reason = "E","NO_TRADE_VERSUS_MISSING_ACTIVITY_UNRESOLVED"
    return dict(classification=code,class_name=CLASS_NAMES[code],reason=reason,
                synthetic_price_authorized=False)

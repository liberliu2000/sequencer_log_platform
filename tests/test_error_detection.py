from app.schemas.common import NormalizedEvent
from app.detectors.error_detection import normalize_error_signature


def test_error_signature_normalization():
    event = NormalizedEvent(
        source_file="a.log",
        parser_name="error_log",
        message="Ice.ConnectionLostException request id 123 timeout:285 at D:\\Code\\a.cs:445",
        raw_text="Ice.ConnectionLostException request id 123 timeout:285 at D:\\Code\\a.cs:445",
        level="ERROR",
        method_name="SendFluidicsBoardInfos",
        exception_type="Ice.ConnectionLostException",
    )
    sig, family, severity = normalize_error_signature(event)
    assert sig is not None
    assert family in {"connection_lost", "timeout", "rpc_ice"}
    assert severity == "error"

from anomaly_lab.compliance import FORBIDDEN_TERMS, scan_forbidden


def test_clean_text_passes():
    assert scan_forbidden("这是一段干净的文本", FORBIDDEN_TERMS) == []


def test_forbidden_term_detected():
    hits = scan_forbidden("引用了某内部平台名", ["某内部平台名"])
    assert len(hits) == 1

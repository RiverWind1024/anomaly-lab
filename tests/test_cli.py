from pathlib import Path

import pytest

from anomaly_lab.cli import main


def test_generate_then_classify(tmp_path: Path, capsys):
    rc = main(["generate", "--n", "2", "--seed", "1", "--out", str(tmp_path)])
    assert rc == 0
    assert (tmp_path / "index.json").exists()

    rc = main(["classify", "--eval", "--data", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "分类准确率" in out or "accuracy" in out.lower()


def test_unimplemented_command_exits_2(tmp_path: Path):
    with pytest.raises(SystemExit) as e:
        main(["compare", "--data", str(tmp_path)])
    assert e.value.code == 2


def test_compliance_check_passes_on_clean_repo():
    rc = main(["compliance-check"])
    assert rc == 0


def test_detect_and_evaluate_pipeline(tmp_path: Path, capsys):
    data = tmp_path / "data"
    out = tmp_path / "reports"
    assert main(["generate", "--n", "2", "--seed", "1", "--out", str(data)]) == 0
    assert main(["detect", "--detector", "iqr", "--data", str(data)]) == 0
    assert main(["evaluate", "--data", str(data), "--report", str(out)]) == 0
    assert (out / "report.json").exists()
    assert (out / "report.md").exists()
    out_text = capsys.readouterr().out
    assert "F1" in out_text or "f1" in out_text.lower()


def test_report_command_writes_summary(tmp_path: Path):
    data = tmp_path / "data"
    assert main(["generate", "--n", "2", "--seed", "3", "--out", str(data)]) == 0
    assert main(["detect", "--detector", "iqr", "--data", str(data)]) == 0
    out = tmp_path / "summary.md"
    assert main(["report", "--data", str(data), "--out", str(out)]) == 0
    assert "F1" in out.read_text(encoding="utf-8")

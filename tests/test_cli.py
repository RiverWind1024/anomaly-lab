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
        main(["detect", "--data", str(tmp_path)])
    assert e.value.code == 2


def test_compliance_check_passes_on_clean_repo():
    rc = main(["compliance-check"])
    assert rc == 0

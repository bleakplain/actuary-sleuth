from pathlib import Path

from rebuild_kb import _parse_args, main


def test_stage_cli_keeps_entry_point_in_scripts():
    args = _parse_args([
        "stage",
        "--excel",
        "/tmp/source.xlsx",
        "--kb-root",
        "/tmp/kb",
        "--references-dir",
        "/tmp/kb/references",
    ])

    assert args.command == "stage"
    assert args.version == "v5"


def test_fingerprint_cli_is_read_only(
    tmp_path: Path,
    capsys,
):
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")

    assert main(["fingerprint", "--manifest", str(manifest)]) == 0
    assert len(capsys.readouterr().out.strip()) == 64


def test_rollback_cli_requires_service_stop_confirmation(
    tmp_path: Path,
    capsys,
):
    kb_root = tmp_path / "kb"

    result = main([
        "rollback",
        "--kb-root",
        str(kb_root),
        "--references-dir",
        str(kb_root / "references"),
        "--backup-dir",
        str(kb_root / "backups" / "old"),
        "--identity-path",
        str(tmp_path / "kb_build_identity.json"),
    ])

    assert result == 1
    assert "停止" in capsys.readouterr().out


def test_stage_cli_rejects_directory_outside_reserved_staging_root(
    tmp_path: Path,
    capsys,
):
    kb_root = tmp_path / "kb"
    references = kb_root / "references"
    references.mkdir(parents=True)
    excel = tmp_path / "source.xlsx"
    excel.write_text("source", encoding="utf-8")

    result = main([
        "stage",
        "--excel",
        str(excel),
        "--kb-root",
        str(kb_root),
        "--references-dir",
        str(references),
        "--stage-dir",
        str(kb_root / "unsafe-stage"),
    ])

    assert result == 1
    assert ".staging" in capsys.readouterr().out
    assert not (kb_root / "unsafe-stage").exists()

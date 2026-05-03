"""Tests for the real CAD/export converter smoke runner."""

from __future__ import annotations

import shlex
import sys
import textwrap
from pathlib import Path

from app.config import Settings
from app.services.engineering_converters import run_engineering_converter_smoke


def _converter_settings(
    *,
    command_template: str,
    timeout_seconds: int = 30,
    output_dir: str,
    output_extension: str = ".pdf",
    smoke_input_path: str = "",
) -> Settings:
    return Settings(
        _env_file=None,
        engineering_converter_command_template=command_template,
        engineering_converter_timeout_seconds=timeout_seconds,
        engineering_converter_output_dir=output_dir,
        engineering_converter_output_extension=output_extension,
        engineering_converter_smoke_input_path=smoke_input_path,
    )


def _script_template(script_path: Path) -> str:
    return (
        f"{shlex.quote(sys.executable)} {shlex.quote(str(script_path))} "
        "--input {input} --output {output}"
    )


def _write_script(path: Path, body: str) -> None:
    path.write_text(textwrap.dedent(body), encoding="utf-8")


def test_smoke_runner_requires_command_and_input_configuration(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        engineering_converter_output_dir=str(tmp_path / "converted"),
    )

    result = run_engineering_converter_smoke(settings)

    assert result.success is False
    assert result.exit_code != 0
    assert result.status == "configuration_required"
    assert result.message.startswith("Configuration Required")
    assert result.diagnostics["configured"] is False
    assert result.diagnostics["missing"] == [
        "engineering_converter_command_template",
        "engineering_converter_smoke_input_path",
    ]


def test_smoke_runner_rejects_missing_smoke_input_path(tmp_path: Path) -> None:
    command_sentinel = tmp_path / "command-ran.txt"
    script_path = tmp_path / "missing-input guard.py"
    _write_script(
        script_path,
        f"""
        from pathlib import Path
        import sys

        Path({str(command_sentinel)!r}).write_text("ran", encoding="utf-8")
        raise SystemExit(91)
        """,
    )

    missing_input = tmp_path / "absent.dwg"
    settings = _converter_settings(
        command_template=_script_template(script_path),
        output_dir=str(tmp_path / "converted"),
        smoke_input_path=str(missing_input),
    )

    result = run_engineering_converter_smoke(settings)

    assert result.success is False
    assert result.exit_code != 0
    assert result.status == "missing_input"
    assert result.message.startswith("Configuration Required")
    assert result.conversion is None
    assert result.diagnostics["smoke_input_exists"] is False
    assert result.diagnostics["missing"] == ["engineering_converter_smoke_input_path"]
    assert not command_sentinel.exists()


def test_smoke_runner_proves_configured_fake_converter(tmp_path: Path) -> None:
    source_dir = tmp_path / "smoke inputs"
    source_dir.mkdir()
    output_dir = tmp_path / "converted output"
    script_path = tmp_path / "fake smoke converter.py"
    source_path = source_dir / "Site Plan.DWG"
    source_path.write_text("dwg payload", encoding="utf-8")

    _write_script(
        script_path,
        """
        from pathlib import Path
        import sys

        input_path = sys.argv[sys.argv.index("--input") + 1]
        output_path = sys.argv[sys.argv.index("--output") + 1]

        assert Path(input_path).read_text(encoding="utf-8") == "dwg payload"
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text("converted payload", encoding="utf-8")
        print(f"smoke converted {input_path}")
        print("smoke stderr note", file=sys.stderr)
        """,
    )

    settings = _converter_settings(
        command_template=_script_template(script_path),
        output_dir=str(output_dir),
        output_extension=".PDF",
        smoke_input_path=str(source_path),
    )
    result = run_engineering_converter_smoke(settings)
    expected_output = output_dir / "Site Plan.pdf"

    assert result.success is True
    assert result.exit_code == 0
    assert result.status == "success"
    assert result.message == f"Real converter smoke passed: Site Plan.DWG -> {expected_output}"
    assert result.diagnostics["smoke_input_path"] == str(source_path)
    assert result.diagnostics["smoke_input_exists"] is True
    assert result.diagnostics["smoke_status"] == "success"
    assert result.conversion is not None
    assert result.conversion.success is True
    assert result.conversion.status == "success"
    assert result.conversion.output_path == str(expected_output)
    assert result.conversion.command_exit_code == 0
    assert result.conversion.source_extension == ".dwg"
    assert result.conversion.warnings == ()
    assert result.conversion.diagnostics["argv"] == [
        sys.executable,
        str(script_path),
        "--input",
        str(source_path),
        "--output",
        str(expected_output),
    ]
    assert result.conversion.diagnostics["stderr_excerpt"] == "smoke stderr note\n"
    assert result.conversion.diagnostics["output_exists"] is True
    assert result.conversion.diagnostics["output_size"] == len("converted payload")
    assert Path(result.conversion.output_path).read_text(encoding="utf-8") == "converted payload"

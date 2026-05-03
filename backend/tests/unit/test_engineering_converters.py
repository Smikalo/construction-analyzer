"""Tests for the CAD/export converter seam."""

from __future__ import annotations

import shlex
import sys
import textwrap
from pathlib import Path

from app.config import Settings
from app.services.engineering_converters import (
    CLIEngineeringConverter,
    MissingEngineeringConverter,
    get_engineering_converter,
)


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


def test_missing_command_template_returns_safe_adapter(tmp_path: Path) -> None:
    converter = get_engineering_converter(Settings(_env_file=None))

    assert isinstance(converter, MissingEngineeringConverter)

    source_path = tmp_path / "incoming" / "drawing.dwg"
    result = converter.convert(str(source_path))

    assert result.success is False
    assert result.status == "missing_configuration"
    assert result.error is not None
    assert "not configured" in result.error
    assert result.diagnostics["configured"] is False
    assert result.output_path == "/app/data/conversions/drawing.pdf"
    assert converter.get_diagnostics()["configured"] is False


def test_cli_converter_success_handles_uppercase_extension_and_paths_with_spaces(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "incoming cad"
    source_dir.mkdir()
    output_dir = tmp_path / "converted output"
    script_path = tmp_path / "fake converter.py"
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
        print(f"converted: {input_path}")
        print("converter stderr note", file=sys.stderr)
        """,
    )

    settings = _converter_settings(
        command_template=_script_template(script_path),
        output_dir=str(output_dir),
        output_extension=".PDF",
        smoke_input_path=str(source_path),
    )
    converter = get_engineering_converter(settings)

    assert isinstance(converter, CLIEngineeringConverter)
    assert converter.get_diagnostics()["configured"] is True

    result = converter.convert(str(source_path))
    expected_output = output_dir / "Site Plan.pdf"

    assert result.success is True
    assert result.status == "success"
    assert result.output_path == str(expected_output)
    assert result.command_exit_code == 0
    assert result.timeout_seconds == 30
    assert result.source_extension == ".dwg"
    assert result.warnings == ()
    assert Path(result.output_path).read_text(encoding="utf-8") == "converted payload"
    assert result.diagnostics["argv"] == [
        sys.executable,
        str(script_path),
        "--input",
        str(source_path),
        "--output",
        str(expected_output),
    ]
    assert result.diagnostics["stdout_excerpt"].startswith("converted: ")
    assert result.diagnostics["stderr_excerpt"] == "converter stderr note\n"
    assert result.diagnostics["output_exists"] is True
    assert result.diagnostics["output_size"] == len("converted payload")


def test_converter_rejects_unsupported_extension_without_running_script(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "mystery.bin"
    source_path.write_bytes(b"binary")
    script_path = tmp_path / "should_not_run.py"
    _write_script(
        script_path,
        """
        raise AssertionError("unsupported extension should short-circuit before subprocess")
        """,
    )

    settings = _converter_settings(
        command_template=_script_template(script_path),
        output_dir=str(tmp_path / "converted"),
    )
    converter = get_engineering_converter(settings)

    result = converter.convert(str(source_path))

    assert result.success is False
    assert result.status == "unsupported_extension"
    assert result.output_path == str(tmp_path / "converted" / "mystery.pdf")
    assert result.warnings == ("unsupported_extension",)
    assert result.error == "unsupported source extension: .bin"
    assert result.diagnostics["command"] == []
    assert result.diagnostics["supported_extensions"] == [
        ".dbn",
        ".dwg",
        ".ern",
        ".p2n",
        ".pln",
        ".vwx",
    ]


def test_converter_reports_non_zero_exit_with_bounded_output(tmp_path: Path) -> None:
    source_path = tmp_path / "drawing.dwg"
    source_path.write_text("payload", encoding="utf-8")
    script_path = tmp_path / "failing converter.py"
    _write_script(
        script_path,
        """
        import sys

        print("stdout-" + "A" * 3000)
        print("stderr-" + "B" * 3000, file=sys.stderr)
        sys.exit(7)
        """,
    )

    settings = _converter_settings(
        command_template=_script_template(script_path),
        output_dir=str(tmp_path / "converted"),
    )
    converter = get_engineering_converter(settings)

    result = converter.convert(str(source_path))

    assert result.success is False
    assert result.status == "failed"
    assert result.command_exit_code == 7
    assert result.timeout_seconds == 30
    assert result.output_path == str(tmp_path / "converted" / "drawing.pdf")
    assert result.warnings[0] == "converter_non_zero_exit"
    assert "converter_stdout_truncated" in result.warnings
    assert "converter_stderr_truncated" in result.warnings
    assert result.diagnostics["stdout_truncated"] is True
    assert result.diagnostics["stderr_truncated"] is True
    assert result.diagnostics["stdout_excerpt"].endswith("\n...[truncated]")
    assert result.diagnostics["stderr_excerpt"].endswith("\n...[truncated]")
    assert "converter exited with code 7" in result.error
    assert "stderr-" in result.error


def test_converter_times_out(tmp_path: Path) -> None:
    source_path = tmp_path / "drawing.dwg"
    source_path.write_text("payload", encoding="utf-8")
    script_path = tmp_path / "slow converter.py"
    _write_script(
        script_path,
        """
        import sys
        import time

        print("starting", flush=True)
        print("sleeping", file=sys.stderr, flush=True)
        time.sleep(2)
        """,
    )

    settings = _converter_settings(
        command_template=_script_template(script_path),
        timeout_seconds=1,
        output_dir=str(tmp_path / "converted"),
    )
    converter = get_engineering_converter(settings)

    result = converter.convert(str(source_path))

    assert result.success is False
    assert result.status == "timeout"
    assert result.timeout_seconds == 1
    assert result.output_path == str(tmp_path / "converted" / "drawing.pdf")
    assert "converter_timeout" in result.warnings
    assert result.diagnostics["timeout_seconds"] == 1
    assert result.diagnostics["stdout_excerpt"] == "starting\n"
    assert result.diagnostics["stderr_excerpt"] == "sleeping\n"
    assert "timed out after 1s" in result.error


def test_converter_reports_missing_output_when_script_succeeds_without_writing_file(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "drawing.dwg"
    source_path.write_text("payload", encoding="utf-8")
    script_path = tmp_path / "no-output converter.py"
    _write_script(
        script_path,
        """
        print("converted but forgot the file")
        """,
    )

    settings = _converter_settings(
        command_template=_script_template(script_path),
        output_dir=str(tmp_path / "converted"),
    )
    converter = get_engineering_converter(settings)

    result = converter.convert(str(source_path))

    assert result.success is False
    assert result.status == "missing_output"
    assert result.command_exit_code == 0
    assert result.output_path == str(tmp_path / "converted" / "drawing.pdf")
    assert result.warnings == ("converter_missing_output",)
    assert result.diagnostics["output_exists"] is False
    assert "did not create output file" in result.error


def test_converter_rejects_template_missing_input_placeholder(tmp_path: Path) -> None:
    source_path = tmp_path / "drawing.dwg"
    source_path.write_text("payload", encoding="utf-8")
    script_path = tmp_path / "bad-template converter.py"
    _write_script(
        script_path,
        """
        print("should not run")
        """,
    )

    settings = _converter_settings(
        command_template=(
            f"{shlex.quote(sys.executable)} {shlex.quote(str(script_path))} --output {{output}}"
        ),
        output_dir=str(tmp_path / "converted"),
    )
    converter = get_engineering_converter(settings)

    result = converter.convert(str(source_path))

    assert result.success is False
    assert result.status == "failed"
    assert result.warnings == ("converter_invalid_template",)
    assert "must include input placeholder" in result.error
    assert result.diagnostics["template_error"].startswith(
        "engineering converter command template must include input"
    )


def test_converter_rejects_output_extension_without_leading_dot(tmp_path: Path) -> None:
    source_path = tmp_path / "drawing.dwg"
    source_path.write_text("payload", encoding="utf-8")
    script_path = tmp_path / "converter.py"
    _write_script(
        script_path,
        """
        print("should not run")
        """,
    )

    settings = _converter_settings(
        command_template=_script_template(script_path),
        output_dir=str(tmp_path / "converted"),
        output_extension="pdf",
    )
    converter = get_engineering_converter(settings)

    result = converter.convert(str(source_path))

    assert result.success is False
    assert result.status == "failed"
    assert result.output_path is None
    assert result.warnings == ("converter_invalid_output_extension",)
    assert "must start with a dot" in result.error
    assert result.diagnostics["configuration_error"] == (
        "converter output extension must start with a dot"
    )


def test_converter_reports_missing_source_file(tmp_path: Path) -> None:
    source_path = tmp_path / "missing.dwg"
    script_path = tmp_path / "converter.py"
    _write_script(
        script_path,
        """
        print("should not run")
        """,
    )

    settings = _converter_settings(
        command_template=_script_template(script_path),
        output_dir=str(tmp_path / "converted"),
    )
    converter = get_engineering_converter(settings)

    result = converter.convert(str(source_path))

    assert result.success is False
    assert result.status == "failed"
    assert result.output_path == str(tmp_path / "converted" / "missing.pdf")
    assert result.warnings == ("converter_missing_source",)
    assert "source file does not exist" in result.error
    assert result.diagnostics["source_exists"] is False
    assert result.diagnostics["command"] == []

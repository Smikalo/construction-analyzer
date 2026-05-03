"""CAD/export converter adapters used by ingestion and smoke checks."""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from string import Formatter
from typing import Any, Literal, Protocol, TypeAlias

from app.config import Settings, get_settings
from app.services.engineering_files import SUPPORTED_CAD_EXPORT_EXTENSIONS

ConversionStatus: TypeAlias = Literal[
    "success",
    "missing_configuration",
    "unsupported_extension",
    "failed",
    "timeout",
    "missing_output",
]

_CONVERSION_OUTPUT_EXCERPT_LIMIT = 2_000
_SUPPORTED_CAD_EXPORT_EXTENSION_SET = frozenset(
    extension.lower() for extension in SUPPORTED_CAD_EXPORT_EXTENSIONS
)
_ALLOWED_TEMPLATE_FIELDS = frozenset({"input", "output"})


@dataclass(frozen=True, slots=True)
class ConversionResult:
    """Outcome from attempting to convert one engineering file."""

    success: bool
    status: ConversionStatus
    output_path: str | None
    warnings: tuple[str, ...] = ()
    error: str | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)
    command_exit_code: int | None = None
    timeout_seconds: int | None = None
    source_extension: str = ""


@dataclass(frozen=True, slots=True)
class EngineeringConverterSmokeResult:
    """Outcome from the real-runtime CAD/export smoke command."""

    success: bool
    exit_code: int
    status: str
    message: str
    diagnostics: dict[str, Any] = field(default_factory=dict)
    conversion: ConversionResult | None = None


class EngineeringConverter(Protocol):
    """Protocol for the CAD/export conversion seam."""

    def convert(self, source_path: str) -> ConversionResult:
        """Convert a single source file and return a bounded result."""

    def get_diagnostics(self) -> dict[str, Any]:
        """Return a JSON-serializable snapshot of the configured converter."""


@dataclass(frozen=True, slots=True)
class _EngineeringConverterConfig:
    command_template: str
    timeout_seconds: int
    output_dir: str
    output_extension: str
    smoke_input_path: str

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> _EngineeringConverterConfig:
        active_settings = settings or get_settings()
        return cls(
            command_template=active_settings.engineering_converter_command_template.strip(),
            timeout_seconds=active_settings.engineering_converter_timeout_seconds,
            output_dir=active_settings.engineering_converter_output_dir.strip(),
            output_extension=active_settings.engineering_converter_output_extension.strip(),
            smoke_input_path=active_settings.engineering_converter_smoke_input_path.strip(),
        )

    @property
    def normalized_output_extension(self) -> str:
        return self.output_extension.lower()


@dataclass(frozen=True, slots=True)
class MissingEngineeringConverter:
    """Adapter returned when the converter command is not configured."""

    config: _EngineeringConverterConfig
    reason: str = "engineering converter command template is not configured"

    def convert(self, source_path: str) -> ConversionResult:
        source_extension = _source_extension(source_path)
        output_path, output_error = _derive_output_path(self.config, source_path)
        diagnostics = _base_diagnostics(
            self.config,
            source_path=source_path,
            source_extension=source_extension,
            output_path=output_path,
            converter_type="missing",
            configured=False,
            status="missing_configuration",
            command=[],
        )
        if output_error is not None:
            diagnostics["configuration_error"] = output_error

        warnings = ["converter_not_configured"]
        if output_error is not None:
            warnings.append("converter_invalid_output_extension")

        return ConversionResult(
            success=False,
            status="missing_configuration",
            output_path=output_path,
            warnings=tuple(warnings),
            error=self.reason,
            diagnostics=diagnostics,
            source_extension=source_extension,
        )

    def get_diagnostics(self) -> dict[str, Any]:
        return _converter_configuration_diagnostics(
            self.config,
            converter_type="missing",
            configured=False,
            reason=self.reason,
        )


@dataclass(frozen=True, slots=True)
class CLIEngineeringConverter:
    """Shell-free converter adapter that runs a configured command template."""

    config: _EngineeringConverterConfig

    def convert(self, source_path: str) -> ConversionResult:
        source_path_obj = Path(source_path)
        source_extension = _source_extension(source_path)
        output_path, output_error = _derive_output_path(self.config, source_path)
        template_error = _validate_command_template(self.config.command_template)
        if template_error is not None:
            diagnostics = _base_diagnostics(
                self.config,
                source_path=source_path,
                source_extension=source_extension,
                output_path=output_path,
                converter_type="cli",
                configured=True,
                status="failed",
                command=[],
            )
            diagnostics["template_error"] = template_error
            return ConversionResult(
                success=False,
                status="failed",
                output_path=output_path,
                warnings=("converter_invalid_template",),
                error=template_error,
                diagnostics=diagnostics,
                source_extension=source_extension,
            )

        if not source_path_obj.is_file():
            diagnostics = _base_diagnostics(
                self.config,
                source_path=source_path,
                source_extension=source_extension,
                output_path=output_path,
                converter_type="cli",
                configured=True,
                status="failed",
                command=[],
            )
            diagnostics["source_exists"] = False
            return ConversionResult(
                success=False,
                status="failed",
                output_path=output_path,
                warnings=("converter_missing_source",),
                error=f"source file does not exist: {source_path_obj}",
                diagnostics=diagnostics,
                source_extension=source_extension,
            )

        if source_extension not in _SUPPORTED_CAD_EXPORT_EXTENSION_SET:
            diagnostics = _base_diagnostics(
                self.config,
                source_path=source_path,
                source_extension=source_extension,
                output_path=output_path,
                converter_type="cli",
                configured=True,
                status="unsupported_extension",
                command=[],
            )
            diagnostics["supported_extensions"] = sorted(_SUPPORTED_CAD_EXPORT_EXTENSION_SET)
            return ConversionResult(
                success=False,
                status="unsupported_extension",
                output_path=output_path,
                warnings=("unsupported_extension",),
                error=f"unsupported source extension: {source_extension or '<none>'}",
                diagnostics=diagnostics,
                source_extension=source_extension,
            )

        if output_error is not None:
            diagnostics = _base_diagnostics(
                self.config,
                source_path=source_path,
                source_extension=source_extension,
                output_path=None,
                converter_type="cli",
                configured=True,
                status="failed",
                command=[],
            )
            diagnostics["configuration_error"] = output_error
            return ConversionResult(
                success=False,
                status="failed",
                output_path=None,
                warnings=("converter_invalid_output_extension",),
                error=output_error,
                diagnostics=diagnostics,
                source_extension=source_extension,
            )

        timeout_seconds = self.config.timeout_seconds
        if timeout_seconds <= 0:
            diagnostics = _base_diagnostics(
                self.config,
                source_path=source_path,
                source_extension=source_extension,
                output_path=output_path,
                converter_type="cli",
                configured=True,
                status="failed",
                command=[],
            )
            diagnostics["configuration_error"] = "timeout_seconds must be greater than 0"
            return ConversionResult(
                success=False,
                status="failed",
                output_path=output_path,
                warnings=("converter_invalid_timeout",),
                error="timeout_seconds must be greater than 0",
                diagnostics=diagnostics,
                timeout_seconds=timeout_seconds,
                source_extension=source_extension,
            )

        assert output_path is not None
        resolved_output_path = output_path
        output_path_obj = Path(resolved_output_path)
        try:
            output_path_obj.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            diagnostics = _base_diagnostics(
                self.config,
                source_path=source_path,
                source_extension=source_extension,
                output_path=output_path,
                converter_type="cli",
                configured=True,
                status="failed",
                command=[],
            )
            diagnostics["configuration_error"] = str(exc)
            return ConversionResult(
                success=False,
                status="failed",
                output_path=output_path,
                warnings=("converter_output_directory_unwritable",),
                error=f"could not create output directory {output_path_obj.parent}: {exc}",
                diagnostics=diagnostics,
                source_extension=source_extension,
            )

        try:
            argv = _build_command_argv(
                self.config.command_template,
                input_path=str(source_path_obj),
                output_path=resolved_output_path,
            )
        except ValueError as exc:
            diagnostics = _base_diagnostics(
                self.config,
                source_path=source_path,
                source_extension=source_extension,
                output_path=output_path,
                converter_type="cli",
                configured=True,
                status="failed",
                command=[],
            )
            diagnostics["command_template_error"] = str(exc)
            return ConversionResult(
                success=False,
                status="failed",
                output_path=output_path,
                warnings=("converter_invalid_template",),
                error=str(exc),
                diagnostics=diagnostics,
                source_extension=source_extension,
            )

        try:
            completed = subprocess.run(  # noqa: S603 - shell=False with argv tokens
                argv,
                shell=False,
                capture_output=True,
                check=False,
                text=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            stdout_excerpt, stdout_truncated = _excerpt_text(_coerce_text(exc.stdout))
            stderr_excerpt, stderr_truncated = _excerpt_text(_coerce_text(exc.stderr))
            diagnostics = _base_diagnostics(
                self.config,
                source_path=source_path,
                source_extension=source_extension,
                output_path=output_path,
                converter_type="cli",
                configured=True,
                status="timeout",
                command=argv,
            )
            diagnostics.update(
                {
                    "stdout_excerpt": stdout_excerpt,
                    "stderr_excerpt": stderr_excerpt,
                    "stdout_truncated": stdout_truncated,
                    "stderr_truncated": stderr_truncated,
                    "timeout_seconds": timeout_seconds,
                }
            )
            warnings = ["converter_timeout"]
            warnings.extend(
                _excerpt_warnings(
                    stdout_truncated=stdout_truncated,
                    stderr_truncated=stderr_truncated,
                )
            )
            return ConversionResult(
                success=False,
                status="timeout",
                output_path=output_path,
                warnings=tuple(warnings),
                error=f"converter timed out after {timeout_seconds}s",
                diagnostics=diagnostics,
                timeout_seconds=timeout_seconds,
                source_extension=source_extension,
            )
        except FileNotFoundError as exc:
            diagnostics = _base_diagnostics(
                self.config,
                source_path=source_path,
                source_extension=source_extension,
                output_path=output_path,
                converter_type="cli",
                configured=True,
                status="failed",
                command=argv,
            )
            diagnostics["command_error"] = str(exc)
            return ConversionResult(
                success=False,
                status="failed",
                output_path=output_path,
                warnings=("converter_command_not_found",),
                error=str(exc),
                diagnostics=diagnostics,
                source_extension=source_extension,
            )
        except OSError as exc:
            diagnostics = _base_diagnostics(
                self.config,
                source_path=source_path,
                source_extension=source_extension,
                output_path=output_path,
                converter_type="cli",
                configured=True,
                status="failed",
                command=argv,
            )
            diagnostics["command_error"] = str(exc)
            return ConversionResult(
                success=False,
                status="failed",
                output_path=output_path,
                warnings=("converter_command_failed",),
                error=str(exc),
                diagnostics=diagnostics,
                source_extension=source_extension,
            )

        stdout_excerpt, stdout_truncated = _excerpt_text(completed.stdout)
        stderr_excerpt, stderr_truncated = _excerpt_text(completed.stderr)
        diagnostics = _base_diagnostics(
            self.config,
            source_path=source_path,
            source_extension=source_extension,
            output_path=output_path,
            converter_type="cli",
            configured=True,
            status="success" if completed.returncode == 0 else "failed",
            command=argv,
        )
        diagnostics.update(
            {
                "argv": argv,
                "return_code": completed.returncode,
                "stdout_excerpt": stdout_excerpt,
                "stderr_excerpt": stderr_excerpt,
                "stdout_truncated": stdout_truncated,
                "stderr_truncated": stderr_truncated,
                "timeout_seconds": timeout_seconds,
            }
        )

        if completed.returncode != 0:
            warnings = ["converter_non_zero_exit"]
            warnings.extend(
                _excerpt_warnings(
                    stdout_truncated=stdout_truncated,
                    stderr_truncated=stderr_truncated,
                )
            )
            error = _build_exit_error(completed.returncode, stderr_excerpt)
            return ConversionResult(
                success=False,
                status="failed",
                output_path=output_path,
                warnings=tuple(warnings),
                error=error,
                diagnostics=diagnostics,
                command_exit_code=completed.returncode,
                timeout_seconds=timeout_seconds,
                source_extension=source_extension,
            )

        if not output_path_obj.exists():
            diagnostics["output_exists"] = False
            return ConversionResult(
                success=False,
                status="missing_output",
                output_path=output_path,
                warnings=("converter_missing_output",),
                error=f"converter did not create output file: {output_path}",
                diagnostics=diagnostics,
                command_exit_code=completed.returncode,
                timeout_seconds=timeout_seconds,
                source_extension=source_extension,
            )

        try:
            output_size = output_path_obj.stat().st_size
        except OSError as exc:
            diagnostics["output_stat_error"] = str(exc)
            return ConversionResult(
                success=False,
                status="failed",
                output_path=output_path,
                warnings=("converter_output_unreadable",),
                error=str(exc),
                diagnostics=diagnostics,
                command_exit_code=completed.returncode,
                timeout_seconds=timeout_seconds,
                source_extension=source_extension,
            )

        diagnostics["output_exists"] = True
        diagnostics["output_size"] = output_size
        if output_size <= 0:
            return ConversionResult(
                success=False,
                status="missing_output",
                output_path=output_path,
                warnings=("converter_missing_output",),
                error=f"converter produced empty output file: {output_path}",
                diagnostics=diagnostics,
                command_exit_code=completed.returncode,
                timeout_seconds=timeout_seconds,
                source_extension=source_extension,
            )

        warnings = _excerpt_warnings(
            stdout_truncated=stdout_truncated,
            stderr_truncated=stderr_truncated,
        )
        return ConversionResult(
            success=True,
            status="success",
            output_path=output_path,
            warnings=tuple(warnings),
            error=None,
            diagnostics=diagnostics,
            command_exit_code=completed.returncode,
            timeout_seconds=timeout_seconds,
            source_extension=source_extension,
        )

    def get_diagnostics(self) -> dict[str, Any]:
        return _converter_configuration_diagnostics(
            self.config,
            converter_type="cli",
            configured=True,
        )


def get_engineering_converter(settings: Settings | None = None) -> EngineeringConverter:
    """Return the configured converter or a safe missing-configuration adapter."""
    config = _EngineeringConverterConfig.from_settings(settings)
    if not config.command_template:
        return MissingEngineeringConverter(config=config)
    return CLIEngineeringConverter(config=config)


def run_engineering_converter_smoke(
    settings: Settings | None = None,
) -> EngineeringConverterSmokeResult:
    """Run the real converter against the configured smoke input path."""
    active_settings = settings or get_settings()
    config = _EngineeringConverterConfig.from_settings(active_settings)

    missing: list[str] = []
    if not config.command_template:
        missing.append("engineering_converter_command_template")
    if not config.smoke_input_path:
        missing.append("engineering_converter_smoke_input_path")

    if missing:
        diagnostics = _converter_configuration_diagnostics(
            config,
            converter_type="missing",
            configured=False,
            reason="configuration required",
        )
        diagnostics.update(
            {
                "status": "configuration_required",
                "missing": missing,
                "smoke_input_exists": False,
            }
        )
        return EngineeringConverterSmokeResult(
            success=False,
            exit_code=2,
            status="configuration_required",
            message="Configuration Required: " + ", ".join(missing),
            diagnostics=diagnostics,
        )

    smoke_input_path = Path(config.smoke_input_path)
    if not smoke_input_path.is_file():
        diagnostics = _converter_configuration_diagnostics(
            config,
            converter_type="cli",
            configured=True,
        )
        diagnostics.update(
            {
                "status": "missing_input",
                "missing": ["engineering_converter_smoke_input_path"],
                "smoke_input_exists": False,
            }
        )
        return EngineeringConverterSmokeResult(
            success=False,
            exit_code=2,
            status="missing_input",
            message=f"Configuration Required: smoke input file does not exist: {smoke_input_path}",
            diagnostics=diagnostics,
        )

    converter = get_engineering_converter(active_settings)
    conversion = converter.convert(str(smoke_input_path))
    diagnostics = dict(conversion.diagnostics)
    diagnostics.update(
        {
            "smoke_input_path": str(smoke_input_path),
            "smoke_input_exists": True,
            "smoke_status": conversion.status,
        }
    )

    if conversion.success:
        return EngineeringConverterSmokeResult(
            success=True,
            exit_code=0,
            status=conversion.status,
            message=(
                f"Real converter smoke passed: {smoke_input_path.name} -> {conversion.output_path}"
            ),
            diagnostics=diagnostics,
            conversion=conversion,
        )

    command_exit_code = conversion.command_exit_code
    if command_exit_code is None or command_exit_code == 0:
        exit_code = 1
    else:
        exit_code = command_exit_code
    return EngineeringConverterSmokeResult(
        success=False,
        exit_code=exit_code,
        status=conversion.status,
        message=_smoke_failure_message(conversion),
        diagnostics=diagnostics,
        conversion=conversion,
    )


def format_engineering_converter_smoke_report(result: EngineeringConverterSmokeResult) -> str:
    """Format a bounded, human-readable smoke report for operators."""
    lines = ["CAD/export converter smoke"]
    lines.append(f"  status: {result.status}")
    lines.append(f"  success: {result.success}")
    lines.append(f"  exit_code: {result.exit_code}")
    lines.append(f"  message: {result.message}")
    diagnostics = result.diagnostics
    if diagnostics:
        lines.append("  diagnostics:")
        for key in (
            "converter_type",
            "configured",
            "missing",
            "smoke_input_path",
            "smoke_input_exists",
            "source_extension",
            "output_path",
            "command_exit_code",
            "timeout_seconds",
            "output_size",
        ):
            if key in diagnostics:
                value = diagnostics[key]
                if value in (None, "", [], {}):
                    continue
                lines.append(f"    {key}: {value}")

        if result.conversion is not None:
            if result.conversion.warnings:
                lines.append(f"    warnings: {list(result.conversion.warnings)}")
            if result.conversion.error:
                lines.append(f"    error: {result.conversion.error}")
            stdout_excerpt = result.conversion.diagnostics.get("stdout_excerpt")
            if stdout_excerpt:
                lines.append(
                    "    stdout_excerpt: " + _smoke_excerpt_for_report(_coerce_text(stdout_excerpt))
                )
            stderr_excerpt = result.conversion.diagnostics.get("stderr_excerpt")
            if stderr_excerpt:
                lines.append(
                    "    stderr_excerpt: " + _smoke_excerpt_for_report(_coerce_text(stderr_excerpt))
                )
    return "\n".join(lines)


def _smoke_failure_message(conversion: ConversionResult) -> str:
    if conversion.error:
        return f"CAD/export converter smoke failed ({conversion.status}): {conversion.error}"
    return f"CAD/export converter smoke failed ({conversion.status})"


def _smoke_excerpt_for_report(text: str, *, limit: int = 240) -> str:
    normalized = text.replace("\n", "\\n")
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit] + "...[truncated]"


def _converter_configuration_diagnostics(
    config: _EngineeringConverterConfig,
    *,
    converter_type: str,
    configured: bool,
    reason: str | None = None,
) -> dict[str, Any]:
    diagnostics: dict[str, Any] = {
        "converter_type": converter_type,
        "configured": configured,
        "command_template": config.command_template,
        "timeout_seconds": config.timeout_seconds,
        "output_dir": config.output_dir,
        "output_extension": config.output_extension,
        "normalized_output_extension": config.normalized_output_extension,
        "smoke_input_path": config.smoke_input_path,
        "supported_extensions": sorted(_SUPPORTED_CAD_EXPORT_EXTENSION_SET),
    }
    if reason is not None:
        diagnostics["reason"] = reason
    return diagnostics


def _base_diagnostics(
    config: _EngineeringConverterConfig,
    *,
    source_path: str,
    source_extension: str,
    output_path: str | None,
    converter_type: str,
    configured: bool,
    status: str,
    command: list[str],
) -> dict[str, Any]:
    diagnostics = _converter_configuration_diagnostics(
        config,
        converter_type=converter_type,
        configured=configured,
    )
    diagnostics.update(
        {
            "status": status,
            "source_basename": Path(source_path).name,
            "source_extension": source_extension,
            "output_path": output_path,
            "command": command,
        }
    )
    return diagnostics


def _build_command_argv(
    command_template: str,
    *,
    input_path: str,
    output_path: str,
) -> list[str]:
    if _validate_command_template(command_template) is not None:
        raise ValueError(_validate_command_template(command_template))

    rendered = command_template.format(
        input=shlex.quote(input_path),
        output=shlex.quote(output_path),
    )
    try:
        argv = shlex.split(rendered)
    except ValueError as exc:
        raise ValueError(f"converter command template could not be tokenized: {exc}") from exc
    if not argv:
        raise ValueError("converter command template did not produce a command")
    return argv


def _validate_command_template(command_template: str) -> str | None:
    if not command_template.strip():
        return "engineering converter command template is not configured"

    fields: set[str] = set()
    try:
        for _literal_text, field_name, format_spec, conversion in Formatter().parse(
            command_template
        ):
            if field_name is None:
                continue
            if format_spec or conversion:
                return (
                    "engineering converter command template must use plain {input} and {output} "
                    "placeholders"
                )
            fields.add(field_name)
    except ValueError as exc:
        return f"engineering converter command template is invalid: {exc}"

    missing_fields = _ALLOWED_TEMPLATE_FIELDS - fields
    if missing_fields:
        return (
            "engineering converter command template must include "
            f"{', '.join(sorted(missing_fields))} placeholder(s)"
        )

    unsupported_fields = fields - _ALLOWED_TEMPLATE_FIELDS
    if unsupported_fields:
        return (
            "engineering converter command template includes unsupported placeholder(s): "
            f"{', '.join(sorted(unsupported_fields))}"
        )

    return None


def _derive_output_path(
    config: _EngineeringConverterConfig,
    source_path: str,
) -> tuple[str | None, str | None]:
    output_dir = config.output_dir.strip()
    if not output_dir:
        return None, "converter output directory is not configured"

    output_extension = config.normalized_output_extension
    if not output_extension.startswith(".") or output_extension == ".":
        return None, "converter output extension must start with a dot"

    source_name = Path(source_path).name
    source_stem = Path(source_name).stem.strip()
    if not source_stem:
        return None, "source file name must not be empty"

    return str(Path(output_dir) / f"{source_stem}{output_extension}"), None


def _source_extension(source_path: str) -> str:
    return Path(source_path).suffix.lower()


def _coerce_text(value: object | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return str(value)


def _excerpt_text(text: str, *, limit: int = _CONVERSION_OUTPUT_EXCERPT_LIMIT) -> tuple[str, bool]:
    clean_text = text or ""
    if len(clean_text) <= limit:
        return clean_text, False
    return clean_text[:limit] + "\n...[truncated]", True


def _excerpt_warnings(*, stdout_truncated: bool, stderr_truncated: bool) -> list[str]:
    warnings: list[str] = []
    if stdout_truncated:
        warnings.append("converter_stdout_truncated")
    if stderr_truncated:
        warnings.append("converter_stderr_truncated")
    return warnings


def _build_exit_error(exit_code: int, stderr_excerpt: str) -> str:
    if stderr_excerpt:
        return f"converter exited with code {exit_code}: {stderr_excerpt}"
    return f"converter exited with code {exit_code}"


__all__ = [
    "CLIEngineeringConverter",
    "ConversionResult",
    "ConversionStatus",
    "EngineeringConverter",
    "EngineeringConverterSmokeResult",
    "MissingEngineeringConverter",
    "format_engineering_converter_smoke_report",
    "get_engineering_converter",
    "run_engineering_converter_smoke",
]

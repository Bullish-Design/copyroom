"""Explicit Templateer generation with frozen artifact provenance."""

from __future__ import annotations

import base64
import importlib.metadata
import re
from pathlib import Path
from typing import Any

from templateer.api import TemplateRegistry
from templateer.constants import DEFAULT_MODEL

from .composer import (
    FileEntry,
    RenderPlan,
    digest_bytes,
    digest_composer,
    digest_source,
    digest_templateer,
    plan_digest,
    safe_output_path,
)
from .errors import LocalError
from .source import marker
from .workflow import _attach_layer, _layer_record, preview


def _generation(
    source: Path,
    template_name: str,
    request: str,
    model_name: str,
    context: dict[str, Any],
    max_attempts: int,
) -> tuple[RenderPlan, dict[str, Any]]:
    """Call Templateer and return a validated frozen render plan."""

    source = source.absolute()
    if source.is_symlink():
        raise LocalError(f"source must not be a symlink: {source}")
    before_source = digest_source(source)
    before_templateer = digest_templateer()
    try:
        registry = TemplateRegistry.from_paths([source / "templates"])
        template = registry.get_template(template_name)
    except Exception as exc:
        raise LocalError(f"cannot load Templateer artifact {template_name}: {exc}") from exc
    if template.metadata.output.kind != "full_file":
        raise LocalError("generation requires a full_file Templateer artifact", 3)
    try:
        result = registry.generate(
            template_name=template_name,
            user_request=request,
            context=context,
            model_name=model_name,
            max_attempts=max_attempts,
        )
    except Exception as exc:
        raise LocalError(f"Templateer generation failed: {exc}") from exc
    if not result.succeeded:
        raise LocalError(
            f"Templateer generation failed ({result.failure_reason}): {result.error_detail or 'no detail'}",
        )
    if result.kind != "full_file" or not isinstance(result.model, dict) or not isinstance(result.artifact, str):
        raise LocalError("Templateer returned an incomplete full-file result")
    normalized = template.get_schema_class().model_validate(result.model).model_dump(mode="json")
    errors, warnings = registry.validate_artifact(template_name, result.artifact, model_data=normalized)
    if errors or warnings:
        raise LocalError(f"{template_name}: validation findings: errors={errors!r}; warnings={warnings!r}")
    raw_path = result.output_path or template.metadata.output.path
    output_path = safe_output_path(raw_path, normalized)
    artifact = result.artifact.encode("utf-8")
    if digest_source(source) != before_source or digest_templateer() != before_templateer:
        raise LocalError("source or Templateer changed during generation", 1)
    files = {output_path: FileEntry("file", artifact, 0o644)}
    plan = RenderPlan(
        files=files,
        owners={output_path: f"generated:{template_name}"},
        answers=normalized,
        source_digest=before_source,
        manifest_digest=digest_bytes((source / "manifest.json").read_bytes()),
        templateer_version=importlib.metadata.version("templateer"),
        templateer_digest=before_templateer,
        composer_digest=digest_composer(),
        render_digest=plan_digest(files),
    )
    metadata = {
        "template_name": template_name,
        "output_path": output_path,
        "request": request,
        "model_name": model_name,
        "model": normalized,
        "artifact_base64": base64.b64encode(artifact).decode("ascii"),
        "artifact_sha256": digest_bytes(artifact),
        "template_source_digest": before_source,
        "templateer_digest": before_templateer,
        "provider_revision": "unknown",
        "usage": result.usage,
        "attempt": result.attempt,
        "mode": 0o644,
    }
    return plan, metadata


def generate(
    project: Path,
    source: Path,
    template_name: str,
    request: str,
    model_name: str = DEFAULT_MODEL,
    context: dict[str, Any] | None = None,
    max_attempts: int = 3,
) -> dict[str, str]:
    """Generate and attach one artifact after an explicit provider request."""

    plan, metadata = _generation(source, template_name, request, model_name, context or {}, max_attempts)
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", template_name).strip("-") or "artifact"
    layer = f"gen-{slug}"
    return _attach_layer(project, source, plan, layer, metadata)


def refresh(
    project: Path,
    layer: str,
    out: Path,
    request: str,
    source_override: Path | None = None,
    model_name: str = DEFAULT_MODEL,
    context: dict[str, Any] | None = None,
    max_attempts: int = 3,
) -> dict[str, Any]:
    """Generate a replacement artifact and preview it for review."""

    project = project.absolute()
    data = marker(project)
    record = _layer_record(data, layer)
    if record.get("kind") != "generated" or not isinstance(record.get("generation"), dict):
        raise LocalError(f"layer is not a generated artifact owner: {layer}", 3)
    from .source import resolve_source

    source = resolve_source(project, data, source_override, record)
    template_name = str(record["generation"]["template_name"])
    plan, metadata = _generation(
        source, template_name, request, model_name, context or {}, max_attempts,
    )
    if plan.owners != record["owners"]:
        raise LocalError("refresh changed the generated artifact path; use an explicit ownership transfer", 1)
    return preview(
        project,
        out,
        source_override=source,
        layer=layer,
        plan_override=plan,
        record_metadata=metadata,
    )


__all__ = ["generate", "refresh"]

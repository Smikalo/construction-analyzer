"""Tests for converted drawing artifact extraction helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

import app.services.converted_drawing_elements as converted_drawing_elements
from app.services.engineering_converters import ConversionResult


class FakePage:
    def __init__(self, text: str | None) -> None:
        self._text = text

    def extract_text(self) -> str | None:
        return self._text


def test_extract_converted_drawing_emits_exact_text_layer_summary_and_fact_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_path = tmp_path / "north.PDF"
    artifact_path.write_bytes(b"%PDF-1.7\n")
    source_path = tmp_path / "input" / "north.dwg"
    source_path.parent.mkdir(parents=True)
    source_path.write_text("source placeholder", encoding="utf-8")

    conversion = ConversionResult(
        success=True,
        status="success",
        output_path=str(artifact_path),
        warnings=("converter_note", "converter_note"),
        diagnostics={
            "layers": ["A-WALL"],
            "views": ["Level 1"],
            "entities": ["Door 7"],
            "stdout": "sensitive stdout should not be copied",
            "stderr": "sensitive stderr should not be copied",
        },
        source_extension=".DWG",
    )

    class FakePdfReader:
        def __init__(self, reader_path: str) -> None:
            assert reader_path == str(artifact_path)
            self.pages = [
                FakePage("Label: North entry\nDimension: 12'-0\""),
                FakePage(
                    "Layer: A-WALL\nView: Level 1\nEntity: Door 7\nRevision: R3\nNote: verify field"
                ),
            ]

    monkeypatch.setattr(converted_drawing_elements, "PdfReader", FakePdfReader)

    elements = converted_drawing_elements.extract_converted_drawing(
        str(artifact_path),
        source="north.dwg",
        source_path=str(source_path),
        conversion=conversion,
        document_id="doc-1",
    )

    assert [element.element_type for element in elements] == [
        "drawing",
        "drawing_fact",
        "drawing_fact",
        "drawing_fact",
        "drawing_fact",
        "drawing_fact",
        "drawing_fact",
        "drawing_fact",
    ]

    summary = elements[0]
    assert summary.document_id == "doc-1"
    assert summary.source == "north.dwg"
    assert summary.path == str(artifact_path)
    assert summary.page is None
    assert summary.element_type == "drawing"
    assert summary.extraction_mode == "converted_drawing_text_summary"
    assert summary.content == (
        "Subject: converted_drawing\n"
        "Source CAD file: north.dwg\n"
        f"Source CAD path: {source_path}\n"
        f"Derived artifact path: {artifact_path}\n"
        "Conversion status: success\n"
        "Conversion source extension: .dwg\n"
        "Artifact extension: .pdf\n"
        "Text layer mode: exact\n"
        "Pages: 2\n"
        "Text pages: 2\n"
        "Exact facts: 7\n"
        "Fact kinds: label, dimension, layer, entity_view, revision_marker, visible_note\n"
        "Conversion warnings: converter_note\n"
        "Layers: A-WALL\n"
        "Views: Level 1\n"
        "Entities: Door 7"
    )
    assert summary.confidence == 1.0
    assert summary.warnings == ("converter_note",)
    assert summary.metadata == {
        "subject": "converted_drawing",
        "source_cad_file": "north.dwg",
        "source_cad_path": str(source_path),
        "derived_artifact_path": str(artifact_path),
        "conversion_status": "success",
        "conversion_source_extension": ".dwg",
        "conversion_warnings": ["converter_note"],
        "drawing_artifact_extension": ".pdf",
        "conversion_diagnostics": {
            "layers": ["A-WALL"],
            "views": ["Level 1"],
            "entities": ["Door 7"],
        },
        "drawing_fact_type": "summary",
        "drawing_page_count": 2,
        "drawing_text_page_count": 2,
        "drawing_fact_count": 7,
        "drawing_fact_types": [
            "label",
            "dimension",
            "layer",
            "entity_view",
            "revision_marker",
            "visible_note",
        ],
        "drawing_layers": ["A-WALL"],
        "drawing_views": ["Level 1"],
        "drawing_entities": ["Door 7"],
    }

    facts = elements[1:]
    assert [element.page for element in facts] == [1, 1, 2, 2, 2, 2, 2]
    assert [element.extraction_mode for element in facts] == [
        "converted_drawing_text_fact",
        "converted_drawing_text_fact",
        "converted_drawing_text_fact",
        "converted_drawing_text_fact",
        "converted_drawing_text_fact",
        "converted_drawing_text_fact",
        "converted_drawing_text_fact",
    ]
    assert [element.content for element in facts] == [
        "Label: North entry",
        "Dimension: 12'-0\"",
        "Layer: A-WALL",
        "View: Level 1",
        "Entity: Door 7",
        "Revision: R3",
        "Note: verify field",
    ]
    assert [element.metadata["drawing_fact_type"] for element in facts] == [
        "label",
        "dimension",
        "layer",
        "entity_view",
        "entity_view",
        "revision_marker",
        "visible_note",
    ]
    assert [element.metadata["drawing_fact_value"] for element in facts] == [
        "North entry",
        "12'-0\"",
        "A-WALL",
        "Level 1",
        "Door 7",
        "R3",
        "verify field",
    ]
    assert [element.metadata["drawing_fact_subtype"] for element in facts[3:5]] == [
        "view",
        "entity",
    ]
    assert all(element.warnings == ("converter_note",) for element in facts)
    assert all(element.metadata["source_cad_file"] == "north.dwg" for element in facts)
    assert all(element.metadata["source_cad_path"] == str(source_path) for element in facts)
    assert all(element.metadata["derived_artifact_path"] == str(artifact_path) for element in facts)
    assert all(element.metadata["conversion_status"] == "success" for element in facts)
    assert all(element.metadata["conversion_source_extension"] == ".dwg" for element in facts)
    assert all(element.metadata["conversion_warnings"] == ["converter_note"] for element in facts)
    assert all(element.metadata["drawing_artifact_extension"] == ".pdf" for element in facts)
    assert all(
        element.metadata["conversion_diagnostics"]
        == {
            "layers": ["A-WALL"],
            "views": ["Level 1"],
            "entities": ["Door 7"],
        }
        for element in facts
    )


def test_extract_converted_drawing_emits_warning_bearing_summary_for_textless_artifacts(
    tmp_path: Path,
) -> None:
    artifact_path = tmp_path / "site.PNG"
    artifact_path.write_bytes(b"binary image payload")
    source_path = tmp_path / "input" / "site.dwg"
    source_path.parent.mkdir(parents=True)
    source_path.write_text("source placeholder", encoding="utf-8")

    conversion = ConversionResult(
        success=True,
        status="success",
        output_path=str(artifact_path),
        warnings=("converter_note", "converter_note"),
        diagnostics={
            "layers": ["A-REF"],
            "views": ["Site Plan"],
            "entities": ["Door 7"],
            "page_count": 1,
            "stdout": "sensitive stdout should not be copied",
        },
        source_extension=".DWG",
    )

    elements = converted_drawing_elements.extract_converted_drawing(
        str(artifact_path),
        source="site.dwg",
        source_path=str(source_path),
        conversion=conversion,
        document_id="doc-2",
    )

    assert elements == [
        converted_drawing_elements.DocumentElement(
            document_id="doc-2",
            source="site.dwg",
            path=str(artifact_path),
            page=None,
            element_type="drawing",
            extraction_mode="converted_drawing_visual_summary",
            content=(
                "Subject: converted_drawing\n"
                "Source CAD file: site.dwg\n"
                f"Source CAD path: {source_path}\n"
                f"Derived artifact path: {artifact_path}\n"
                "Conversion status: success\n"
                "Conversion source extension: .dwg\n"
                "Artifact extension: .png\n"
                "Text layer mode: visual-only\n"
                "Pages: 1\n"
                "Text pages: 0\n"
                "Exact facts: 0\n"
                "Fact kinds: none\n"
                "Conversion warnings: converter_note\n"
                "Warnings: converted_artifact_no_text_layer\n"
                "Layers: A-REF\n"
                "Views: Site Plan\n"
                "Entities: Door 7"
            ),
            confidence=0.35,
            warnings=("converter_note", "converted_artifact_no_text_layer"),
            metadata={
                "subject": "converted_drawing",
                "source_cad_file": "site.dwg",
                "source_cad_path": str(source_path),
                "derived_artifact_path": str(artifact_path),
                "conversion_status": "success",
                "conversion_source_extension": ".dwg",
                "conversion_warnings": ["converter_note"],
                "drawing_artifact_extension": ".png",
                "conversion_diagnostics": {
                    "layers": ["A-REF"],
                    "views": ["Site Plan"],
                    "entities": ["Door 7"],
                    "page_count": 1,
                },
                "drawing_fact_type": "summary",
                "drawing_page_count": 1,
                "drawing_text_page_count": 0,
                "drawing_fact_count": 0,
                "drawing_fact_types": [],
                "drawing_layers": ["A-REF"],
                "drawing_views": ["Site Plan"],
                "drawing_entities": ["Door 7"],
            },
        )
    ]


def test_extract_converted_drawing_rejects_unsupported_artifact_extension(
    tmp_path: Path,
) -> None:
    artifact_path = tmp_path / "north.svg"
    artifact_path.write_text("<svg />", encoding="utf-8")

    with pytest.raises(
        ValueError,
        match=r"unsupported converted drawing artifact extension: \.svg",
    ):
        converted_drawing_elements.extract_converted_drawing(
            str(artifact_path),
            source="north.dwg",
            conversion=None,
        )


def test_extract_converted_drawing_propagates_pdf_reader_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_path = tmp_path / "broken.PDF"
    artifact_path.write_bytes(b"%PDF-1.7\n")

    class BrokenPdfReader:
        def __init__(self, reader_path: str) -> None:
            assert reader_path == str(artifact_path)
            raise RuntimeError("pdf parse failed")

    monkeypatch.setattr(converted_drawing_elements, "PdfReader", BrokenPdfReader)

    with pytest.raises(RuntimeError, match="pdf parse failed"):
        converted_drawing_elements.extract_converted_drawing(
            str(artifact_path),
            source="broken.dwg",
            conversion=None,
        )

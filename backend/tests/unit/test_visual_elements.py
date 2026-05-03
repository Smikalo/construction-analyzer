"""Tests for visual summary normalization helpers."""

from __future__ import annotations

import pytest

from app.services.visual_elements import (
    APPROXIMATE_VALUE_WARNING,
    VISUAL_ELEMENT_TYPES,
    VISUAL_EXTRACTION_MODE,
    visual_element_from_summary,
)


def test_visual_constants_match_visual_summary_contract() -> None:
    assert VISUAL_ELEMENT_TYPES == ("chart", "diagram", "drawing", "image")
    assert VISUAL_EXTRACTION_MODE == "visual_summary"
    assert APPROXIMATE_VALUE_WARNING == "approximate_values"


@pytest.mark.parametrize("element_type", VISUAL_ELEMENT_TYPES)
def test_allowed_visual_types_set_element_type(element_type: str) -> None:
    element = visual_element_from_summary(
        "Site sketch",
        element_type=element_type,
        source="figure.png",
    )

    assert element is not None
    assert element.element_type == element_type
    assert element.extraction_mode == VISUAL_EXTRACTION_MODE


@pytest.mark.parametrize("element_type", ["paragraph", "table", "chartish", ""])
def test_invalid_visual_types_raise_value_error(element_type: str) -> None:
    with pytest.raises(ValueError, match="unsupported visual element type"):
        visual_element_from_summary("Sketch", element_type=element_type, source="figure.png")


@pytest.mark.parametrize("summary", [None, "", "   \n\t  "])
def test_blank_visual_output_without_facts_returns_none(summary: str | None) -> None:
    assert (
        visual_element_from_summary(
            summary,
            element_type="diagram",
            source="figure.png",
        )
        is None
    )


@pytest.mark.parametrize(
    ("labels", "relationships", "uncertainty", "expected_content", "expected_metadata"),
    [
        (
            ("North edge",),
            (),
            None,
            "Labels: North edge",
            {"visual_summary_chars": 0, "labels": ["North edge"]},
        ),
        (
            (),
            ("Roof -> Wall",),
            None,
            "Relationships: Roof -> Wall",
            {"visual_summary_chars": 0, "relationships": ["Roof -> Wall"]},
        ),
        (
            (),
            (),
            "approximate from field notes",
            "Uncertainty: approximate from field notes",
            {
                "visual_summary_chars": 0,
                "uncertainty": "approximate from field notes",
            },
        ),
    ],
)
def test_blank_summary_can_still_render_other_visual_facts(
    labels: tuple[object | None, ...],
    relationships: tuple[object | None, ...],
    uncertainty: str | None,
    expected_content: str,
    expected_metadata: dict[str, object],
) -> None:
    element = visual_element_from_summary(
        "   \n  ",
        element_type="drawing",
        source="figure.png",
        labels=labels,
        relationships=relationships,
        uncertainty=uncertainty,
    )

    assert element is not None
    assert element.content == expected_content
    assert element.metadata == expected_metadata


def test_visual_summary_renders_content_in_deterministic_order() -> None:
    element = visual_element_from_summary(
        "  Roof plan\nwith notes  ",
        element_type="chart",
        source="roof.png",
        document_id="doc-visual",
        path="backend/data/documents/roof.png",
        page=8,
        confidence=0.72,
        labels=("  Roof  ", "  Beam  "),
        relationships=("Roof supports Beam", "  Roof -> Wall "),
        uncertainty="  approximate from scaled screenshot  ",
        approximate=True,
        warnings=("existing_warning", APPROXIMATE_VALUE_WARNING),
        metadata={"captured_by": "parser", "labels": ["caller label"], "custom": "kept"},
    )

    assert element is not None
    assert element.document_id == "doc-visual"
    assert element.source == "roof.png"
    assert element.path == "backend/data/documents/roof.png"
    assert element.page == 8
    assert element.confidence == 0.72
    assert element.element_type == "chart"
    assert element.extraction_mode == VISUAL_EXTRACTION_MODE
    assert element.content == (
        "Roof plan with notes\n"
        "Labels: Roof; Beam\n"
        "Relationships: Roof supports Beam; Roof -> Wall\n"
        "Uncertainty: approximate from scaled screenshot"
    )
    assert element.warnings == ("existing_warning", APPROXIMATE_VALUE_WARNING)
    assert element.metadata == {
        "visual_summary_chars": len("Roof plan with notes"),
        "labels": ["caller label"],
        "relationships": ["Roof supports Beam", "Roof -> Wall"],
        "uncertainty": "approximate from scaled screenshot",
        "approximate": True,
        "captured_by": "parser",
        "custom": "kept",
    }


def test_visual_summary_ignores_blank_items_after_whitespace_normalization() -> None:
    element = visual_element_from_summary(
        "  Axis labels  ",
        element_type="image",
        source="render.png",
        labels=("  ", None, "North", "\t", "South"),
        relationships=("", "  North -> South  "),
        uncertainty=" \n ",
    )

    assert element is not None
    assert element.content == ("Axis labels\nLabels: North; South\nRelationships: North -> South")
    assert element.metadata == {
        "visual_summary_chars": len("Axis labels"),
        "labels": ["North", "South"],
        "relationships": ["North -> South"],
    }


def test_approximate_warning_is_added_once_when_already_present() -> None:
    element = visual_element_from_summary(
        "  Area estimate  ",
        element_type="diagram",
        source="diagram.png",
        approximate=True,
        warnings=("existing", APPROXIMATE_VALUE_WARNING, "existing"),
    )

    assert element is not None
    assert element.content == "Area estimate"
    assert element.warnings == ("existing", APPROXIMATE_VALUE_WARNING)
    assert element.metadata == {
        "visual_summary_chars": len("Area estimate"),
        "approximate": True,
    }

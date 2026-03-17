from __future__ import annotations

from rime_ui.shortcuts import (
    ACCEPT_GHOST,
    DELETE_SELECTION,
    MOVE_BACKWARD,
    RUN_INFERENCE,
    SHOW_SHORTCUTS,
    build_shortcut_sections,
    display_shortcut,
    resolve_shortcuts,
    shortcut_aliases,
)


def test_shortcut_catalog_has_expected_sections_and_bindings() -> None:
    sections = build_shortcut_sections()
    section_titles = [section.title for section in sections]

    assert section_titles == [
        "Playback",
        "Annotation Editing",
        "Timeline Selection",
        "Panels And Layout",
        "Session And Models",
        "Help",
    ]

    entries = {
        (entry.shortcut, entry.action)
        for section in sections
        for entry in section.entries
    }
    assert ("Space", "Play or pause the active video") in entries
    assert ("Return / Enter", "Accept the selected ghost annotation") in entries
    delete_entry = next(
        action
        for shortcut, action in entries
        if action == "Delete the selected annotation or snap point, or reject a ghost"
    )
    delete_shortcut = next(
        shortcut
        for shortcut, action in entries
        if action == "Delete the selected annotation or snap point, or reject a ghost"
    )
    assert set(delete_shortcut.split(" / ")) == {"Delete", "Backspace"}
    assert delete_entry == "Delete the selected annotation or snap point, or reject a ghost"
    assert ("F5", "Show or hide the annotation list") in entries
    assert ("F6", "Show or hide the model runner panel") in entries
    assert ("F7", "Show or hide the model evaluation panel") in entries
    assert ("F8", "Show or hide the clinical outcomes panel") in entries
    assert ("F9", "Show or hide the IRR panel") in entries
    assert ("Ctrl+R", "Run inference with the active model") in entries
    assert ("F1", "Open Preferences on the Shortcuts tab") in entries


def test_shortcut_catalog_display_labels_are_unique() -> None:
    labels = [entry.shortcut for section in build_shortcut_sections() for entry in section.entries]

    assert len(labels) == len(set(labels))


def test_shortcut_overrides_can_rebind_or_unbind_entries() -> None:
    resolved = resolve_shortcuts(
        {
            ACCEPT_GHOST: "A",
            DELETE_SELECTION: "",
            SHOW_SHORTCUTS: "Ctrl+/",
            MOVE_BACKWARD: "A",
        }
    )

    assert resolved[ACCEPT_GHOST] == "A"
    assert resolved[DELETE_SELECTION] == ""
    assert resolved[RUN_INFERENCE] == "Ctrl+R"
    assert resolved[MOVE_BACKWARD] == "Left"


def test_shortcut_display_and_aliases_expand_common_equivalents() -> None:
    assert set(shortcut_aliases("Delete")) == {"Delete", "Backspace"}
    assert shortcut_aliases("Return") == ("Return", "Enter")
    assert set(display_shortcut("Delete").split(" / ")) == {"Delete", "Backspace"}

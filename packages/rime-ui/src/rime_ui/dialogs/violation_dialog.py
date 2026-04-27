"""Rule violation dialog with optional auto-fix action."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtWidgets import QMessageBox, QWidget

from rime_core.rule_engine import Violation


@dataclass
class ViolationDecision:
    """User decision for a violation prompt."""

    apply_fix: bool = False


class ViolationDialog:
    """Helper for presenting violations and collecting user decisions."""

    @staticmethod
    def fix_label(violation: Violation) -> str:
        """Return the user-facing label for applying a violation fix."""
        if violation.rule_action == "coincidence" and violation.fix_annotation is not None:
            return f"Auto-Create {violation.fix_annotation.lane}"
        if violation.rule_action == "must_not_overlap":
            return "Clip & Continue"
        return "Apply Fix"

    @staticmethod
    def ask(violation: Violation, parent: QWidget | None = None) -> ViolationDecision:
        """Show a violation dialog and return user action."""
        source = violation.source_annotation
        detail = f"{source.lane}/{source.label} [{int(source.start_ms)}ms - {int(source.end_ms)}ms]"

        if not violation.can_auto_fix or violation.fix_annotation is None:
            QMessageBox.warning(parent, "Rule Violation", f"{violation.message}\n\n{detail}")
            return ViolationDecision(apply_fix=False)

        msg = QMessageBox(parent)
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setWindowTitle("Rule Violation")
        msg.setText(f"{violation.message}\n\n{detail}")
        msg.setInformativeText("Apply automatic fix?")

        ignore_button = msg.addButton("Ignore", QMessageBox.ButtonRole.RejectRole)
        fix_button = msg.addButton(ViolationDialog.fix_label(violation), QMessageBox.ButtonRole.AcceptRole)
        msg.setDefaultButton(fix_button)
        msg.exec()
        return ViolationDecision(apply_fix=msg.clickedButton() is fix_button and ignore_button is not None)

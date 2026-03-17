"""Schema-driven rule engine for annotation side effects and violations."""

from __future__ import annotations

from dataclasses import dataclass, replace

from rime_core.annotations import Annotation, AnnotationStore, generate_id
from rime_core.schema import ProtocolSchema


@dataclass
class SideEffect:
    """An auto-created annotation to add to the store."""

    annotation: Annotation


@dataclass
class Violation:
    """A rule violation to present to the user."""

    rule_action: str
    message: str
    source_annotation: Annotation
    can_auto_fix: bool = False
    fix_annotation: Annotation | None = None


class RuleEngine:
    """Executes rule declarations from schema rules."""

    def __init__(self, schema: ProtocolSchema) -> None:
        self.rules = schema.rules
        self._schema = schema

    def on_create(
        self, annotation: Annotation, store: AnnotationStore
    ) -> tuple[list[SideEffect], list[Violation]]:
        """Evaluate create-trigger rules against one newly created annotation."""
        side_effects: list[SideEffect] = []
        violations: list[Violation] = []

        for rule in self._rules_for_trigger("create", annotation):
            action = rule.get("action")
            if action == "auto_create":
                effect = self._auto_create(rule, annotation, store)
                if effect:
                    side_effects.append(effect)
            elif action == "must_be_subset_of":
                violation = self._must_be_subset_of(rule, annotation, store)
                if violation:
                    violations.append(violation)
            elif action == "must_not_overlap":
                violations.extend(self._must_not_overlap(rule, annotation, store))

        return side_effects, violations

    def on_import(self, store: AnnotationStore) -> tuple[list[SideEffect], list[Violation]]:
        """Evaluate create-trigger rules for all imported annotations."""
        side_effects: list[SideEffect] = []
        violations: list[Violation] = []

        originals = store.all()
        for ann in originals:
            new_effects, new_violations = self.on_create(ann, store)
            violations.extend(new_violations)
            for effect in new_effects:
                store.add(effect.annotation)
                side_effects.append(effect)

        return side_effects, violations

    def validate(self, store: AnnotationStore) -> list[Violation]:
        """Run validate-trigger rules against a full annotation store."""
        violations: list[Violation] = []

        for rule in self._rules_for_trigger("validate"):
            action = rule.get("action")
            if action != "coincidence":
                continue

            on_lane = rule.get("on_lane")
            if not on_lane:
                continue

            on_label = rule.get("on_label")
            for ann in store.get_by_lane(on_lane):
                if on_label and ann.label != on_label:
                    continue

                if not self._has_coincidence(rule, ann, store):
                    target_lane = rule.get("target_lane", "")
                    target_label = rule.get("target_label", "")
                    fix = Annotation(
                        id=generate_id(),
                        lane=target_lane,
                        label=target_label or self._default_label_for_lane(target_lane),
                        start_ms=ann.start_ms,
                        end_ms=ann.start_ms if self._schema.is_point_lane(target_lane) else ann.end_ms,
                        event_type="point" if self._schema.is_point_lane(target_lane) else "interval",
                        source="rule:auto_create",
                        ghost=bool(rule.get("ghost", False)),
                    )
                    violations.append(
                        Violation(
                            rule_action="coincidence",
                            message=rule.get(
                                "message",
                                f"{ann.lane}/{ann.label} must coincide with "
                                f"{target_lane}/{target_label or '*'}",
                            ),
                            source_annotation=ann,
                            can_auto_fix=True,
                            fix_annotation=fix,
                        )
                    )

        return violations

    def _rules_for_trigger(
        self, trigger: str, annotation: Annotation | None = None
    ) -> list[dict]:
        result: list[dict] = []
        accepted = {trigger, f"on_{trigger}"}
        for rule in self.rules:
            if rule.get("trigger") not in accepted:
                continue
            if annotation is None:
                result.append(rule)
                continue

            if rule.get("on_lane") != annotation.lane:
                continue

            on_label = rule.get("on_label")
            if on_label and on_label != annotation.label:
                continue

            result.append(rule)
        return result

    def _auto_create(
        self, rule: dict, annotation: Annotation, store: AnnotationStore
    ) -> SideEffect | None:
        target_lane = rule.get("target_lane")
        if not target_lane:
            return None

        target_label = rule.get("target_label") or self._default_label_for_lane(target_lane)
        start_ms = annotation.start_ms
        end_ms = annotation.end_ms
        ghost = bool(rule.get("ghost", False))
        is_point_lane = self._schema.is_point_lane(target_lane)
        if is_point_lane:
            end_ms = start_ms

        for existing in store.get_by_lane(target_lane):
            if (
                existing.label == target_label
                and abs(existing.start_ms - start_ms) < 0.001
                and abs(existing.end_ms - end_ms) < 0.001
            ):
                return None

        created = Annotation(
            id=generate_id(),
            lane=target_lane,
            label=target_label,
            start_ms=start_ms,
            end_ms=end_ms,
            event_type="point" if is_point_lane else "interval",
            source="rule:auto_create",
            ghost=ghost,
        )
        return SideEffect(annotation=created)

    def _must_be_subset_of(
        self, rule: dict, annotation: Annotation, store: AnnotationStore
    ) -> Violation | None:
        target_lane = rule.get("target_lane")
        if not target_lane:
            return None

        for candidate in store.get_by_lane(target_lane):
            if annotation.is_subset_of(candidate):
                return None

        msg = rule.get(
            "message",
            f"{annotation.lane}/{annotation.label} must be within {target_lane}",
        )
        return Violation(
            rule_action="must_be_subset_of",
            message=msg,
            source_annotation=annotation,
        )

    def _must_not_overlap(self, rule: dict, annotation: Annotation, store: AnnotationStore) -> list[Violation]:
        target_lane = rule.get("target_lane")
        if not target_lane:
            return []

        target_label = rule.get("target_label")
        resolution = rule.get("resolution", "")
        violations: list[Violation] = []
        for candidate in store.get_by_lane(target_lane):
            if target_label and candidate.label != target_label:
                continue
            if not annotation.overlaps(candidate):
                continue

            can_fix = False
            fix_annotation: Annotation | None = None
            if resolution == "warn_and_clip":
                fix = self._clip_to_avoid_overlap(annotation, candidate)
                if fix is not None:
                    can_fix = True
                    fix_annotation = fix

            message = rule.get(
                "message",
                f"{annotation.lane}/{annotation.label} overlaps {candidate.lane}/{candidate.label}",
            )
            violations.append(
                Violation(
                    rule_action="must_not_overlap",
                    message=message,
                    source_annotation=annotation,
                    can_auto_fix=can_fix,
                    fix_annotation=fix_annotation,
                )
            )
        return violations

    def _clip_to_avoid_overlap(
        self, source_annotation: Annotation, target_annotation: Annotation
    ) -> Annotation | None:
        clipped_start = source_annotation.start_ms
        clipped_end = source_annotation.end_ms

        if source_annotation.start_ms < target_annotation.start_ms < source_annotation.end_ms:
            clipped_end = target_annotation.start_ms
        elif source_annotation.start_ms < target_annotation.end_ms < source_annotation.end_ms:
            clipped_start = target_annotation.end_ms
        else:
            return None

        if clipped_end - clipped_start < 1:
            return None

        return replace(source_annotation, start_ms=clipped_start, end_ms=clipped_end)

    def _has_coincidence(self, rule: dict, annotation: Annotation, store: AnnotationStore) -> bool:
        target_lane = rule.get("target_lane")
        if not target_lane:
            return True

        target_label = rule.get("target_label")
        for candidate in store.get_by_lane(target_lane):
            if target_label and candidate.label != target_label:
                continue
            if annotation.is_subset_of(candidate):
                return True
        return False

    def _default_label_for_lane(self, lane_name: str) -> str:
        return self._schema.get_default_label(lane_name) or ""

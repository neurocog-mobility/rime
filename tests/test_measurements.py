from dataclasses import FrozenInstanceError, replace
import json

import pytest

from rime_core import Annotation, ProtocolSchema, VideoSource, WorkingContext
from rime_core.outcomes import OutcomeDefinition, Selector
from rime_core.measurements import MeasurementDefinition, MeasurementRecord, calculate, compare


@pytest.fixture
def context(tmp_path):
    # A public synthetic protocol without automatic annotation side effects.
    schema = ProtocolSchema.from_dict({
        'name': 'Measurement check', 'version': '1',
        'lanes': [{'name': name, 'level': i, 'color': '#777777', 'labels': [name],
                   'allow_overlap': True} for i, name in enumerate(['FOG', 'Task'])],
        'groups': [], 'rules': [],
    })
    ctx = WorkingContext.create_workspace(tmp_path / 'work', 'Measurement checks', schema=schema,
                                         videos=[(tmp_path / 'absent.mp4', VideoSource())])
    for id_, lane, start, end in [('a', 'FOG', 10000, 16000), ('b', 'FOG', 14000, 22000),
                                 ('task', 'Task', 0, 60000)]:
        ctx.store.add(Annotation(id=id_, lane=lane, label=lane, start_ms=start, end_ms=end))
    ctx.save()
    return ctx


def definition(**kwargs):
    return MeasurementDefinition(OutcomeDefinition('fog', 'Time frozen', 'percentage_coverage', Selector('FOG')), ((0, 60000),),
                                 review_status='complete', **kwargs)


def test_overlap_scope_clipping_and_contributor_identity(context):
    result = calculate(context.current_revision(), definition())
    assert result.value == 20
    assert result.covered_ms == 12000  # not the 14000 sum of the source durations
    assert len(result.contributors) == 2 and len(result.event_spans) == 1
    scoped = replace(definition(), observation=((15000, 30000),))
    result = calculate(context.current_revision(), scoped)
    assert result.covered_ms == 7000
    assert result.eligible_ms == 15000
    assert result.contributors[0].annotation_id == 'a'
    assert result.contributors[0].original == (10000, 16000)
    assert result.contributors[0].clipped == ((15000, 16000),)


def test_capture_survives_edits_reopening_missing_media_and_copy(context, tmp_path):
    first = context.capture_measurement(definition())
    context.edit_annotation('b', end_ms=25000)
    second = context.capture_measurement(definition())
    assert first.result.value == 20 and second.result.value == 25
    assert first.verify() and second.verify()
    assert first.revision.id != second.revision.id
    reopened = WorkingContext.open(context.workspace.path)
    assert [r.result.value for r in reopened.measurements] == [20, 25]
    copied = reopened.save_workspace_copy(tmp_path / 'copy')
    assert copied.measurements == reopened.measurements
    assert copied.measurements[0].id == first.id
    assert '25000' not in json.dumps(first.revision.domain()['annotation_set']['annotations'])
    differences = compare(first, second)
    assert differences['Annotation set and boundaries']
    assert not differences['Observation scope and exclusions']
    assert str(tmp_path) not in json.dumps(first.to_dict())


def test_dependency_snapshot_is_immutable_and_evidence_change_can_leave_value_unchanged(context):
    first = context.capture_measurement(definition())
    detached = first.revision.domain()
    detached['annotation_set']['annotations'].clear()
    assert first.verify() and len(first.result.contributors) == 2
    with pytest.raises(FrozenInstanceError):
        first.definition.outcome.name = 'Changed'
    context.set_source_offset('video', context.recordings.videos[0].id, 450)
    second = context.capture_measurement(definition())
    assert second.result.value == first.result.value
    changes = compare(first, second)
    assert changes['Source descriptions and timing (evidence)']
    assert not changes['Annotation set and boundaries']
    assert first.revision.domain()['recordings']['videos'][0]['offset_ms'] == 0


def test_scope_change_40_percent_and_union_of_tasks(context):
    first = context.capture_measurement(definition())
    second = context.capture_measurement(replace(definition(), observation=((0, 30000),)))
    assert second.result.value == 40
    assert compare(first, second)['Observation scope and exclusions']
    context.store.add(Annotation(id='task2', lane='Task', label='Task', start_ms=50000, end_ms=80000))
    result = calculate(context.current_revision(), replace(definition(), outcome=replace(definition().outcome, scope=Selector('Task'))))
    assert result.eligible_ms == 60000  # clipped to declared observation, counted once
    assert len(result.scope_contributors) == 2


def test_exclusions_clip_both_sides_without_rounding(context):
    d = replace(definition(), observation=((14000.125, 22000.375),), exclusions=((16000, 18000),))
    result = calculate(context.current_revision(), d)
    assert result.covered_ms == 5999.875
    assert result.eligible_ms == 6000.25
    assert result.event_spans == ((14000.125, 16000), (18000, 22000))


def test_zero_denominator_and_no_events_with_unknown_review_are_explicit(context):
    zero = calculate(context.current_revision(), replace(definition(), observation=((0, 0),)))
    assert zero.value is None and 'zero' in zero.undefined_reason
    no_events = replace(definition(), observation=((0, 5000),), review_status='unknown')
    assert calculate(context.current_revision(), no_events).value is None
    assert calculate(context.current_revision(), replace(no_events, review_status='complete')).value == 0
    unknown = calculate(context.current_revision(), replace(definition(), review_status='incomplete'))
    assert unknown.value == 20 and unknown.eligible_ms == 60000


def test_pending_proposals_and_point_events_do_not_join_retained_coverage(context):
    context.store.add(Annotation(id='proposal', lane='FOG', label='FOG', start_ms=0, end_ms=60000, ghost=True))
    context.store.add(Annotation(id='point', lane='FOG', label='FOG', start_ms=1000, end_ms=1000, event_type='point'))
    assert calculate(context.current_revision(), definition()).value == 20


@pytest.mark.parametrize('damage', ['result', 'revision', 'timeline', 'reference', 'rule', 'version'])
def test_changed_results_and_broken_dependencies_are_rejected(context, damage):
    raw = json.loads(json.dumps(context.capture_measurement(definition()).to_dict()))
    if damage == 'result':
        raw['result']['value'] = 99
    elif damage == 'revision':
        raw['revision']['annotation_set']['annotations'][0]['end_ms'] = 99999
    elif damage == 'timeline':
        raw['revision']['annotation_set']['timeline_id'] = 'missing'
    elif damage == 'reference':
        raw['result']['contributors'][0]['annotation_id'] = 'missing'
    elif damage == 'version':
        raw['version'] = 'unknown'
    else:
        raw['definition']['outcome']['calculation'] = 'unknown'
    with pytest.raises(ValueError):
        MeasurementRecord.from_dict(raw)


def test_failed_capture_is_not_retained_in_memory_or_on_disk(context, monkeypatch):
    def fail():
        raise OSError('Disk full')
    monkeypatch.setattr(context, 'save', fail)
    with pytest.raises(OSError):
        context.capture_measurement(definition())
    assert context.measurements == []
    assert WorkingContext.open(context.workspace.path).measurements == []


@pytest.mark.parametrize('operation,expected,unit', [
    ('covered_duration', 12, 's'), ('percentage_coverage', 20, '%'), ('count', 2, 'count'),
])
def test_three_outcomes_share_inputs_and_reopen(context, operation, expected, unit):
    d = replace(definition(), outcome=replace(definition().outcome, calculation=operation))
    record = context.capture_measurement(d)
    assert record.result.value == expected and record.result.unit == unit
    reopened = WorkingContext.open(context.workspace.path).measurements[0]
    assert reopened == record and reopened.verify()
    if operation == 'count':
        assert type(reopened.result.value) is int


def test_count_is_per_annotation_not_per_merged_span_or_clipped_fragment(context):
    d = replace(definition(), outcome=replace(definition().outcome, calculation='count'),
                observation=((12000, 21000),), exclusions=((15000, 17000),))
    result = calculate(context.current_revision(), d)
    assert result.value == 2
    assert result.contributors[1].clipped == ((14000, 15000), (17000, 21000))
    # Two distinct annotations with identical boundaries still represent two retained entries.
    context.store.add(Annotation(id='same-bounds', lane='FOG', label='FOG', start_ms=10000, end_ms=16000))
    assert calculate(context.current_revision(), d).value == 3
    context.store.add(Annotation(id='pending', lane='FOG', label='FOG', start_ms=12000, end_ms=21000, ghost=True))
    assert calculate(context.current_revision(), d).value == 3


def test_count_points_uses_half_open_scope_and_ignores_pending(context):
    from rime_core.schema import LaneSchema
    context.schema.lanes.append(LaneSchema('Steps', 3, '#777777', ['Step'], lane_type='point'))
    for id_, time, pending in [('start', 1000, False), ('middle', 2000, False),
                              ('end', 3000, False), ('pending', 1500, True)]:
        context.store.add(Annotation(id=id_, lane='Steps', label='Step', start_ms=time, end_ms=time,
                                     event_type='point', ghost=pending))
    d = MeasurementDefinition(OutcomeDefinition('steps', 'Step count', 'count', Selector('Steps')),
                              ((1000, 3000),))
    result = calculate(context.current_revision(), d)
    assert result.value == 2
    assert {c.annotation_id for c in result.contributors} == {'start', 'middle'}


def test_literal_zero_count_does_not_claim_complete_review(context):
    d = replace(definition(), outcome=replace(definition().outcome, calculation='count'),
                observation=((0, 5000),), review_status='unknown')
    record = context.capture_measurement(d)
    assert record.result.value == 0 and record.definition.review_status == 'unknown'
    assert calculate(context.current_revision(), replace(d, observation=((0, 0),))).value is None


def test_protocol_roundtrip_and_capture_pin_selected_outcome(context):
    outcome = OutcomeDefinition('fog-count', 'FOG episodes', 'count', Selector('FOG'), Selector('Task'))
    context.schema.measurements = [outcome]
    context.save()
    reopened = WorkingContext.open(context.workspace.path)
    assert reopened.schema.measurements == [outcome]
    record = reopened.capture_measurement(MeasurementDefinition(outcome, ((0, 60000),)))
    reopened.schema.measurements[0] = replace(outcome, calculation='covered_duration', version='2')
    revised = reopened.capture_measurement(MeasurementDefinition(reopened.schema.measurements[0], ((0, 60000),)))
    assert record.result.value == 2 and record.result.unit == 'count'
    assert revised.result.value == 12 and revised.result.unit == 's'
    assert record.verify() and compare(record, revised)['Scoring rule and event selection']


@pytest.mark.parametrize('damage', ['lane', 'operation', 'duplicate', 'scope'])
def test_protocol_rejects_invalid_outcome_declarations(context, damage):
    from rime_core.schema import SchemaValidationError
    raw = context.schema.to_dict()
    item = OutcomeDefinition('fog-count', 'FOG episodes', 'count', Selector('FOG')).to_dict()
    raw['measurements'] = [item]
    if damage == 'lane':
        item['events']['lane'] = 'Missing'
    elif damage == 'operation':
        item['calculation'] = 'unsupported'
    elif damage == 'duplicate':
        raw['measurements'] *= 2
    else:
        item['scope'] = {'lane': 'Missing'}
    with pytest.raises(SchemaValidationError):
        ProtocolSchema.from_dict(raw)

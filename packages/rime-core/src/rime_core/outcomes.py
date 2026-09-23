"""Small, declarative outcome definitions embedded in clinical protocols."""
from __future__ import annotations

from dataclasses import asdict, dataclass

CALCULATIONS = {
    'covered_duration': 'Duration of matching retained intervals within eligible time; overlaps count once.',
    'percentage_coverage': 'Covered duration divided by eligible duration, multiplied by 100; overlaps count once.',
    'count': 'Number of matching retained annotations in eligible time. Each annotation counts once; intervals must overlap the scope and points must fall within it.',
}


@dataclass(frozen=True)
class Selector:
    lane: str
    label: str | None = None

    def __post_init__(self):
        if not isinstance(self.lane, str) or not self.lane.strip():
            raise ValueError('A selector requires a lane.')
        if self.label is not None and not isinstance(self.label, str):
            raise ValueError('A selector label must be text or null.')


@dataclass(frozen=True)
class OutcomeDefinition:
    id: str
    name: str
    calculation: str
    events: Selector
    scope: Selector | None = None
    version: str = '1'
    calculation_version: str = '1'

    def __post_init__(self):
        if any(not isinstance(s, str) or not s.strip() for s in (self.id, self.name, self.version)):
            raise ValueError('Outcome identity, name and version must be nonempty text.')
        if self.calculation not in CALCULATIONS or self.calculation_version != '1':
            raise ValueError('Unsupported calculation or calculation version.')
        if not isinstance(self.events, Selector) or (self.scope is not None and not isinstance(self.scope, Selector)):
            raise ValueError('Invalid outcome event or scope selector.')

    @property
    def description(self) -> str:
        return CALCULATIONS[self.calculation]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> OutcomeDefinition:
        return cls(**{**data, 'events': Selector(**data['events']),
                      'scope': Selector(**data['scope']) if data.get('scope') is not None else None})

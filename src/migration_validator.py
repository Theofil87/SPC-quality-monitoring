"""Compare complete record sets without accessing a database."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from decimal import Decimal
import math
from types import MappingProxyType


Scalar = bool | int | float | Decimal | str | bytes | date | datetime | time | None
PrimaryKey = tuple[Scalar, ...]
_NormalizedValue = tuple[str, Scalar]
_NormalizedKey = tuple[_NormalizedValue, ...]


@dataclass(frozen=True)
class Record:
    primary_key: PrimaryKey
    values: Mapping[str, Scalar]


@dataclass(frozen=True)
class FieldDifference:
    field: str
    source: Scalar
    target: Scalar


@dataclass(frozen=True)
class RecordDifference:
    primary_key: PrimaryKey
    fields: tuple[FieldDifference, ...]


@dataclass(frozen=True)
class ComparisonReport:
    source_count: int
    target_count: int
    matched: tuple[Record, ...]
    source_only: tuple[Record, ...]
    target_only: tuple[Record, ...]
    different: tuple[RecordDifference, ...]

    @property
    def status(self) -> str:
        return "FAIL" if self.source_only or self.target_only or self.different else "PASS"


def _normalize(value: object) -> _NormalizedValue:
    if value is None:
        return ("null", None)
    if type(value) is bool:
        return ("bool", value)
    if type(value) is int:
        return ("int", value)
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("float values must be finite")
        return ("float", value)
    if type(value) is Decimal:
        if not value.is_finite():
            raise ValueError("Decimal values must be finite")
        return ("decimal", value)
    if type(value) is str:
        return ("str", value)
    if type(value) is bytes:
        return ("bytes", value)
    if type(value) is datetime:
        if value.tzinfo is None:
            return ("datetime-naive", value.replace(fold=0))
        if value.utcoffset() is None:
            raise ValueError("datetime timezone must provide a UTC offset")
        return ("datetime-aware", value.astimezone(timezone.utc))
    if type(value) is date:
        return ("date", value)
    if type(value) is time:
        if value.tzinfo is not None:
            raise ValueError("timezone-aware time values are not supported")
        return ("time", value.replace(fold=0))
    raise TypeError(f"unsupported value type: {type(value).__name__}")


def _primary_key_columns(primary_key: str | Sequence[str]) -> tuple[str, ...]:
    if isinstance(primary_key, str):
        columns = (primary_key,)
    elif isinstance(primary_key, Sequence) and not isinstance(primary_key, bytes):
        columns = tuple(primary_key)
    else:
        raise TypeError("primary_key must be a column name or a sequence of column names")
    if not columns or any(not isinstance(column, str) or not column for column in columns):
        raise ValueError("primary_key must contain non-empty column names")
    if len(set(columns)) != len(columns):
        raise ValueError("primary_key columns must be unique")
    return columns


def _index_records(
    rows: Iterable[Mapping[str, object]],
    key_columns: tuple[str, ...],
    side: str,
    columns: frozenset[str] | None,
    key_types: tuple[str, ...] | None,
) -> tuple[
    dict[_NormalizedKey, tuple[Record, dict[str, _NormalizedValue]]],
    frozenset[str] | None,
    tuple[str, ...] | None,
]:
    if isinstance(rows, (str, bytes, Mapping)):
        raise TypeError(f"{side} must be an iterable of record mappings")
    indexed: dict[_NormalizedKey, tuple[Record, dict[str, _NormalizedValue]]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise TypeError(f"{side} records must be mappings")
        if any(not isinstance(name, str) or not name for name in row):
            raise ValueError(f"{side} record column names must be non-empty strings")
        row_columns = frozenset(row)
        if not set(key_columns).issubset(row_columns):
            raise ValueError(f"{side} record is missing a primary key column")
        if columns is None:
            columns = row_columns
        elif row_columns != columns:
            raise ValueError(f"{side} record columns do not match")
        normalized = {name: _normalize(value) for name, value in row.items()}
        key = tuple(normalized[column] for column in key_columns)
        if any(value is None for _, value in key):
            raise ValueError(f"{side} primary key must not contain NULL")
        current_key_types = tuple(kind for kind, _ in key)
        if key_types is None:
            key_types = current_key_types
        elif current_key_types != key_types:
            raise ValueError(f"{side} primary key types do not match")
        if key in indexed:
            raise ValueError(f"{side} contains a duplicate primary key")
        values = {name: normalized[name][1] for name in sorted(row_columns)}
        record = Record(
            primary_key=tuple(normalized[column][1] for column in key_columns),
            values=MappingProxyType(values),
        )
        indexed[key] = (record, normalized)
    return indexed, columns, key_types


def compare_records(
    source: Iterable[Mapping[str, object]],
    target: Iterable[Mapping[str, object]],
    primary_key: str | Sequence[str],
) -> ComparisonReport:
    """Compare all records by primary key; invalid input raises an exception.

    Aware datetimes compare as UTC instants; naive datetimes compare as local
    wall times. Unsupported types and non-finite numeric values are rejected.
    """
    key_columns = _primary_key_columns(primary_key)
    source_index, columns, key_types = _index_records(
        source, key_columns, "source", None, None
    )
    target_index, columns, _ = _index_records(
        target, key_columns, "target", columns, key_types
    )
    matched: list[Record] = []
    source_only: list[Record] = []
    target_only: list[Record] = []
    different: list[RecordDifference] = []
    for key in sorted(source_index.keys() | target_index.keys(), key=repr):
        if key not in target_index:
            source_only.append(source_index[key][0])
        elif key not in source_index:
            target_only.append(target_index[key][0])
        else:
            source_record, source_values = source_index[key]
            target_record, target_values = target_index[key]
            fields = tuple(
                FieldDifference(name, source_record.values[name], target_record.values[name])
                for name in sorted(columns or ())
                if source_values[name] != target_values[name]
            )
            if fields:
                different.append(RecordDifference(source_record.primary_key, fields))
            else:
                matched.append(source_record)
    return ComparisonReport(
        source_count=len(source_index),
        target_count=len(target_index),
        matched=tuple(matched),
        source_only=tuple(source_only),
        target_only=tuple(target_only),
        different=tuple(different),
    )

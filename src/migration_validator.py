"""Compare complete record sets without accessing a database."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence
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
    matched_count: int
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


def _iter_records(
    rows: Iterable[Mapping[str, object]],
    key_columns: tuple[str, ...],
    side: str,
) -> Iterator[tuple[_NormalizedKey, Record, frozenset[str], tuple[str, ...]]]:
    if isinstance(rows, (str, bytes, Mapping)):
        raise TypeError(f"{side} must be an iterable of record mappings")
    columns = None
    key_types = None
    previous_key = None
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
        if key == previous_key:
            raise ValueError(f"{side} contains a duplicate primary key")
        if previous_key is not None and key < previous_key:
            raise ValueError(f"{side} records must be ordered by primary key")
        previous_key = key
        values = {name: normalized[name][1] for name in sorted(row_columns)}
        record = Record(
            primary_key=tuple(value for _, value in key),
            values=MappingProxyType(values),
        )
        yield key, record, columns, key_types


def compare_records(
    source: Iterable[Mapping[str, object]],
    target: Iterable[Mapping[str, object]],
    primary_key: str | Sequence[str],
) -> ComparisonReport:
    """Compare records from ascending primary-key streams.

    Aware datetimes compare as UTC instants; naive datetimes compare as local
    wall times. Unsupported types and non-finite numeric values are rejected.
    Invalid input or records not ordered by primary key raise an exception.
    """
    key_columns = _primary_key_columns(primary_key)
    source_rows = iter(_iter_records(source, key_columns, "source"))
    target_rows = iter(_iter_records(target, key_columns, "target"))
    source_row = next(source_rows, None)
    target_row = next(target_rows, None)

    source_columns = source_row[2] if source_row else None
    target_columns = target_row[2] if target_row else None
    if source_columns is not None and target_columns is not None:
        if source_columns != target_columns:
            raise ValueError("target record columns do not match")
    columns = source_columns or target_columns

    source_key_types = source_row[3] if source_row else None
    target_key_types = target_row[3] if target_row else None
    if source_key_types is not None and target_key_types is not None:
        if source_key_types != target_key_types:
            raise ValueError("target primary key types do not match")

    source_count = int(source_row is not None)
    target_count = int(target_row is not None)
    matched_count = 0
    source_only: list[Record] = []
    target_only: list[Record] = []
    different: list[RecordDifference] = []

    while source_row is not None and target_row is not None:
        source_key, source_record, _, source_types = source_row
        target_key, target_record, _, target_types = target_row
        if source_types != target_types:
            raise ValueError("source and target primary key types do not match")
        if source_key < target_key:
            source_only.append(source_record)
            source_row = next(source_rows, None)
            source_count += int(source_row is not None)
        elif target_key < source_key:
            target_only.append(target_record)
            target_row = next(target_rows, None)
            target_count += int(target_row is not None)
        else:
            fields = tuple(
                FieldDifference(name, source_record.values[name], target_record.values[name])
                for name in sorted(columns)
                if _normalize(source_record.values[name])
                != _normalize(target_record.values[name])
            )
            if fields:
                different.append(RecordDifference(source_record.primary_key, fields))
            else:
                matched_count += 1
            source_row = next(source_rows, None)
            target_row = next(target_rows, None)
            source_count += int(source_row is not None)
            target_count += int(target_row is not None)

    while source_row is not None:
        source_only.append(source_row[1])
        source_row = next(source_rows, None)
        source_count += int(source_row is not None)

    while target_row is not None:
        target_only.append(target_row[1])
        target_row = next(target_rows, None)
        target_count += int(target_row is not None)

    return ComparisonReport(
        source_count=source_count,
        target_count=target_count,
        matched_count=matched_count,
        source_only=tuple(source_only),
        target_only=tuple(target_only),
        different=tuple(different),
    )

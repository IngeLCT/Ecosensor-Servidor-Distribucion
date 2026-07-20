from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from config import LOCAL_TIMEZONE


UTC = timezone.utc


def configured_timezone() -> ZoneInfo:
    """Zona IANA única usada exclusivamente para presentación."""
    return ZoneInfo(LOCAL_TIMEZONE)


def utc_now() -> datetime:
    return datetime.now(UTC)


def utc_now_iso() -> str:
    return utc_now().isoformat(timespec='seconds').replace('+00:00', 'Z')


def server_local_now() -> datetime:
    return utc_now().astimezone(configured_timezone())


def server_local_now_naive() -> datetime:
    return server_local_now().replace(tzinfo=None)


def parse_timestamp(value: Any, *, naive_origin: str = 'local') -> datetime | None:
    """Interpreta ISO-8601 sin destruir Z/offset.

    Los formatos históricos sin zona se clasifican mediante ``naive_origin``:
    ``local`` conserva el significado legado visible y ``utc`` los trata como
    UTC. Los valores ambiguos no se convierten por heurística.
    """
    text = str(value or '').strip()
    if not text:
        return None
    normalized = text[:-1] + '+00:00' if text.endswith(('Z', 'z')) else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        parsed = None
        for fmt in ('%d-%m-%Y %H:%M:%S', '%Y-%m-%d %H:%M:%S'):
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        if parsed is None:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC if naive_origin == 'utc' else configured_timezone())
    return parsed


def to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=configured_timezone())
    return value.astimezone(UTC)


def to_server_local(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=configured_timezone())
    return value.astimezone(configured_timezone())


def to_server_local_naive(value: datetime) -> datetime:
    return to_server_local(value).replace(tzinfo=None)


def iso_utc(value: datetime | None = None) -> str:
    return to_utc(value or utc_now()).isoformat(timespec='seconds').replace('+00:00', 'Z')


def iso_server_local(value: datetime | None = None) -> str:
    return to_server_local(value or utc_now()).isoformat(timespec='seconds')


def visible_date_time(value: Any, *, naive_origin: str = 'local') -> tuple[str, str]:
    parsed = parse_timestamp(value, naive_origin=naive_origin)
    if parsed is None:
        return '', ''
    local = to_server_local(parsed)
    return local.strftime('%Y-%m-%d'), local.strftime('%H:%M:%S')


def visible_datetime(value: Any, *, naive_origin: str = 'local') -> str:
    date_part, time_part = visible_date_time(value, naive_origin=naive_origin)
    return f'{date_part} {time_part}'.strip()


def unix_epoch(value: Any, *, naive_origin: str = 'local') -> int | None:
    parsed = value if isinstance(value, datetime) else parse_timestamp(value, naive_origin=naive_origin)
    if parsed is None:
        return None
    return int(to_utc(parsed).timestamp())


def drift_seconds(first: Any, second: Any) -> int | None:
    first_epoch = unix_epoch(first)
    second_epoch = unix_epoch(second)
    if first_epoch is None or second_epoch is None:
        return None
    return first_epoch - second_epoch

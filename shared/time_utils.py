from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from config import LOCAL_TIMEZONE


def configured_timezone() -> ZoneInfo | None:
    """Zona horaria opcional del proyecto.

    Si ECOSENSOR_TIMEZONE no está configurado, se usa la zona local real de la
    máquina donde corre el servidor mediante datetime.now().astimezone().
    """
    if not LOCAL_TIMEZONE:
        return None
    try:
        return ZoneInfo(LOCAL_TIMEZONE)
    except ZoneInfoNotFoundError:
        return None


def server_local_now() -> datetime:
    """Hora local de la máquina que ejecuta el servidor.

    Por defecto respeta la zona horaria del sistema operativo. ECOSENSOR_TIMEZONE
    solo sirve como override explícito para instalaciones que lo necesiten.
    """
    tz = configured_timezone()
    return datetime.now(tz) if tz is not None else datetime.now().astimezone()


def server_local_now_naive() -> datetime:
    return server_local_now().replace(tzinfo=None)


def to_server_local_naive(value: datetime) -> datetime:
    tz = configured_timezone()
    if value.tzinfo is None:
        return value
    if tz is not None:
        return value.astimezone(tz).replace(tzinfo=None)
    return value.astimezone().replace(tzinfo=None)


def iso_server_local(value: datetime | None = None) -> str:
    dt = to_server_local_naive(value or server_local_now())
    return dt.isoformat(timespec='seconds')

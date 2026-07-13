"""Compatibilidad para código antiguo.

El reverse geocoding activo del proyecto vive en ``services.reverse_geocoding``
y usa Nominatim público con caché SQLite local. Este módulo se conserva para
evitar romper imports viejos, pero ya no contiene lógica de Geoapify ni proxy externo.
"""

from services.reverse_geocoding import (  # noqa: F401
    coordinate_key,
    fallback_label,
    get_cached_location,
    reverse_geocode_cached,
    resolve_unique_locations,
)

resolve_location = reverse_geocode_cached

# Reverse geocoding con Nominatim

La página `/ubicaciones` usa reverse geocoding directo contra Nominatim público de OpenStreetMap para convertir el centroide de cada grupo de mediciones GPS en una etiqueta legible, por ejemplo `Cuernavaca (Vista Hermosa)`.

## Arquitectura

- `pages/locations_page.py` agrupa mediciones por proximidad y solo geocodifica el punto representativo de cada grupo.
- `services/reverse_geocoding.py` resuelve cada coordenada representativa con este flujo:
  1. redondea coordenadas con `GEOCODING_CACHE_PRECISION`;
  2. busca en caché SQLite local;
  3. si no existe caché y todavía hay cupo por carga, consulta Nominatim;
  4. guarda la respuesta normalizada en caché;
  5. si falla, devuelve fallback seguro con coordenadas redondeadas.
- `services/geocoding_client.py` queda solo como compatibilidad para imports antiguos y apunta al servicio nuevo.

No se usa Geoapify, API key, Hostinger ni endpoint externo propio en esta versión.

## Configuración principal

Las constantes viven en `config.py` y pueden sobrescribirse con variables de entorno:

- `REVERSE_GEOCODING_PROVIDER = "nominatim"`
- `NOMINATIM_BASE_URL = "https://nominatim.openstreetmap.org/reverse"`
- `NOMINATIM_USER_AGENT = "EcoSensorServidor/1.0 (LCT Didacticos; contacto: ingenieria@lctdidacticos.com)"`
- `NOMINATIM_TIMEOUT_SECONDS = 8`
- `NOMINATIM_MIN_SECONDS_BETWEEN_REQUESTS = 1.1`
- `NOMINATIM_MAX_LOOKUPS_PER_PAGE_LOAD = 10`
- `GEOCODING_CACHE_DB = "data/geocoding_cache.sqlite3"`
- `GEOCODING_CACHE_PRECISION = 4`
- `GEOCODING_ENABLE_REMOTE_LOOKUP = True`
- `GEOCODING_DEFAULT_ZOOM = 14`
- `GEOCODING_ACCEPT_LANGUAGE = "es"`

## Caché SQLite

La caché se inicializa automáticamente cuando se llama al servicio por primera vez. La ruta relativa `data/geocoding_cache.sqlite3` se resuelve dentro de `DATA_DIR`, normalmente:

```text
%LOCALAPPDATA%/EcoSensorServidor/geocoding_cache.sqlite3
```

o en Linux/desarrollo:

```text
~/AppData/Local/EcoSensorServidor/geocoding_cache.sqlite3
```

si no se define `ECOSENSOR_DATA_DIR`.

La tabla usada es `reverse_geocoding_cache` con clave única `(provider, lat_key, lon_key)`.

## Cómo borrar la caché

Para regenerar ubicaciones, cerrar la app y borrar el archivo configurado en `GEOCODING_CACHE_DB` dentro de `DATA_DIR`, por ejemplo:

```text
EcoSensorServidor/geocoding_cache.sqlite3
```

Al volver a abrir `/ubicaciones`, la tabla se recrea automáticamente y las ubicaciones se resolverán de nuevo respetando el límite por carga.

## Ejemplo de salida

```python
{
    "ok": True,
    "source": "cache",
    "provider": "nominatim",
    "lat_key": 18.9204,
    "lon_key": -99.2175,
    "label": "Cuernavaca (Vista Hermosa)",
    "formatted": "...",
    "city": "Cuernavaca",
    "suburb": "Vista Hermosa",
    "district": None,
    "neighbourhood": None,
    "municipality": "Cuernavaca",
    "county": None,
    "state": "Morelos",
    "country": "México",
    "postcode": None,
    "raw": {...},
}
```

Si no hay internet o Nominatim falla:

```python
{
    "ok": False,
    "source": "fallback",
    "provider": "nominatim",
    "lat_key": 18.9204,
    "lon_key": -99.2175,
    "label": "18.9204, -99.2175",
    "formatted": None,
    "error": "...",
}
```

## Pruebas manuales recomendadas

1. Primera carga con coordenada nueva:
   - abrir `/ubicaciones`;
   - verificar que hasta 10 clusters nuevos consulten Nominatim;
   - confirmar que se crea `geocoding_cache.sqlite3`.
2. Segunda carga con la misma coordenada:
   - recargar `/ubicaciones`;
   - confirmar que usa `source = cache` y no vuelve a consultar Nominatim.
3. Sin internet:
   - abrir la página con coordenadas ya cacheadas y confirmar que usa caché;
   - abrir con coordenadas no cacheadas y confirmar fallback `lat, lon` sin romper mapa.
4. Coordenada inválida:
   - verificar que no rompe la UI y muestra fallback seguro.
5. Muchos clusters:
   - confirmar que no hay más de `NOMINATIM_MAX_LOOKUPS_PER_PAGE_LOAD` consultas remotas por carga;
   - confirmar separación mínima de `NOMINATIM_MIN_SECONDS_BETWEEN_REQUESTS` entre requests.
6. Atribución:
   - confirmar que la página muestra: `Ubicaciones aproximadas usando datos de © OpenStreetMap contributors / Nominatim.`

## Cambiar proveedor en el futuro

`REVERSE_GEOCODING_PROVIDER` deja clara la intención. Actualmente el único proveedor implementado es `nominatim`. Para agregar otro proveedor:

1. crear otro cliente en `services/`;
2. conservar la estructura estable de salida;
3. mantener caché local por `(provider, lat_key, lon_key)`;
4. cambiar la función de despacho en `reverse_geocode_cached` o crear un adaptador.

## Riesgos y limitaciones de Nominatim público

- Es un servicio público compartido, no recomendado para cargas masivas o uso intensivo.
- La política de uso exige User-Agent identificable y máximo aproximado de 1 request por segundo.
- La cobertura de colonias/suburbios depende de los datos de OpenStreetMap; algunas zonas pueden devolver solo ciudad/estado.
- Puede haber latencia o fallas temporales; por eso el mapa debe funcionar con caché o fallback.
- Si el volumen crece, conviene migrar a un proveedor propio, comercial o una instancia dedicada de Nominatim.

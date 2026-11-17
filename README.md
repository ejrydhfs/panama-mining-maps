# Concesiones mineras de Panamá — mapa vectorial 2008–2026

Mapa web (Leaflet) que reconstruye los recintos mineros publicados por el
**MICI / Dirección de Recursos Minerales** de Panamá. **Todo el contenido es
vectorial: el sitio no incluye ninguna imagen.**

- **2008-07 → 2021-07** — 167 867 cajas extraídas de los **DWG** oficiales
  (geometría vectorial real, UTM 17N → WGS84).
- **2022-01 → 2026-10** — 90 235 cajas obtenidas por **reconocimiento de imagen**
  (segmentación de color + detección de rectángulos) sobre las hojas PDF.
- **Áreas protegidas y reservas mineras** — 370 polígonos extraídos de las
  capas `Areas Protegida` / `RESERVA MINERA` de los DWG, dibujados como capa de
  contexto (activada por defecto).

Total: **141 meses, 259 059 recintos**, 8,3 MB de JSON + 0,2 MB de zonas.

## Estructura

| archivo | contenido |
|---|---|
| `boxes.json` | `{ "YYYY-MM": { "metal/contratos": [[W,S,E,N], …] } }` — 254 363 recintos |
| `zones.json` | polígonos `[[lon,lat],…]` de áreas protegidas / reservas |
| `boxcodes.json` | recinto → código de licencia impreso en la hoja (19 745 enlaces) |
| `license.json` | ficha por código: empresa, tipo, hectáreas, estado, `active` |
| `sheets.json` | origen de cada hoja (URL original, Wayback/sitio) |
| `MANIFEST.csv` | inventario de los 503 archivos fuente descargados |

Categorías: `metal|nometal` × `contratos|solicitudes|ambos`, todas activas por
defecto. Cada recinto enlazado con su ficha muestra código, empresa, superficie y
estado; la casilla **«solo vigentes»** deja únicamente las licencias activas.

Los meses sin tabla publicada (2022-01…05, 2022-12, 2023-11) no se filtran: el
contador indica «N sin ficha» y sus recintos siguen visibles.

Las fichas salen de las tablas `LISTADO-*` del MICI (157 mes|categoría, 20 783
filas) y el enlace se hace leyendo el código impreso en cada polígono (OCR a
resolución nativa, 33 010 códigos). 57 % de los enlaces están confirmados por la
tabla del mes; el 43 % restante son meses sin tabla publicada o códigos que no
aparecen en ella.

## Cómo se generó

1. Censo de `mici.gob.pa` + subdominios en la Wayback Machine
   (82 574 URL; 9 356 PDF, 275 DWG, 96 ZIP).
2. **DWG**: LibreDWG → DXF; recintos = `LWPOLYLINE`/`POLYLINE`/`HATCH` en capas
   de concesiones; UTM 17N → WGS84 con TM inversa (validada contra `pyproj`,
   error < 1 cm); filtro 80 m – 25 km de lado y < 250 km².
3. **PDF**: rasterizado a 200 dpi; el PDF no contiene vectores (una sola
   imagen JPEG a 250 ppi por página), así que la geometría se reconstruye desde
   los píxeles: máscara de líneas cartográficas → runs horizontales/verticales
   (con tolerancia a huecos por las etiquetas) → emparejado de bordes que
   forman rectángulos axis-aligned → deduplicado por IoU.
4. Georreferencia de cada hoja PDF por mínimos cuadrados sobre su retícula
   impresa (OCR de `83°00'…77°24'` / `9°54'…6°18'`), residuo < 1 px.

## Límites (importante)

- La era **PDF es aproximada**: la fuente es una imagen, no hay geometría
  publicada. Se detectan los recintos dibujados como rectángulos de color, pero
  se pierden los que quedan ocultos bajo etiquetas o muy pequeños, y las cajas
  son envolventes. Tratar como ~80 % de cobertura, no como catastro exacto.
- **2021-08 → 2021-11** no tiene ninguna hoja publicada/capturada.
- Huecos heredados del archivo: 2018 ene–nov, 2020 ene–jul, 2022 jul/oct,
  2023 dic, 2024 ene–jun y nov–dic.
- **Las cajas sobre el mar son válidas:** incluyen concesiones de minería
  submarina / extracción en lecho marino publicadas por el MICI; no son falsos
  positivos.
- Cada mes es una foto de lo publicado ese mes, no un acumulado histórico.
- Desde nov-2024 el MICI sólo publica hojas de minerales no metálicos.

## Créditos

Datos públicos del MICI (Panamá); sitio no afiliado. Mapa base © OpenStreetMap;
imágenes satelitales © Esri, Maxar, Earthstar Geographics.

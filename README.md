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
| `boxcodes.json` | recinto → código de licencia (163 149 enlaces: 152 538 de la era DWG, 10 611 de la era raster) |
| `license.json` | ficha por código: empresa, tipo, hectáreas, estado, `active` (216 mes\|categoría, 33 000 fichas + 334 alias canónicos marcados `_alias`) |
| `sheets.json` | origen de cada hoja (URL original, Wayback/sitio) |
| `MANIFEST.csv` | inventario de los 503 archivos fuente descargados |

Categorías: `metal|nometal` × `contratos|solicitudes|ambos`, todas activas por
defecto. Cada recinto enlazado con su ficha muestra código, empresa, superficie y
estado; la casilla **«solo vigentes»** deja únicamente las licencias activas.

Los meses sin tabla publicada (2022-01…05, 2022-12, 2023-11) no se filtran: el
contador indica «N sin ficha» y sus recintos siguen visibles.

Las fichas salen de las tablas `LISTADO-*` del MICI (264 mes|categoría, 36 214
filas, recuperadas de Wayback) y el enlace se hace leyendo el código impreso en cada polígono (OCR a
resolución nativa, 33 010 lecturas de etiqueta). De los 10 611 recintos de la era
raster, 6 646 tienen ficha y 3 965 no se enlazan: 3 674 no aparecen en la tabla del
mes, 289 son truncamientos que la tabla admitiría tras una reparación inequívoca (no se
enlazan sin confirmación de la segunda lectura) y 2 son ambiguos. En la era DWG el
informe adversarial cuenta 9 278 códigos que sólo coinciden tras reparar un truncamiento;
tampoco se enlazan. De esos 10 611
recintos, 10 396 (98 %) tienen además la relectura OCR concordante; en la era DWG la tabla sólo existe desde
2017-06, así que 105 289 enlaces anteriores a esa fecha no tienen ficha.

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

## Tope de superficie (era PDF)

Las hojas dibujan también redes de líneas (bordes provinciales, reservas viales)
que el extractor podía cerrar en rectángulos del tamaño de una provincia. Se descartan las cajas de más de **5 km de lado (no metálicos)** o **20 km
(metálicos)** — además de los topes de área de 60/250 km² — los no metálicos son mucho más pequeños en la fuente (mediana
282 ha frente a 3 299 ha de los metálicos) —, las de contorno rojo de más de
100 km² y, en la era PDF, las de contorno rojo no metálicas de más de 25 km²:
esas son corredores de reserva («Reserva a 300 m del río Chagres», bordes de
parque) que el extractor cerraba en rectángulos. 17 060 cajas eliminadas. En la fuente los bloques reales son cuadrados
de 1-6 km.

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

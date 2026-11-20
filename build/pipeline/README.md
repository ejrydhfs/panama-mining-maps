# Copia de auditoría del pipeline

Estos son los scripts que produjeron los datos publicados, copiados tal cual desde
`site_build/` del árbol de trabajo. Se publican para que cualquiera pueda leer cómo
se obtiene cada cifra; **no** son ejecutables desde aquí: esperan el layout
`site_build/` y los PDF/JPEG descargados del MICI, que no se distribuyen.

| script | produce |
|---|---|
| `parse_listados.py` | `listados.json` (código, empresa, ha, página, fila) |
| `codes.py` | `codes/*.json` (lectura de etiquetas a 3×) |
| `second_read.py` | `codecheck.json` (relectura a 4×, gate de la ficha) |
| `join_codes.py` | `boxcodes.json`, `license.json` |
| `rows_index.py`, `normalize_keys.py` | versiones ejecutables en `build/` |
| `adversarial_review.py` | `review.html` |
| `legal_page.py` | `legal.html` |

Copia canónica del código ejecutable: `build/rows_index.py` y `build/normalize_keys.py`.

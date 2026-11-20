# Generadores de los datos publicados

Estos dos scripts producen `license.json` y `licrows.json` a partir de las tablas
`LISTADO-*` ya parseadas (`listados.json`, fuera del repositorio: se obtiene con
`parse_listados.py` desde los PDF del MICI).

```
python3 build/rows_index.py      # licrows.json  {code: {f: fila global, p: página, r: fila en la página}}
python3 build/normalize_keys.py  # license.json  + alias canónicos marcados _alias
```

- `PANAMA_ROOT` permite ejecutarlos desde otro árbol (`PANAMA_ROOT=/ruta/repo`).
- Ambos son idempotentes: repetirlos no altera los ficheros.
- `r` reinicia en cada página porque los PDF no imprimen números de fila; `p` alimenta
  el ancla `#page=` del popup.
- Los alias existen porque el mapa usa `norm_code()` (`83-6` → `83-06`) y las tablas
  conservan el texto original. Se marcan `_alias: true` para que ningún recuento los
  cuente dos veces.

import json, os

S = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'site')
boxes = json.load(open(os.path.join(S, 'boxes.json')))
codes = json.load(open(os.path.join(S, 'boxcodes.json')))
rev = json.load(open(os.path.join(S, 'review.json')))
unrel = json.load(open(os.path.join(S, 'unreliable.json')))

n_boxes = sum(len(v) for m in boxes.values() for v in m.values())
n_codes = sum(len(v) for v in codes.values())
n_months = len({d for d in boxes})

html = f"""<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Aviso legal · Concesiones Panamá</title>
<style>
 body{{margin:0;background:#0e1116;color:#e9eef6;font:14.5px/1.6 ui-sans-serif,system-ui,sans-serif}}
 .wrap{{max-width:820px;margin:0 auto;padding:36px 20px 90px}}
 h1{{font-size:24px;margin:0 0 6px}} h2{{font-size:15px;margin:26px 0 8px;color:#9fb0c6;
 text-transform:uppercase;letter-spacing:.04em}} p,li{{color:#d6dfea}} a{{color:#7cc4ff}}
 .box{{background:#141a22;border:1px solid #28303c;border-radius:12px;padding:14px 18px;margin:18px 0}}
 .warn{{border-color:#7a5b1e;background:#1d1a12}}
</style></head><body><div class="wrap">
<h1>Aviso legal</h1>
<p>Este sitio es un <b>archivo independiente</b> de documentos públicos. No está afiliado al
Ministerio de Comercio e Industrias (MICI) ni a ninguna empresa mencionada, y no constituye
asesoramiento jurídico ni un catastro oficial.</p>

<div class="box warn"><b>Nada de lo que muestra este mapa afirma que una empresa haya actuado
ilegalmente.</b> La presencia de un polígono sobre un área protegida, una reserva minera o una
zona en disputa no implica incumplimiento, ilegalidad ni irregularidad alguna: las concesiones
pueden solaparse legítimamente con figuras de protección, y las hojas del MICI dibujan capas
distintas (contratos, solicitudes, reservas) sobre el mismo territorio.</div>

<h2>Qué son los datos</h2>
<p>{n_months} meses, {n_boxes:,} recintos y {n_codes:,} códigos de licencia, reconstruidos a partir
de las hojas mensuales y las tablas <code>LISTADO-*</code> publicadas por el MICI. Los polígonos son
<b>cajas envolventes</b> de lo dibujado en esas hojas: no son linderos, no tienen validez catastral
y su superficie puede ser mayor o menor que la otorgada. Los datos de empresa, hectáreas y estado
solo se muestran cuando el código impreso coincide con una fila de la tabla de <i>ese mismo mes</i>;
si no coincide, el recinto aparece con «?» y sin empresa.</p>

<h2>Límites conocidos</h2>
<ul>
<li>La era 2021-12 a 2026-10 se reconoce por imagen sobre un PDF raster; se pierden recintos ocultos
bajo etiquetas y pueden aparecer falsos positivos.</li>
<li>{len(unrel)} combinaciones mes|categoría tienen tabla y hoja que cubren códigos distintos: en
esas no se publica empresa, hectáreas ni estado.</li>
<li>Meses sin tabla publicada no llevan ficha de licencia.</li>
<li>Los códigos pueden repetirse entre años con titulares distintos; no deben agregarse entre meses.</li>
</ul>
<p>El <a href="review.html">informe adversarial</a> enumera, mes por mes, qué afirmaciones no sostiene
la evidencia y enlaza el PDF de origen de cada una.</p>

<h2>Correcciones y retirada</h2>
<p>Si usted es titular, apoderado o afectado por un dato incorrecto, abra una incidencia en
<a href="https://github.com/ejrydhfs/panama-mining-maps/issues/new" target="_blank" rel="noopener">el
repositorio</a> indicando mes, categoría, código y qué debe corregirse. También puede escribir a
<a href="mailto:correcciones@example.invalid">correcciones@example.invalid</a> (sustituya por su
buzón real antes de publicar). Las solicitudes de rectificación o retirada se atienden antes que
cualquier otra mejora.</p>

<h2>Responsabilidad</h2>
<p>Los datos se ofrecen «tal cual», sin garantía de exactitud, integridad ni actualidad. En la medida
en que la ley lo permita, el autor no responde por decisiones tomadas a partir de este sitio ni por
el uso que terceros hagan de él. La fuente primaria y vinculante es siempre la publicación oficial
del MICI.</p>

<h2>Fuentes y créditos</h2>
<p>Documentos del MICI obtenidos del propio sitio y de Internet Archive (Wayback Machine); mapa base
© OpenStreetMap; imágenes satelitales © Esri, Maxar, Earthstar Geographics. El código y los datos
están en <a href="https://github.com/ejrydhfs/panama-mining-maps" target="_blank" rel="noopener">GitHub</a>.</p>

<p style="margin-top:28px"><a href="./">← volver al mapa</a></p>
</div></body></html>"""
open(os.path.join(S, 'legal.html'), 'w').write(html)
print('legal.html bytes', os.path.getsize(os.path.join(S, 'legal.html')))

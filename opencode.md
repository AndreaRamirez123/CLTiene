# opencode.md — Memoria de sesión CLTiene

> Este archivo es la **memoria de sesión** de trabajo con opencode. Hereda de `CLAUDE.md`
> (contexto permanente del proyecto) y documenta **solo lo ejecutado en cada sesión** +
> pendientes para la siguiente, para seguimiento e informes. Actualizar al terminar cada sesión.

## Estado al cierre (01-oct-2026)

- **BD BigQuery:** **50.994 filas** · historia **2025-10-10 → 2026-09-20** · 0 `Cuenta NULL` · 0 `tipo NULL` · 27 asesores. **Sin cambios hoy también**: el SQL Server de la CUN **no avanzó** desde el 28-sep (máx `2026-09-20 14:00:11`, crudo 59.177) ⇒ la corrida fue un **no-op de datos**, útil solo como validación end-to-end del pipeline con los fixes del 28/29-sep.
- **Carga ejecutada** (09:28:32 → 09:29:43, **71 s**): `MODELO_HABLANTES=gpt-4o`, **1 sola API key** (el `.env` local ya no tiene `OPENAI_API_MUNDIAL_2`), cache de 23.165 transcripciones ⇒ fase IA de **1 s** y **0 llamadas a OpenAI ($0)**. Leídas 59.177 → dedup 8.183 (13,8%) → escritas 50.994. Backup previo: `..._backup_20261001` (**9º/10 backups**).
- **Verificación post-carga OK:** schema **idéntico al backup** (57 columnas, `Fecha`/`fecha_carga` = **INTEGER ns** ⇒ contrato `DIV(Fecha,1000)` intacto) · `tipo` = **2 valores exactos** (ventas 28.911 / servicio 22.083; `mixto`=0, `servicios`=0, `venta`=0, NULL=0) · `Tipo_Llamada` sin cambios (NULL 25.029 / Saliente 20.019 / Entrante 5.946) · el **WHERE real de `filters()`** ejecutado en BigQuery para 14→20 sep devuelve **998** (590 ventas / 408 servicio) = el origen y los 3 informes · texto sin V4 1.034 (fragmentos STT, esperado) · **65 tests OK**.
- 🔴 **Hallazgo nuevo (upstream):** el origen tiene un **hueco de 4 días** — 10, 11, 12 y 13-sep traen **0 llamadas** (y nada después del 20-sep). No es efecto fin de semana (la semana anterior sí tiene sábado 81 y domingo 22) ⇒ faltan ~700-900 llamadas. Mismo tipo de pérdida del cruce audio↔Excel → **sumarlo al segundo correo** de pedidos a Juan Manuel.
- **Envío semanal: APAGADO** (sin cambios) — Scheduler PAUSADO, `REPORTE_ENABLED=0`, `ALERTA_ENABLED=0`, `cltiene_reportes_enviados` vacía. **Sin deploy, sin commit, cero escrituras al SQL Server.**
- **Pendientes sin cambio:** reenviar los 3 informes con el fix del TMO (solo con OK), segundo correo de pedidos de datos, reactivar el envío, informe técnico v3.4.

## Estado al cierre de la sesión anterior (29-sep-2026)

- **BD BigQuery:** **50.994 filas** · historia **2025-10-10 → 2026-09-20** · 0 `Cuenta NULL` · 0 `tipo NULL` · 27 asesores. **Sin cambios hoy** (la del 28-sep ya estaba al día, y el origen tampoco avanzó).
- **TMO `N/D` RESUELTO** — era un bug de semáforo, no un dato malo: sin duración medible ahora sale `⚪` y el contexto declara la cobertura. **Verificado en el origen**: las 189 entrantes de la semana traen `NULL` en `Tiempo␣␣de␣Conversacion` **y** en `Tiempo␣␣de␣Llamada` ⇒ el archivo de entradas no trae la columna. Suite **65 tests**.
- **Correo de AUTOMATIZACIÓN ENVIADO** a `Juan_marin@` + `Juan_ganicac@` (29-sep), **sin fecha de reunión aún**. El objeto son las **DOS etapas de código** (la del COE —hoy un notebook— y la nuestra). 7 preguntas abiertas. Tono de escalada, sin copia a Fabián. Ver "Ejecutado en esta sesión".
- **Envío semanal: APAGADO** (decisión del usuario, sin cambios) — Scheduler `cltiene-reporte-semanal` **PAUSADO** y job
  `cltiene-envio-reporte` con `REPORTE_ENABLED=0` + `ALERTA_ENABLED=0`. `cltiene_reportes_enviados` **vacía**.
  ⚠️ La BD llegó al 20-sep ⇒ el **preflight A se cumpliría** (semana a reportar: **14-sep → 20-sep**).
- **Pendiente en curso:** reenviar los **3 informes con el fix del TMO** (solo con OK explícito — el correo de prueba del 28-sep lleva las versiones previas) + el **segundo correo** con los pedidos de datos sueltos.
- **Informe de sesión** más reciente: `informe_sesion_2026-09-28.html`. Nota del día 29-sep: `CLTieneBobeda/Informes/2026-09-29 - Cambios del día.md`.

## Ejecutado en esta sesión (01-oct-2026)

> Corrida de **validación end-to-end** (los datos no cambiaron) + verificación del ORIGEN que destapó el hueco del 10–13 sep.

### 1. Pre-flight en seco (decisión de seguridad: no escribir a ciegas)
- Origen (SQL Server CUN, **solo lectura**): crudo **59.177** (52.035 ISO + 7.142 en formato español de oct-2025), `MAX(Fecha)` = **2026-09-20 14:00:11**, idéntico al 28-sep.
- `cargar_desde_sql()` **sin subir** → dedup 8.183 (13,8%) → **50.994** = exactamente lo que había en la tabla ⇒ se confirmó que la carga **no iba a traer nada** antes del `WRITE_TRUNCATE`.
- `tipo` crudo con 4 variantes (ventas 28.731 / servicio 21.658 / servicios 425 / venta 180) → tras la normalización de `procesar()` queda en **ventas 28.911 / servicio 22.083** ⇒ el fix `mixto` del 28-sep sigue correcto.

### 2. Backup + carga
- **Backup:** `desarrollo-investigaciones.call_center.cltiene_llamadas_procesadas_backup_20261001`, 50.994 filas, 57 columnas, schema **idéntico** al de la tabla. Es el **9º** de la serie (`_20260709` → `_20261001`).
  - ⚠️ El primer intento con `client.copy_table(...)` falló con `TypeError: Client.copy_table() got an unexpected keyword argument 'write_disposition'` (el parámetro no existe en esa firma) ⇒ se hizo con **DDL** `CREATE TABLE ... COPY ...`, que además es atómico.
- **Carga:** `$env:PYTHONIOENCODING='utf-8'; $env:MODELO_HABLANTES='gpt-4o'; python .\subir_datos.py` desde `back/`, red CUN, **1 sola API key**.
  - Cache de BigQuery **23.165** transcripciones → fase IA de **1 segundo** ⇒ **0 llamadas a OpenAI, $0**. (El "Nuevas/cambiadas: 25.739" del log son filas casi todas sin transcripción, como siempre.)
  - Leídas 59.177 → dedup 8.183 (13,8%) → escritas **50.994** en **71 s** (09:28:32 → 09:29:43).

### 3. Verificación post-carga (BigQuery)
| Chequeo | Resultado |
|---|---|
| Filas / historia | 50.994 · 2025-10-10 → **2026-09-20** |
| Asesores · `Cuenta` NULL | 27 · 0 |
| `tipo` | ventas **28.911** · servicio **22.083** · `mixto`/`servicios`/`venta`/NULL = **0** |
| `Tipo_Llamada` | NULL 25.029 (49%) · Saliente 20.019 · Entrante 5.946 — sin cambios |
| Schema vs backup | **idéntico** (57 columnas) · `Fecha` y `fecha_carga` = **INTEGER ns** |
| Filtro de fechas | 14→20 sep = **998** (590 ventas / 408 servicio) = origen y 3 informes |
| Texto sin `Transcripcion_V4` | 1.034 (fragmentos STT de 1–9 chars, esperado) |
| Tests | **65 OK** (`$env:PYTHONPATH='.'; python -m unittest discover -s tests`) |

- **Truco reutilizable:** se ejecutó en BigQuery el `WHERE` que genera el backend de verdad — `FilterModel(fecha_desde, fecha_hasta, tipo_llamada).get_query()` devuelve `Fecha >= UNIX_MICROS(TIMESTAMP('2026-09-14')) * 1000 AND Fecha <= UNIX_MICROS(TIMESTAMP('2026-09-20 23:59:59')) * 1000 AND tipo = 'ventas'`. Si algún día el contrato `Fecha` INTEGER-ns se rompe, ese WHERE deja de filtrar bien y el conteo no cuadra con el origen ⇒ **es la prueba end-to-end más barata de la carga**.
- ⚠️ Entorno: `get_table()` **no** acepta el nombre con backticks (el cliente los agrega) y `database.py` exige `GOOGLE_CLOUD_PROJECT` si no hay `.env` cargado; `UNIX_MICROS()` no acepta INT64 (hay que pasarle un `TIMESTAMP`).

### 4. 🔴 Hallazgo: el ORIGEN tiene un hueco de 4 días (10–13 sep)

```
07-sep (lu)  74   │  10-sep (ju)   0  ←  14-sep (lu) 175
08-sep (ma)  84   │  11-sep (vi)   0  ←  15-sep (ma) 168
09-sep (mi)  74   │  12-sep (sa)   0  ←  16-sep (mi) 172
                  │  13-sep (do)   0  ←  17-sep 155 / 18-sep 215 / 19-sep 80 / 20-sep 33
```

- **No es fin de semana** (la semana anterior sí tiene sábado 81 y domingo 22) ⇒ faltan **jue+vie+sáb+dom** ≈ 700-900 llamadas, y **nada después del 20-sep**.
- Es el mismo tipo de pérdida upstream ya conocida (cruce audio↔Excel con llave de 3 variables) → **sumarlo al segundo correo** de pedidos de datos a Juan Manuel.
- El 20-sep trae solo **33** llamadas (tope 14:00) ⇒ día incompleto, aunque la semana 14→20 sí da las 998 de los informes.

### 5. Documentación
- `CLAUDE.md` → nueva sección "Sesión 2026-10-01".
- Bóveda: `11 - Pendientes` (hueco upstream), `12 - Historial` (fila 01-oct), `Informes/2026-10-01 - Cambios del día.md` + índice, y `Trabajo con IA/01 - Perfil de opencode.md` (memorías de sesión **7ª y 8ª**: se añadió la del 29-sep, que faltaba).
- ⚠️ El código de las sesiones 28/29-sep **ya está commiteado** (`b060481`). Lo de hoy son **solo documentos**
  (`CLAUDE.md` + `opencode.md`), pendientes de commit a la espera de aprobación.
- 🧹 `.gitignore` cubre `back/reportes_segmentados/*.pdf` pero **no** los `.txt` (subproductos del validador):
  `reporte_{general,ventas,servicio}_2026-09-14_2026-09-20.txt` aparecen como untracked. Decidir si se ignoran
  o se borran (no se tocó nada sin OK).

## Ejecutado en la sesión anterior (29-sep-2026)

### 1. Fix del TMO `N/D` (el semáforo 🔴 era falso)
- **Síntoma:** los bloques de **llamadas entrantes** de los 3 informes salían con TMO `N/D` y semáforo **🔴 rojo**. No era mal desempeño: `AVG(dur_seg)` sobre un conjunto 100% NULL devuelve `NULL` y el semáforo coercionaba `None → 0`. Además el TMO general se calculaba sobre las 809 salientes y se presentaba como si fuera de las 998 (cobertura real 81,1%).
- `back/helpers/utils.py` → el CTE `resumen` ahora trae `COALESCE(COUNTIF(dur_seg > 0), 0) AS tmo_n` (conteo de llamadas **con** duración) además del `AVG`; se derivan `tmo_sin_dato` y `tmo_cubierto` (`tmo_n / total`) → alimentan el contexto y el semáforo. **Sin llamada medible → `⚪`** en vez de 🔴. El contexto dice que **no se puede calcular** y que no debe interpretarse como mal desempeño; en el parcial declara `1:17 (promediado sobre 809 de 998 llamadas = 81,1% de cobertura; el resto son entrantes sin campo de duración)`. La leyenda de rangos incluye `⚪ sin dato`.
- `back/api/ia/generar_reporte_completo.py` → prohibido inventar/estimar/juzgar un TMO `N/D`, y obligatorio citar la cobertura cuando sea parcial.
- `back/reporte_pdf.py` **no necesitó cambio**: ya mapeaba `⚪` → `N/D` con badge gris desde el 28-sep.
- **+5 tests** (`TestSemaforoTmoSinDato`) ⇒ suite **60 → 65**; `git diff --check` limpio.
- **Regenerados los 3:** general `1:17` 🟡 (81,1% cobertura) · Ventas Entrantes `N/D` ⚪ / Salientes `1:18` 🟡 · Servicio Entrantes `N/D` ⚪ / Salientes `1:14` 🟡 — 4 / 6 / 6 páginas. Validados: cero `None`/`nan`/`N/A`, cero "Sin dirección", `rgb(15,23,42)` eliminado.

### 2. 🔒 Verificación en el ORIGEN (SQL Server de la CUN) — solo lectura
- Script temporal con guardas que rechazan cualquier palabra de escritura en el texto de la consulta (se eliminó al terminar). ODBC Driver 18 a 172.16.1.33. **Cero escrituras.**
- **Origen, 14–20 sep:** `Salientes` 809 → `Tiempo␣␣de␣Conversacion` **809** y `Tiempo␣␣de␣Llamada` **809**. `Entrantes` 189 → **0 y 0**, con valor `NULL` (no cadena vacía) ⇒ el **archivo de origen de entradas no trae la columna**.
- **Total 998** llamadas · 9 asesores · tope `2026-09-20 14:00:11` ⇒ cuadra exacto con los 3 informes. Cero filas nuevas ⇒ la BD ya estaba al día.
- 🪤 **Trampa:** la columna se llama `Tiempo␣␣de␣Conversacion`, con **doble espacio**; con un solo espacio falla con `Invalid column name`. El pipeline la mapea bien (queda `Tiempo__de_Conversacion` en BigQuery), pero cualquier query manual la tropieza.
- **Contraste:** el lote de oct-2025 (7.142 filas, sin dirección) **sí trae duración al 100%** ⇒ la columna existe y se llena; lo que falta es en el archivo de **entradas**. ⇒ **No hay de dónde sacar el TMO de las entrantes**, y Steven lo pidió como KPI. Pedido nuevo para Cristian/CL Tiene y Juan Manuel.

### 3. 📧 Correo de automatización a los Juanes (29-sep) — enviado por el usuario
- **Para:** `Juan_marin@cun.edu.co` + `Juan_ganicac@cun.edu.co` (ambos en *Para*, sin copia). **Sin fecha de reunión.**
- **Corrección de encuadre:** el objetivo **no es solo nuestro pipeline**, sino **las dos etapas de código**. (a) **COE / Juan Manuel:** SFTP + STT + cruce + Ollama, hoy un **notebook** ⇒ hay que volverlo script parametrizable; es la parte difícil. (b) **nosotros:** `subir_datos.py` ya es script autónomo ⇒ `PythonOperator` sin reescribir nada.
- **7 preguntas:** nodo **GPU/CUDA** para `faster-whisper` · **dónde vive Ollama** y si es alcanzable desde Airflow · **credenciales** de SFTP y BD · **salida a `api.openai.com` y BigQuery** (la más crítica tras la auditoría) · **secrets** · **dependencias/ODBC Driver 18** en la imagen · **gobernanza** del DAG.
- **Quitado del borrador por decisión del usuario:** el split Frente 1 (código al DAG, con Excel manual) / Frente 2 (eliminar el Excel, depende de S3), y la pregunta del día de corte semanal. **Cierre en tono de escalada** ("reunión urgente", "escalar con quien corresponda", "solución definitiva").
- ⚠️ **Riesgos a vigilar en la respuesta:** (1) al no conservar el split, "eliminar los Excel" puede leerse como "reemplaza el Excel por ContactVox", que **no está en manos de Juan Manuel** (depende de S3; Fabián ya tiene el hilo con Daniel Obando) — la respuesta es que el frente 1 sí lo destraba él; (2) **"los dos casos" es ambiguo** (las dos etapas *o* los dos problemas de datos) → aclarar en una línea en el primer reply.

### 4. Decisiones tomadas (usuario) para este commit
- **Los 3 PDF de `back/reportes_segmentados/` NO entran al repo** (salida de producción, regenerable con `--solo-pdf`) → se agregan al `.gitignore` junto a `reporte_semanal_dryrun.pdf`. **Los 2 HTML sidecar sí** (función de auditoría).
- `informe_sesion_2026-09-28.html` entra en el **mismo commit** (la convención del repo es que los informes viven en la raíz).
- **Segundo correo con los pedidos de datos** (WAP, NO ANSWER/BUSY, `Salientes→Saliente`, hora del filename, duración en entradas): **no se manda hoy** — el correo del 29-sep fue solo de automatización.

## Ejecutado en la sesión anterior (28-sep-2026)

> Estado al cierre de esa sesión: BigQuery **50.994 filas** (historia 2025-10-10 → **2026-09-20**, 27 asesores,
> 0 `Cuenta NULL`); el SQL CUN volvió a avanzar tras el no-op del 25-sep. `mixto` eliminado y `tipo`
> normalizado a **2 valores exactos** — ventas **28.911** / servicio **22.083** (los filtros por tipo ya ven el
> 100% de las llamadas, antes escondían el 21,6%). **3 informes PDF** generados (general + ventas + servicio),
> sin correo ni registro.

### 1. Fix del bug `mixto` (2 archivos, 3 hunks)
- `back/subir_datos.py` → el query principal usa `b.[tipo] AS tipo` (se eliminan el CTE `registros_unicos` y su
  `INNER JOIN`). Verificado con queries que el JOIN devolvía **exactamente** las mismas 52.035 filas que el `WHERE`
  ⇒ cero cambio en el conjunto de filas. Comentario explicativo agregado en el código.
- `back/subir_datos.py` → una línea de normalización en `procesar()`, junto a la de `Tipo_Llamada`:
  `df['tipo'] = df['tipo'].str.strip().str.lower().replace({'venta':'ventas','servicios':'servicio'})`
  (el origen trae `venta` y `servicios` como variantes).
- `back/api/upload/procesador.py` (legacy) → mismo simplificado del query + la misma normalización, para que el
  endpoint muerto no reintroduzca el bug. Diff total: **+19 / −31 líneas** en 2 archivos.
- `tipo` no lo lee ningún otro paso del pipeline (verificado con grep) → sin efectos colaterales.

### 2. Recarga de la BD (49.996 → 50.994 filas)
- **Pre-flight en seco antes de escribir** (decisión de seguridad): se corrió `cargar_desde_sql()` sin subir →
  59.177 leídas, dedup 8.183, **50.994** y `tipo` ya en 2 valores ⇒ el fix se confirmó **antes** del `WRITE_TRUNCATE`.
- **Sin backup nuevo** (decisión del usuario): `..._cltiene_llamadas_procesadas_backup_20260925` (49.996) **era el
  estado exacto previo** ⇒ sirve de punto de rollback.
- Corrida `$env:PYTHONIOENCODING='utf-8'; $env:MODELO_HABLANTES='gpt-4o'; python .\subir_datos.py` desde `back/`,
  red CUN, 2 API keys. **09:03:45 → 09:07:37** (~4 min). Leídas 59.177 (52.035 ISO + 7.142 español) → dedup
  **8.183 (13.8%)** → escritas **50.994**.
- **37 tests OK** (`$env:PYTHONPATH='.'; python -m unittest discover -s tests`). ⚠️ El venv local no tenía
  `fastapi` ⇒ `test_reporte_semanal` no importaba (fallo de entorno, no de código); se resolvió con
  `python -m pip install fastapi` (0.141.1), sin tocar pandas.
- Entorno: **Python 3.14.5, pandas 3.0.5** (el fix INTEGER-ns de `subir_bigquery()` aplica y se verificó),
  pyodbc 5.3.0 / ODBC Driver 18, sqlalchemy 2.0.54.

### 3. Verificación post-carga (BigQuery)
- `SELECT tipo, COUNT(*)` → **ventas 28.911 / servicio 22.083** (= 50.994). `mixto = 0`, `servicios = 0`, `venta = 0`, `tipo NULL = 0`.
- **Schema idéntico al backup `_20260925`**: 57 columnas, `Fecha` y `fecha_carga` = **INTEGER ns** ⇒ contrato
  `DIV(Fecha,1000)` del backend intacto (el riesgo del 16-sep).
- `Cuenta NULL = 0` · 27 asesores · historia 2025-10-10 → **2026-09-20**.
- `Tipo_Llamada` **sin cambios**: Entrante 5.946 / Saliente 20.019 / NULL 25.029 (49%) ⇒ los 998 nuevos traeían todos dirección.
- **Sin regresión de `Transcripcion_V4`:** filas con texto pero sin V4 959 → 1.034 (fragmentos STT cortos, esperado).
- **KPIs de referencia (28-sep):** contacto efectivo **27,9%** (14.236 Contactado / 36.758 Sin Contacto = 100% del total)
  · saludo completo `Sí` 425 (Sí+Parcial 8.122) · posibles ventas (regex) 886 · marcador (46.191 con dato):
  ANSWERED 35.172 / NO ANSWER 11.017 / BUSY 1.
- Cobertura tipo × dirección post-fix: ventas 1.414 entrantes / 13.334 salientes / 14.163 NULL; servicio 4.532 / 6.685 / 10.866.

### 4. Documentación actualizada (sin commit — no hay aprobación)
- `CLAUDE.md` → nueva sección "Sesión 2026-09-28" + el hallazgo del 25-sep marcado como resuelto.
- Bóveda: `11 - Pendientes` (cerrado el `mixto`, fechas al 20-sep), `12 - Historial` (fila 28-sep + sección del bug),
  `13 - Envío Semanal` (roadmap actualizado, preflight A cumplido), `Informes/informe_sesion_2026-09-28.html`.
- `opencode.md` (este archivo) + `Trabajo con IA/01 - Perfil de opencode.md` (memoria de sesión 6).
- ⚠️ **Trampa latente NO tocada (fuera de alcance):** la pareja `tipo_llamada`→columna `tipo` (negocio) y
  `seguimiento_llamada`→columna `Tipo_Llamada` (dirección) está **invertida**; renombrarla exige deploy backend + frontend.

## Ejecutado en la sesión anterior (25-sep-2026)

### 1. Apagado del envío automático (protecciones, decisión del usuario)
- `gcloud scheduler jobs pause cltiene-reporte-semanal` (region `us-central1`) → estado **PAUSED**.
- `gcloud run jobs update cltiene-envio-reporte` → **`REPORTE_ENABLED=0`** y **`ALERTA_ENABLED=0`**
  (ambos verificados en la plantilla del job; un primer intento con un solo `--update-env-vars` mal formado
  se corrigió antes de correr nada ⇒ ningún correo salió).
- **Revertir:** `gcloud scheduler jobs resume cltiene-reporte-semanal` + `gcloud run jobs update
  cltiene-envio-reporte --update-env-vars REPORTE_ENABLED=1`. Ninguna de las dos se ejecuta sin OK del usuario.
- Gotcha: PowerShell rompe `--update-env-vars A=0,B=0` (lo pasa como un string) → **flags-file JSON** o pares simples.

### 2. Backup + carga incremental (no-op) — `subir_datos.py`
- **Backup:** `desarrollo-investigaciones.call_center.cltiene_llamadas_procesadas_backup_20260925` (49.996 filas).
- Corrida: `$env:PYTHONIOENCODING='utf-8'; $env:MODELO_HABLANTES='gpt-4o'; python .\subir_datos.py` desde `back/`,
  red CUN, 2 API keys. Terminó 15:09:29.
- Leídas **58.179** (51.037 ISO + 7.142 fallback español) → dedup **8.183 (14.1%)** → escritas **49.996**.
- **La tabla NO cambió:** `MAX(Fecha)` sigue 2026-09-09 (el SQL no avanzó). Backup de igual tamaño que la tabla.
- Verificado: 27 asesores, 0 `Cuenta NULL`, historia 2025-10-10 → 2026-09-09, schema `Fecha`/`fecha_carga` =
  INTEGER ns (contrato con el backend intacto). **959 filas sin `Transcripcion_V4`** = fragmentos STT de 1–9
  chars (esperado, no bug).

### 3. Cero correos (verificado)
- `call_center.cltiene_reportes_enviados` → **0 filas**.
- La ejecución del job de las 15:00 terminó `succeeded=1` con `[SKIP]` por BD desactualizada (y con el switch en 0).

### 4. 🔴 Hallazgo: `mixto` es un bug de mapeo (origen de los 2 informes)
- `back/subir_datos.py:154` → `CASE WHEN a.cant > 1 THEN 'mixto' ELSE b.tipo END`; el CTE `registros_unicos`
  cuenta filas por `COALESCE(cuenta, Agente)` + **timestamp** (no "día"). Resultado: **10.783 filas (~21,6%)**
  marcadas `mixto` → **invisibles** en los filtros `tipo=ventas` / `tipo=servicio` aunque el origen sí tiene tipo.
- El mismo `CASE` está en `back/api/upload/procesador.py:85-88` (endpoint legacy) → hay que corregirlo también.
- El fallback (`sql_fb`, línea 168) ya usa `b.[tipo] AS tipo` (sin `mixto`).
- **Cruce real medido (BigQuery, 49.996 filas):**

  | tipo | Entrante | Saliente | NULL | Total |
  |---|---|---|---|---|
  | ventas | 978 | 11.476 | 11.884 | 24.338 |
  | servicio | 289 | 5.348 | 9.234 | 14.871 |
  | mixto | 4.486 | 2.386 | 3.911 | 10.783 |
  | servicios (typo) | — | — | — | 4 |
  | **Total** | 5.757 | 19.210 | 25.029 | 49.996 |

  ⇒ `Tipo_Llamada` es **NULL en el 50%** de las llamadas. Cualquier informe "entrantes vs salientes" debe
  declarar la cobertura o incluir un apartado **"Sin dirección"**.

### 5. Decisiones tomadas (usuario) + cierre de las 3 preguntas abiertas
- **2 archivos PDF**: Ventas y Servicio, cada uno con apartados **Entrantes** y **Salientes**. **Sin correo.**
- **`mixto` se elimina del mapeo** de `subir_datos.py` (usar `b.[tipo] AS tipo`, eliminar CTE + JOIN) → recupera
  ~10.783 filas en los filtros por tipo. No se descartan filas.
- Cerrado por mí con su OK: incluir **"Sin dirección"** (si no, se omite el 50%), normalizar
  **`servicios` → `servicio`** (4 filas), **replicar el fix en `procesador.py`**, y usar como periodo la
  **última semana completa disponible 2026-08-31 → 2026-09-06** (la BD no pasa del 09-sep).

### 6. Auditoría de reportes/filtros (solo lectura)
- `generar_reporte_completo(FilterModel)` ya acepta `tipo_llamada` y `seguimiento_llamada` (los filtros CLI son
  solo de fecha) → reutilizable con overrides.
- `contexto_tipo_llamada()` adapta el prompt a Servicio, pero **no excluye** la métrica "Posibles ventas"
  (y el desglose por asesor / semáforo la siguen incluyendo) → quitar en modo servicio.
- `get_data_context()` **no trae** el desglose por `Tipo_Llamada` → hay que agregarlo para los 2 PDFs.
- `enviar_reporte_semanal.py` no tiene flags de tipo/dirección: para los PDFs se necesita un script nuevo
  (o flags nuevos) — **no tocar el job de producción** (queda apagado).

## Ejecutado en la sesión anterior (23-sep-2026)

### 1. Carga incremental de la BD (49.880 → 49.996 filas)
- **Backup previo:** `desarrollo-investigaciones.call_center.cltiene_llamadas_procesadas_backup_20260923`
  (estado previo, 49.880 filas).
- **SQL CUN verificado:** servidor 172.16.1.33 alcanzable · total crudo **58.179** · `MAX(Fecha)` ISO =
  **2026-09-09** · filas nuevas post-06-sep = **232** (07-sep:74, 08-sep:84, 09-sep:74).
- **Corrida incremental** con `gpt-4o` + 2 API keys (rotación), desde la red CUN.
- **Resultado:** BigQuery 49.880 → **49.996 filas**; `MAX(Fecha)` 06-sep → **09-sep**. Dedup quitó
  **8.183 (14.1%)**. Cache reutilizó 24.362 transcripciones.
- **Verificado** (BQ): 49.996 filas, 0 `Cuenta NULL`, historia 2025-10-10 → 2026-09-09, filas nuevas
  por día: 06-sep 22 · 07-sep 37 · 08-sep 42 · 09-sep 37.
- **Entorno local:** Python 3.14 (sin venv), sqlalchemy 2.0.50, pandas 2.3.3, pyodbc 5.3.0
  (ODBC Driver 18). Correr con `PYTHONIOENCODING=utf-8`.

### 2. Reporte semanal NO enviado (verificado — comportamiento correcto)
- `python enviar_reporte_semanal.py --dry-run` → `[AUTO] MAX(Fecha)=2026-09-09 → última semana
  completa 2026-08-31 a 2026-09-06`; `[SKIP] BD desactualizada ... requiere terminar >= 2026-09-16
  (exit 0)`.
- El scheduler (`cltiene-reporte-semanal`) seguirá en SKIP hasta que exista una semana completa que
  termine **≥ 16-sep**. NO se disparó correo colateral por la carga.
- **Decisión tomada:** NO fijar `REPORTE_ENABLED=0` → se confía en el gate de frescura del job.

### 3. Informe de sesión `informe_sesion_2026-09-23.html`
- Réplica exacta de la plantilla `informe_sesion_2026-08-24.html` (mismo CSS, logo CL Tiene base64).
- **Alcance elegido por el usuario:** todo el proyecto 2026 (resumen + entregables + evolución BD +
  cierre sesión + pendientes + anexo Rosselin). Guardado en la raíz del repo.
- **Nota de encoding:** el primer reemplazo del logo con `Set-Content` de PowerShell corrompió los
  acentos (produjo caracteres corruptos tipo mojibake) → se **reescribió el archivo con UTF-8 limpio**
  y el logo (base64 de 22.274 chars extraído de la plantilla) se insertó con un **script Python**
  (evita recodificación).
- **Sección 6 · Anexo — Entregables de Rosselin:** agrega al informe la mención (sin copiar archivos)
  de los 2 entregables ya hechos de Rosselin Ibarra Castillo (ver hallazgo abajo).

### 4. Hallazgo de negocio — Cristian Galeano (21-sep-2026, WhatsApp)
- **La venta real NO es enlazable a una llamada por ahora:** "la llamada no está enlazada a un caso
  en Zoho".
- Cristian (reemplazo de Sergio) pasará los datos **separando Servicio y Ventas**, como indicó Steven.
- Entregables de Rosselin YA existentes en `C:\Users\diego_ojeda\Downloads\`:
  - `Metodologia_Replicacion_Rosselin.pptx` — 5 diapositivas: datos del caso (1.411 llamadas, puesto
    2/11, 10.0% calidad, 79% saludo completo, posibles ventas 0.57% vs 2.58% equipo → modelo =
    disciplina/volumen, no cierre), 5 fases (Diagnosticar→Codificar→Transferir→Acompañar→Medir),
    plan 4 semanas y metas del equipo.
  - `mi-desempeno-Rosselin Ibarra Castillo (10) (1).pdf` — informe general de desempeño (14-sep-2026,
    la más reciente de 13 versiones). ⚠️ La IA **no puede leer PDFs** (solo se describió desde el PPTX
    y datos BigQuery).

## Pendientes puntuales para la siguiente sesión

### Nuestro lado (DivergencyAI / Diego) — **prioridad de esta semana**
- [x] **Quitar `mixto` del mapeo** (`back/subir_datos.py` + `back/api/upload/procesador.py`) + normalizar
      `servicios` → `servicio`, recargar y verificar `mixto = 0` → **HECHO 2026-09-28** (50.994 filas, 2 tipos).
- [x] **Generar los informes PDF locales** = **3 informes**: el **general** (el que va al correo) + los 2
      **segmentados** (ventas / servicio), estos últimos con apartados **Entrantes** y **Salientes** (el bucket
      "Sin dirección" se **excluyó** por decisión del usuario, aunque el histórico tiene 49% sin dirección),
      periodo **2026-09-14 → 2026-09-20** → **HECHO 2026-09-28**. Ventas 14/576 · Servicio 175/233 (998 en total).
      Modo Servicio con **0 menciones de ventas** (Tablero de 7 filas). **Sin SMTP, sin registro, sin tocar el
      job/scheduler.** Script segmentador: `back/generar_reportes_segmentados.py` (`--solo-html`, `--solo-pdf`,
      `--forzar`, `--tipos`, `--direcciones`); validador `back/tests/validar_reportes_segmentados.py` (cubre los 3).
- [x] **Arreglar el TMO `N/D` de los entrantes** (era semáforo 🔴 falso) + verificar en el origen →
      **HECHO 2026-09-29**. `tmo_n`/`tmo_cubierto`, `⚪` en vez de 🔴, cobertura declarada. **65 tests OK.**
- [x] **Correo de automatización a los Juanes** (las 2 etapas de código + 7 preguntas) → **HECHO 2026-09-29**,
      enviado por el usuario. **Pendiente: que agenden la reunión.**
- [ ] **Reenviar los 3 informes con el fix del TMO** — solo con OK explícito (el correo de prueba del 28-sep
      lleva las versiones previas al fix).
- [ ] **Segundo correo con los pedidos de datos sueltos** — llave WAP, NO ANSWER/BUSY, `Salientes→Saliente`,
      hora del filename, y el **campo de duración ausente en el Excel de entradas** (nuevo, verificado en origen).
- [ ] **Reactivar el envío automático** solo con OK explícito: `gcloud scheduler jobs resume` +
      `REPORTE_ENABLED=1` (hoy: PAUSADO / `REPORTE_ENABLED=0` / `ALERTA_ENABLED=0`). Ya no falta frescura de datos.
- [ ] **Informe técnico v3.4:** portada/footer, pestaña 7 "Prueba de Saludos", tablas stale
      (KPIs/embudo), sección Despliegue (auth + min-instances + job/scheduler), sección
      "Actualizaciones Sep-2026", limitaciones. Sincronizar copia en `CLTieneBobeda\Documentos\`.
- [ ] **Renombrar la pareja invertida** `tipo_llamada`→`tipo` (negocio) y `seguimiento_llamada`→`Tipo_Llamada`
      (dirección): es la trampa latente más confusa del esquema. Requiere deploy backend + frontend.
- [ ] **Partir el monolito** `subir_datos.py` (~1.130 líneas) en módulos · `clear_cache()` al final del pipeline.
- [ ] Decidir **migración del remote git** a `https://github.com/AndreaRamirez123/CLTiene.git`
      (la URL vieja avisa movida).

### Lado CUN / CL Tiene (upstream)
- [ ] **Venta real** (Zoho `Cerrado Ganado`): sigue **no enlazable a una llamada** (Cristian Galeano, 21-sep:
      "la llamada no está enlazada a un caso en Zoho"). Cristian pasará los datos separando Servicio/Ventas.
- [ ] **Juan Manuel (CUN):** cargar Excel nuevos al SQL (**🔴 la BD no avanza desde el 20-sep y tiene un hueco de
      4 días: 10, 11, 12 y 13-sep con 0 llamadas, ≈700-900 perdidas — verificado en el origen el 01-oct**) ·
      incluir NO ANSWER/BUSY · mejorar STT (large-v3, beam_size, VAD) · parsear la hora real del filename (arregla
      Hora Pico 00:00) · cruce por llave WAP (~40% pérdida) · **`Salientes` → `Saliente`** (prometido en jul, sin aplicar).
- [ ] **Juan Manuel (CUN) — pedidos NUEVOS del 29-sep:**
  - [ ] **Añadir el campo de duración al Excel de ENTRADAS** (verificado en origen: 189/189 entrantes con `NULL`
        en `Tiempo␣␣de␣Conversacion` **y** `Tempo␣␣de␣Llamada`; el lote oct-2025 sí lo trae al 100%). Sin eso el
        TMO de las entrantes no existe, y Steven lo pidió como KPI. Coordinar con Cristian.
  - [ ] **Convertir el notebook en script parametrizable** (fecha de corte, reintentos, logs) para que un DAG lo orqueste.
  - [ ] **Responder las 7 preguntas** del correo del 29-sep (nodo GPU, Ollama, credenciales SFTP/BD, egress a
        OpenAI/BigQuery, secrets, dependencias/ODBC, gobernanza) y **agendar la reunión**.
- [ ] **S3:** agregar cédula del cliente al origen (pendiente respuesta).
- [ ] **CL Tiene:** renombrar carpeta `ecendales` → `agenteN` (Edwin Cendales aparece).
- [ ] **Airflow** (Santamaría / infraestructura): eliminar Excel intermedios. Correo enviado el 29-sep; el bloqueo
      real es de **entorno**, no de código. ⚠️ "Eliminar el Excel" (frente 2) depende de S3 y **no** de esta reunión.

## Inventario de herramientas / automatización usadas

| Categoría | Herramienta | Detalle |
|---|---|---|
| Base de datos | **BigQuery** (Google) | Tabla `desarrollo-investigaciones.call_center.cltiene_llamadas_procesadas` + **10 backups** (dates 20260709 → 20261001). `Fecha` INTEGER ns → `DATETIME(TIMESTAMP_MICROS(DIV(Fecha,1000)))`. El backup se crea con **DDL `CREATE TABLE ... COPY`**, no con `copy_table(write_disposition=...)` (no existe ese parámetro). |
| Backend | **Cloud Run** `cltiene-backend` | FastAPI, `min-instances=1` (sin cold start), CORS restringido, auth Firebase. |
| Envío semanal | **Cloud Run Job** `cltiene-envio-reporte` | Corre `python enviar_reporte_semanal.py` (WeasyPrint PDF + SMTP). ⚠️ **25-sep: `REPORTE_ENABLED=0`** (apagado por decisión del usuario). |
| Programación | **Cloud Scheduler** `cltiene-reporte-semanal` | `0 8-18 * * 1-5`, tz `America/Bogota`. ⚠️ **25-sep: PAUSADO** (`gcloud scheduler jobs resume` para revertir). |
| Secretos | **Secret Manager** `smpt-diego-cun` | App password Gmail (16 chars corridos). |
| Build | **Cloud Build** | Imagen del backend (deploy `--source` desde `back/`). |
| Frontend | **Firebase Hosting + Auth** | `cltiene-dashboard.web.app`; login con dominio @cltiene.com/@cun.edu.co. |
| IA | **OpenAI gpt-4o** | Endpoints IA (12) + separación de hablantes (prompt v16); `OPENAI_API_MUNDIAL` + `_2` rotando. |
| Origen | **SQL Server CUN** 172.16.1.33 | ODBC Driver 18; solo lectura (regla: nunca escribir). |
| Correo | **SMTP Gmail** | `divergencyai@gmail.com` (app password MFA) → Steven (reporte) / Juanes (alerta opcional). |
| PDF | **WeasyPrint** | HTML→PDF con branding (pinned weasyprint==62.3 + pydyf==0.11.0). |
| CLI | **gcloud CLI** | ⚠️ **28-sep: el token volvió a expirar** y no se puede reautenticar en modo no interactivo (`Reauthentication failed. cannot prompt during non-interactive execution`) → `bq` no sirve; **BigQuery se sigue consultando con Python (ADC funciona)**. Reautenticar con `gcloud auth login` desde una terminal normal. |
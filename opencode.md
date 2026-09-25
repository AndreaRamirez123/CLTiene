# opencode.md — Memoria de sesión CLTiene

> Este archivo es la **memoria de sesión** de trabajo con opencode. Hereda de `CLAUDE.md`
> (contexto permanente del proyecto) y documenta **solo lo ejecutado en cada sesión** +
> pendientes para la siguiente, para seguimiento e informes. Actualizar al terminar cada sesión.

## Estado al cierre (25-sep-2026)

- **BD BigQuery:** 49.996 filas · historia **2025-10-10 → 2026-09-09** · 0 `Cuenta NULL` · 27 asesores.
  El SQL CUN **no tiene datos después del 09-sep** → la carga del 25-sep fue un **no-op** (la tabla no cambió).
- **Envío semanal: APAGADO** (decisión del usuario) — Scheduler `cltiene-reporte-semanal` **PAUSADO** y job
  `cltiene-envio-reporte` con `REPORTE_ENABLED=0` + `ALERTA_ENABLED=0`. `cltiene_reportes_enviados` **vacía**:
  nunca se ha enviado el reporte real a Steven. Ver "Ejecutado 2026-09-25".
- **Pendiente en curso:** quitar el `mixto` del mapeo (`subir_datos.py` + `procesador.py`) y generar **2 informes
  PDF locales** (Ventas y Servicio, cada uno con Entrantes/Salientes) — sin correo.
- **Informe de sesión** más reciente: `informe_sesion_2026-09-23.html` (portada oscura `#FC3276`, 6 secciones).

## Ejecutado en esta sesión (25-sep-2026)

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
- [ ] **Quitar `mixto` del mapeo** en `back/subir_datos.py` (`b.[tipo] AS tipo` + eliminar CTE/JOIN) **y** en
      `back/api/upload/procesador.py:85-88`; normalizar `servicios` → `servicio`. Recargar incremental
      (backup `..._backup_20260925` listo) y verificar `mixto = 0` sin cambiar el total ni `Tipo_Llamada`.
- [ ] **Generar 2 informes PDF locales** (Ventas / Servicio), cada uno con **Entrantes**, **Salientes** y
      **"Sin dirección"**, periodo **2026-08-31 → 2026-09-06**: agregar el desglose por `Tipo_Llamada` a
      `get_data_context()`, quitar "Posibles ventas" del prompt en modo servicio, y un script nuevo con
      overrides de tipo/dirección. **Sin SMTP, sin registro de envíos, sin tocar el job.**
- [ ] **Reactivar el envío automático** solo con OK explícito: `gcloud scheduler jobs resume` +
      `REPORTE_ENABLED=1` (hoy: PAUSADO / `REPORTE_ENABLED=0` / `ALERTA_ENABLED=0`).
- [ ] **Informe técnico v3.4:** portada/footer, pestaña 7 "Prueba de Saludos", tablas stale
      (KPIs/embudo), sección Despliegue (auth + min-instances + job/scheduler), sección
      "Actualizaciones Sep-2026", limitaciones. Sincronizar copia en `CLTieneBobeda\Documentos\`.
- [ ] **Commit/push pendientes:** `informe_sesion_2026-09-23.html`, `CLAUDE.md` y `opencode.md`.
- [ ] **Partir el monolito** `subir_datos.py` (~1.130 líneas) en módulos · `clear_cache()` al final del pipeline.
- [ ] Decidir **migración del remote git** a `https://github.com/AndreaRamirez123/CLTiene.git`
      (la URL vieja avisa movida).

### Lado CUN / CL Tiene (upstream) — sin cambios
- [ ] **Venta real** (Zoho `Cerrado Ganado`): sigue **no enlazable a una llamada** (Cristian Galeano, 21-sep:
      "la llamada no está enlazada a un caso en Zoho"). Cristian pasará los datos separando Servicio/Ventas.
- [ ] **Juan Manuel (CUN):** cargar Excel nuevos al SQL (la BD está parada en 09-sep) · incluir NO ANSWER/BUSY ·
      mejorar STT (large-v3, beam_size, VAD) · parsear la hora real del filename (arregla Hora Pico 00:00) ·
      cruce por llave WAP (~40% pérdida).
- [ ] **S3:** agregar cédula del cliente al origen (pendiente respuesta).
- [ ] **CL Tiene:** renombrar carpeta `ecendales` → `agenteN` (Edwin Cendales aparece).
- [ ] **Santamaría:** migración a Airflow (eliminar Excel intermedios).

## Inventario de herramientas / automatización usadas

| Categoría | Herramienta | Detalle |
|---|---|---|
| Base de datos | **BigQuery** (Google) | Tabla `desarrollo-investigaciones.call_center.cltiene_llamadas_procesadas` + **9 backups** (dates 20260709 → 20260925). `Fecha` INTEGER ns → `DATETIME(TIMESTAMP_MICROS(DIV(Fecha,1000)))`. |
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
| CLI | **gcloud CLI** | Reautenticado el 25-sep (`gcloud auth login`) tras expirar los tokens. |
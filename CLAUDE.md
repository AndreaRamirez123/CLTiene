# CLTiene Dashboard — Contexto para Claude Code

> Este archivo se carga automáticamente en cada conversación. Mantenerlo actualizado al terminar cada sesión.

## Proyecto

Dashboard de análisis de llamadas de call center para **CL Tiene Soluciones** (Colombia).
Desarrollado por **DivergencyAI SAS**.

## Actores del ecosistema (aclarado 2026-07-03)

| Actor | Qué es | Rol |
|---|---|---|
| **CL Tiene Soluciones** | Empresa de asistencias (hogar/salud/vehículo) — cltiene.com | **El cliente**, dueño de las llamadas y del dashboard. **Sergio Nieto** (admin del call center) es quien **envía/coordina los datos** desde CL Tiene: el Excel de metadata y las carpetas de audio (`agenteN`) |
| **DivergencyAI SAS** | Nosotros — **spinoff de la CUN** (vicerrectoría de innovación, investigación y extensión). divergencyai.com | Desarrollamos el dashboard (pipeline V4 + BigQuery + frontend) |
| **CUN** | Corporación Unificada Nacional de Educación Superior — universidad (Bogotá) | Su **COE de analítica** (Juan Manuel Marín) hace el STT + Ollama y hostea el SQL Server intermedio (`CUN_REPOSITORIO`, 172.16.1.33). DivergencyAI es spinoff de su vicerrectoría de innovación |
| **S3 Simple Smart Speedy S.A.S.** | Proveedor de telecom/datacenter/hosting (Bogotá) — s3.com.co. **NO es AWS S3** | Maneja la **infraestructura del audio/grabaciones** (el origen). Con ellos se habla la calidad del audio; su encargado está en gestiones de auditoría |
| **ContactVox** | Marcador/dialer | Genera las grabaciones (carpeta `ContactVox_CLTIENE` en el FTP) |
| **David Cerón Aponte ("el BI")** | Persona en la CUN | Maneja un **segundo dashboard/tablero de CL Tiene, desarrollado por la CUN** (aparte del nuestro). Cuando Juan dice "decirle al BI" para actualizar, se refiere a ESE tablero, no al de DivergencyAI |

> **Ojo — hay DOS dashboards de CL Tiene:** (1) el **nuestro** (DivergencyAI, React + BigQuery, `cltiene-dashboard.web.app`, se actualiza con `subir_datos.py`) y (2) el de la **CUN** (lo maneja David Cerón / "el BI"). Ambos se alimentan del mismo SQL Server pero son productos distintos.
>
> **Dashboard de la CUN** = un **Power BI** ("Dashboard de Llamadas de Ventas", app.powerbi.com) enfocado en KPIs de ventas + sentimiento: total llamadas, % Efectivas (usa `efectiva`), % contestación/abandono, ventas, ticket promedio, y los campos TextBlob (Subjetividad/Confianza/Polaridad por asesor). Separa correctamente `efectiva` de ventas.
>
> **Diferenciadores del NUESTRO** (lo que el Power BI de la CUN NO tiene): visor de transcripciones (chat cliente/asesor), separación de hablantes con IA (v16 + gpt-4o), análisis por llamada con IA (scorecard/coaching), historial por teléfono, reportes IA que se adaptan a Ventas/Servicio. Resumen: el de la CUN es **reporte de KPIs**; el nuestro es **análisis profundo con IA + transcripciones** (complementarios, distinto propósito).

## Stack

| Capa | Tecnología |
|------|-----------|
| Frontend | React 19 + Vite 7 → Firebase Hosting |
| Backend | Python 3.11 + FastAPI → Google Cloud Run |
| Base de datos | Google BigQuery |
| IA | OpenAI gpt-4o (`OPENAI_API_MUNDIAL`) |

## URLs de producción

- **Frontend:** https://cltiene-dashboard.web.app
- **Backend:** `https://cltiene-backend-293865702055.us-central1.run.app`
  - Centralizado en `src/config.js` como `API_BASE`

## Flujo de datos completo (confirmado con Diego 2026-07-03)

```
CL Tiene
  ├── FTP: AUDIO de las llamadas (en carpetas por agente → por eso importa el nombre "agenteN")
  └── Excel: metadata (Tiempo de Conversacion, agente, fecha)
         │
         ▼
   Código de Juan Manuel (COE) — notebook `Proceso llamadas CL Tiene.ipynb`:
     1. EXTRACCIÓN: baja el audio del FTP y hace el STT (audio → texto)  ← el STT vive AQUÍ
     2. cruce con el Excel por fecha + agente
     3. EVALUACIÓN: Ollama qwen2.5 (7 categorías de calidad + efectiva)
         │
         ▼
   SQL Server (CUN, 172.16.1.33) → BigQuery (nuestro pipeline subir_datos.py) → Dashboard
```

- **El audio vive en un FTP** (de CL Tiene), en carpetas por agente. El **cruce** con el Excel es por **fecha + agente** (frágil → tema del martes / Airflow).
- **El STT (audio → texto) se hace DENTRO del código de Juan** con **`faster-whisper`** (modelo Whisper de OpenAI, local en GPU/CUDA), en la parte de "extracción" del notebook. NO es un servicio de un tercero. (La parte que revisamos, "evaluación de llamadas", es solo el Ollama de calidad.)
  - Fuente audio: **SFTP** `/u01/bk/ftp/telefonia/ContactVox_CLTIENE` (marcador **ContactVox**), recorrido por carpeta agente → año → fecha (por eso importa `agenteN`).
  - **Config actual del STT (verificada en el notebook 2026-07-03) — explica las transcripciones malas:**
    | Parámetro | Valor actual | Problema / mejora |
    |---|---|---|
    | `MODEL_NAME` | `"medium"` | Modelo mediano → palabras deformes. Subir a `large-v3` mejora mucho. |
    | `beam_size` | `1` | El más rápido pero menos preciso. Subir a `5`. |
    | `vad_filter` | `True` (min_silence 400ms) | **Recorta silencios/voz baja → causa probable de "se entrecortan".** Revisar/ajustar. |
- **Ahí es donde se pierden/entrecortan las transcripciones.** Dos causas, con responsables distintos:
  - **Audio malo/cortado en el FTP** → lo genera CL Tiene (grabación).
  - **STT débil (faster-whisper `medium` + `beam_size=1` + VAD agresivo)** → es config del código de Juan (COE); se puede mejorar.
  - Llamada muy corta → el STT solo capta el saludo (esperado).
- **Es el cuello de botella real y está upstream de nosotros.** La separación cliente/asesor (nuestra, con OpenAI) solo puede ser tan buena como el texto del STT — si llega mal, ningún prompt lo arregla.
- **Caso Edwin Cendales:** su carpeta de audio en el FTP se llama `ecendales` (no `agenteN`) y el código de Juan solo lee carpetas con la palabra "agente" → por eso no aparece. Lo corrige CL Tiene renombrando la carpeta.
- Nuestro pipeline V4 **solo separa cliente/asesor** (Transcripcion_V4); NO hace STT ni el cruce — eso es del lado de la CUN.

## BigQuery

- Tabla: `desarrollo-investigaciones.call_center.cltiene_llamadas_procesadas`
- `Fecha` es INTEGER en nanosegundos → `DATETIME(TIMESTAMP_MICROS(DIV(Fecha, 1000)))`
- `Resultado_Llamada = 'Venta'` (BigQuery es case-sensitive)
- `saludo_inicial` (CUN, 0/1) ≠ `Saludo_Completo` (pipeline, "Sí"/"Parcial"/"No")

## Columnas de la CUN — cómo se calculan (código de Heider/Juan Manuel, notebook `Proceso llamadas CL Tiene.ipynb`)

> Confirmado en reunión BD 2026-07-01. El proceso de la CUN es **independiente** de nuestro pipeline V4.

- **Motor:** Ollama local con modelo `qwen2.5:7b-instruct` (temperature 0). No usa OpenAI.
- **7 categorías de calidad (cada una 0/1)**, el LLM devuelve JSON con 1 si aparece claramente:
  `saludo_inicial`, `identificacion_cliente`, `comprension_problema`, `ofrecimiento_solucion`, `manejo_inquietudes`, `cierre_servicio`, `proximo_paso`
- **`efectiva` NO es venta.** Es score de calidad: `puntaje = sum(7 categorías)/7`; `efectiva = 1 if puntaje >= 0.8 else 0` (mínimo 6 de 7 categorías cumplidas).
  - ⚠️ NO usar `efectiva` como sinónimo de `Resultado_Llamada = 'Venta'`. Miden cosas distintas: `efectiva` = calidad del asesor; `Venta` = si hubo venta real (lo detecta nuestro pipeline).
- **`polarity`, `subjectivity`, `clasificacion`, `confianza`** → vienen de TextBlob/NaiveBayes, NO del LLM.
  - `clasificacion` = `positivo` si polarity≥0.1, `negativo` si ≤−0.1, `neutro` en medio.
- **`palabras`** = conteo regex `\b\w+\b` sobre la transcripción.
- **`Tiempo de Conversacion` sale del Excel que envía CL Tiene, NO se calcula del audio** → por eso puede no coincidir con la duración real de la transcripción. Juan Manuel solo cruza (join) ese Excel con la transcripción por fecha + agente.
- **Transcripciones entrecortadas** = llamadas de pocos segundos; el STT solo alcanza a capturar el saludo. Es esperado, no un bug.

### Hallazgos reunión 2026-07-01 (pendientes del lado CUN)
- **Edwin Cendales sin datos desde 3-feb:** su carpeta en el servidor se llama `ecendales` (su nombre), no `agenteN`. El algoritmo solo extrae carpetas con la palabra "agente". → **CL Tiene** (Sergio Nieto / admin del call center) debe renombrar todas las carpetas a `agenteN`. NO es tarea de la CUN/COE ni de DivergencyAI.
- **`Salientes` vs `Saliente`:** error de Juan Manuel, lo corregirá en la BD (dejar una sola nomenclatura).
- **`Agente` vs `Cuenta` truncado:** hay dos formatos de Excel (entrante/saliente) con estructura distinta; en uno la info viene truncada. Se alinea en reunión del martes.
- **Reunión martes 2026-07-07 9am** ("Revisión de procesos de llamadas"): objetivo = eliminar los Excel y automatizar con **Airflow** (lo desarrolla Santamaría). Diego agendado por Sofía.

### Documentación oficial del COE (el BI anterior, ~ene-2026 — puede estar desactualizada)
Diego tiene 4 docs oficiales de la CUN sobre la tabla `COE.LLAMADAS_CL_TIENE` y el Power BI. **Confirman** lo que reverse-engineeramos:
- **`efectiva` ≥ 0.8 (80%)** ✅ · **`archivo` = archivo de transcripción** ✅ · **Agente = código, Cuenta = nombre** ✅ · **NLP solo con transcripción válida** ✅ · **Exclusiones: registros duplicados** ✅ (validó el dedup) · **Ventas = tabla aparte** (`DAX_Tabla_trans_ventas`: Asesor/Categoría/Valor = el CRM) ✅.
- **Frecuencia oficial: SEMANAL** (no diaria — el `registrar_tarea.ps1` asumía 7am diario).
- **Método de las 7 categorías HOY = Ollama** (el notebook lo confirma: `build_prompt` + `/api/generate` con `qwen2.5`). El `PALABRAS_CLTIENE.txt` (diccionario de palabras clave por categoría, "NLP por similitud") es el **método VIEJO** que reemplazaron. El notebook es la fuente de verdad de lo que corre; los docs (~ene-2026) describen el enfoque anterior.
- Power BI de la CUN: página única, relación por ID llamada + Agente + Fecha, "no incluye ingresos ni llamadas sin transcripción".

## Arquitectura clave

```
FilterModel (back/api/models.py) → get_query() → WHERE clause BigQuery
buildQuery() (src/FiltersContext.jsx) → query params para fetch del frontend
```

Todos los endpoints de IA aceptan `FilterModel` como query params.

## Patrones de código establecidos

### Frontend — fetch con filtros
```js
const { buildQuery } = useFilters();
const params = buildQuery();
const query = params ? `?${params}` : '';
const response = await fetch(`${API_BASE}/ia/endpoint${query}`);
```

### Frontend — HTML de IA (limpiar colores oscuros antes de renderizar)
```js
const raw = result.result || '';
const limpio = raw
  .replace(/background-color\s*:\s*rgb\(15,\s*23,\s*42\)[^;"']*/g, 'background-color: #f8fafc')
  .replace(/color\s*:\s*rgb\(203,\s*213,\s*225\)[^;"']*/g, 'color: #334155')
  .replace(/border-bottom\s*:\s*1px solid rgb\(30,\s*41,\s*59\)[^;"']*/g, 'border-bottom: 1px solid #e2e8f0');
```

### Frontend — diseño CSS para resultados IA (estilo ReporteCompleto)
```jsx
// Tarjeta contenedora
<div style={{
  backgroundColor: '#ffffff', borderRadius: '16px', padding: '36px 40px',
  border: '1px solid #e2e8f0', boxShadow: '0 2px 10px rgba(0,0,0,0.05)',
}}>
  {/* Header con acento rosa */}
  <div style={{
    borderLeft: '5px solid #FC3276',
    background: 'linear-gradient(90deg, #fff5f9 0%, transparent 80%)',
    borderRadius: '0 10px 10px 0',
    padding: '14px 20px', marginBottom: '28px',
  }}>
    <span style={{ fontSize: '18px', fontWeight: '700', color: '#FC3276' }}>
      🔍 Título del análisis
    </span>
  </div>
  {/* Cuerpo */}
  <div style={{ lineHeight: '1.8', color: '#334155', fontSize: '14px' }}
    dangerouslySetInnerHTML={{ __html: htmlLimpio }} />
</div>
```

### Frontend — botón IA estándar
```jsx
<button style={{
  padding: '14px 22px',
  background: cargando ? '#cbd5e0' : mostrar
    ? 'linear-gradient(135deg, #64748b 0%, #475569 100%)'
    : 'linear-gradient(135deg, #FC3276 0%, #db2777 100%)',
  color: 'white', border: 'none', borderRadius: '12px',
  fontSize: '14px', fontWeight: '700', cursor: cargando ? 'not-allowed' : 'pointer',
}}>
  {cargando ? '⌛ Analizando...' : mostrar ? '✕ Ocultar' : '🧠 Analizar con IA'}
</button>
```

### Backend — siempre desempaquetar `call()`
```python
content, error = call(system_prompt, user_message)
if error: return {"error": error}
```

### Backend — adaptar reportes IA al filtro Servicio
`contexto_tipo_llamada(filters)` (en `helpers/utils.py`) devuelve una instrucción que se antepone al
system prompt. Cuando `tipo_llamada == 'servicio'` le dice a la IA que NO hable de ventas/conversión y
se enfoque en calidad de atención. Para cualquier otro caso devuelve `''` (sin cambios).
```python
from helpers.utils import get_data_context, contexto_tipo_llamada
content, error = call(
    prompt_html(contexto_tipo_llamada(filters) + "System prompt original..."),
    f"...\n{get_data_context(filters.get_query())}"
)
```
Aplicado en: `generar_insights`, `analisis_automatico`, `generar_reporte_completo`,
`analisis_comparativo_ranking`, `analizar_inteligencia_operativa`, `analizar_patrones_ventas`,
`analizar_patrones_dashboard`. El frontend (`esServicio = filters.tipo_llamada === 'servicio'`) ya
oculta columnas/pasos de ventas en Resumen, Rendimiento, Inteligencia, Embudo e IndicadoresTabla.

## Tabs del dashboard

| Tab | Archivo | Estado |
|-----|---------|--------|
| Resumen Ejecutivo | `src/tabs/Resumen.jsx` | ✅ |
| Rendimiento Asesores | `src/tabs/Rendimiento.jsx` | ✅ |
| Análisis Detallado | `src/tabs/Analisis.jsx` | ✅ |
| Inteligencia Operativa | `src/tabs/Inteligencia.jsx` | ✅ |
| Transcripciones | `src/tabs/Transcripciones.jsx` | ✅ |
| Agente IA PRO | `src/tabs/Agente.jsx` | ✅ |
| Prueba de Saludos | `src/tabs/PruebaSaludos.jsx` | ✅ desplegada (2026-07-29) |

> **Prueba de Saludos** (`PruebaSaludos.jsx`) es una pestaña **estática/puntual** (NO viene del pipeline/BigQuery): analiza la prueba A/B de 5 saludos comerciales que CL Tiene corrió sobre la base "No Contactados" (reporte de Steven Aldana, 27-jul). Los 29 registros + análisis de transcripciones están hardcodeados en un array (`RESULTADOS`), fácil de actualizar. Hallazgo: el saludo que engancha nombra el plan específico + framing de seguimiento (Saludo 4/3); los que fallan piden "¿recuerda cuál plan?" o admiten "es una llamada de ventas" (Saludo 1/5).

> ⚠️ **ESTADO al 2026-07-29 (para la próxima sesión):** la pestaña "Prueba de Saludos" ya está **DESPLEGADA** en Firebase ✅ (incluye análisis + 7 transcripciones con audio + botón PDF de informe completo). **PENDIENTE: commit + push** (`src/tabs/PruebaSaludos.jsx` nuevo, `src/pages/Dashboard.jsx`, `CLAUDE.md` sin commitear). El backend NO cambió (último rev en prod: `00116-l2l`).

## Endpoints IA

| Endpoint | Componente | Filtros conectados |
|----------|------------|-------------------|
| `GET /ia/generar_insights` | `InsightsCard.jsx` | ✅ |
| `GET /ia/inteligencia_operativa` | `Inteligencia.jsx` | ✅ |
| `GET /ia/analizar_asesor?asesor=X` | `Rendimiento.jsx` | ✅ |
| `GET /ia/analizar_llamada?llamada_id=X` | `MetricasGrid.jsx` | ✅ |
| `GET /ia/analisis_automatico?tipo_analisis=X` | `AnalisisAu.jsx` | revisar |
| `GET /ia/reporte_completo` | `ReporteCompleto.jsx` | revisar |
| `GET /ia/analisis_ranking` | `RankingIA.jsx` | revisar |

## Envío semanal automático del reporte a Steven (2026-09-15, rama `feat/envio-reporte-semanal`, DESPLEGADO 2026-09-22)

> Automatiza lo que Diego hacía a mano cada semana: generaba el Reporte Ejecutivo (Agente IA PRO → `GET /ia/reporte_completo`, HTML con gpt-4o) y enviaba el PDF (jsPDF del navegador) a **Steven Aldana** (`supervisor_contact@cltiene.com`). El PDF ya no se arma en el navegador: lo genera **Python (WeasyPrint)**.

- **Arquitectura:** Cloud Run Job `cltiene-envio-reporte` (dispara `python enviar_reporte_semanal.py`) + **Cloud Scheduler** `cltiene-reporte-semanal` cada hora laboral **lun-vie 08:00-18:00** Bogotá (`0 8-18 * * 1-5`, tz `America/Bogota` — jerarquía cada hora→ reintenta solo cuando hay semana fresca). Detecta la **semana pasada completa (lunes→domingo)** desde `MAX(Fecha)` y, si el envío de esa semana no está registrado, genera **PDF (WeasyPrint)** + **resumen en el cuerpo** y envía por **SMTP**. `--fecha-desde/--fecha-hasta` fuerza período manual (usa la semana más reciente completa de la BD, no la de calendario).
- **`back/enviar_reporte_semanal.py`** (nuevo, script del job): (1) período = semana pasada; (2) **PREFLIGHT A (BD actualizada):** `MAX(DATE(TIMESTAMP_MICROS(DIV(Fecha,1000))))` ≥ domingo pasado y el período tiene filas — si no → error claro + exit 1, NO envía; (3) **PREFLIGHT B (no duplicado):** hash **md5 de `get_data_context`** (determinista, NO del HTML de la IA) contra la tabla **`call_center.cltiene_reportes_enviados`** (`fecha_desde, fecha_hasta, hash_datos, enviado_at`, auto-creada con `CREATE TABLE IF NOT EXISTS`) — mismo hash ya enviado → no reenvía, hash distinto → reenvío legítimo; (4) `generar_reporte_completo(FilterModel)` → HTML; (5) PDF; (6) `_extraer_resumen()` → bullets del Resumen Ejecutivo para el cuerpo; (7) `smtplib` → correo; (8) INSERT en la tabla de estado solo tras éxito. Flags: `--dry-run`, `--fecha-desde/--fecha-hasta`, `--no-preflight`, `--outdir`.
- **`back/reporte_pdf.py`** (nuevo): HTML→PDF con **WeasyPrint** — limpia el fondo oscuro de la IA (`rgb(15,23,42)`→claro, igual que `limpiarHTML` del frontend), convierte el semáforo 🟢🟡🔴→palabra (como el `clean()` de ReporteCompleto.jsx) + CSS branding CL Tiene (acento `#FC3276`, tablas zebra, footer "Confidencial" + nº de página). Logo en `back/assets/logo_cl_tiene.png`.
- **SMTP REAL (hookeado al Gmail):** `smtp.gmail.com:587`, remitente **`divergencyai@gmail.com`** (`EMAIL_FROM_NAME` = "DivergencyAI SAS") → `EMAIL_TO` default `supervisor_contact@cltiene.com`. ⚠️ **El Office365 de `@cun.edu.co` (diego_ojeda) quedó DESHABILITADO** (la auth básica de Microsoft 365 está desactivada por defecto y daba `535 5.7.139`); se migró a un **Gmail** `divergencyai@gmail.com` con **contraseña de aplicación** (MFA) en el secreto `smpt-diego-cun`. ⚠️ La app password son **16 caracteres corridos** (los espacios cada 4 letras son solo visuales: `abcd efgh ijkl mnop` → `abcdefghijklmnop`); un espacio/salto extra corrompe y da `535`.
- **Kill-switches INDEPENDIENTES:** `REPORTE_ENABLED` (solo apaga el reporte a CL Tiene) y `ALERTA_ENABLED` (default `0`; enciende la alerta de BD desactualizada a `EMAIL_ALERT_TO=Juan_ganicac@cun.edu.co,Juan_marin@cun.edu.co`, una por día) — mismo patrón `AUTH_ENABLED`. **Contrato exit:** `0` = ok o skip legítimo, `1` = error real. Deploy en 2 fases: primero `REPORTE_ENABLED=0` (probar), luego `1` (activar). 🔴 **ESTADO 2026-09-25: APAGADO POR DECISIÓN DEL USUARIO** — Scheduler `cltiene-reporte-semanal` **PAUSADO** + `REPORTE_ENABLED=0` + `ALERTA_ENABLED=0` (verificado en la plantilla del job). `cltiene_reportes_enviados` tiene **0 filas** ⇒ nunca se envió el reporte real a Steven. Revertir SOLO con OK: `gcloud scheduler jobs resume cltiene-reporte-semanal` + `gcloud run jobs update cltiene-envio-reporte --update-env-vars REPORTE_ENABLED=1`.
- **`back/requirements.txt`:** +`weasyprint==62.3` +`pydyf==0.11.0` (⚠️ pin: 62.3 revienta con pydyf ≥ 0.12, `AttributeError: 'super' object has no attribute 'transform'`). **`back/Dockerfile`:** +libs `libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf-2.0-0 fonts-dejavu` (PAra WeasyPrint en Linux). El job reusa la imagen del backend con `--command python --args enviar_reporte_semanal.py`.
- **Local (Windows):** WeasyPrint necesita **GTK3 Runtime** (`winget install tschoonj.GTKForWindows`) y que `$env:PATH` incluya `C:\Program Files\GTK3-Runtime Win64\bin` antes de importar. Correr con `$env:PYTHONIOENCODING="utf-8"`.
- **Flags del script:** `--dry-run` (PDF a disco sin enviar/registrar), `--fecha-desde/--fecha-hasta` (período manual; salta detección automática pero NO salta preflights A/B), `--no-preflight` (debug), `--no-registrar` (envía pero NO registra el hash → test; mantiene libre el envío real futuro de esa semana), `--outdir`.
- **Verificado:** 37 tests (incluye `TestKillSwitchAlerta`: switch apagado no envía, encendido envía+registra + dedupe diario), **SMTP real en vivo**: dry-run local 17-23 ago, ejecuciones en Cloud con período 31-ago..06-sep: `[ENVÍO] Correo enviado a diego_ojeda@cun.edu.co` (test) y `a jose_forero@cun.edu.co` (prueba enviada por Diego a su jefe `--no-registrar`, 2026-09-22), dedup por hash `749c91…`, preflights A/B y SKIP por BD desactualizada verificados en logs. **Primer envío real a Steven sale automático cuando la BD esté fresca** (semana completa terminada ≤ 7 días; el scheduler lo reintenta cada hora).
- **Nota:** el job importa los módulos del backend directamente (NO llama al API HTTP) → **no necesita token Firebase**. Solo lee BigQuery (no toca el SQL Server de la CUN).

## Autenticación — token Firebase verificado en el backend (2026-09-02, rama `feat/auth-firebase`, DESPLEGADO)

> Cierra el hueco que marcó la revisión externa de seguridad: el frontend **ya tenía login Firebase** (`src/pages/Login.jsx` + `App.jsx` con `onAuthStateChanged`), pero el **backend NO verificaba nada** → cualquiera con la URL de Cloud Run bajaba todos los datos saltándose el login. Y el CORS era `allow_origins=["*"]` + `allow_credentials=True` (abierto e inválido).

- **Backend `back/api/auth.py`:** dependencia FastAPI `verificar_token` que valida el `Authorization: Bearer <idToken>` de Firebase — firma contra las llaves públicas de Google (`google.auth.jwt.decode`, **sin dependencias nuevas**, usa `google-auth` ya instalado), audiencia = `desarrollo-investigaciones`, emisor `securetoken.google.com/<proyecto>`, expiración, + exige dominio `@cltiene.com`/`@cun.edu.co` (igual que el front). **Certs cacheados 1h** (evita fetch por request). Sin token → **401**; dominio no permitido → 403.
- **`main.py`:** CORS restringido a `cltiene-dashboard.web.app` (+ `.firebaseapp.com` + `localhost:5173/3000`), ya no `*` (+ env `CORS_EXTRA_ORIGINS`). Dependencia global en los routers: `include_router(router, dependencies=[Depends(verificar_token)])` (a nivel router, no app). En producción, `/docs`, `/redoc` y `/openapi.json` están ocultos.
- **Rollback instantáneo sin re-deploy:** `AUTH_ENABLED=0` por env → apaga la verificación (`gcloud run services update cltiene-backend --update-env-vars AUTH_ENABLED=0 ...`).
- **Frontend `src/config.js`:** `apiFetch(url, options)` adjunta el token (`auth.currentUser.getIdToken()`) en `Authorization`; se reemplazaron los **29 `fetch`** por `apiFetch` en 21 archivos. Merge de headers preserva `Content-Type` de los POST.
- **Orden de despliegue (OBLIGATORIO):** frontend **primero** (empieza a mandar token; el backend viejo lo ignora → nada se rompe) → backend **después** (lo exige). **NO** se toca `--allow-unauthenticated` (Cloud Run sigue público; lo que asegura es el token a nivel app — Cloud Run IAM necesita OIDC de Google, no el token Firebase).
- **Verificado:** local (TestClient: 401 sin/con token malo, CORS bloquea `evil.com` y echa el origen real, toggle 200, 19 tests, build limpio) + **en vivo** (curl sin token → 401; dashboard logueado carga los 10 KPIs + Contacto Efectivo + Embudo).
- **Alcance:** solo autenticación. El **scoping por asesor** (que cada uno vea solo SUS datos) es Fase 1 de la propuesta → espera aprobación de CL Tiene. `verificar_token` ya devuelve los claims (`email`) para engancharlo después.
- **Local:** correr el backend sin token con `AUTH_ENABLED=0` en `.env`.
- **Endurecimiento defensa-en-profundidad (2026-09-03, tras revisión externa):** (1) en prod (`AUTH_ENABLED=1`) se **ocultan `/docs`, `/redoc` y `/openapi.json`** (`main.py`, `docs_url=None...`) para no publicar el mapa de endpoints; en local siguen disponibles. (2) `auth.py` imprime un **WARNING ruidoso a stderr al arrancar con `AUTH_ENABLED=0`** (evita dejar la escotilla abierta por olvido). (3) Pendiente futuro: cuando se construya el **scoping por asesor** (Fase 1 propuesta), la identidad del usuario autenticado va **parametrizada** (`ScalarQueryParameter`), NUNCA por `_esc()`. (4) **Cumplimiento (no-código, para Fabián/legal CUN):** las transcripciones (datos personales de clientes) se mandan a OpenAI = tratamiento con tercero + transferencia internacional → conviene base legal/autorización documentada (Ley 1581).

## Inyección SQL: torniquete → parametrización nativa (2026-09-02, en `main` + DESPLEGADO)

> Cierra la DEUDA del torniquete `_esc()` que había en 6 interpolaciones crudas (commit `dd6361c`).

- **Parametrización con `ScalarQueryParameter`** (commits `486edcb` + `3ce0b8f`): los 6 puntos de inyección de texto libre / ids ahora usan **parámetros nativos de BigQuery** (`@param`) en vez de escape manual:
  - `utils.py` → `get_asesor_context` (`@asesor`), `get_search_results_context` (`@q`), `get_llamada_context` (`@llamada_id`), `get_history` (acepta `query_parameters`).
  - `api/filters/transcripcion/llamada.py` (`@buscar`), `metricas.py` (`@rowid`), `api/routes.py` `resumir_llamada` (`@id`).
  - `result()` (database.py) ya soportaba `query_parameters` y el cache-key los incluye. Los 3 `client.query()` directos de `utils.py` pasan `job_config=QueryJobConfig(query_parameters=[...])`.
- **`_esc()` queda SOLO en `filters()`** (el escape base de los ~50 valores de dropdown/enum del `FilterModel`; parametrizarlo es el refactor grande de los 50 llamadores, no urgente).
- **Fix del bug `asesor` (backend, mismo lote):** `llamada.py` filtraba por `LOWER(asesor)`, columna que **no existe** (solo `Cuenta`/`Agente`/`Telefono`) → el parámetro `buscar` daba `400 Unrecognized name: asesor`. Cambiado a `LOWER(CAST(cuenta AS STRING))`. ⚠️ Ese parámetro `buscar` **NO lo usa la caja de búsqueda del tab Transcripciones** (ver siguiente).
- **Fix de la búsqueda por asesor en Transcripciones (frontend, 2026-09-02, DESPLEGADO):** la caja "Buscar por teléfono o asesor" mandaba el nombre escrito como `id` entero a `/api/transcripcion/llamada/{id}` (typed `int`) → `422`, no cargaba nada. Fix en `FiltrosLateral.jsx`: al escribir un nombre (no teléfono) aplica el filtro `nombre_asesor` (debounced 500ms, salta el 1er render para no pisar el filtro del sidebar) → el dropdown "Seleccionar llamada" (`/api/transcripcion/llamadas`, que reacciona a `filters`) se filtra a las llamadas de ese asesor. Verificado en vivo: escribir "Jimmy" → KPIs a 8.752 + dropdown con las llamadas suyas.
  - **2 fixes de seguimiento (backend, 2026-09-03):** (1) el filtro `nombre_asesor` era **case-sensitive** (`cuenta LIKE '%jimmy%'` NO matchea "Jimmy") → `filters()` ahora usa `LOWER(cuenta) like LOWER(...)`; el sidebar pasa el nombre exacto, así que sin regresión. (2) el dropdown `/api/transcripcion/llamadas` no tenía LIMIT (~21.690 opciones sin filtro) → `ORDER BY Fecha DESC LIMIT 300` (las 300 más recientes; el `id` = ROW_NUMBER se mantiene consistente con metricas/llamada). Tests de `nombre_asesor` actualizados. `FiltrosLateral.jsx` + estos 2 pendientes de commitear + deploy backend.
- **Verificado:** 19 tests, app ensambla (65 rutas), inyecciones inertes (INT64 rechazados por `int()` antes del SQL; texto como literal vía `@param`), y tras el deploy `curl` sin token → 401 (sin regresión). Behavior-preserving para valores válidos.

## Mejoras de código / seguridad (2026-08-26, rev `00150`→`00151`, en `main` + desplegado)

> 🔒 **REGLA (memoria):** NUNCA tocar el **SQL Server de la CUN** (`coe.CLTIENE_LLAMADAS`) — solo lectura y con permiso. Todo lo de abajo es código del lado **BigQuery**, cero escrituras al SQL Server. Diego se pone nervioso con esto: reconfirmarlo.

Tanda de mejoras hechas en ramas (`mejoras-seguridad`, `refactor-tabla`, ya mergeadas a `main` y borradas). Todas **behavior-preserving** (verificado LOCAL vs PROD idéntico) y desplegadas:
- **🔒 Inyección SQL cerrada** (`helpers/utils.py` `filters()`): antes interpolaba los valores del usuario directo (`f"{key} = '{value}'"`). Ahora `_esc()` escapa comilla/backslash/saltos y `_DATE_RE` valida las fechas (YYYY-MM-DD; no-fecha se ignora). Cambio en 1 función, sin tocar los ~50 llamadores; para valores válidos el SQL sale idéntico. **Es el cimiento del scoping por asesor** de la propuesta.
- **🧹 `helpers/sql.py` = fuente única:** `TABLE` (nombre de tabla con backticks), `CONTACTADO`/`SIN_CONTACTO` (tuplas de la partición Contacto Efectivo) + `CONTACTADO_SQL`/`SIN_CONTACTO_SQL` (fragmentos). Un solo lugar para SQL y Python → no divergen (fue el bug del embudo). Consolidada la **partición** (distribucion_resultado, embudo, utils) y el **nombre de tabla** en las 28 queries de charts/filters/ia/routes + utils. `procesador.py` se deja con su `BQ_TABLA` sin backticks (es la API de **escritura** a BigQuery, no una query SQL).
- **✅ Tests (`back/tests/`, unittest, 19):** `test_filters.py` (escape anti-inyección + WHERE builder) y `test_sql.py` (partición excluyente, cubre las 8 categorías, Venta cuenta como contacto). Correr: `PYTHONPATH=. python -m unittest discover -s tests`.
- **📊 Motivo Rechazo sin N/A** (`motivo_rechazo.py`): excluye `Motivo_Rechazo='N/A'` (97.5% = no rechazadas) → el chart muestra los rechazos reales ("No Interesa" 92%). Mascota/Vehículo ya filtraban N/A.
- **⚡ Cache TTL en `database.py` (rev `00152`):** `result()`/`option()` cachean en memoria (TTL 5 min, tope 500, `clear_cache()`). Los KPIs+gráficas lanzan muchas queries por carga; como los datos son semanales, el cache evita re-consultar BigQuery sin arriesgar datos viejos. Verificado: 1ª query ~2.85s → 2ª 0.00s (hit). Con min-instances=1 la instancia caliente lo conserva.
- **🧩 `routes_new.py` unificado en `routes.py` (rev `00152`):** los 6 endpoints de ranking/IA se movieron a `routes.py` con `/api` explícito (antes `prefix="/api"` en main.py); `routes_new.py` eliminado, `main.py` simplificado. **Red de seguridad:** lista de rutas IDÉNTICA antes/después (ninguna URL cambió).
- **🐛 Lección (bug propio, corregido):** el refactor de tabla (34c0f8f) metió `{TABLE}` en 2 queries de `routes_new.py` que eran **strings PLANOS** (no f-strings) → rompió `/api/ranking_ia` y `/api/analisis_automatico` (POST) en prod. **NO los usa el frontend** (sin impacto), pero se corrigió (f-string) + se verificó con **AST** que no queda ningún `{TABLE}` en strings planos. **Regla nueva: al sustituir en queries, verificar con AST que el string sea f-string, y smoke-testear TODOS los endpoints (incluidos POST).**
- **Pendientes de refactor (grande, para sesión fresca):** partir el monolito `subir_datos.py` (~1130 líneas).

## Despliegue

> ⚠️ **SIEMPRE desplegar el backend DESDE `back/`** (`cd back/` primero). La raíz del repo tiene su
> propio `Dockerfile` + `package.json` (frontend); si corres `gcloud run deploy cltiene-backend --source .`
> desde la raíz, despliega el FRONTEND como backend y **tumba la API** (todos los endpoints devuelven el
> HTML del dashboard). Pasó el 2026-08-18 (rev 00128); se arregló re-desplegando desde `back/` (00129).

```bash
# Backend
cd back/
gcloud run deploy cltiene-backend --source . --region us-central1 --project desarrollo-investigaciones --quiet

# Frontend
npm run build
firebase deploy --only hosting:cltiene-dashboard
```

### Cold start eliminado — `min-instances=1` (2026-08-24, rev `00149-f6s`)
- **Síntoma:** al abrir la app tras inactividad, los KPIs quedaban en "-" varios segundos (hasta ~30s) porque Cloud Run escalaba a **0** y la primera petición tenía que arrancar el contenedor (cold start). El keep-alive de 9 min solo evita esto **mientras la pestaña ya está abierta**, no en la primera apertura del día.
- **Fix:** `gcloud run services update cltiene-backend --min-instances=1 --region us-central1 --project desarrollo-investigaciones`. Mantiene 1 instancia siempre caliente → cero cold start (verificado: `/api/kpi` responde ~0.1s). Rev `00149-f6s`.
- **Tradeoff:** una instancia idle 24/7 (costo bajo continuo, pocos USD/mes). Si la CUN lo cuestiona por costo, revertir con `--min-instances=0` (alternativa más barata evaluada: Cloud Scheduler con ping en horario laboral).

## Cuándo sacar un informe de sesión (criterio, definido 2026-07-15)

> 📚 **Bóveda de conocimiento en `CLTieneBobeda/`** (Obsidian): incluye la sección **`Trabajo con IA/`** — perfil personal de cada IA con sus **memorias fechadas por sesión** (índice, perfil de opencode, manual maestro). **Cualquier IA nueva: leer `Trabajo con IA/02 - Manual maestro para agentes de IA` y crear su propio perfil** (`Trabajo con IA/01 - Perfil de <nombre>`) al entrar, editando solo el suyo.

Dos ritmos distintos, no confundir:
- **Bitácora (nota semanal en el Tablero de trabajo de Diego):** SEMANAL, ligera ("en qué trabajé esta semana").
- **Informe de sesión (HTML formal, `informe_sesion_YYYY-MM-DD.html`):** POR HITO, no por calendario. En la práctica sale ~cada 2-3 semanas.

Sacar el informe formal SOLO cuando pase algo que se le mostraría a Fabián (jefe) y valga la pena documentar:
- Un **despliegue** a producción · un **lote de fixes/features** importante · una **reunión clave** con decisiones · un **cambio de dirección**.
- Si en 2 semanas no pasó nada de eso, NO forzarlo — la bitácora semanal cubre el registro.
- **TODOS los informes deben ser coherentes entre sí** (es la serie de DivergencyAI para CL Tiene):
  - **Mismo diseño:** plantilla de `informe_sesion_2026-06-25.html` (portada oscura, acento `#FC3276`, logo `CL<span>Tiene</span>`, secciones numeradas, `fix-list` por color, tabla, footer "Confidencial"). Reusar el mismo CSS tal cual.
  - **Misma estructura:** Resumen ejecutivo (cards) → secciones numeradas → Archivos/Pendientes. Nombre `informe_sesion_YYYY-MM-DD.html`.
  - **Datos consistentes:** las cifras y hechos NO deben contradecir informes anteriores ni el CLAUDE.md (ej. `efectiva` = score de calidad, ventas inferidas infladas, total de filas). Si un dato cambió, reflejar el antes→después, no re-escribir la historia.
  - Antes de crear uno nuevo, revisar el informe anterior para heredar estilo y no repetir/contradecir.
- Próximo disparador natural: cuando se integre la **columna de venta real** (reemplazar el regex) — habrá un antes/después claro.

## Fixes importantes ya aplicados

- `translate="no"` en `<html>` (evita barra de Google Translate que interfiere con React)
- `ErrorBoundary` en `App.jsx`
- `saludo_inicial` × 100 en `routes.py` (era 0.436% en vez de 43.6%)
- SALUDO OK filtra solo llamadas con transcripción (`kpi.py`)
- `hallazgos` en Reporte Completo debe ser array de strings (no objetos)
- `Resultado_Llamada = 'Venta'` (case-sensitive, verificado en BigQuery)
- Sidebar expande/contrae el contenido principal (estado en `Dashboard.jsx`)
- `Asistencia LIKE '%valor%'` en `utils.py` (antes usaba `LIKE 'valor%'`, fallaba si el item no era el primero en la lista separada por comas)
- `UNNEST(SPLIT(Asistencia, ', '))` en `asistencia_mencionada.py` para explotar valores múltiples del dropdown

## Cambios sesión 2026-06-19

### Pipeline V4 — `back/subir_datos.py`
- Integrado `estructurar_dialogo()` → genera `Transcripcion_V4` con turnos `[Asesor]` / `[Cliente]`
- Nuevo campo `Asistencia`: catálogo de 35+ servicios detectados por regex
- `detectar_duracion_estimada()` usa `Tiempo de Conversacion` (HH:MM:SS) en vez de longitud de texto
- `detectar_despedida_correcta()` analiza últimas 3 líneas de `Transcripcion_V4`
- 36,969 filas en BigQuery (`cltiene_llamadas_procesadas`)

### Frontend
- `IndicadoresTabla.jsx`: columna **Ventas** oculta cuando `tipo_llamada = 'servicio'` (mismo patrón `esServicio` que el resto del dashboard)
- `Dashboard.jsx`: **keep-alive ping** cada 9 min (evita cold start de Cloud Run mientras la pestaña está abierta) + **Page Visibility API** que muestra banner "Reconectando..." y recarga KPIs al volver a la pestaña tras 5+ min

---

## Cambios sesión 2026-06-23

### Pipeline — Detección de hablantes con OpenAI (`back/subir_datos.py`)
- **Reemplazado regex por OpenAI `gpt-4o-mini`** para separar `[Asesor]` / `[Cliente]` en `Transcripcion_V4`
- `estructurar_dialogos_ia()`: procesamiento async con `asyncio.gather`, 25–50 llamadas simultáneas
- `_PROMPT_HABLANTES` (v15): prompt con 15 ejemplos few-shot, señales inequívocas, REGLA CRÍTICA frase por frase
  - Pasa `[Tipo: saliente/entrante]` al prompt → resuelve ambigüedad del primer hablante
  - Detecta interjecciones cortas del cliente (`¿Cómo?`, `No, [corrección]`) dentro de bloques del asesor
  - Prohíbe inventar texto no presente en la transcripción
  - Maneja texto repetitivo por falla STT como un solo turno
- Fallback automático a regex si OpenAI falla
- **37,879 filas** en BigQuery (última actualización 2026-06-23)

### Cache incremental — `cargar_cache_bigquery()`
- Al arrancar, carga `{hash_md5(transcripcion): Transcripcion_V4}` de BigQuery
- Solo llama a OpenAI para transcripciones **nuevas o cambiadas**
- Costo: ~$20 primera vez → ~$0.50–1 en runs posteriores (solo registros nuevos)

### Soporte dos API keys — `.env`
```
OPENAI_API_MUNDIAL=sk-proj-...
OPENAI_API_MUNDIAL_2=sk-proj-...
```
- `_batch_ia()` rota entre ambas keys automáticamente
- Concurrencia: 25 por key → 50 total cuando hay dos keys activas
- Tiempo de run completo: ~65 min (1 key) → ~35 min (2 keys)

### Scripts de comparación (`back/`)
- `comparar_metodos.py`: compara regex vs OpenAI en muestra fija de 100 llamadas
  - Sección 1: acuerdo en primer hablante
  - Sección 2: acuerdo en `Resultado_Llamada` + ventas
  - Sección 3: concordancia vs BigQuery original (ground truth)
  - Sección 4: casos donde difieren (primeros 8)
- `muestra_fija.csv`: muestra fija de 100 llamadas para comparación reproducible
- Ejecutar: `$env:PYTHONIOENCODING="utf-8"; python comparar_metodos.py 100`

### Métricas del prompt v14 (muestra fija 100 llamadas)
| Métrica | Valor |
|---------|-------|
| Acuerdo hablantes (IA vs regex) | 60% |
| Acuerdo efectividad | 80% |
| Ventas detectadas | 100% ✅ |
| IA vs BigQuery | 76% |

> El 40% de "desacuerdo" en hablantes es en su mayoría **IA más correcta** que regex
> (regex asignaba Asesor en llamadas salientes donde el cliente contesta primero)

---

## TAREAS PENDIENTES

### Sesión 2026-06-19
- ✅ `Rendimiento.jsx`: `analizar_asesor` ahora pasa filtros del sidebar con `buildQuery()`
- ✅ `Rendimiento.jsx`: `estiloBadge` corregido
- ✅ Creado `CLAUDE.md`

### Sesión 2026-06-23
- ✅ Detección de hablantes reemplazada por OpenAI (prompt v14)
- ✅ Cache incremental implementado
- ✅ Soporte dos API keys con rotación automática
- ✅ Script `comparar_metodos.py` + `muestra_fija.csv`
- ✅ 37,879 filas actualizadas en BigQuery

### Sesión 2026-06-25
- ✅ Prompt v15: regla "CLIENTE nunca se llama a sí mismo por nombre" + ejemplo `Correcto, señora Rosalía → ASESOR`
- ✅ `metricas.py`: añade **Duración Real** (`Tiempo__de_Conversacion` HH:MM:SS) + **Turnos** (REGEXP desde V4) + ORDER BY
- ✅ Sincronización IDs: `llamadas.py`, `metricas.py`, `get_llamada_context` usan mismo WHERE → ROW_NUMBER coincide
- ✅ Dropdown `llamadas.py`: fecha + resultado + asesor + teléfono (en vez de `#id`)
- ✅ `llamada.py`: retorna `info.telefono` (campo real `Telefono` de SQL Server, no `Cuenta`)
- ✅ Nuevo `historial_telefono.py`: endpoint `/api/transcripcion/historial/{telefono}` con IDs globales
- ✅ `FiltrosLateral.jsx`: historial dinámico al seleccionar llamada o escribir teléfono; clic carga transcripción
- ✅ Creados `informe_sesion_2026-06-25.html` + `informe_tecnico.html` (v3.0 con secciones 10 y 11)

### Backlog
- [ ] **Re-procesar BigQuery con `--full`** (prompt v16 + `gpt-4o`) — LISTO PARA CORRER, esperando OK del usuario
  - Prompt **v16** aplicado (`subir_datos.py`): regla del vocativo como REGLA #1 al inicio ("el cliente jamás dice un nombre propio como vocativo → siempre ASESOR").
  - Modelo configurable: `MODELO_HABLANTES` (default **`gpt-4o`**; override a `gpt-4o-mini`). El pipeline diario y `--full` usan `gpt-4o`.
  - Flag `--full` (o env `REPROCESO_COMPLETO=1`) ignora el cache y reprocesa las ~38k con el prompt actual.
  - **Validación (banco de pruebas aislado, sin tocar prod):** `gpt-4o`+v16 = ~2% error de atribución vs `mini`+v15 (prod) = ~7%, sobre 85 transcripciones aleatorias. En 5 casos difíciles: 0 fallos en 14 corridas.
  - Costo estimado re-proceso completo con `gpt-4o`: **~$300** (una vez). Antes de correr: **backup de la tabla BigQuery**.
- ✅ Validado que `AnalisisAu`, `RankingIA`, `ReporteCompleto` (Agente IA PRO) pasan filtros sidebar (frontend `buildQuery()` → backend `FilterModel` → `filters.get_query()`; verificado en prod: reporte con filtro fecha 2026-06-16 mostró 245 llamadas, no los ~38k)
- ✅ Separar métricas Ventas vs Servicio en reportes (dashboard vía `esServicio` + reportes IA vía `contexto_tipo_llamada()` — ver patrón abajo)
- [ ] Pipeline V4: registrar tarea automática en PC con sesión CUN
- ✅ Aclarado qué mide `efectiva` vs `Resultado_Llamada = 'Venta'` (reunión BD 2026-07-01 — ver sección "Columnas de la CUN")

### Reunión pendiente 2026-07-07 (martes 9am — "Revisión de procesos de llamadas")
- [ ] Migración a Airflow: eliminar Excel intermedios, automatizar el proceso (lo desarrolla Santamaría)
- [ ] CL Tiene: renombrar carpetas de agentes a formato `agenteN` (caso Edwin Cendales sin datos desde 3-feb)
- [ ] CUN/Juan Manuel: corregir nomenclatura `Salientes` → `Saliente` en la BD
- [ ] Alinear formatos de Excel (entrante/saliente traen `Agente`/`Cuenta` con estructura distinta)
- [ ] **Calidad del STT (voz a texto) de la CUN** — tema aparte de la separación de hablantes
- **Audio / "S3"** — RESPONDIDO por S3 (2026-07-07): el audio de origen está OK, el foco es el STT.
  - Grabaciones en el servidor del proveedor → un script las copia a un **servidor de backup** (= el FTP `/u01/bk/...` que consulta la CUN). Solo copia, no degrada.
  - "Se generan **únicamente cuando hay audio** en alguno de los dos sentidos" → cuando hay audio, queda completo (llamadas sin audio no generan grabación).
  - Formato **mp3, sin cambios recientes**.
  - Contacto para novedades: **centro.servicios@s3.com.co** cc **oscar.obando@s3.com.co**.
  - **Conclusión:** descartado el audio de origen → la palanca real de las transcripciones malas es el **STT de Juan/COE** (faster-whisper `medium` + `beam_size=1` + VAD). Duda abierta: ¿la grabación es voz-activada (VOX) que omite silencios dentro de la llamada? Preguntar si el problema persiste tras mejorar el STT.
- [ ] **Duplicados en la tabla origen `coe.CLTIENE_LLAMADAS`** (verificado 2026-07-03): ~**5.321 filas (~10%)** son el **mismo audio cargado más de una vez** (misma `fecha+cuenta+telefono+transcripcion+archivo`). Inflaban los conteos del dashboard ~10%. El proceso de carga de la CUN debería **insertar con deduplicación** (Airflow). Nosotros ya blindamos el dashboard con dedup en `subir_datos.py` (ver abajo), pero la raíz está en la carga.
  - Nota: `IDENTIFICACION` NO es clave de fila — es el documento del agente (solo ~13 distintos) y tiene formato inconsistente (`...053.0` float vs `...053` int).

## Deduplicación en el pipeline (`subir_datos.py`, sesión 2026-07-03)
- `cargar_desde_sql()` aplica `drop_duplicates(subset=[Fecha, Cuenta, Telefono, transcripcion, archivo])` tras leer de SQL Server.
- **`archivo` es clave**: sin él se borraban por error llamadas distintas sin transcripción que comparten `fecha+cuenta+telefono` (el dedup de 4 columnas quitaba 7.863 en vez de 5.321). Con `archivo` solo se quitan audios idénticos repetidos.
- Loguea cuántos duplicados quitó en cada corrida.

## Automatización de la subida SQL→BigQuery (analizado 2026-07-09)
- **El SQL Server (172.16.1.33) está en la red PRIVADA de la CUN** → lo que automatice el pipeline **tiene que correr DENTRO de esa red**.
- **Cloud Run NO sirve para el pipeline**: corre en Google Cloud (fuera de la red CUN) y no llega a la IP privada del SQL. (Cloud Run sí es ideal para el **backend**, que lee BigQuery, no SQL.) Solo funcionaría con un Cloud VPN/VPC connector a la red CUN — improbable tras la auditoría de seguridad.
- **Opciones reales de automatización:**
  1. ⭐ **Airflow (Santamaría)** — corre en la red CUN, tiene acceso nativo al SQL, ya lo están montando. Nuestro `subir_datos.py` se puede agregar como un `PythonOperator`/`BashOperator` que corra tras dejar los datos en SQL. **Vía elegida** — Diego coordina con Santamaría.
  2. **PC/servidor fijo en la red CUN** con `registrar_tarea.ps1` (tarea Windows) — funciona pero frágil (depende de que el PC esté encendido y en la red).
- **Para la automatización usar `MODELO_HABLANTES=gpt-4o-mini`** (costo ~$3/corrida vs ~$49 con gpt-4o) y **frecuencia semanal** (la fuente se actualiza semanal, según la doc oficial del COE).

### Airflow — dificultad real: NO es el código, es el ENTORNO (analizado 2026-08-24)
- **El código es FÁCIL:** `subir_datos.py` ya es un script autónomo con `__main__` → en Airflow se engancha como un `BashOperator` (`python subir_datos.py`) o `PythonOperator` en un DAG semanal. Cero reescritura.
- **Lo difícil es el entorno (infra + coordinación), 4 cosas a verificar con Santamaría:**
  1. **🔴 Egress a internet (el mayor riesgo):** el pipeline llama a **OpenAI** (separación de hablantes) y escribe en **BigQuery** — ambos FUERA de la red CUN. Tras la auditoría, el host de Airflow podría **no tener salida** a esos destinos. **Pregunta clave a Santamaría:** *"¿el host de Airflow puede salir a api.openai.com y a BigQuery, o está cerrado?"* Si está cerrado, es EL bloqueo.
  2. **Secrets:** las 2 API keys de OpenAI + credenciales GCP (service account BigQuery) deben ir en el entorno de Airflow (Connections/Variables o secret manager).
  3. **Dependencias:** el host/imagen necesita **ODBC Driver 18** + paquetes Python (pandas, openai, google-cloud-bigquery, pyodbc). Si es Docker, meter el driver en la imagen.
  4. **Gobernanza:** es el Airflow de Santamaría/CUN → él agrega el DAG o le da acceso a Diego.
- **A favor:** el SQL sí lo alcanza nativo (Airflow está en la red CUN). Plan B mientras tanto: el task de Windows (`registrar_tarea.ps1`).

## "Ventas Cerradas" — detección poco confiable + fuente real (CRM) (verificado 2026-07-08)

- **El KPI "Ventas Cerradas" del dashboard está MUY sobreestimado.** Se infiere de la transcripción con un regex débil en `detectar_resultado_llamada()` (`subir_datos.py`): marca "Venta" si aparece `procedemos|te confirmo|queda activ|...`.
- **`te confirmo` es el culpable** (78% de las 374 "ventas" lo contienen): se usa muchísimo para confirmar **teléfonos, nombres y visitas de médico a domicilio** (servicio), no ventas.
- **Validación (2026-07-08):** de 40 "ventas" muestreadas → regex estricto deja 5%, IA (gpt-4o-mini) deja **0%**. Incluso las 9 que mencionan el precio $33.900 → la IA dice NO (son *pitches*, no cierres). El 78% mencionan médico/domicilio = son llamadas de **servicio**, no ventas.
- **Conclusión:** inferir la venta desde la transcripción NO es confiable (ni regex ni IA) porque el cierre real rara vez queda en el texto (y el STT lo corta).
- **FUENTE REAL DE VENTAS = tabla `coe.CLTIENE_VENTAS`** (SQL Server CUN): es el **CRM (Zoho)** de negociaciones (14.342 deals), con columna **`Fase`**. Las ventas reales = **`Fase = 'Cerrado Ganado'` = 959** (histórico ~ago-2023 a may-2026). Tiene `Importe`, `Fecha de cierre`, `Propietario de Negociación`, `Identificación`, `Correo`, etc. Los IDs de negociación empiezan por `zom_...` (Zoho).
- Esta tabla es **SEPARADA del pipeline de Juan** (el notebook solo maneja `CLTIENE_LLAMADAS`; nunca toca `CLTIENE_VENTAS`). La mantiene el **lado BI (David Cerón)** desde el CRM; alimenta el Power BI de la CUN.
- **Pendiente / recomendación:** el dashboard debe tomar la venta real de `CLTIENE_VENTAS` (`Fase='Cerrado Ganado'`), no de la inferencia por transcripción. Reto: cruzar CRM ↔ llamadas por cédula (`Identificación`) / asesor / fecha.

### Sergio confirmó la fuente de ventas (WhatsApp 2026-07-14)
- Diego preguntó a Sergio por una columna de venta real y por la fuente de `CLTIENE_VENTAS`. Sergio confirmó en nota de voz:
  - ✅ **La tabla se baja de Zoho** (el CRM), es "el tema de negociaciones". (El STT deformó "Zoho" como "su ojo".)
  - ✅ **`Fase='Cerrado Ganado'` = venta real** — valida el filtro que ya teníamos.
  - ⚠️ **Hay registros de PRUEBA** dentro de la tabla que **inflan el conteo** → ni las 959 son 100% limpias; hay que **excluir los "pruebas"** al cruzar.
  - ✅ Reconfirmó que **la venta se cierra fuera de la llamada** (link de contrato al cliente) → no queda en el audio.
- **Diego observó que `CLTIENE_VENTAS` está desactualizada** en el SQL Server → la actualización desde Zoho la maneja el **lado BI (David Cerón)**.
- **Siguiente paso — REUNIÓN DE VENTAS agendada 2026-07-15 9am** (Sergio agendó el Meet). Asistentes: **Sergio Nieto** (CL Tiene, dueño de Zoho), **Juan Marín** (COE/CUN, dueño del SQL+pipeline), **Juan Garnica** (CUN, coordinación) y **Fabián** (DivergencyAI, jefe de Diego). Objetivo: (1) confirmar venta real = Zoho `Cerrado Ganado`, (2) mantener `CLTIENE_VENTAS` actualizada desde Zoho (¿API o export?), (3) filtrar registros de prueba, (4) definir el cruce CRM↔llamadas por cédula+fecha+asesor.

### RESULTADO reunión de ventas 2026-07-15 (37 min, los 5 asistentes)
> Actores: **Fabián Forero** (`JOSE FABIAN FORERO RODRIGUEZ`, jefe de Diego/DivergencyAI), **Juan Garnica** (`JUAN FRANCISCO GARNICA CASTRO`, CUN coordinación), **Juan Manuel Marín** (`JUAN MANUEL MARIN QUINTERO`, COE/analítica, dueño del pipeline+STT), **Sergio Nieto** (CL Tiene), **Diego**.

- **✅ DECISIÓN PRINCIPAL — Sergio agrega 3 columnas al Excel semanal:** (1) **venta sí/no** (marca si esa llamada cerró venta), (2) **ID de negociación/Zoho**, (3) **identificación (cédula)** del cliente. Flujo: Sergio marca en el Excel → **Juan Manuel la mete como variable nueva en la BD** (SQL Server) → **Diego la toma para el dashboard**. Esto **reemplaza la inferencia por regex** (`detectar_resultado_llamada`). ⇒ Cuando la columna llegue al SQL, cambiar el pipeline para **leer la columna real** en vez del regex.
- **Matiz clave:** la marca de venta es de la **llamada de CIERRE** (aceptación del contrato: firma virtual por link, o llamada grabada que suben a soporte y marcan `Cerrado Ganado` en Zoho), **no de toda la negociación**. Una venta = una llamada de cierre puntual. Sergio: "**no son muchas realmente**" (~10-15/mes) → confirma que el 708/374 está MUY inflado.
- **Zoho tiene registros de PRUEBA** que inflan el reporte de Zoho; la marcación manual de Sergio en el Excel debería venir limpia.
- **🔴 Hallazgo técnico (Juan Manuel, upstream):** el cruce audio↔Excel usa una **llave de 3 variables** (agente+celular+fecha) y **pierde ~40% de las llamadas** (solo cruza ~60%). Propone cambiar a una **llave única, el "punto wat"/WAP** (identificador único que ya está en el Excel) → cruce mucho más confiable. Explica huecos de datos. Fix de él.
- **Frecuencia:** datos al **2-jul**; se mantiene envío **SEMANAL** (Sergio envía el **lunes**, con **fecha fija de corte** para que Juan Manuel sepa desde dónde correr el algoritmo). Fabián: **quincenal NO sirve** (el dashboard alimenta servicio + formación, no solo ventas → hay que tomar decisiones frescas).
- **Automatización (largo plazo):** directriz CUN = eliminar Excel → todo a BD + **Airflow**. Ya existe extracción automática desde **ContactVox**, PERO su estructura ≠ la que Sergio arma a mano (él clasifica servicio/venta manualmente y separa entrante/saliente) → por eso Juan Manuel aún **no se puede "pegar" directo al servidor**. Meta final: quitar el paso manual de Sergio y luego el de Juan Manuel (Airflow).
- **Dependencia de S3 (proveedor):** la **cédula NO viene en los archivos de audio** del origen. Sergio ya pidió al área de desarrollo de S3 que la agreguen a la estructura; **pendiente respuesta**. Falta **reunión con S3/Oscar** (Fabián la propuso) para alinear la estructura ANTES de que el proveedor desarrolle (evitar desarrollo equivocado). El servidor `172.16.1.33`/FTP es un **backup** que S3 alimenta desde el servidor principal (copia exacta).
- **Pendientes por responsable:**
  - **Sergio:** agrega columnas (venta + zoho id + cédula) al Excel, con fecha fija, envío lunes; gestiona con S3 lo de la cédula en el origen.
  - **Juan Manuel:** mete la columna venta a la BD; cambia el cruce a llave única (WAP); sigue actualizando desde 2-jul.
  - **Fabián/Diego:** agendar reunión con S3/Oscar para alinear estructura.
  - **Diego (nuestro pipeline):** cuando la columna `venta` esté en SQL, reemplazar la inferencia regex por lectura directa.

### Columnas a SOLICITAR a Sergio (todas salen de Zoho `CLTIENE_VENTAS`)
> Ya acordadas: `venta` (sí/no), `ID negociación/Zoho`, `cédula` del cliente. Pedir además estas — habilitan KPIs que hoy el dashboard NO tiene:
- **`Importe` (valor de la venta)** ⭐ → **ingresos totales + ticket promedio** (hoy no existen; iguala/supera al Power BI de la CUN). Es la de mayor valor, sola justifica la petición.
- **`Producto (Negociación)` (plan vendido)** → "Plan Vendido" REAL vs el "Plan Mencionado" que hoy se infiere.
- **`Fecha de cierre`** → separar fecha de venta ≠ fecha de llamada (la venta se cierra fuera del audio); necesaria para cruzar bien.
- Opcionales: **`Fase` completa** (embudo Ganado/Perdido/en proceso, no solo sí/no) · **flag `es_prueba`** (excluir limpio los registros de prueba que inflan Zoho).
- **NO pedir a Sergio como columna:** la **llave única WAP/"punto wat"** para el cruce del ~40% — ya está en el Excel y es tema de Juan Manuel (enlace audio↔Excel), solo confirmarle que la usará.

### ⚠️ Sergio SALE de CL Tiene (2026-07-16) — riesgo de continuidad
- Sergio Nieto avisó que **sale hoy de CL Tiene** (está haciendo la **entrega de cargo**). Le dijo a Diego: "habla con Fabián cómo van a manejar eso".
- **Sergio era la pieza clave del flujo de datos:** (1) envía el Excel semanal, (2) **clasifica servicio/venta a mano** (esa clasificación NO la da ContactVox automático), (3) era quien iba a agregar la columna de venta real + cédula + las nuevas (Importe/Plan/Fecha). Su salida **pone en riesgo el envío semanal y todo el plan de ventas**.
- **Diego respondió (bien):** se encarga con Fabián; los pendientes de la reunión 15-jul (columnas nuevas + reunión S3) quedan **para el reemplazo de Sergio**.
- **PENDIENTE CRÍTICO:** definir **quién asume el rol de Sergio** en CL Tiene y conectarlo con Diego para: continuar el envío semanal, la clasificación servicio/venta, y las columnas acordadas. Es lo que Diego coordina con **Fabián** (gerencia).
- **Refuerza el caso de automatizar (Airflow/ContactVox):** depender de una sola persona con Excel manual es frágil — se acaba de comprobar. Mientras no esté automatizado, alguien debe reemplazar el trabajo manual de Sergio.
- **Steven Aldana NO es el reemplazo de Sergio (corregido 2026-07-30):** **Steven Alexander Aldana Sanabria** (`supervisor_contact@cltiene.com`) es **Supervisor Contact Center** de CL Tiene (maneja asesores/ventas), pero **NO cubre el rol de datos de Sergio** (Excel, clasificación servicio/venta, columnas). Su primer trabajo que vimos: la prueba A/B de 5 saludos (ver pestaña "Prueba de Saludos").
- **El reemplazo real de Sergio SIGUE PENDIENTE (reunión comité 2026-07-29):** Sandra Castillo mencionó "un chico que reemplaza a Sergio" armando cuadros de mando con el equipo de Claudia (lado BI/CUN), pero "bien flojitos aún" (no entienden el modelo de negocio). → **Las columnas de venta/cédula siguen esperando** a que ese rol se estabilice.
- **Plan interino (Diego, 2026-07-30):** pedir a **Juan Manuel que actualice la BD SIN el Excel** (jalar directo de ContactVox) para mantener los datos frescos. ⚠️ Tradeoff: mantiene llamadas+transcripciones al día, PERO se pierde la clasificación manual servicio/venta y la marca de venta que hacía Sergio (no viene automática de ContactVox) → el **KPI de ventas real sigue pendiente** del reemplazo. Son dos frentes separados: frescura de datos ≠ columna de venta.
- **✅ RESUELTO — Cristian Galeano es el reemplazo de Sergio (2026-08-24):** **Cristian Galeano** (`analista.datos@cltiene.com`, WhatsApp @CristianGaleanoD) es el nuevo **Analista de Datos** de CL Tiene que reemplaza a Sergio ("Checho"). **Maneja el Excel de ENTRADA** (llamadas entrantes) — el hueco abierto desde la salida de Sergio. Diego lo contactó por WhatsApp + le reenvió por correo los 2 Excel de Checho como referencia de formato. **Cristian se comprometió a enviar el Excel de ENTRADA del 3-jul → 22-ago el 2026-08-25 antes de mediodía.** Que sea analista de datos facilita mucho (se puede ir técnico: WAP, columnas, cruce). **Guion para la llamada con él:** (1) retomar entrada semanal, (2) mantener la clasificación servicio/venta, (3) sembrar las columnas de venta real (venta sí/no + ID Zoho) + cédula + llenar `Estado de Gestion`. El Excel de entrada trae la **llave WAP** (`Identificador único`) → oportunidad para el cruce único de Juan.

### Análisis de los Excel crudos de Sergio + diccionario COE (2026-08-14)
Diego consiguió los archivos fuente reales (los que **Sergio siempre enviaba** semanal, corte 26-jun→2-jul) + el diccionario oficial del COE. Analizados con pandas. Hallazgos que confirman/avanzan los pendientes:
- **`Registro de llamadas salientes...xlsx`** (16 columnas, hojas `Servicio` 293 filas + `ventas` 1.627): tiene `Cuenta`, `Modulo`, `Estado de Gestion`, `Direccion grabacion`. **NO tiene** un identificador único.
- **`Entrada de llamadas...xlsx`** (24 columnas, hojas `Servicio` 181 + `Ventas` 9): estructura MUY distinta — `Hora` aparte, `Cola`, `Identificacion` (cédula), **`Identificador único`** (la llave WAP, ej `1783050377.161541`), `Troncal`, `Estatus` (ANSWERED/DISCARTED/ABANDON). Confirma el problema conocido de "2 formatos distintos" entrante/saliente.
- 🔴 **`Estado de Gestion` VACÍO EN EL ORIGEN** (293/293 nan en salientes, todo nan en entrada/ventas). ⇒ **No es que Juan no lo cargue: Sergio nunca lo llenaba.** Por eso está vacío en BigQuery. Para venta real + Estados Prospectos, alguien en CL Tiene debe **empezar a llenarlo** (o traerlo de ContactVox/Zoho).
- 🔴 **Cédula (`Identificacion`) VACÍA** en entrada (0/181) → confirma la dependencia de **S3** (agregar la cédula en el origen).
- 🟢 **La llave WAP (`Identificador único`) SÍ existe, pero solo en ENTRADA, no en SALIENTES** → para el cruce único de Juan Manuel habría que pedir que ese ID también venga en el Excel de salientes.
- **Hojas `Servicio` + `ventas`/`Ventas`** = la **clasificación manual de Sergio** (servicio vs venta). Es justo lo que se pierde si Juan jala directo de ContactVox (no clasifica). **No hay columna "venta sí/no"** → la que Sergio iba a agregar **nunca se agregó** (salió el 16-jul antes de hacerlo).
- **`COE_DICC_DB_LLAMADAS_METRICAS.xlsx`** (diccionario oficial COE de `CLTIENE_LLAMADAS`, periodicidad **Mensual**): la hoja "Diccionario_Ventas" en realidad documenta los **13 campos NLP** (no ventas). Confirma oficialmente: **`efectiva` = Texto Sí/No** = calidad (puntaje de las 7 categorías ≥ umbral), **NO venta**; las 7 categorías + `polaridad`/`clasificacion`/`confianza`/`subjectivity`/`palabras` salen de la **transcripción de audios** (Ollama + TextBlob/NaiveBayes). **NO incluye venta/cédula/Estado_de_Gestion** → reconfirma que la venta vive en **Zoho `CLTIENE_VENTAS`** (`Fase='Cerrado Ganado'`), no en `CLTIENE_LLAMADAS`.
- **Conclusión:** todo el plan de venta real está **congelado esperando el reemplazo de Sergio**. Qué pedir concretamente cuando llegue: (1) llenar `Estado de Gestion` (o marcar venta sí/no + zoho id), (2) el WAP también en salientes, (3) la cédula vía S3. La venta real definitiva = Zoho `CLTIENE_VENTAS`.

### Steven Aldana ya envía el Excel (parcial) — corte 1-ago (2026-08-14)
Diego confirmó que **Steven Aldana empezó a enviar el Excel** (`registro de llamadas salientes del 01 de agosto a la fecha.xlsx`, corte 1-ago→10-ago), cubriendo **parcialmente** el rol de envío de Sergio. Analizado con pandas — es una **versión degradada**:
- 🟡 **Steven SÍ manda el Excel de salientes → la base de datos SÍ se puede actualizar** (con salientes; por eso se subió hasta el 9-ago). Pero **NO manda el de ENTRADA** porque **no sabe cómo lo descargaba Sergio ("Checho")** → las llamadas de entrada de agosto son el hueco (no llegan a SQL ni al dashboard).
- **NO se capacita a Steven** (es Supervisor Contact Center, NO el reemplazo de Sergio → no se le cargan las tareas de datos). **Hay que esperar el reemplazo real de Sergio**: es quien retoma el envío completo (entrada + clasificación servicio/venta + llenar `Estado de Gestion`). Steven solo cubre el envío **parcial de salientes** de forma interina.
- 🔴 **Sin clasificación manual servicio/venta:** manda **1 sola hoja "Hoja 1"** plana (Sergio partía en `Servicio` + `ventas`) → se perdió la clasificación que hacía Sergio a mano.
- 🟡 **Formato con basura:** 3 filas arriba (título "Fecha Inicio/Fin" + blancos); el header real está en la fila 4 (índice 3). Juan Manuel debe saltarlas al importar a SQL.
- Mismas **16 columnas** que el saliente de Sergio; 2.004 filas; `Estado de la LLamada` con datos (NO ANSWER 996 / ANSWERED 979 / BUSY 25); **`Estado de Gestion` sigue VACÍO** (2004/2004 nan) → la venta real sigue bloqueada.

### 🔴 Las NO CONTESTADAS se pierden upstream — "Total Marcaciones" subcuenta (2026-08-18)
Steven vio el primer reporte (P1), lo entendió "súper bien", envió la base por correo, y **pidió agregar "cuántas personas no contestaron y cuántas sí"**. Al verificarlo se descubrió un gap de datos importante:
- **El reporte YA tiene la sección "Estatus de Llamadas"** (Contestada/No Contestada), pero sale **~100% contestada** en TODOS los meses recientes (mar-ago 2026) → parece que nadie deja de contestar.
- **Causa (verificada):** el SQL de la CUN (`CLTIENE_LLAMADAS`) trae **SOLO ANSWERED** (agosto: 848, todas contestadas). Las **NO ANSWER/BUSY se botan al cruzar con audio** (una llamada no contestada no tiene grabación → no cruza → no entra al SQL). Nuestro pipeline NO las bota: nunca llegan.
- **La data SÍ existe en el Excel crudo de Steven.** Ej. `registro de llamadas salientes semana del 10 de agosto al 18.xlsx`: **2.217 marcaciones → NO ANSWER 1.190 (54%), ANSWERED 1.014 (46%), BUSY 13**. El del 1-ago: NO ANSWER 996 / ANSWERED 979 / BUSY 25.
- **Implicación seria:** nuestro **"Total llamadas (marcaciones)" en realidad son solo las CONTESTADAS** (~1.000/semana), NO las marcaciones reales (~2.200). "Total Marcaciones" es el **KPI #1 de la plantilla ContactVox** de Steven → hoy lo subcontamos >50%. Y la **contactabilidad real** está mal medida (dividimos entre contestadas, no entre marcaciones totales).
- **Opciones:** **(A, recomendada, upstream)** pedir a **Juan Manuel** que incluya las filas NO ANSWER/BUSY (metadata sin audio) en `CLTIENE_LLAMADAS`, como las de oct-2025 que ya recuperamos → fluye solo al reporte. **(B, interina)** leer el Excel de Steven directo para sacar marcaciones/contestadas/no-contestadas (el Excel trae `Estado de la LLamada` limpio). Depende de que Steven lo mande siempre.
- **Munición reunión Juan (STT):** "el Excel del 10-17 ago tiene 2.217 marcaciones (1.190 no contestadas); a BigQuery solo llegan las 1.014 contestadas → ¿puedes incluir las NO ANSWER/BUSY en `CLTIENE_LLAMADAS`?" Va junto con el pedido de mejorar el STT (large-v3, beam_size 5, ablandar VAD).
- **🔴 Verificado (2026-08-24): la pérdida de asesores es UPSTREAM (Excel→SQL), NO de nuestro pipeline.** El reporte P3 (10-17 ago) salió con solo **3 asesores / 471 llamadas** (vs 9 la semana previa). Reconciliación con dato duro **Excel → SQL → BigQuery**:
  - **Excel de Steven (salientes 10-17):** 2.217 marcaciones · **1.014 contestadas** · 9 asesores.
  - **SQL `coe.CLTIENE_LLAMADAS`:** **471 / 3 asesores** (Andres 245, Rosselin 223, Paula 3) — verificado en **SSMS directo** por Diego.
  - **BigQuery:** **471 / 3, IDÉNTICO al SQL** (mismos conteos).
  - ⇒ **SQL = BigQuery exacto** → nuestro pipeline copia fiel, no pierde nada. Los **6 asesores / ~521 contestadas** que faltan (Melany 104, Johan 98, Edwin 69, Nicolas 55, Angie 17, Nicoll 178 — casi todo servicio) se pierden **entre el Excel y el SQL**: el import de Juan + el cruce audio↔Excel por 3 variables (~40%, aquí ~54%).
  - **Query SSMS reproducible:** `SELECT cuenta, COUNT(*) n FROM CUN_REPOSITORIO.coe.CLTIENE_LLAMADAS WHERE TRY_CONVERT(datetime,fecha,120) >= '2026-08-10' AND TRY_CONVERT(datetime,fecha,120) < '2026-08-18' GROUP BY cuenta` → 471/3.
  - **Correos enviados a Juan Manuel** (Juan Garnica en copia): (1) el hallazgo de la pérdida + pedir revisar el cruce; (2) aparte, el Excel nuevo de **salientes 17-22 ago** para actualizar la BD (plazo: mañana). El pedido de incluir las **no contestadas** (1.203) queda para un 3er correo (Diego lo enviará después).
  - **Reporte P3 NO se le manda a Steven** hasta que la data esté completa (opción A — un reporte con 3 de 9 asesores lo confundiría). Cuando Juan recupere los asesores + cargue lo nuevo → correr `subir_datos.py` → reporte completo.
- **🔴 Verificado (2026-08-24): la pérdida de asesores es UPSTREAM (Excel→SQL), NO de nuestro pipeline.** El reporte P3 (10-17 ago) salió con solo **3 asesores / 471 llamadas** (vs 9 la semana previa). Reconciliación con dato duro **Excel → SQL → BigQuery**:
  - **Excel de Steven (salientes 10-17):** 2.217 marcaciones · **1.014 contestadas** · 9 asesores.
  - **SQL `coe.CLTIENE_LLAMADAS`:** **471 / 3 asesores** (Andres 245, Rosselin 223, Paula 3) — verificado en **SSMS directo** por Diego.
  - **BigQuery:** **471 / 3, IDÉNTICO al SQL** (mismos conteos).
  - ⇒ **SQL = BigQuery exacto** → nuestro pipeline copia fiel, no pierde nada. Los **6 asesores / ~521 contestadas** que faltan (Melany 104, Johan 98, Edwin 69, Nicolas 55, Angie 17, Nicoll 178 — casi todo servicio) se pierden **entre el Excel y el SQL**: el import de Juan + el cruce audio↔Excel por 3 variables (~40%, aquí ~54%).
  - **Query SSMS reproducible:** `SELECT cuenta, COUNT(*) n FROM CUN_REPOSITORIO.coe.CLTIENE_LLAMADAS WHERE TRY_CONVERT(datetime,fecha,120) >= '2026-08-10' AND TRY_CONVERT(datetime,fecha,120) < '2026-08-18' GROUP BY cuenta` → 471/3.
  - **Correos enviados a Juan Manuel** (Juan Garnica en copia): (1) el hallazgo de la pérdida + pedir revisar el cruce; (2) aparte, el Excel nuevo de **salientes 17-22 ago** para actualizar la BD (plazo: mañana). El pedido de incluir las **no contestadas** (1.203) queda para un 3er correo (Diego lo enviará después).
  - **Reporte P3 NO se le manda a Steven** hasta que la data esté completa (opción A — un reporte con 3 de 9 asesores lo confundiría). Cuando Juan recupere los asesores + cargue lo nuevo → correr `subir_datos.py` → reporte completo.
- **✅ Solución INTERINA implementada (2026-08-18, rev `00132-wkg`): "Contacto Efectivo" en el reporte.** Mientras Juan integra las no-contestadas del marcador, el reporte ya muestra lo que SÍ tenemos: de las llamadas registradas, en cuántas se **habló con la persona** (Contactado, de `Resultado_Llamada`, inferido de la transcripción: cliente habló ≥2 turnos) vs no (Sin Contacto = buzón/no disponible/número equivocado/no se habló). Verificado que cuadra con la gráfica "Distribución de Resultados" (P2: Contactado 317 / Sin Contacto 260 = buzón 61 + sin contacto 194 + no disp 4 + num eq 1).
  - `get_data_context` (utils.py): por asesor `contactado`/`sin_contacto`/`contactado_pct` + agregado "CONTACTO EFECTIVO".
  - Prompt: sección "3. Estatus de Llamadas y Contacto Efectivo" (marcador + Contactado/Sin Contacto + Nota); **Productividad por Asesor cambia la columna "Contacto%" (que era `efectiva`/calidad MAL etiquetada) por `Contactado | Sin Contacto`** (contacto real).
  - **⚠️ 3 "contactos" distintos, no confundir** (el prompt lo aclara): (a) **Contestada** = estatus del marcador; (b) **Contactabilidad/llamadas de calidad** = `efectiva`≥80% (calidad); (c) **Contacto efectivo** = Contactado/Sin Contacto (si se habló con la persona). El "no contestó" del marcador (1.190) sigue pendiente de Juan; esto es "contacto efectivo dentro de lo registrado", NO el mismo número.
- **Contacto Efectivo = partición LIMPIA que suma al total (2026-08-18, rev `00136-ch6`):** en el reporte, `Contactado` y `Sin Contacto` ahora particionan TODAS las llamadas: **Contactado** (se habló con la persona) = `Resultado_Llamada IN ('Contactado','Rechazado','Venta')` (un rechazo ES un contacto); **Sin Contacto** = `IN ('No Disponible','Buzón de Voz','Número Equivocado','Sin Contacto','Sin Clasificar')`. Así Contactado+Sin Contacto = Llamadas (antes no sumaba: Rechazado y Sin Clasificar quedaban fuera). P2 agregado: Contactado **340 (48.9%)** / Sin Contacto 355. **La gráfica del dashboard se alineó (rev `00137-hdk`):** `distribucion_resultado.py` ahora usa la MISMA partición (2 barras Contactado/Sin Contacto, suma al total), y el título del chart pasó a **"Contacto Efectivo"** (`ResultadosChart.jsx`). Antes mostraba el desglose granular (Contactado 317 / Sin Contacto 260 / Rechazado / Venta) que divergía del reporte. Ahora reporte y dashboard dan el mismo número.
  - **Mapeo verificado con datos (2026-08-18):** se comprobó cada categoría de `Resultado_Llamada` por turnos-del-cliente promedio (de `Transcripcion_V4` `[Cliente]`) y largo de transcripción. Grupo **Contactó** (conversación real): Contactado 4.0 turnos/1147 chars, Rechazado 5.6/1701, Venta 2.0/418. Grupo **Sin Contacto** (poca/ninguna conversación): Sin Contacto 0.2 turnos/15 chars, Buzón 0.0/137, Sin Clasificar 0.8/404. ✅ La agrupación es coherente. **Matiz (5 llamadas, impacto nulo):** `No Disponible` (4, 3.5 turnos) y `Número Equivocado` (1, 7 turnos) SÍ tuvieron conversación pero con alguien que NO es el cliente objetivo (contestó un familiar / número errado) → correctamente en "Sin Contacto" = no se contactó al CLIENTE. Nota: parte de `Sin Clasificar` podrían ser conversaciones reales que el STT no separó bien (límite upstream, no error de mapeo).
  - **⚠️ Confiabilidad del mapeo limitada por el STT (verificado 2026-08-18):** la lógica de `detectar_resultado_llamada` es correcta, PERO se infiere de la transcripción → hereda los errores del STT. En P2, del grupo "Sin Contacto" (355), **43 llamadas (~6% del total) tienen transcripción LARGA (>400 chars) pero ≤1 turno de cliente** → probablemente son **conversaciones reales que el STT no separó bien** (no etiquetó al `[Cliente]`), mal contadas como "Sin Contacto". ⇒ **"Contactado" es un SUBconteo** (P2 real ≈380+, no 340); "Sin Contacto" un sobreconteo. El big picture (≈mitad/mitad) es correcto, pero el número exacto tiene ~5-6% de error. **La raíz es el STT** (mismo tema de la reunión con Juan): mejorar el STT (large-v3, beam_size, VAD) mejora la separación de hablantes → esas ~43 se reclasificarían solas como Contactado. Munición extra para el STT: "mejorar el STT también arregla la clasificación de Contacto Efectivo, hoy ~6% mal clasificado".
- **Columna "Saludos" → "Saludo%" en Productividad por Asesor (2026-08-18, rev `00135-hv6`):** el conteo crudo de `Saludo_Completo='Sí'` sobre TODAS las llamadas era engañoso (daba 0-5 por asesor). Hallazgo: casi ningún saludo es `'Sí'` (completo) — en P2 la distribución es **No 530 / Parcial 155 / Sí 10**. Nueva métrica **`Saludo%` = (Sí+Parcial) / contactadas** (tope 100%): denominador justo (solo las que tuvieron conversación real, no buzón) e incluye Parcial. Da tasas comparables (Andres 68%, Rosselin 80%, Nicolas 15%). El tablero global sigue mostrando "Saludo" completo (`Sí`) como el estándar estricto (titular real: solo 10 saludos completos/semana). En `get_data_context`: `saludo_ok` (Sí+Parcial) + `saludo_ok_pct`; prompt columna "Saludo%".

### Prompts de IA alineados: builders de asesor y ranking (2026-08-19)
- **Auditoría de los 12 endpoints de IA:** todos usan `call()` → heredan `MODEL=gpt-4o` (ninguno pasa `model=` explícito); cero uso del término viejo "ventas cerradas". Los 5 agregados (Insights, Inteligencia, Análisis Automático, Patrones Ventas, Reporte) usan `get_data_context`, que ya trae las etiquetas con guardarraíl ("Llamadas de calidad …NO es contacto", "Contacto efectivo", "Posibles ventas …NO es venta cerrada real").
- **Hallazgo:** 2 builders NO usaban `get_data_context` y quedaron con etiquetas viejas ambiguas: `get_asesor_context` (endpoint `analizar_asesor`, botón "Analizar con IA" por asesor en Rendimiento) y `get_ranking_context` (endpoint `analisis_comparativo_ranking`, RankingIA en Agente IA PRO). Decían **"Contactadas (efectivas)"** (es `efectiva`=calidad, NO contacto), **"Ventas"** crudo (sin caveat de inferida), y **"Despedida/Saludo correcta"** (spin sobre un conteo heurístico).
- **Fix (relabel de strings, sin cambio de lógica ni de números):** ambos builders ahora dicen **"Llamadas de calidad (efectiva >= 80%, calidad del asesor; NO es contacto)"**, **"Posibles ventas (inferidas de la transcripción, NO es venta cerrada real)"**, y los conteos de calidad como **detección heurística** ("Saludo detectado", "Beneficios expuestos", "Despedida detectada") con nota "NO juicios". Verificado local: ambos emiten las etiquetas nuevas y ya no las viejas. **PENDIENTE DESPLEGAR** (token gcloud expiró al momento del deploy).

### Embudo alineado a la partición Contacto Efectivo (2026-08-19, rev `00147`)
- **Hallazgo (verificación integral dashboard+reporte):** el paso "Contactado" del **embudo** (`embudo_conversacion.py`) usaba `Resultado_Llamada = 'Contactado'` (literal) = **10.496**, mientras la gráfica **Contacto Efectivo** (`distribucion_resultado.py`) y el reporte usan la **partición** `IN ('Contactado','Rechazado','Venta')` = **12.400**. Misma etiqueta "Contactado", dos números distintos en el mismo dashboard; y el embudo quedaba ilógico (Ventas=734 NO era subconjunto del 'Contactado' literal, son categorías excluyentes). Venía de que el embudo se hizo (16-jul) antes de crear la partición (18-ago).
- **Fix:** el paso "Contactado" del embudo ahora usa la misma partición → **12.400**. Embudo: 47409 → 18848 → 13995 → **12400** → 734 (descendente, Ventas ⊂ Contactado). "Contactado" significa lo mismo en todo el dashboard. Verificado en vivo: embudo=12400 = Contacto Efectivo chart=12400.
- **Verificación integral (2026-08-19):** se cruzaron TODOS los endpoints del dashboard vs ground truth de BigQuery (KPIs, Contacto Efectivo, Estatus, embudo, rendimiento/TMO, evolución, ventas-vs-servicio, %efectivas) + el reporte P2 (datos, 8 semáforos, leyenda, TMO síntoma, despedida neutral, Metas SMART). Todo consistente; filtros propagan (KPI y Contacto Efectivo con filtro P2 = 695 y 340/355, idénticos al reporte).

### RESULTADO reunión con S3 2026-07-23 (23 min: Diego, Fabián, Juan Garnica, Daniel Obando de S3)
> Reunión que Fabián convocó tras la salida de Sergio, para hablar DIRECTO con el proveedor (S3) sin intermediarios. Presenta **Daniel Obando** (S3, área de las grabaciones; Fabián a ratos le dice "Oscar" — es `oscar.obando@s3.com.co`).

- **🔴 CAUSA RAÍZ del Hora Pico `00:00:00` — la hora real está en el NOMBRE del archivo, no en el timestamp.** S3 hizo (feb-2026, prod) un desarrollo para guardar las grabaciones en formato tipo "Five9": carpetas por agente activo → año → días con llamadas → entrada/salida. El script **copia las grabaciones a medianoche (00:15)** del servidor del proveedor (ContactVox) al **servidor de backup** (el FTP `172.16.1.33` que lee la CUN) → por eso el *timestamp del archivo* es `00:15` (la transferencia), no la llamada. La **hora real de la llamada va en el nombre**: ej. `3057780167byagente11@07_05_22PM.mp3` (7:05 PM) o formato `...@fecha@hora` (`@18092025@10_00_00`).
  - ⇒ Los ~3.873 registros con `00:00:00` en BigQuery = el pipeline tomó la fecha pero **no parseó la hora del nombre**. Nuestro fix (excluirlos de la moda) es parche correcto; **la hora es recuperable en el origen** parseando el filename → tarea de **Juan Manuel** (su pipeline lee las carpetas de audio). Ver sección "Hora Pico daba 00:00".
- **Estado de los reportes/columnas (por qué Fabián convocó):** Sergio había pedido a S3 agregar al Excel una columna con el identificador de la grabación. S3: "sí, pero ContactVox tiene MUCHÍSIMOS reportes; cambiarlos todos = **una millonada**; díganme *cuáles* reportes y qué campos exactos". Quedó pendiente con Sergio → Sergio se fue → **se congeló**. Faltó **definir el alcance** con precisión ("teléfono roto", todo pasaba por Sergio).
- **✅ Continuidad resuelta:** **Fabián toma el contacto DIRECTO con S3** (Daniel guardó su número, sin intermediarios). Daniel enviará a Fabián la **hoja de requerimientos/alcance** (lo aprobado y pagado: "Script de modificación de formato de audios", 24h) + captura del resultado.
- **API de ContactVox:** se mencionó que **puede existir una API** para conectarse (lo preguntó la CUN/Juan) → vía potencial para automatizar y dejar el Excel. S3 pide saber el fin/alcance.
- **Arquitectura de audio (reconfirmada):** grabaciones en el proveedor (ContactVox) → script S3 hace rsync a medianoche al backup → FTP CUN. Formato **MP3**, sin cambios recientes. Se genera grabación solo cuando hay audio. Novedades: centro.servicios@s3.com.co cc oscar.obando@s3.com.co.
- **Pendientes:** **Fabián** define QUÉ reportes + QUÉ campos necesita CL Tiene (para que S3 cotice) · **Juan Manuel** parsea la hora del filename (arregla 00:00 en origen) + cédula + WAP · posible **reunión a 3** (S3 + CUN + DivergencyAI).

### KPI "Posibles ventas" (rename 2026-08-11) + pendiente de BD limpia
- **Renombrado en el display:** "Ventas Cerradas"/"Venta Cerrada" → **"Posibles ventas"** en TODO el dashboard (KPI card `Dashboard.jsx`, embudo `embudo_conversacion.py`, chart `ResultadosChart.jsx`, dropdown `resultado_llamada.py`, filtro Servicio). El **valor interno sigue siendo `Resultado_Llamada = 'Venta'`** (732, del regex `detectar_resultado_llamada`). Es honesto: el usuario ve "Posibles ventas", el enum técnico es 'Venta'.
- **Extendido a las gráficas de Inteligencia (2026-08-18, rev `00125-2bg` + Firebase):** se descubrió que 3 vistas mostraban "Ingresos/Ventas" engañosos: (1) **Evolución de Ventas** — el backend (`/evolucion-ventas`) tenía `COUNT(*) ingresos` (¡el conteo de llamadas disfrazado de dinero!) y `SUM(efectiva) ventas` (calidad, no venta) → se corrigió a `llamadas` + `posibles_ventas` (COUNTIF `Venta`); el frontend (`Evolucion.jsx`) ahora grafica **Llamadas** (rosa) y **Posibles ventas** (verde), título **"Evolución de Llamadas y Posibles Ventas"**. (2) **Ventas vs Servicio** (`Ventas.jsx`): barra verde "Efectivas" → **"Posibles ventas"** (el dato ya era `COUNTIF(Venta)`). (3) **Rendimiento**: columna "% Ventas" → **"% Posibles ventas"**. Consistente con el rename del KPI; sigue siendo el regex inflado internamente (`Resultado_Llamada='Venta'`).
- **Verificado (2026-08-11):** "Posibles ventas" (732) ≠ "venta cerrada". Son datos distintos: 732 = regex inflado; "venta cerrada" = estado de gestión de ContactVox/Zoho que **NO está en la BD** (`Estado_de_Gestion` viene **VACÍO** — 0 filas no-nulas). La venta real vive en ese campo (`Estado_de_Gestion='venta cerrada'`) o en Zoho `Cerrado Ganado` (~10-15/mes).
- **💡 Camino más simple a la venta real:** poblar `Estado_de_Gestion` (que trae 'venta cerrada', 'no contactado', 'en gestión') resolvería DOS cosas de una: (1) la venta real y (2) los "Estados Prospectos" de la plantilla del contact center. Pedírselo a Juan Manuel.
- **⚠️ PENDIENTE (limpieza de BD, cuando llegue la venta real):** cambiar el **valor interno** `'Venta'` → `'Posibles ventas'` (o mejor, reemplazar el regex por la venta real) es un refactor de **15+ referencias** (`subir_datos.py`, `procesador.py`, `kpi.py`, `embudo`, `rendimiento_agente.py`, `duraccion_efectivo.py`, `routes.py`, `routes_new.py`, `utils.py`×4, `analizar_patrones_dashboard.py`×2, `Resumen.jsx`) + `UPDATE` de los 732 registros en BigQuery. **NO hacerlo aislado** (cero cambio visual, mucho riesgo) → hacerlo **junto con la integración de la venta real** (Estado_de_Gestion/Zoho) en un solo refactor limpio.

### Plantilla del contact center (informe del año pasado, de Steven 2026-08-11)
- Steven pasó el informe base que quiere el contact center (ContactVox "ESTADISTICAS GENERALES CONTAC CENTER"): Total Marcaciones, **TMO**, Estatus Llamadas (Ocupada/No Contestada/Fallida/Contestada), Total+TMO por agente, y "Estados Prospectos/Negociación" (No contactado/En gestión/Interesados).
- **Requisitos de Steven para el informe semanal:** nº llamadas, contestaron/no contestaron, **tiempo hablado promedio (TMO)**, estados de prospecto; y calidad: **llamada buena/no tan buena** + **si se deja hablar al cliente**.
- **Ya agregado al dashboard (2026-08-11):** KPI **TMO** (promedio de `Tiempo de Conversacion`, H:MM:SS) y **Participación Cliente** (% de turnos del cliente en V4 = "si se deja hablar al cliente"). Ambos respetan todos los filtros.
- **Buildeable de la plantilla:** Estatus de Llamadas (de `Estado_de_la_LLamada`: ANSWERED/NO ANSWER/BUSY → Contestada/No Contestada/Ocupada), columna TMO por asesor en Rendimiento.
- **NO buildeable aún:** "Estados Prospectos/Negociación" → `Estado_de_Gestion` vacío (mismo pendiente de arriba).
- **✅ HECHO (2026-08-14, rev backend `00121-gfd` + Firebase):** los 2 buildeables ya están en el dashboard:
  - **Gráfica "Estatus de Llamadas"** — nuevo endpoint `GET /api/estatus_llamadas` (`back/api/charts/estatus_llamadas.py`, traduce `Estado_de_la_LLamada` con `UPPER(TRIM())`: ANSWERED→Contestada verde, NO ANSWER→No Contestada ámbar, BUSY→Ocupada rojo, resto=raw; devuelve label/valor/porcentaje/color; respeta filtros). Componente `EstatusChart.jsx` (auto-fetch estilo `DuracionChart`) agregado a `Resumen.jsx`. En vivo: Contestada 74.7% / No Contestada 25.3%.
  - **Columna TMO por asesor** en Rendimiento — `rendimiento_agente.py` ahora devuelve `tmo_seg` (AVG de `Tiempo__de_Conversacion` en segundos, solo rows con tiempo>0). `Rendimiento.jsx`: helper `fmtTMO(seg)`→H:MM:SS, columna "TMO" tras "Llamadas", ordenable por `tmo_seg`. De paso se corrigió el mapeo de orden de "% Efectividad"→`contacto_pct` (antes mapeaba a un campo inexistente).

### Reporte Ejecutivo (Agente IA PRO) rehecho estilo Steven (2026-08-12, rev `00120-xr5`)
- Steven pasó el informe del año pasado (ContactVox "ESTADISTICAS GENERALES") como base de formato y pidió un reporte **más ejecutivo**. Se rehízo el `reporte_completo` (NO se creó pestaña nueva; es el mismo botón "Generar Reporte Ejecutivo" → PDF).
- **`get_data_context()` (`helpers/utils.py`) enriquecido** — ahora el reporte (y todos los que lo usan: insights, análisis automático, inteligencia, patrones, chat) reciben además: **Estatus de Llamadas** (Contestada/No Contestada/Ocupada, traducido de `Estado_de_la_LLamada`), **TMO global y por asesor** (parseado de `Tiempo__de_Conversacion`), **Participación del cliente** (% turnos cliente en V4), y por asesor Contacto%/Saludos/TMO. Cambio **aditivo** (solo suma texto al ctx) → no rompe los otros endpoints.
- **Prompt (`generar_reporte_completo.py`) reescrito a "Director de Operaciones / comité semanal":** BLUF (lo esencial primero) → Tablero con semáforo 🟢🟡🔴 → Estatus de Llamadas → Productividad por Asesor (Llamadas/TMO/Contacto%/Saludos/Posibles ventas) → Calidad → Patrones → Rechazos → Recomendaciones priorizadas (impacto+responsable) → Plan 4 semanas → Metas SMART. Incluye reglas anti-error: "posibles ventas" ≠ venta real, "calidad" ≠ contacto, explica TMO y participación.
- El PDF (`ReporteCompleto.jsx`) parsea HTML genérico → las secciones nuevas (semáforo, tablas) salen sin tocar el front. Verificado en vivo con filtro 25-jul→1-ago: detectó "Melany genera 75% de posibles ventas con bajo volumen" y "Nicoll TMO 3:04 con baja efectividad".
- **Fix PDF emojis (frontend desplegado):** la fuente estándar de jsPDF no renderiza emojis de color → el semáforo 🟢🟡🔴 salía como basura (`Ø=ßâ`) y causaba espaciado raro entre letras. `clean()` ahora mapea 🟢→Verde, 🟡→Amarillo, 🔴→Rojo y **strippea cualquier char fuera de Latin-1** (`/[^\x00-\xFF]/g`) para eliminar emojis sueltos. En pantalla los emojis se siguen viendo bien (solo el PDF los traduce).
- **Tablas reales en el PDF (frontend desplegado):** la IA emite `<table>/<thead>/<td>` reales; antes el PDF las aplanaba a texto con ` | `. Nueva función `drawTable(headers, rows)` en `ReporteCompleto.jsx` dibuja grid de verdad: encabezado rosa (#FC3276) con texto blanco, filas zebra (#f8fafc), bordes, columnas auto-ancho (proporcional al contenido más largo), col 0 a la izquierda y el resto centrado, wrap por celda y **repite el encabezado al saltar de página**. El `walk` extrae `thead`/`tbody` (o primera fila como header) y padea/trunca filas a `headers.length`.
- **Logo CL Tiene en el PDF (frontend desplegado):** `descargarPDF` es ahora `async`; `cargarLogo()` carga `assets/logo_cl_tiene.png` (wordmark blanco + swoosh) a un dataURL vía canvas y se embebe con `doc.addImage` a la derecha de la banda rosa del encabezado (130pt de ancho, alto proporcional, centrado vertical). Si falla la carga, el PDF sale sin logo (fallback silencioso).
- **Separación "Llamadas de calidad" vs "Contacto efectivo" en el reporte (2026-08-19, rev `00142-9zf`; feedback de GPT):** la última ambigüedad conceptual era llamar "Contactabilidad" a lo que es `efectiva≥80%` (calidad, no contacto). Se **renombró en todo el reporte "Contactabilidad" → "Llamadas de calidad"** (3.9%) y se agregó **"Contacto efectivo" (48.9%)** como indicador SEPARADO. El **Tablero pasó a 8 filas** (Total, Llamadas de calidad, Contacto efectivo, TMO, Participación, Saludo, Calidad, Posibles ventas), con semáforos precalculados en `get_data_context` (`sem_ce`: 🔴<40/🟡40-60/🟢>60). También (feedback GPT): (a) regla para NO juzgar conteos de calidad (Saludo/Beneficios/WhatsApp/Despedida) como bueno/malo automáticamente (203 despedidas ≠ "falta de cierre"); (b) regla anti "aumentar el tiempo por aumentar el tiempo" en recomendaciones (mejor "desarrollar la conversación sin extender artificialmente"). Verificado: tablero 8 filas, sin "contactabilidad", sin juicio negativo de despedida.
  - **Leyenda de rangos del semáforo (mismo día, feedback GPT/Diego):** el 🟡 de "Contacto efectivo 48.9%" se afirmaba sin decir contra qué umbral ("ligeramente por debajo de lo esperado", vago). Se agregó `RANGOS DEL SEMÁFORO` en `get_data_context` (los umbrales de Llamadas de calidad, Contacto efectivo, TMO, Participación, Posibles ventas) y el prompt la reproduce como **nota "Rangos del semáforo:" justo debajo del Tablero** → cada color queda justificado. Además se PROHIBIÓ la frase vaga "por debajo de lo esperado": debe citar el rango concreto. La leyenda usa **palabras** ("más de 60%", "40 a 60%", "menos de 40%") a propósito: evita `<`/`>` (glitch en pantalla) y el guion largo `–` (que el sanitizador Latin-1 del PDF borra → "1020%"). Verificado en vivo: leyenda bajo el tablero, sin `<`/`>`/`–`, sin "por debajo de lo esperado".
  - **Conteos de calidad neutrales + Metas SMART de una sola métrica (mismo día, 2º feedback GPT):** (a) la regla anterior frenó el juicio NEGATIVO de la despedida pero la IA lo volteó a POSITIVO ("despedida correcta en 203, buen manejo de cierre"). Se reescribió: los conteos (Saludo/Beneficios/WhatsApp/Despedida) se reportan NEUTROS, prohibido adjetivar en CUALQUIER dirección (ni "buen manejo/saludable" ni "exceso/falta de cierre") salvo que se calcule una TASA sobre denominador; "despedida" es detección heurística, no "despedida correcta". (b) Meta SMART #3 mezclaba 2 métricas sin línea base ("beneficios y cierre efectivo en 20%"). Regla nueva: cada meta = UNA métrica con UNA línea base numérica y UN objetivo en la misma unidad; usar solo métricas con base clara en el contexto (llamadas de calidad 3.9%, posibles ventas 0.29%, calidad /100 25.6, saludos). Verificado: despedida sin spin; Metas SMART = 3.9→10% / 0.29→2% / 25.6→40.
  - **Refuerzo TMO (mismo día, tras revisar el PDF):** la IA seguía poniendo "Aumentar el TMO a 1:25" como **Meta SMART** (el bloque viejo "OJO CON EL VERBO" daba licencia a fijar meta de TMO con tal de usar el verbo correcto). Se reescribió: **el TMO es SÍNTOMA, no palanca ni meta** → PROHIBIDO como meta numérica o acción en Recomendaciones/Metas SMART; solo se menciona como consecuencia esperada. Metas SMART ahora van sobre resultados (calidad, saludos, ventas). Verificado en vivo: Metas SMART sin TMO; el TMO solo aparece como diagnóstico ("cierres prematuros").
- **Fix determinista: estatus/contacto fuera del Resumen del PDF (frontend desplegado 2026-08-19):** el modelo insistía en meter el estatus del marcador / contacto efectivo en el Resumen Ejecutivo (tras 3 intentos por prompt seguía colándose). Solución en `ReporteCompleto.jsx` (extracción del panel Resumen): recorre el bloque del Resumen (hermanos de su `<h2>` hasta el siguiente encabezado), y cualquier `<li>`/`<p>` que matchee `/contestad|contacto efectivo|sin contacto|estatus del marcador|no contestad/i` lo **reubica en la sección "Estatus de Llamadas"** (crea `<p>` nuevos tras ese `<h2>`, con anchor que preserva orden). El Resumen queda con bullets+conclusión; el estatus no se pierde. Es fix del PDF (en pantalla `dangerouslySetInnerHTML` puede seguir mostrándolo). Las reglas del prompt se dejan (reducen frecuencia) → cinturón y tirantes.
- **Fix legibilidad en PANTALLA (frontend desplegado 2026-08-13):** el reporte se veía ilegible en el dashboard (texto oscuro sobre el fondo oscuro `rgb(15,23,42)` que emite la IA). `limpiarHTML()` en `ReporteCompleto.jsx` convierte esos colores a tema claro (bg→#ffffff, texto rgb(203,213,225)→#334155, muted→#64748b, borde→#e2e8f0) SOLO para el `dangerouslySetInnerHTML` de pantalla. El **PDF sigue usando el HTML crudo** (`reporte`) porque parsea tags, no estilos. Es el patrón "limpiar colores oscuros" ya documentado arriba.
- **Consistencia entre informes + gpt-4o + comparación período anterior (2026-08-18, rev `00129-lfg`):** tras mostrar 2 informes a Steven (P1 25jul-1ago vs P2 2-9ago), se detectaron inconsistencias que Steven notaría. Cambios (todos verificados en vivo, números cuadran con BigQuery):
  - **Modelo IA subido a `gpt-4o` en TODOS los endpoints** vía env `MODEL=gpt-4o` en Cloud Run (`gcloud run services update ... --update-env-vars MODEL=gpt-4o`, también en `.env` local). Antes era gpt-4o-mini (default de `call()`). Razona mejor; costo ~$0.03/reporte (on-demand). Ojo: distinto de `MODELO_HABLANTES` (pipeline).
  - **Semáforo DETERMINISTA** — se calcula en código (`get_data_context`, bloque "SEMÁFOROS YA CALCULADOS" con umbrales fijos: Contactabilidad 🔴<10/🟡10-20/🟢>20; TMO 🔴<1:00o>5:00/🟡1-2o4-5min/🟢2-4min; Participación 🔴<30o>70/🟡30-40o60-70/🟢40-60; Posibles ventas 🔴<2%/🟡2-5%/🟢>5%) y la IA solo lo COPIA. Arregla que 49.3%→amarillo y 49.8%→verde (mismo valor, distinto color).
  - **Comparación período-vs-período** — `get_periodo_anterior_context()` (utils.py) + `_contexto_periodo_anterior()` (calcula el período inmediatamente anterior con `filters.model_copy`, mismos filtros salvo fechas) → el Resumen compara "vs el período anterior subió/bajó". P2 auto-compara con P1.
  - **TMO en formato M:SS consistente** (`_fmt_tmo` → "1:22" no "0:01:22") + regla en el prompt.
  - **Posibles ventas siempre "N (X%)"** (número + porcentaje) en Resumen/Tablero/asesor.
  - **Nota metodológica** contestada ≠ contacto efectivo (cuando 100% contestada + "sin contacto", para que no parezca contradicción).
  - **Estatus nunca vacío** (regla reforzada: cada sección con su propio contenido, el estatus NO se mueve al Resumen).
- **Fix encabezados de tabla partidos en el PDF (frontend desplegado 2026-08-14):** en Productividad por Asesor los headers se partían ("Llamada/s", "Contacto/%", "Saludo/s") porque el ancho era proporcional al conteo de chars y quedaba < al texto del header. `drawTable` ahora calcula `minW` por columna con `getTextWidth` real del header (garantiza 1 línea) + la col 0 (texto) acomoda el nombre más largo hasta un tope (`cap = 52% maxW`); el sobrante se reparte por peso de datos. Verificado en Node: los 6 headers y los nombres largos caben en 1 línea (sumW=515 exacto).
- **Pase "más formal/ejecutivo" del PDF (frontend desplegado 2026-08-13):** 6 ajustes de forma en `ReporteCompleto.jsx`: (1) **semáforo como badge de color** (pill roja/ámbar/verde con texto blanco, `STATUS` map + `roundedRect`) en vez de la palabra en gris; (2) **títulos de sección en gris pizarra `#1e293b`** con regla rosa de acento corta + línea gris (antes todo rosa = se veía marketing); (3) **Resumen Ejecutivo en panel destacado** (`panelResumen`: recuadro gris claro `#f8fafc` con barra rosa a la izquierda, se extrae del DOM y se renderiza aparte antes del `walk`); (4) **viñetas dibujadas** (`vineta()` pinta un punto rosa con `doc.circle` — el char `•` U+2022 lo borraba el strip de emojis, por eso las listas salían sin viñeta); (5) **números alineados a la derecha** en tablas (col 0 izq, semáforo centrado, resto der → estilo reporte financiero); (6) **acentos** (Estratégico, Período, histórico, Página). Verificado que las primitivas jsPDF (`circle`/`roundedRect "FD"`/`text {baseline:"middle"}`/`getTextWidth`) no revientan (test en Node).

## Dos tipos de error en las transcripciones (NO confundir)

Al revisar el ChatVisor pueden aparecer dos problemas distintos con causas y soluciones diferentes:

1. **Error de ATRIBUCIÓN de hablante** (quién habla) → lo genera nuestro pipeline con OpenAI.
   - Ejemplo: `[CLIENTE]: Correcto, señora Rosalía.` cuando debería ser `[ASESOR]` (el cliente no se dirige a sí mismo por su nombre).
   - **Solución:** prompt v16 (regla del vocativo como REGLA #1 en `_PROMPT_HABLANTES`) + modelo `gpt-4o`. Se corrige al **re-procesar BigQuery con `--full`**. Nota: incluso `gpt-4o`+v16 falla ~2% en llamadas con STT muy deforme (no es 100%).

2. **Error de STT (voz a texto)** (qué palabras) → lo genera el motor de transcripción de la CUN, upstream.
   - Ejemplos: "Celetines Aluciones"/"usted le tiene soluciones" → "CL Tiene Soluciones"; "Rodalia"/"DSLTN" → nombres deformados; "mi feliz tía" → "un feliz día".
   - **NO se corrige con ningún prompt** (el texto de origen ya viene deformado). Depende de mejorar el STT en la CUN → **tema para la reunión del martes**.

> Antes de reportar una transcripción "mal", distinguir cuál de los dos es: si quién habla está bien pero las palabras están deformes → es STT (no nuestro). Si quién habla está intercambiado → es atribución (v15).

### Medición de calidad de transcripciones (2026-08-11, sobre 21.690 con V4)
- Diego reportó una llamada mal transcrita (tel 3144201397, 29-jul). **Diagnóstico verificado a nivel de dato:** el STT entregó un **bloque corrido sin separación de hablantes y con palabras deformes** ("Rosselin"→"Rocio Arrames", "CL Tiene Soluciones"→"le tienes soluciones", "Fusagasugá/Cundinamarca"→"Fuacha con Dinamarco", "gatico"→"cacico"). Con ese mush, gpt-4o **no puede separar** → un `[Cliente]` gigante mezcla pitch del asesor + respuestas del cliente. **Es error de STT, no de atribución** (el prompt no puede arreglar un texto inseparable).
- **Heurística sobre las 21.690:** turnos promedio **6.2**; **42.1%** con ≤2 turnos (incluye cortas legítimas: buzón/no contesta); **29.3% (6.359)** con un turno >400 chars = **bloque mezclado** (síntoma del STT corrido). Palabras deformes en casi todas.
- **Conclusión:** el techo de calidad lo pone el **STT de la CUN** (`faster-whisper medium` + `beam_size=1` + VAD), no nuestra atribución. **~1 de cada 3 llega inseparable.** Palanca real = mejorar el STT (Juan Manuel: `large-v3`, subir `beam_size`, ajustar VAD). Crítico ahora que Jarvey pide análisis (saludos/cierre/WhatsApp) basado en estas transcripciones → sin mejor STT el análisis tiene tope.

## Sesión 2026-07-08 — Fixes de KPI, verificación de gráficas y accesos GCP

### KPIs corregidos (`back/api/charts/kpi.py`) — commiteados, PENDIENTE DESPLEGAR
- **Hora Pico**: mostraba el `AVG` de los timestamps (16:08, siempre media tarde). Ahora usa la **moda** (hora con más llamadas = 09:00) vía nuevo CTE `top_hora`. Verificado que respeta filtros.
- **Calidad IA**: promediaba las 7 métricas sobre las 38k incluyendo el 64% **sin transcripción** (métricas=0) → 14.1. Ahora solo sobre las evaluadas (`IF(transcripcion... , metric, NULL)`) → **28.0**.
- **"Llamadas Efectivas" → "Llamadas de Calidad"** (`src/pages/Dashboard.jsx`): `efectiva` es score de calidad ≥80%, no contacto efectivo.
- Verificación completa: los 8 KPIs calculan bien (coinciden con el dashboard). Total 38.148, Ventas 374 (inflado, ver arriba), Día Pico Martes, Asesor Top Jimmy Rusinque, Saludo 49.3%.

### Gráficas — problemas encontrados (PENDIENTE arreglar + decidir)
- **Motivo Rechazo / Tipo Mascota / Tipo Vehículo** devuelven `'N/A'` que domina (91-98%) → ocultan las categorías reales. El frontend NO lo filtra. Recomendación: filtrar `!= 'N/A'` en Motivo Rechazo (deja el takeaway "92% rechazan por 'No Interesa'"); esconder/quitar Mascota y Vehículo (muy escasas, no aportan).
- **`rendimiento_hora.py` — CÓDIGO MUERTO (no es bug visible)**: el endpoint `/api/rendimiento_hora` (que usa `rendimiento_hora.py`, con el CTE `suma_efectivos` sin filtro y agrupando por `resultado_llamada`) **NO lo llama el frontend**. La gráfica que SÍ se muestra (Inteligencia Operativa, línea por hora) usa `x_rendimiento_hora` → endpoint `/rendimiento-hora` (query inline en `routes.py`), que agrupa por **hora** y **respeta los filtros** (correcto). Se puede **borrar** `rendimiento_hora.py` + `/api/rendimiento_hora`.
- **Mislabel corregido (2026-07-08)**: 3 gráficas de Inteligencia (`x_rendimiento_hora` `/rendimiento-hora`, `x_rendimiento_dia` `/rendimiento-dia`, `duracion_vs_efectividad` `/duracion-vs-efectividad`) calculaban `ventas/total` pero el frontend las etiqueta **"% Efectivas"**. Cambiadas a `SUM(CAST(efectiva AS FLOAT64))/total` → ahora muestran la efectividad real (score de calidad, ~3-3.5% por hora) en vez de la venta inflada (~0.5%). La etiqueta "% Efectivas" ya es correcta. Pendiente desplegar.
- Distribuciones correctas (reflejan realidad): Duración (56% Buzón), Resultado (63% Sin Contacto), Planes reales.

### Hora Pico daba 00:00 con filtro "Solo con transcripción" (2026-07-16)
- **Causa (dato upstream):** hay **~3.873 registros con `Fecha` a `00:00:00` exacto** — traen la fecha pero **perdieron la hora del día**. Casi todos (99%) tienen transcripción, así que al filtrar "Solo con transcripción" ese lote (3.887) superaba a la hora 11 (2.617) y la moda daba **00:00**. Sin filtro no se notaba (la hora 11 tiene más volumen total).
- **Fix (`kpi.py`, CTE `top_hora`):** excluir del cálculo de la moda los registros con `00:00:00` exacto (`NOT (HOUR=0 AND MINUTE=0 AND SECOND=0)`). Se conservan los 41 de medianoche "real" (con minutos/segundos). Verificado: con y sin filtro de transcripción ahora da **11:00**.
- **Raíz upstream (CONFIRMADA en reunión S3 2026-07-23):** la hora real de la llamada va en el **nombre del archivo** de grabación (ej. `...byagente11@07_05_22PM.mp3`), NO en el timestamp (el archivo se transfiere a medianoche 00:15). Los `00:00:00` = el pipeline no parseó la hora del filename. Recuperable en origen (Juan Manuel). Ver "RESULTADO reunión con S3 2026-07-23".
- **KPIs con 0 datos → muestran `0` (2026-07-16, rev `00116-l2l`):** cuando un filtro no arroja filas, Hora Pico/Día Pico/Asesor Top daban `None`. Ahora `IFNULL(...,'0')` / `COALESCE(...,'0')` → muestran `0` (los numéricos ya daban 0). Verificado: los 8 KPIs se comportan bien con todos los filtros (asesor, tipo, resultado, duración, fecha, transcripción y combos), y son lógicamente consistentes (Ventas→calidad alta, Buzón→calidad baja, Servicio→asesor top de servicio).

### Embudo de conversión arreglado (2026-07-16, desplegado rev `00114-g9v`)
- **Problema:** `embudo_conversacion.py` tenía como paso 2 `"Efectivas (contacto)" = COUNTIF(efectiva=1.0)` (2.212). Como `efectiva` es score de calidad (chico), el embudo **no descendía** (caía a 2.212 y volvía a subir a 15.981) y la etiqueta contradecía el KPI ya renombrado a "Llamadas de Calidad". Además el query **no tenía `ORDER BY`** (orden no garantizado).
- **Fix:** se quitó el paso de `efectiva`, se agregó `"Contactado" = COUNTIF(Resultado_Llamada='Contactado')`, y se añadió columna `orden` + `ORDER BY orden`. Embudo final (descendente): Total 39.916 → Conv>30s 15.981 → Con Saludo 12.396 → Contactado 9.775 → Ventas 708.
- Solo backend; el frontend (`EmbudoChart.jsx`) dibuja lo que llega y su filtro Servicio (oculta "Ventas Cerradas") sigue igual.

### Accesos GCP (BLOQUEA el deploy) — auditoría de seguridad CUN 2026-07-06
- La CUN (Jonathan López, GCP admin) **quitó el rol Owner** de `diego_ojeda@cun.edu.co` en el proyecto `desarrollo-investigaciones` (auditoría de menor privilegio).
- Roles actuales: `bigquery.admin/dataEditor/jobUser`, `firebase.admin`, `run.admin`, `secretmanager.admin`.
- **FALTAN para desplegar Cloud Run** (`gcloud run deploy --source` da `PERMISSION_DENIED: iam.serviceaccounts.actAs`):
  - `roles/iam.serviceAccountUser` (actAs la SA del runtime — el error exacto)
  - `roles/cloudbuild.builds.editor` (build de `--source`)
  - `roles/storage.admin` (subir el código fuente al bucket)
  - `roles/logging.viewer` (opcional, depurar)
- Diego ya envió el correo a Jonathan pidiéndolos (2026-07-08). Verificar con `gcloud projects get-iam-policy desarrollo-investigaciones --flatten="bindings[].members" --filter="bindings.members:diego_ojeda@cun.edu.co"`.
- **Nota:** BigQuery/consultas funcionan (vía ADC), solo el deploy de Cloud Run está bloqueado.

#### Actualización 2026-07-14 — casi listo, falta UN permiso (`serviceusage.services.use`)
- Diego pidió a Jonathan: `roles/editor` + `iam.serviceAccountUser` + `secretmanager.admin` (+ mantener `firebase.admin`). Jonathan asignó **todo menos Editor** (Editor es "rol básico" y la política de seguridad de la CUN no lo permite).
- **Roles actuales (10):** `bigquery.admin/dataEditor/jobUser`, `cloudbuild.editor`, `firebase.admin`, `iam.serviceAccountUser`, `logging.viewer`, `run.admin`, `secretmanager.admin`, `storage.admin`.
- **Verificado empíricamente** (`cloudresourcemanager.testIamPermissions` vía REST con el token ADC de Diego): de 8 permisos críticos para `run deploy`, tiene **7**. El **único que falta es `serviceusage.services.use`** (lo traía Editor). `iam.serviceAccounts.actAs` ✅ ya cubierto por `iam.serviceAccountUser`.
- **Falta pedir a Jonathan un solo rol:** **`roles/serviceusage.serviceUsageConsumer`** (solo "usar servicios ya habilitados" → cumple menor privilegio). Con ese, el deploy debería completar. **No hay otros bloqueos ocultos** (los otros 7 permisos ya están).
- Re-verificar permiso puntual: `curl -s -X POST "https://cloudresourcemanager.googleapis.com/v1/projects/desarrollo-investigaciones:testIamPermissions" -H "Authorization: Bearer $(gcloud auth print-access-token)" -H "Content-Type: application/json" -d '{"permissions":["serviceusage.services.use"]}'` → si devuelve el permiso, ya se puede desplegar.

#### ✅ RESUELTO 2026-07-14 — backend DESPLEGADO
- Jonathan asignó `roles/serviceusage.serviceUsageConsumer` → `serviceusage.services.use` ✅ (verificado). Los permisos personales de Diego quedaron completos.
- **Segundo bloqueo (SA de Compute, no de Diego):** el deploy `--source` falló con `403: 293865702055-compute@developer.gserviceaccount.com does not have storage.objects.get` sobre el bucket `run-sources-...`. La auditoría dejó a la SA de Compute (la que Cloud Build usa para construir la imagen) **sin ningún rol de Storage** (sí tiene `artifactregistry.admin` + `logging.admin`).
- **Fix (self-service, Diego tiene `storage.buckets.setIamPolicy`):** `gcloud storage buckets add-iam-policy-binding gs://run-sources-desarrollo-investigaciones-us-central1 --member="serviceAccount:293865702055-compute@developer.gserviceaccount.com" --role="roles/storage.objectViewer"`. NO requiere a Jonathan.
- **Deploy OK:** revisión `cltiene-backend-00113-r7j` sirviendo 100%. Verificado en vivo (`/api/kpi`): Hora Pico = **11:00** (moda, ya no 16:08), Calidad = **32.2** (solo evaluadas, ya no ~14). Total 39.916. Gráficas `% Efectivas` con `efectiva` real. `ventas: 708` sigue inflado (pendiente Zoho).

### Columna de venta real (de CL Tiene) — Sergio CONFIRMÓ el diagnóstico (2026-07-14)
- Diego pidió a Sergio una columna con la venta real. **Sergio confirmó por nota de voz lo que encontramos:**
  - **La venta muchas veces NO pasa en la llamada** — en varios casos le envían al cliente un **link de contrato** que él completa, o se leen las condiciones y se para para la autorización → el cierre queda **fuera del audio**.
  - *"No son muchas realmente las llamadas con las que sí se generó una venta"* → confirma que el 374 (inferido) está inflado.
  - *"eso se puede sacar"* → **el dato de venta real EXISTE y se puede extraer** (lo tienen registrado).
  - **La venta se asocia al contrato/CLIENTE, no a una llamada puntual.**
- **Reto de integración:** cruzar la venta ↔ llamadas por **cédula/cliente + fecha + asesor**, NO por llamada individual. Es justo la tabla `CLTIENE_VENTAS` (CRM, `Fase='Cerrado Ganado'`).
- **Siguiente paso:** Diego propuso reunión con Juan para definir de dónde se toma la venta real (¿`CLTIENE_VENTAS`?) y cómo se cruza. La fuente real conocida sigue siendo `CLTIENE_VENTAS` (`Fase='Cerrado Ganado'` = 959).

### ✅ RESUELTO: recuperadas ~2.630 llamadas por Cuenta NULL con COALESCE (2026-07-09)
- El `INNER JOIN registros_unicos a ON a.cuenta = b.cuenta` descartaba las filas con `cuenta` NULL/vacía (~2.647, 5.2%).
- **Fix aplicado:** `cargar_desde_sql()` ahora usa `COALESCE(cuenta, Agente)` en el CTE, el JOIN y el SELECT de Cuenta. Recupera las filas usando el nombre de `Agente` cuando `Cuenta` es NULL.
- **Resultado (re-corrida 2026-07-09):** BigQuery 37.286 → **39.916 filas**, `Cuenta NULL = 0`, 21 asesores. **Edwin Cendales pasó de 0 a 482 llamadas** (aunque aún puede faltar por el tema de carpeta `ecendales` vs `agenteN` en el STT, que es de CL Tiene).
- **Fix de fondo (CL Tiene/Sergio):** estandarizar los nombres en el origen (el "fix de nombres" pendiente) — así no hay que depender del COALESCE.

### Fix formato de fecha español (Windows es-CO) — recuperadas ~5.8k filas de oct-2025 (2026-08-14)
- **Hallazgo (Copilot lo detectó a medias, verificado por nosotros):** `cargar_desde_sql()` solo parseaba fechas ISO con `TRY_CONVERT(datetime, fecha, 120)` → **descartaba en silencio 7.142 filas (13%)** del total crudo (54.652). NO eran 15.101/32% como decía Copilot, y su fix (formato 103) **recupera 0**.
- **Causa real:** esas 7.142 filas son el **lote oct-2025** (10-oct → 7-nov, ANTES de que la fuente cambiara a ISO el 8-nov). Vienen en formato regional español de Windows: `'DD/MM/YYYY h:mm:ss a. m./p. m.'` con **espacio angosto U+202F** (doble). SQL NO lo parsea: probado `TRY_CONVERT` 103/105/default, `TRY_PARSE es-CO/en-US` y normalización con `REPLACE(NCHAR(8239))` → **todos 0** (el U+202F no se deja reemplazar por collation).
- **Fix (`subir_datos.py`):** nueva `parse_fecha_es()` (normaliza espacios Unicode con `unicodedata.category=='Zs'` + regex + 12h→24h) parsea el formato en **Python** (7.142/7.142 OK). El query principal (ISO 120) **NO se tocó**; se agregó un **query fallback aditivo** (`sql_fb`, `WHERE TRY_CONVERT(120) IS NULL AND fecha LIKE '%/%/%'`) que trae esas filas crudas y se concatenan tras parsear en Python. Columnas compartidas vía `_COLS_MEDIO` (sin duplicar). Se agregó **log** de recuperadas/descartadas (punto válido de Copilot).
- **Nota:** las 7.142 son **solo metadata** (0 transcripción → $0 OpenAI, sin V4/atribución); solo suman volumen/estatus de oct-2025 y extienden la historia. Aparecen **4 asesores nuevos** (rotación: gente que salió antes de nov).

## Sesión 2026-09-25 — envío apagado + hallazgo `mixto` + roadmap de 2 informes segmentados

> Fecha de referencia de la BD: **49.996 filas · 2025-10-10 → 2026-09-09 · 27 asesores · 0 `Cuenta NULL`**.

### 1. Envío semanal APAGADO (decisión del usuario)
- Scheduler **`cltiene-reporte-semanal` PAUSADO** + job `cltiene-envio-reporte` con **`REPORTE_ENABLED=0`** y **`ALERTA_ENABLED=0`**.
- `cltiene_reportes_enviados` = **0 filas** ⇒ el reporte real a Steven **nunca** se ha enviado. La ejecución de las 15:00 terminó `succeeded=1` con `[SKIP]` (BD antigua).
- Revertir solo con OK: `gcloud scheduler jobs resume cltiene-reporte-semanal` + `gcloud run jobs update cltiene-envio-reporte --update-env-vars REPORTE_ENABLED=1`.
- ⚠️ PowerShell no acepta `--update-env-vars A=0,B=0` (lo pasa como un string) → **flags-file JSON** o pares simples.

### 2. Carga incremental run7 = **no-op** (SQL sin datos nuevos)
- Backup `cltiene_llamadas_procesadas_backup_20260925` (49.996). Corrida `python .\subir_datos.py` con `MODELO_HABLANTES=gpt-4o` (2 keys, red CUN), terminada 15:09:29.
- Leídas **58.179** (51.037 ISO + 7.142 fallback español) → dedup **8.183 (14.1%)** → escritas **49.996**. La tabla **NO cambió**: el SQL CUN no pasa del **2026-09-09**.
- Verificado: 27 asesores, 0 `Cuenta NULL`, historia 2025-10-10 → 2026-09-09, `Fecha`/`fecha_carga` = INTEGER ns (contrato con `DIV(Fecha,1000)` intacto). 959 filas sin `Transcripcion_V4` = fragmentos STT de 1–9 chars (esperado, no bug).

### 3. Hallazgo `mixto` (bug de mapeo) → ✅ **RESUELTO el 2026-09-28** (ver Sesión 2026-09-28)
- **Qué era `mixto` (NO "llamadas mezcladas"):** el CTE `registros_unicos` del query principal contaba filas por `COALESCE(cuenta,Agente)` + **timestamp** y hacía `CASE WHEN a.cant > 1 THEN 'mixto' ELSE b.tipo END`. El tipo del origen siempre estuvo bien; el `INNER JOIN` solo servía para ese conteo. Impacto: **10.783 filas (21,6%)** invisibles en los filtros por tipo + una 3ª barra fantasma en la gráfica "Ventas vs Servicio". El mismo `CASE` estaba duplicado en `back/api/upload/procesador.py` (legacy).

### 4. Roadmap acordado — 2 informes PDF segmentados (Ventas / Servicio), sin correo
- **2 archivos**: `reporte_ventas_<periodo>.pdf` y `reporte_servicio_<periodo>.pdf`, cada uno con apartados **Entrantes** + **Salientes** + **"Sin dirección"** (obligatorio: 50% de `Tipo_Llamada` NULL). Periodo: última semana completa **2026-08-31 → 2026-09-06**.
- Requisitos (de auditoría de solo lectura): `generar_reporte_completo(FilterModel)` ya acepta `tipo_llamada` / `seguimiento_llamada` (reutilizable con overrides) pero `enviar_reporte_semanal.py` solo acepta fechas → hace falta **script/flags nuevos**; `get_data_context()` **no trae** el desglose por `Tipo_Llamada` (agregarlo); `contexto_tipo_llamada()` adapta el prompt a Servicio pero **no excluye** "Posibles ventas" (ni el desglose por asesor ni el semáforo) → quitarla en modo servicio.
- Salida **local**: sin SMTP, sin registro en `cltiene_reportes_enviados`, sin tocar el job/scheduler.
- **Venta real sigue bloqueada upstream:** Cristian Galeano (21-sep) confirmó que la llamada **no está enlazada** a un caso en Zoho.

### ✅ Los 3 informes HECHOS (2026-09-28) — general (correo) + ventas + servicio

> **Son 3 informes, no 2:** el **general** (el mismo que se envía al correo a Steven) + los 2 **segmentados por
> frente** (ventas / servicio), cada uno con los apartados Entrantes / Salientes / Sin dirección.
> Semana **2026-09-14 → 2026-09-20** (998 llamadas). **Sin envío, sin registro, sin tocar job/scheduler.**

| Informe | Págs | Cómo se generó |
|---|---|---|
| `reporte_general_<periodo>.pdf` | 4 | `enviar_reporte_semanal.py --dry-run --no-preflight --fecha-desde/--fecha-hasta` (**idéntico al que se enviaría por correo**) |
| `reporte_ventas_<periodo>.pdf` | 6 | `generar_reportes_segmentados.py` (2 bloques) |
| `reporte_servicio_<periodo>.pdf` | 6 | ídem |

- **Entregables** en `back/reportes_segmentados/`. Los 2 segmentados llevan además `.html` sidecar (auditoría); el general solo PDF (el dry-run no lo guarda y **no se tocó el script del job**, que corre en Cloud Run).
- **Bloques (2 por informe):** Ventas → Entrantes **14** (2,4%) · Salientes **576** (97,6%). Servicio → Entrantes **175** (42,9%) · Salientes **233** (57,1%). Cada bloque abre **página nueva** (`.bloque{break-before:page}`) con portadilla `Ventas — Salientes · N llamadas (X% del frente)`.
- 🚫 **El bucket "Sin dirección" (`Tipo_Llamada IS NULL`) se EXCLUYÓ de los 3 informes** (decisión del usuario 2026-09-28: el corte que importa es **Ventas vs Servicio**, no la dirección). Cada informe quedó con **2 bloques**. Se quitó también la `NOTA DE COBERTURA` del contexto (`helpers/utils.py`), que ya no declara ese faltante.
  - ⚠️ **Consecuencia a tener presente:** el campo viene vacío en el origen para ~49% del histórico (nov-2025→ene-2026 y feb-2026). Para esas fechas, Entrantes+Salientes **no** suma el total. Desde mar-2026 el origen trae la dirección siempre, así que los informes semanales (que siempre son la última semana) no tienen ese problema. Verificado: hoy las 3 salidas traen 0 menciones de "Sin dirección".
  - El centinela `seguimiento_llamada='null'` → `Tipo_Llamada IS NULL` **se conserva** en `filters()` (mecanismo genérico, con sus tests), aunque los informes ya no lo usen.
- **Modo Servicio (verificado: 0 menciones de ventas en PDF y HTML):** `es_informe_de_servicio()` → `get_data_context(ocultar_ventas=True)` quita la métrica, la columna de asesor, la fila del Tablero, el semáforo/rango y las metas SMART ⇒ **Tablero de 7 filas**. En Ventas y en el general se conserva todo (8 filas).
- **Cambios en el código:** (1) `helpers/utils.py`: `_SIN_DIRECCION` (sentinelas `null`/`sin_direccion`/…) → `Tipo_Llamada IS NULL`; nuevo bloque **DIRECCIÓN DE LAS LLAMADAS** con Entrantes/Salientes/Sin + *NOTA DE COBERTURA*; `get_asesor_context` también se endureció contra 0 filas; (2) `generar_reporte_completo.py` acepta `ocultar_ventas`; (3) `reporte_pdf.html_a_pdf(titulo=, subtitulo=)` + CSS `.bloque`; (4) script nuevo con flags `--fecha-desde/--fecha-hasta --tipos --direcciones --solo-html --solo-pdf --forzar --outdir`; (5) validador `tests/validar_reportes_segmentados.py` (cubre los 3).
- **🔴 3 bugs encontrados y corregidos durante la corrida (todos con regresión):**
  1. **`get_data_context` reventaba con 0 filas** (`SUM` sobre conjunto vacío = NULL → `TypeError: unsupported format string passed to NoneType` y `None%`/`None` en el texto). Pasó al combinar `ventas` + `Sin dirección` (combinación vacía). Fix **doble**: `COALESCE` en los agregados del SQL + `or 0` y `_pct()` (división segura) en Python, en `get_data_context` **y** `get_asesor_context`. Un test lo cazó (el mock sin COALESCE); con datos reales de BigQuery el `COALESCE` ya lo tapaba, pero el bug quedaba latente para el `--forzar` y para cualquier filtro vacío.
  2. **El bloque vacío no abría página** (el `<div>` sin `class="bloque"` pegaba la nota al bloque anterior) → los 3 apartados no se leían como secciones. Fix + regresión.
  3. **El validador daba un falso negativo** (buscaba el em-dash literal, que el PDF extrae como guion corto) y **no medía los residuos del PDF del general** (no tiene HTML). Ambos corregidos; los residuos ahora se miden siempre en el PDF.
- **Verificado:** 60 tests OK (`python -m unittest discover -s tests`); contexto de producción **byte-idéntico al baseline** fuera del bloque DIRECCIÓN (comparado contra los contextos guardados del reporte semanal); ningún PDF con `None`/`nan`/`N/A`; semáforos 🟢🟡🔴 convertidos a **Verde/Amarillo/Rojo** en el texto; `rgb(15,23,42)` (fondo oscuro de la IA) eliminado en el PDF; `cltiene_reportes_enviados` sigue con **0 filas** (el general NO se registró ni se envió).
- **🔴 Verificación de la BD y del origen (2026-09-28, mismo día):** el SQL Server tiene **59.177 filas** con tope **2026-09-20 14:00:11**, idéntico al `MAX(Fecha)` de BigQuery → **0 filas nuevas ⇒ la BD ya estaba al día y NO se recargó** (recargar habría sido un no-op con `WRITE_TRUNCATE` de 50.994 filas). `Tipo_Llamada` en el origen trae **4 valores literales** (`Saliente` 11.575 / `Salientes` 11.776 / `Entrante` 4.388 / `Entrantes` 1.940) + **29.498 NULL**; BigQuery ya los tiene limpios (solo `Saliente`/`Entrante`) porque la normalización vive en `subir_datos.py` L1049 (`WRITE_TRUNCATE`, nunca un `UPDATE` — no existe ningún `UPDATE`/`DELETE`/`MERGE` en el repo). El **fix de nomenclatura `Salientes`→`Saliente` que Juan Manuel se Traders asesoría de julio/2026 NO está aplicado** (13.716 filas) — pendiente reclamárselo junto con llenar la dirección del histórico.
- **Comandos:**
  ```bash
  cd back/
  $env:PYTHONIOENCODING='utf-8'; $env:PATH=$env:PATH+';C:\Program Files\GTK3-Runtime Win64\bin'
  # 1) el general (idéntico al del correo; --no-preflight = cero escrituras en BQ)
  python .\enviar_reporte_semanal.py --dry-run --no-preflight --fecha-desde 2026-09-14 --fecha-hasta 2026-09-20 --outdir .\reportes_segmentados
  # 2) los 2 segmentados (4 llamadas gpt-4o)
  python .\generar_reportes_segmentados.py --outdir .\reportes_segmentados
  python .\generar_reportes_segmentados.py --solo-pdf --outdir .\reportes_segmentados  # re-rasteriza sin gastar tokens
  python .\tests\validar_reportes_segmentados.py .\reportes_segmentados          # valida los 3 PDF
  ```
- **⚠️ WeasyPrint local** requiere GTK3 Runtime en el `$env:PATH`; `pypdf` (solo para validar) se instaló en el venv. **Errores SSL intermitentes a BigQuery desde la red CUN ≈ 1 de cada 2 intentos ⇒ reintentar** (pasó 5 veces hoy). El dry-run escribe `reporte_semanal_dryrun.pdf` → renombrar a `reporte_general_<periodo>.pdf`.
- **Nota de calidad:** el bloque "Ventas · Entrantes" tiene solo **14 llamadas** → sus metas SMART son estadísticamente débiles (la nota del PDF ya advierte interpretarlas junto al volumen). El histórico (49% sin dirección) sí producirá bloques "Sin dirección" con datos cuando se corra sobre un período más antiguo.



### Carga de datos 2026-09-16 (hecha, con gpt-4o + 2 keys) — ⚠️ incluye fix preventivo de tipo `Fecha`
- Corrida **incremental** con `gpt-4o` + 2 keys, Diego en la red CUN. Juan Manuel cargó datos nuevos al SQL (hasta 6-sep).
- **Estado previo:** SQL 57.947 crudas / máx 6-sep; BigQuery 48.842 / 29-ago. → ~1.038 filas nuevas (30-ago→6-sep).
- **Resultado:** BigQuery 48.842 → **49.880 filas** (+1.038 netas). Dedup quitó **8.067 (13.9%)**. Historia **2025-10-10 → 2026-09-06**. Backup: `cltiene_llamadas_procesadas_backup_20260916` (estado previo, 48.842).
- **Verificado** (BQ): 49.880 filas, **27 asesores**, 0 Cuenta NULL, `MAX(DATE(TIMESTAMP_MICROS(DIV(Fecha,1000))))` = **2026-09-06** (la fórmula del backend funciona).
- **🔴 Fix preventivo en `subir_bigquery()` (evita romper prod):** el venv local nuevo (pandas **3.x**, py3.14) autodetecta las fechas como `TIMESTAMP` (pandas ≥3 usa `datetime64[us]`), pero el backend depende de `Fecha`/`fecha_carga` como **INTEGER en nanosegundos** (`DIV(Fecha,1000)`). Se detectó porque el schema de la primera subida difería del backup (`Fecha` INTEGER → TIMESTAMP). **Fix:** en `subir_bigquery()` se convierten explícitamente a `int64` ns: `pd.to_datetime(df[col]).astype("datetime64[ns]").to_numpy().view("int64")` (⚠️ con pandas 3 NO funciona `Series.view`, ni `.astype("int64")` directo, ni `.values.view()` sin forzar `[ns]` → guardaría µs, 1000× corto). Resultado: schema idéntico al backup, `Fecha` y `fecha_carga` en ns.
  - Sin esto, TODOS los endpoints del dashboard fallarían (`DIV(TIMESTAMP,...)` no existe y el valor quedaría 1000× corto). El run de producción (pandas 2.2/py3.11, como el 09-03) es inmune; el peligro es reproducir con el venv nuevo.
- ⚠️ **Redisperando librerías:** en este venv no hay wheel de pandas 2.2.x para py3.14 (compila de fuente y falla) → se usa pandas 3.x + el fix de arriba. Correr con `PYTHONIOENCODING=utf-8` (nota de carga anterior). Errores SSL intermitentes a BigQuery por la red CUN: reintentar.

### Carga de datos 2026-09-03 (hecha, con gpt-4o + 2 keys)
- Corrida **incremental** con `gpt-4o` + 2 keys, Diego en la red CUN. Juan Manuel cargó datos nuevos al SQL (hasta **29-ago**).
- **Estado previo:** SQL 56.909 crudas / máx 29-ago (antes 55.123 / 17-ago); BigQuery 47.880 / 17-ago. → ~1.786 filas nuevas (18-29 ago).
- **Resultado:** BigQuery 47.880 → **48.842 filas** (+962 netas). Dedup quitó **8.067 (14.2%)**. Historia **2025-10-10 → 2026-08-29**. Backup: `cltiene_llamadas_procesadas_backup_20260903` (estado previo, 47.880).
- **Fix `Entrantes` aplicado:** primera carga con la normalización `Entrantes→Entrante` (rev `fb57476`) → `Tipo_Llamada` quedó limpio: `Saliente` 18.410 / `Entrante` 5.403, **cero `Entrantes`** (el WRITE_TRUNCATE no re-introdujo el bug).
- **Verificado** (BQ): 48.842 filas, **26 asesores**, 0 Cuenta NULL, historia al 29-ago.
- ⚠️ **2 líos de encoding en Windows al correr:** (1) `subir_datos.py` abortó con `'charmap' can't encode '→'` (un `→` en un log) → se corre con **`PYTHONIOENCODING=utf-8`** (igual que `comparar_metodos.py`). No llegó a tocar BigQuery, seguro re-correr.

### Carga de datos 2026-08-24 (hecha, con gpt-4o + 2 keys)
- Corrida **incremental** con **`gpt-4o`** + las **2 API keys**. Diego dentro de la red CUN.
- **Estado previo (SQL vs BQ):** SQL tenía datos hasta **17-ago** (55.123 crudas / 47.981 ISO + 7.142 español); BigQuery hasta **9-ago** (47.409). ⇒ ~8 días nuevos (10-17 ago).
- **Resultado:** BigQuery 47.409 → **47.880 filas** (+471 netas). Dedup quitó **7.243 (13.1%)**. **Historia 2025-10-10 → 2026-08-17**. Backup: `cltiene_llamadas_procesadas_backup_20260824` (estado previo, 47.409).
- **Consumo:** fase IA ~75 seg → **pocas transcripciones nuevas** reales (10-17 ago) a OpenAI → **~$2-4**. El log dice "Nuevas/cambiadas: 25.570" pero eso incluye ~25k filas vacías/sin transcripción que NO llaman a OpenAI (Reutilizadas 22.310 del cache).
- **Verificado en vivo** (`/api/kpi` + BQ): total **47.880**, Hora Pico 11:00, Día Martes, Calidad 32.0, Saludo 52.6, TMO 0:01:15, **25 asesores**, **0 Cuenta NULL**. **0 transcripciones REALES sin V4** (las 873 "sin V4" son fragmentos STT de ~6 chars repartidos en todos los meses, correctamente no estructurados — no es un bug del run). `ventas: 738` sigue inflado (pendiente Zoho).

### Carga de datos 2026-08-14 (hecha, con gpt-4o + 2 keys)
- Corrida con **`gpt-4o`** + las **2 API keys**. Diego dentro de la red CUN. Se corrió **2 veces**: (1) actualización normal 40.873→41.568 (datos frescos al 9-ago), (2) tras el **fix de formato de fecha** (arriba) → **41.568 → 47.409 filas** (+5.841 de oct-2025 recuperadas post-dedup).
- **Verificación previa (SQL vs BQ):** SQL tenía datos hasta **9-ago** (54.652 crudas / 47.510 ISO); BigQuery hasta **1-ago** (40.873).
- **Resultado final:** BigQuery **47.409 filas**. **Historia 2025-10-10 → 2026-08-09**. Dedup quitó 7.243 (13.3%). Backup: `cltiene_llamadas_procesadas_backup_20260814` (estado pre-cargas de hoy, 40.873).
- **Consumo:** ~**498 transcripciones nuevas** (>1-ago) a OpenAI en la 1ª corrida → **~$5**. La 2ª corrida (fix fecha) fue **~$0** (oct no tiene transcripción, las ISO ya en cache).
- **Verificado en vivo** (`/api/kpi` + BQ): total **47.409**, Hora Pico 11:00, Día Pico Martes, Calidad 31.9, Saludo 52.6, TMO 0:01:15. 0 transcripciones reales sin V4, 0 Cuenta NULL, **25 asesores**. `ventas: 734` sigue inflado (pendiente Zoho).

### Carga de datos 2026-08-11 (hecha, con gpt-4o + 2 keys)
- Corrida incremental con **`gpt-4o`** (`MODELO_HABLANTES=gpt-4o`) y las **2 API keys** (balanceo ~50/50). Diego dentro de la red CUN.
- **Resultado:** BigQuery 39.916 → **40.873 filas** (+957 netas). Dedup del pipeline quitó **5.891 dups (12.6%)**. **Datos frescos hasta el 1-ago** (antes 2-jul → Juan tenía datos nuevos en el SQL). Backup: `cltiene_llamadas_procesadas_backup_20260730`.
- **Consumo:** ~**731 transcripciones nuevas** a OpenAI → costo **~$7.71** (~$3.85 por key). ⚠️ El log dice "Nuevas/cambiadas: 19.914" pero eso incluye ~19k filas vacías (sin transcripción) que NO llaman a OpenAI; las llamadas reales fueron ~731 (confirmado por el tiempo de proceso: 2.6 min). Estimación previa (`scratchpad/calcular_consumo.py`) daba 731 nuevas y ~$7.71 con gpt-4o.
- **Verificado en vivo** (`/api/kpi`): total **40.873**, Hora Pico 11:00, Calidad 32.1, Saludo 52.8. 0 transcripciones sin V4, 0 Cuenta NULL, 21 asesores. `ventas: 732` sigue inflado (pendiente Zoho). El dashboard refleja los datos nuevos sin re-desplegar (el backend lee BigQuery directo).

### Carga de datos 2026-07-09 (hecha)
- Subido incremental con `gpt-4o-mini` + solo key 2 (`OPENAI_API_MUNDIAL=""`), driver ODBC 18. BigQuery: 38.148 → **37.286 filas** (deduplicado, datos al **2-jul**). Costo ~$3. Backup: `cltiene_llamadas_procesadas_backup_20260709`.
- Verificado: 0 duplicados, 0 transcripciones sin V4, 0 nulos en campos clave, datos de julio presentes (395 filas).
- **Fix del driver SQL** (`_crear_engine()` robusto: Driver 18/17/viejo) aplicado a `subir_datos.py`.

## Sesión 2026-09-28 — bug `mixto` resuelto + recarga al 20-sep (50.994 filas)

> Estado de la BD: **50.994 filas · 2025-10-10 → 2026-09-20 · 27 asesores · 0 `Cuenta NULL` · 0 `tipo` NULL**.
> Decisiones del usuario: **normalizar sí · recargar ya · SIN backup nuevo** (el `_backup_20260925` = estado exacto previo) · **sin deploy** (solo cambian los datos).

### 1. El bug `mixto` (qué era, por qué, y el fix)
- **Causa raíz:** en el query principal de `cargar_desde_sql()`, un CTE (`registros_unicos`) agrupaba por `COALESCE(cuenta, Agente)` + **timestamp** y el `INNER JOIN` marcaba `CASE WHEN a.cant > 1 THEN 'mixto' ELSE b.tipo END`. El tipo del origen **siempre estuvo bien**; el JOIN no aportaba datos, solo el conteo. El mismo `CASE` estaba duplicado en `back/api/upload/procesador.py` (legacy, con LEFT JOIN → `tipo` NULL en 50% de las filas).
- **Impacto real:** **10.783 filas (21,6%)** quedaban **invisibles** en los filtros `tipo=ventas` / `tipo=servicio` y aparecían como barra fantasma en "Ventas vs Servicio"; el dropdown ofrecía 4 categorías (`ventas`, `mixto`, `servicio`, `servicios`) en vez de 2.
- **Fix (2 archivos):**
  - `back/subir_datos.py` → `b.[tipo] AS tipo` (eliminan el CTE y el `INNER JOIN`; se verificó con queries que el JOIN devolvía **exactamente** las mismas 52.035 filas que el `WHERE` ⇒ cero cambio en el conjunto de filas).
  - Una línea de normalización en `procesar()` junto a la de `Tipo_Llamada`: `df['tipo'] = df['tipo'].str.strip().str.lower().replace({'venta':'ventas','servicios':'servicio'})` (el origen trae `venta` y `servicios` como variantes).
  - Replicado en `back/api/upload/procesador.py` (`conectar_y_cargar` + `procesar_dataframe`) para que el legacy no lo reintroduzca.
  - `tipo` no lo lee ningún otro paso del pipeline (verificado con grep) → sin efectos colaterales.
- **Nota de por qué NO era un bug de "llamadas mezcladas":** el nombre `mixto` sugería "llamadas mezcladas"; en realidad solo marcaba "hay más de una llamada del mismo asesor en el mismo minuto".

### 2. Recarga (`subir_datos.py`, 09:03→09:07, gpt-4o + 2 keys, red CUN)
- **Pre-flight en seco (antes de escribir):** `cargar_desde_sql()` → 59.177 leídas (52.035 ISO + 7.142 español), dedup 8.183 (13.8%) → **50.994** y `tipo` normalizado = 2 valores. Con eso se confirmó el fix ANTES del `WRITE_TRUNCATE`.
- **Origen:** SQL crudo **59.177** (998 filas nuevas post-09-sep, del 14 al **20-sep 14:00**: 590 ventas / 408 servicio).
- **BigQuery:** 49.996 → **50.994** (+998). Historia 2025-10-10 → **2026-09-20**.
- **37 tests OK** (`python -m unittest discover -s tests`; hubo que `pip install fastapi` en el venv local, faltaba para `test_reporte_semanal`).
- Entorno: Python 3.14.5, **pandas 3.0.5** (el fix INTEGER-ns de `subir_bigquery()` aplica y se verificó), pyodbc 5.3.0 / ODBC Driver 18.

### 3. Verificación post-carga (BigQuery)
- `tipo` = **2 valores exactos**: ventas **28.911** / servicio **22.083** (= 50.994). `mixto = 0`, `servicios = 0`, `tipo NULL = 0`.
- **Schema idéntico al backup** (57 columnas, `Fecha`/`fecha_carga` = **INTEGER ns**) ⇒ el contrato `DIV(Fecha,1000)` del backend intacto.
- `Cuenta NULL = 0` · 27 asesores · `Tipo_Llamada` **sin cambios**: Entrante 5.946 / Saliente 20.019 / NULL **25.029 (49%)** ⇒ los 998 nuevos traeían todos dirección.
- Sin regresión de `Transcripcion_V4`: filas con texto pero sin V4 959 → 1.034 (fragmentos STT cortos, esperado).
- **KPIs de referencia:** contacto efectivo **27,9%** (14.236 Contactado / 36.758 Sin Contacto = 100% del total) · saludo completo `Sí` **425** (Sí+Parcial 8.122) · posibles ventas (regex) **886** · marcador (46.191 con dato): ANSWERED 35.172 / NO ANSWER 11.017 / BUSY 1.

### 4. Consecuencias
- Los **2 informes PDF segmentados** ya pueden confiar en el override `tipo_llamada` (antes `mixto` contaminaba el filtro). La última semana completa disponible es **2026-09-14 → 2026-09-20** ⇒ el **preflight A** del envío semanal se cumpliría (sigue **APAGADO** por decisión del usuario).
- ⚠️ **Trampa latente NO tocada (fuera de alcance):** la pareja `tipo_llamada`→columna `tipo` (negocio) y `seguimiento_llamada`→columna `Tipo_Llamada` (dirección) está **invertida**. Renombrarla exige deploy de backend + frontend.
- **Pendiente de commit:** `back/subir_datos.py`, `back/api/upload/procesador.py`, `CLAUDE.md`, `opencode.md` y este informe (no commiteado — sin aprobación).

## Sesión 2026-09-29 — TMO `N/D` (fix + verificación en el origen) + correo de automatización a los Juanes

> Continuación de la sesión 2026-09-28. Sin cambios en la BD (50.994 filas, tope 20-sep) y sin deploy.

### 1. El TMO `N/D` con semáforo 🔴 era un bug, no un dato malo
- **Síntoma:** los bloques de **llamadas entrantes** de los 3 informes salían con TMO `N/D` y semáforo **🔴 rojo**, que sugería mal desempeño. No lo era: significaba "cero duración".
- **Causa:** `AVG(dur_seg)` sobre un conjunto 100% `NULL` devuelve `NULL`; el semáforo coercionaba `None → 0` → 🔴. Y el TMO **general** se calculaba sobre las 809 salientes pero se presentaba como si fuera de las 998 llamadas (cobertura real **81,1%**).
- **Fix `back/helpers/utils.py`:**
  - El CTE `resumen` ahora trae `COALESCE(COUNTIF(dur_seg > 0), 0) AS tmo_n` (conteo de llamadas **con** duración) además del `AVG`.
  - Se derivan `tmo_sin_dato` y `tmo_cubierto` (`tmo_n / total`) → alimentan el contexto y el semáforo.
  - **Sin ninguna llamada medible → `⚪`** (no dato) en vez de 🔴. Con cobertura parcial → color por umbral normal, pero el texto declara el porcentaje.
  - Contexto: en el caso sin dato dice que **no se puede calcular** y que no debe interpretarse como mal desempeño; en el parcial, `1:17 (promediado sobre 809 de 998 llamadas = 81,1% de cobertura; el resto son entrantes sin campo de duración)`. La leyenda de rangos incluye `⚪ sin dato`.
- **Prompt `back/api/ia/generar_reporte_completo.py`:** prohibido inventar/estimar/juzgar un TMO `N/D`, y obligatorio citar la cobertura cuando sea parcial.
- `back/reporte_pdf.py` **ya** mapeaba `⚪` → `N/D` con badge gris (y `🟢🟡🔴` → Verde/Amarillo/Rojo, del 28-sep) ⇒ no necesitó cambio en este arreglo.
- **Tests:** +5 (`TestSemaforoTmoSinDato`) ⇒ suite **60 → 65**, `git diff --check` limpio.
- **Informes regenerados:** general `1:17` (81,1% cobertura, 🟡) · Ventas Entrantes `N/D` ⚪ / Salientes `1:18` 🟡 · Servicio Entrantes `N/D` ⚪ / Salientes `1:14` 🟡. 4 / 6 / 6 páginas.

### 2. 🔒 Verificación en el ORIGEN (SQL Server de la CUN) — el hueco NO es nuestro
> BigQuery es nuestra copia: consultarla no probaba nada. Se fue al origen con guardas que rechazan cualquier palabra de escritura en el texto de la consulta. **Cero escrituras, como siempre.**

| Dirección (origen, 14–20 sep) | Llamadas | `Tiempo␣␣de␣Conversacion` | `Tiempo␣␣de␣Llamada` |
|---|---|---|---|
| `Salientes` | 809 | 809 | 809 |
| `Entrantes` | 189 | **0** | **0** |

- En esas 189 filas el valor es **`NULL`**, no cadena vacía ⇒ el **archivo de origen de entradas no trae la columna**. BigQuery lo refleja fiel.
- **No hay columna alternativa:** `Tiempo  de Llamada` (duración total, ~30 s más que la de conversación) **también** viene vacía en las entrantes.
- **Total del origen = 998** llamadas, 9 asesores, tope `2026-09-20 14:00:11` ⇒ cuadra exacto con los 3 informes. Cero filas nuevas (la BD ya estaba al día).
- 🪤 **Trampa para queries nuevas:** la columna se llama **`Tiempo␣␣de␣Conversacion`, con DOBLE espacio**. Con un solo espacio falla con `Invalid column name`. El pipeline la mapea bien (queda como `Tiempo__de_Conversacion` en BigQuery), pero cualquier consulta manual la tropieza.
- **Dato de contraste:** el lote antiguo de 7.142 filas (oct-2025, sin dirección) **sí trae duración al 100%** ⇒ la columna existe y se llena; falta en el archivo de **entradas**. Convierte esto en un pedido concreto para Cristian/CL Tiene y Juan Manuel.
- **Consecuencia de negocio:** el TMO de las entrantes **no es medible** hasta que ese campo llegue — y el TMO es un KPI que Steven pidió explícitamente.

### 3. 📧 Correo de AUTOMATIZACIÓN enviado a los Juanes (29-sep-2026)
- **Para:** `Juan_marin@cun.edu.co` + `Juan_ganicac@cun.edu.co` (ambos en *Para*, sin copia de Fabián). **Sin fecha de reunión aún.**
- **Encuadre corregido:** el objetivo es automatizar **las DOS etapas de código**, no solo nuestro pipeline.
  - **Etapa 1 (COE / Juan Manuel):** SFTP + STT + cruce + Ollama. Hoy es un **notebook** ⇒ hay que volverlo script parametrizable (fecha de corte, reintentos, logs). **Es la parte difícil** y así se cheques en el correo.
  - **Etapa 2 (nosotros):** `subir_datos.py` ya es script autónomo con `__main__` ⇒ `PythonOperator` **sin reescribir nada**.
- **7 preguntas abiertas:** (a) ¿el nodo de Airflow tiene **GPU/CUDA** (`faster-whisper` la necesita)? (b) ¿**dónde vive Ollama** y es alcanzable desde Airflow? (c) ¿dónde quedan las **credenciales** de SFTP y BD? (d) **salida a `api.openai.com` y BigQuery** — la más crítica tras la auditoría de seguridad, (e) **secrets**, (f) **dependencias/ODBC Driver 18** en la imagen, (g) **gobernanza** (¿el DAG lo agrega el equipo de infraestructura o nos dan acceso?).
- **Lo que se quitó del borrador** (decisión del usuario): el split en **Frente 1** (código al DAG, con el Excel manual) y **Frente 2** (eliminar el Excel, que depende de S3); también la pregunta del día de corte semanal.
- **El cierre quedó en tono de escalada** ("reunión urgente", "escalar con quien corresponda", "solución definitiva").
- ⚠️ **Riesgos a vigilar en la respuesta:** (1) al no conservar el split, "eliminar los Excel" puede leerse como "reemplaza el Excel por la extracción de ContactVox", que **no está en manos de Juan Manuel** (depende de S3; Fabián ya tiene el hilo con Daniel Obando) — la respuesta es que el frente 1 sí lo destraba él; (2) **"los dos casos" es ambiguo** (puede leerse como las dos etapas *o* como los dos problemas de datos) → aclarar en una línea en el primer reply.
- **Pendiente:** segundo correo con los pedidos de datos sueltos (llave WAP, NO ANSWER/BUSY, `Salientes→Saliente`, hora del filename, y el campo de duración en el Excel de entradas). Se dejó fuera a propósito: el correo del 29-sep fue solo de automatización.

### 4. Estado
- **Informes:** 3 regenerados con el fix. Las versiones corregidas **NO se han reenviado** (el correo de prueba del 28-sep lleva las previas al fix) — reenviar solo con OK explícito.
- **Envío semanal: APAGADO**, sin cambios. **SQL Server: cero escrituras.** **Sin deploy.**

## Asesores con datos "cortados" — SOLO Edwin es un problema real (verificado 2026-07-14)

Al filtrar por asesor + fechas recientes, muchos asesores no aparecen en el dropdown "Nombre del Asesor"
(el dropdown solo lista asesores con llamadas **en el rango de fechas seleccionado**). Revisando las
últimas fechas de cada asesor en BigQuery aparecían ~11 con datos que se cortan antes de junio-2026.

**Cruce con la lista de asesores ACTIVOS que dio Sergio (30-jun-2026):**
- **Servicio:** Johan Casallas, Edwin Cendales, Angie Lancheros, Melany Ramirez, Nicolas Tovar
- **Cuenta/Ventas:** Andres Barrera, Jimmy Rusinque, Paula Naranjo, Rosselin Ibarra (esta última es de ventas)

De esos **9 activos, 8 tienen datos al día (jul-2026); el ÚNICO cortado es Edwin Cendales (última
llamada 2026-02-05)** → confirma que el problema de carpeta (`ecendales` vs `agenteN` en el STT) afecta
**solo a Edwin**. Los demás "cortados" (Jenifer Rodriguez, Dayana Marulanda, Marjorie Villadiego, Maria
Fernanda Rodriguez, Esmeralda Pena, Juan/Juan Pablo Monroy, Yoharlys Gomez, David Paloma…) **NO están en
la lista de activos → ya no trabajan** (rotación normal), su corte es esperado, no es un bug.

> **Conclusión:** NO hay un problema sistémico de carpetas. Único pendiente para CL Tiene: renombrar la
> carpeta de **Edwin** a `agenteN`. El corte de todos los demás es rotación de personal.

### Pendientes al cierre de la sesión
- [x] **Jonathan asignó los roles GCP + fix del bucket de la SA de Compute → backend DESPLEGADO** (rev `00113-r7j`, KPIs Hora Pico/Calidad + gráficas efectiva en vivo). HECHO 2026-07-14
- [x] **`COALESCE(Cuenta, Agente)` en el pipeline** → recuperadas ~2.630 llamadas (Edwin Cendales 0→482). HECHO 2026-07-09
- [ ] Arreglar gráficas N/A (Motivo Rechazo filtrar N/A; Mascota/Vehículo decidir)
- [ ] Enviar a Sergio el mensaje de la columna de venta (2026-07-09)
- [x] Subir datos al 2-jul (red CUN) — HECHO
- [ ] Ventas: **Sergio agregará columna `venta` (sí/no) + zoho id + cédula al Excel** (reunión 2026-07-15) → Juan Manuel la mete a la BD → cuando esté en SQL, cambiar el pipeline para leer la columna real en vez del regex. (Ver "RESULTADO reunión de ventas 2026-07-15".)
- [ ] Juan/CUN: mejora del STT (en progreso, mostrará diferencia)

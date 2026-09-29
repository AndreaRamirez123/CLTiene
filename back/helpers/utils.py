import re

from google.cloud import bigquery

from api.database import client, calculo_fecha
from helpers.sql import CONTACTADO, SIN_CONTACTO, CONTACTADO_SQL, SIN_CONTACTO_SQL, TABLE


def _esc(value) -> str:
    """Escapa un valor para interpolarlo de forma SEGURA en un literal string de
    BigQuery (previene inyección SQL). Escapa backslash, comilla simple y saltos
    de línea. Para valores normales es transparente (mismo resultado)."""
    return (
        str(value)
        .replace("\\", "\\\\")   # backslash PRIMERO (para no re-escapar los que agregamos)
        .replace("'", "\\'")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )


# Fechas válidas del date picker: YYYY-MM-DD. Si no matchea, se ignora el filtro
# (defensa extra: un valor no-fecha no puede colarse al TIMESTAMP()).
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Valores centinela del filtro `seguimiento_llamada` que significan "llamadas SIN
# dirección registrada" (Tipo_Llamada IS NULL). El origen deja ese campo vacío en
# ~49% de las llamadas; sin este bucket, cualquier informe "Entrantes vs Salientes"
# se leería como si el 100% tuviera dirección.
_SIN_DIRECCION = {"null", "none", "sin_direccion", "sin direccion", "sin dirección"}


def filters(filters: dict) -> dict:
    filtros_object = {}
    filtros_string = []

    print(f"\n\nFilter: {filters}", end="\n\n")

    for key, value in filters.items():

        # Ignorar None
        if value is None:
            continue

        # Ignorar string vacío
        if isinstance(value, str) and value.strip() == "":
            continue

        # Ignorar listas vacías
        if isinstance(value, list) and len(value) == 0:
            continue

        # Ignorar diccionarios vacíos
        if isinstance(value, dict) and len(value) == 0:
            continue

        filtros_object[key] = value

        if key == "fecha_desde":
            if _DATE_RE.match(str(value)):
                filtros_string.append(
                    f"""Fecha >= UNIX_MICROS(TIMESTAMP('{value}')) * 1000""")

        if key == "fecha_hasta":
            if _DATE_RE.match(str(value)):
                filtros_string.append(
                    f"""Fecha <= UNIX_MICROS(TIMESTAMP('{value} 23:59:59')) * 1000""")

        if key in ["resultado_llamada", "plan_mencionado", "Duracion_Estimada"]:
            filtros_string.append(f"{key} = '{_esc(value)}'")

        if key == "duracion_llamada":
            filtros_string.append(f"Duracion_Estimada = '{_esc(value)}'")

        if key == "saludo_asesor":
            filtros_string.append(f"Saludo_Completo = '{_esc(value)}'")

        if key == "nombre_asesor":
            # case-insensitive: el sidebar pasa el nombre exacto, pero la caja de
            # Transcripciones deja escribir a mano (ej. "jimmy" vs "Jimmy").
            filtros_string.append(f"LOWER(cuenta) like LOWER('%{_esc(value)}%')")

        if key == "modulo_atencion":
            filtros_string.append(f"Nombre_del_Modulo = '{_esc(value)}'")

        if key == "tipo_llamada":
            filtros_string.append(f"tipo = '{_esc(value)}'")

        if key == "seguimiento_llamada":
            # Centinelas para el bucket "Sin dirección": ~49% del histórico NO tiene
            # dirección registrada (viene vacía del origen), que el dropdown del
            # dashboard no ofrece. Se comparan en minúsculas contra el texto real
            # de la columna, así que no colisionan con 'Entrante'/'Saliente'.
            if str(value).strip().lower() in _SIN_DIRECCION:
                filtros_string.append("Tipo_Llamada IS NULL")
            else:
                filtros_string.append(f"Tipo_Llamada = '{_esc(value)}'")

        if key == "transcripcion" and value == "true":
            filtros_string.append("transcripcion is not null")

        if key == "clasificacion_sentimiento":
            filtros_string.append(f"clasificacion = '{_esc(value)}'")

        if key == "asistencia_mencionada":
            asistencia = value.replace("...", "").strip()
            filtros_string.append(f"Asistencia LIKE '%{_esc(asistencia)}%'")

    result = {
        "filter_string": " AND ".join(filtros_string) if filtros_string else "1=1",
        "filter_array": filtros_object,
    }

    return result


def es_informe_de_servicio(filters=None) -> bool:
    """True si el filtro activo es de SERVICIO (no de ventas). Es la bandera que
    usa el contexto para quitarle al informe toda la métrica de ventas."""
    if filters is None:
        return False
    return (getattr(filters, "tipo_llamada", None) or "").strip().lower() == "servicio"


def contexto_tipo_llamada(filters=None):
    """
    Instrucción de contexto para la IA según el filtro tipo_llamada.
    Evita que los reportes hablen de ventas cuando se están viendo llamadas de servicio.
    Devuelve '' cuando no hay filtro de servicio → comportamiento sin cambios.
    """
    tipo = ""
    if filters is not None:
        tipo = (getattr(filters, "tipo_llamada", None) or "").lower()

    if tipo == "servicio":
        return (
            "CONTEXTO CRÍTICO: Estás analizando ÚNICAMENTE llamadas de SERVICIO/ATENCIÓN, "
            "NO de ventas. Enfócate en calidad de atención, resolución de solicitudes, "
            "asistencias gestionadas, efectividad del contacto y satisfacción del cliente. "
            "La métrica de éxito es la efectividad del servicio, no la venta.\n"
            "PROHIBIDO en TODO el informe (cualquier sección, tabla, semáforo, resumen o meta):\n"
            "- la métrica 'Posibles ventas' y cualquier cifra de ventas o conversión "
            "(en este informe el contexto NO la incluye: es servicio, no venta);\n"
            "- la columna 'Posibles ventas' de la tabla de Productivity por Asesor;\n"
            "- la fila 'Posibles ventas' del Tablero de Indicadores y su semáforo;\n"
            "- la línea 'Posibles ventas' de la nota 'Rangos del semáforo'.\n"
            "El Tablero de Indicadores de este informe lleva 7 filas (las 7 primeras) y el "
            "análisis de metas se hace sobre CALIDAD DE ATENCIÓN (llamadas de calidad, contacto "
            "efectivo, saludo, participación del cliente, score de calidad, tiempo de resolución).\n\n"
        )
    return ""


def get_data_context(where="1=1", ocultar_ventas=False):
    """Contexto de datos en texto para alimentar los prompts de IA.

    `ocultar_ventas=True` (informe de SERVICIO) omite por completo la métrica
    'Posibles ventas': su línea del encabezado, su semáforo, su rango y la
    columna del desglose por asesor. Con el valor por defecto la salida es
    idéntica a la anterior (solo se AGREGA el bloque de DIRECCIÓN).
    """

    query = f"""
    WITH base AS (
        SELECT
            efectiva,
            Resultado_Llamada,
            Estado_de_la_LLamada,
            Tipo_Llamada,
            Duracion_Estimada,
            Plan_Mencionado,
            Saludo_Completo,
            ofrecimiento_solucion,
            Ofrecio_WhatsApp,
            cierre_servicio,
            Cuenta,
            Motivo_Rechazo,
            transcripcion,
            saludo_inicial, identificacion_cliente, comprension_problema,
            manejo_inquietudes, proximo_paso,
            ARRAY_LENGTH(REGEXP_EXTRACT_ALL(IFNULL(Transcripcion_V4, ''), r'\\[Cliente\\]')) cli_turns,
            ARRAY_LENGTH(REGEXP_EXTRACT_ALL(IFNULL(Transcripcion_V4, ''), r'\\[(?:Asesor|Cliente)\\]')) tot_turns,
            SAFE_CAST(SPLIT(Tiempo__de_Conversacion, ':')[SAFE_OFFSET(0)] AS INT64) * 3600
              + SAFE_CAST(SPLIT(Tiempo__de_Conversacion, ':')[SAFE_OFFSET(1)] AS INT64) * 60
              + SAFE_CAST(SPLIT(Tiempo__de_Conversacion, ':')[SAFE_OFFSET(2)] AS INT64) AS dur_seg
        FROM {TABLE}
        WHERE {where}
    ),

    resumen AS (
        SELECT
            COUNT(*) total,
            -- COALESCE: con 0 filas SUM() devuelve NULL y el formateo del texto
            -- reventaría (un bucket de filtro puede quedar vacío, p.ej. 'Sin dirección').
            COALESCE(SUM(CASE WHEN efectiva = 1.0 THEN 1 ELSE 0 END), 0) contactadas,
            COALESCE(SUM(CASE WHEN Resultado_Llamada = 'Venta' THEN 1 ELSE 0 END), 0) ventas,
            CAST(ROUND(AVG(IF(dur_seg > 0, dur_seg, NULL))) AS INT64) tmo_seg,
            -- Conteo de llamadas que SÍ traen duración: el origen no manda
            -- 'Tiempo de Conversacion' para las ENTRANTES, así que el TMO nunca
            -- cubre el total y hay que decirlo (y no marcarlo en rojo).
            COALESCE(COUNTIF(dur_seg > 0), 0) tmo_n,
            COALESCE(ROUND(SAFE_DIVIDE(SUM(cli_turns), SUM(tot_turns)) * 100, 1), 0) participacion_cliente,
            -- Score de Calidad (0-100): promedio de las 7 categorías sobre las llamadas
            -- EVALUADAS (con transcripción), igual que el KPI del dashboard.
            COALESCE(ROUND((
                AVG(IF(transcripcion IS NOT NULL AND LENGTH(transcripcion) > 50, saludo_inicial, NULL)) +
                AVG(IF(transcripcion IS NOT NULL AND LENGTH(transcripcion) > 50, identificacion_cliente, NULL)) +
                AVG(IF(transcripcion IS NOT NULL AND LENGTH(transcripcion) > 50, comprension_problema, NULL)) +
                AVG(IF(transcripcion IS NOT NULL AND LENGTH(transcripcion) > 50, ofrecimiento_solucion, NULL)) +
                AVG(IF(transcripcion IS NOT NULL AND LENGTH(transcripcion) > 50, manejo_inquietudes, NULL)) +
                AVG(IF(transcripcion IS NOT NULL AND LENGTH(transcripcion) > 50, cierre_servicio, NULL)) +
                AVG(IF(transcripcion IS NOT NULL AND LENGTH(transcripcion) > 50, proximo_paso, NULL))
            ) / 7 * 100, 1), 0) calidad_score
        FROM base
    ),

    calidad AS (
        SELECT
            COALESCE(SUM(CASE WHEN Saludo_Completo = 'Sí' THEN 1 ELSE 0 END), 0) saludo,
            COALESCE(SUM(CASE WHEN ofrecimiento_solucion = 1 THEN 1 ELSE 0 END), 0) beneficios,
            COALESCE(SUM(CASE WHEN Ofrecio_WhatsApp = 'Sí' THEN 1 ELSE 0 END), 0) whatsapp,
            COALESCE(SUM(CASE WHEN cierre_servicio = 1 THEN 1 ELSE 0 END), 0) despedida
        FROM base
    ),

    estatus AS (
        SELECT Estado_de_la_LLamada, COUNT(*) total
        FROM base
        WHERE Estado_de_la_LLamada IS NOT NULL AND Estado_de_la_LLamada != ''
        GROUP BY Estado_de_la_LLamada
    ),

    direccion AS (
        SELECT Tipo_Llamada, COUNT(*) total
        FROM base
        GROUP BY Tipo_Llamada
    ),

    resultados AS (
        SELECT Resultado_Llamada, COUNT(*) total
        FROM base
        GROUP BY Resultado_Llamada
    ),

    duracion AS (
        SELECT Duracion_Estimada, COUNT(*) total
        FROM base
        GROUP BY Duracion_Estimada
    ),

    planes AS (
        SELECT Plan_Mencionado, COUNT(*) total
        FROM base
        GROUP BY Plan_Mencionado
    ),

    asesores AS (
        SELECT
            Cuenta,
            COUNT(*) llamadas,
            SUM(CASE WHEN efectiva = 1.0 THEN 1 ELSE 0 END) contactadas,
            SUM(CASE WHEN Resultado_Llamada = 'Venta' THEN 1 ELSE 0 END) efectivas,
            SUM(CASE WHEN Saludo_Completo = 'Sí' THEN 1 ELSE 0 END) saludo,
            SUM(CASE WHEN Saludo_Completo IN ('Sí', 'Parcial') THEN 1 ELSE 0 END) saludo_ok,
            -- Contacto EFECTIVO real (partición que SUMA al total): se habló con la persona
            -- (Contactado + Rechazado + Venta) vs no se habló (buzón/no disp/num eq/sin contacto/sin clasif)
            SUM(CASE WHEN {CONTACTADO_SQL} THEN 1 ELSE 0 END) contactado,
            SUM(CASE WHEN {SIN_CONTACTO_SQL} THEN 1 ELSE 0 END) sin_contacto,
            CAST(ROUND(AVG(IF(dur_seg > 0, dur_seg, NULL))) AS INT64) tmo_seg
        FROM base
        GROUP BY Cuenta
    ),

    rechazos AS (
        SELECT Motivo_Rechazo, COUNT(*) total
        FROM base
        WHERE Motivo_Rechazo IS NOT NULL
        AND Motivo_Rechazo != 'N/A'
        GROUP BY Motivo_Rechazo
    )

    SELECT
        (SELECT AS STRUCT * FROM resumen) resumen,
        (SELECT AS STRUCT * FROM calidad) calidad,

        ARRAY(
            SELECT AS STRUCT *
            FROM estatus
            ORDER BY total DESC
        ) estatus,

        ARRAY(
            SELECT AS STRUCT
                IFNULL(NULLIF(TRIM(Tipo_Llamada), ''), 'Sin dirección') direccion,
                total
            FROM direccion
            ORDER BY total DESC
        ) direccion,

        ARRAY(
            SELECT AS STRUCT *
            FROM resultados
            ORDER BY total DESC
        ) resultados,

        ARRAY(
            SELECT AS STRUCT *
            FROM duracion
            ORDER BY total DESC
        ) duracion,

        ARRAY(
            SELECT AS STRUCT *
            FROM planes
            ORDER BY total DESC
        ) planes,

        ARRAY(
            SELECT AS STRUCT
                Cuenta,
                llamadas,
                contactadas,
                efectivas,
                saludo,
                saludo_ok,
                tmo_seg,
                contactado,
                sin_contacto,
                ROUND(SAFE_DIVIDE(efectivas,llamadas)*100,2) exito_pct,
                ROUND(SAFE_DIVIDE(contactadas,llamadas)*100,1) contacto_pct,
                COALESCE(ROUND(SAFE_DIVIDE(contactado,llamadas)*100,1), 0) contactado_pct,
                -- Saludo%: (Sí+Parcial) sobre las contactadas (conversación real), tope 100%
                -- COALESCE: si el asesor no tuvo ninguna llamada contactada, el cociente es
                -- NULL y el informe imprimiría "None%" (se muestra 0, que es lo real).
                COALESCE(LEAST(ROUND(SAFE_DIVIDE(saludo_ok, NULLIF(contactado,0))*100,0), 100), 0) saludo_ok_pct
            FROM asesores
            ORDER BY llamadas DESC
        ) asesores,

        ARRAY(
            SELECT AS STRUCT *
            FROM rechazos
            ORDER BY total DESC
        ) rechazos
    """

    job = client.query(query)
    # row = list(job.result())[0]
    row = dict(list(job.result())[0])

    # `or 0`: un bucket de filtro puede devolver 0 filas y entonces los agregados
    # llegan como None (el `,` de f-string y las divisiones reventarían). El SQL ya
    # trae COALESCE; esto es la segunda red de seguridad.
    total = int(row["resumen"]["total"] or 0)
    contactadas = int(row["resumen"].get("contactadas") or 0)
    ventas = int(row["resumen"].get("ventas") or 0)

    # TMO en formato legible M:SS (minutos:segundos), consistente en todo el reporte.
    # Si supera la hora, antepone las horas.
    def _fmt_tmo(seg):
        if not seg or seg <= 0:
            return "N/D"
        seg = int(seg)
        if seg >= 3600:
            return f"{seg // 3600}:{(seg % 3600) // 60:02d}:{seg % 60:02d}"
        return f"{seg // 60}:{seg % 60:02d}"

    tmo_global = _fmt_tmo(row["resumen"].get("tmo_seg"))
    participacion = row["resumen"].get("participacion_cliente") or 0

    def _pct(n):
        """Porcentaje seguro: un filtro puede dejar 0 filas (total=0) y dividir
        reventaría el formateo del contexto."""
        return (n / total * 100) if total else 0

    # Traducción de los estados crudos del marcador a etiquetas de negocio
    estatus_map = {
        "ANSWERED": "Contestada",
        "NO ANSWER": "No Contestada",
        "NOANSWER": "No Contestada",
        "BUSY": "Ocupada",
        "FAILED": "Fallida",
        "CANCEL": "Cancelada",
    }

    # Semáforos calculados en código (umbrales fijos) → deterministas y consistentes
    # entre informes. La IA solo debe copiarlos, no recalcularlos.
    tmo_seg = int(row["resumen"].get("tmo_seg") or 0)
    # TMO sin dato: el origen no trae 'Tiempo de Conversacion' para las ENTRANTES
    # (0 de 189 en la semana del 14-20 sep, 0% en todos los meses). Antes el None
    # se coercionaba a 0 y caía en la rama 🔴, comunicando "TMO malo" cuando en
    # realidad no hay nada que medir. Sin dato -> ⚪ (gris, "N/D" en el PDF), nunca rojo.
    tmo_n = int(row["resumen"].get("tmo_n") or 0)
    tmo_sin_dato = tmo_n == 0
    tmo_cubierto = 100 * tmo_n / total if total else 0
    part = participacion or 0
    contact_pct = contactadas / total * 100 if total else 0
    pv_pct = ventas / total * 100 if total else 0
    calidad = row["resumen"].get("calidad_score") or 0
    # Contacto efectivo (%): se habló con la persona (Contactado+Rechazado+Venta) / total
    ce_cont = sum(r["total"] for r in row["resultados"]
                  if r["Resultado_Llamada"] in CONTACTADO)
    ce_pct = ce_cont / total * 100 if total else 0
    sem_contact = "🔴" if contact_pct < 10 else ("🟡" if contact_pct <= 20 else "🟢")
    sem_ce = "🔴" if ce_pct < 40 else ("🟡" if ce_pct <= 60 else "🟢")
    sem_tmo = ("⚪" if tmo_sin_dato else
               "🟢" if 120 <= tmo_seg <= 240 else
               ("🟡" if (60 <= tmo_seg < 120 or 240 < tmo_seg <= 300) else "🔴"))
    sem_part = "🟢" if 40 <= part <= 60 else ("🟡" if (30 <= part < 40 or 60 < part <= 70) else "🔴")
    sem_pv = "🔴" if pv_pct < 2 else ("🟡" if pv_pct <= 5 else "🟢")
    sem_calidad = "🔴" if calidad < 30 else ("🟡" if calidad <= 60 else "🟢")

    ctx = f"""CALL CENTER CL TIENE SOLUCIONES:
    - Total llamadas (marcaciones): {total:,}
    - Llamadas de calidad (score de calidad del asesor >= 80%; NO es contacto): {contactadas:,} ({_pct(contactadas):.1f}%)
    - Contacto efectivo (se habló con la persona): {ce_cont:,} ({ce_pct:.1f}%)
"""
    if not ocultar_ventas:
        ctx += (
            "    - Posibles ventas (inferidas de la transcripción, NO es venta cerrada real): "
            f"{ventas:,} ({_pct(ventas):.2f}%)\n"
        )
    if tmo_sin_dato:
        ctx += ("    - TMO (tiempo medio de operación / conversación): N/D — NO SE PUEDE CALCULAR. "
                f"Las {total:,} llamadas de este bloque son entrantes y el archivo de origen no "
                "incluye el campo de duración. NO lo interpretes como un TMO malo ni lo compares "
                "con otros períodos: no hay dato.\n")
    else:
        ctx += (f"    - TMO (tiempo medio de operación / conversación): {tmo_global} "
                f"(promediado sobre {tmo_n:,} de {total:,} llamadas = {tmo_cubierto:.1f}% de "
                "cobertura; el resto son entrantes sin campo de duración). Cuando cites el TMO, "
                "dí siempre sobre qué llamadas se midió y NO lo presentes como el de todas.\n")
    ctx += f"""    - Participación del cliente (% de turnos hablados por el cliente): {participacion}%
    - Calidad (score 0-100, promedio de las 7 categorías sobre llamadas evaluadas): {calidad}/100

    VALORES PARA EL TABLERO (usa EXACTO estos):
    - Llamadas de calidad: {_pct(contactadas):.1f}%
    - Contacto efectivo: {ce_pct:.1f}%
    - Saludo: {row["calidad"].get("saludo") or 0}
    - Calidad: {calidad}/100

    SEMÁFOROS YA CALCULADOS (cópialos EXACTO en el Tablero de Indicadores, NO los recalcules):
    - Total llamadas: 🟢
    - Llamadas de calidad: {sem_contact}
    - Contacto efectivo: {sem_ce}
    - TMO: {sem_tmo}
    - Participación cliente: {sem_part}
    - Saludo: 🔴
    - Calidad: {sem_calidad}
"""
    if not ocultar_ventas:
        ctx += f"    - Posibles ventas: {sem_pv}\n"

    ctx += f"""
    RANGOS DEL SEMÁFORO (reprodúcelos TAL CUAL como nota/leyenda bajo el Tablero, para que el color quede justificado; NO uses los signos < ni > ):
    - Llamadas de calidad: 🟢 más de 20% · 🟡 10 a 20% · 🔴 menos de 10%
    - Contacto efectivo: 🟢 más de 60% · 🟡 40 a 60% · 🔴 menos de 40%
    - TMO: 🟢 2 a 4 min · 🟡 1 a 2 o 4 a 5 min · 🔴 menos de 1 o más de 5 min · ⚪ sin dato (el origen no trae duración para las entrantes; NO es un TMO malo)
    - Participación cliente: 🟢 40 a 60% · 🟡 30 a 40 o 60 a 70% · 🔴 menos de 30 o más de 70%
"""
    if not ocultar_ventas:
        ctx += "    - Posibles ventas: 🟢 más de 5% · 🟡 2 a 5% · 🔴 menos de 2%\n"

    ctx += """
    ESTATUS DE LLAMADAS (marcador):
    """

    for e in row.get("estatus", []):
        etiqueta = estatus_map.get(e["Estado_de_la_LLamada"], e["Estado_de_la_LLamada"])
        pct = e["total"] / total * 100 if total else 0
        ctx += f"{etiqueta}: {e['total']} ({pct:.1f}%)\n"

    # DIRECCIÓN de la llamada. Solo Entrantes/Salientes: el bucket "Sin dirección"
    # (Tipo_Llamada vacío) es un hueco del origen y se excluyó de los informes a
    # pedido del usuario — el corte que importa es Ventas vs Servicio.
    _dir = {d["direccion"]: d["total"] for d in row.get("direccion", [])}
    _ent = _dir.get("Entrante", 0)
    _sal = _dir.get("Saliente", 0)
    _otros = sorted(k for k in _dir if k not in ("Entrante", "Saliente", "Sin dirección"))
    ctx += (
        "\nDIRECCIÓN DE LAS LLAMADAS:\n"
        f"Entrantes: {_ent} ({_pct(_ent):.1f}%)\n"
        f"Salientes: {_sal} ({_pct(_sal):.1f}%)\n"
    )
    if _otros:
        ctx += "Otras: " + ", ".join(f"{k}: {_dir[k]}" for k in _otros) + "\n"

    ctx += "\nRESULTADOS:\n"
    for r in row["resultados"]:
        ctx += f"{r['Resultado_Llamada']}: {r['total']}\n"

    # Contacto EFECTIVO agregado (partición que SUMA al total de llamadas). Distinto del
    # estatus del marcador (contestada) y de la contactabilidad de calidad (efectiva).
    _cont = sum(r["total"] for r in row["resultados"]
                if r["Resultado_Llamada"] in CONTACTADO)
    _sinc = sum(r["total"] for r in row["resultados"]
                if r["Resultado_Llamada"] in SIN_CONTACTO)
    _base_ce = _cont + _sinc
    _cont_pct = _cont / _base_ce * 100 if _base_ce else 0
    ctx += (
        f"\nCONTACTO EFECTIVO (de las {total} llamadas registradas, inferido de la conversación):\n"
        f"Contactado (se habló con la persona, incluye rechazos): {_cont} ({_cont_pct:.1f}%)\n"
        f"Sin Contacto (buzón / no disponible / número equivocado / no se habló): {_sinc}\n"
    )

    ctx += "\nDURACIÓN:\n"
    for d in row["duracion"]:
        ctx += f"{d['Duracion_Estimada']}: {d['total']}\n"

    ctx += "\nPLANES:\n"
    for p in row["planes"]:
        ctx += f"{p['Plan_Mencionado']}: {p['total']}\n"

    ctx += f"""
    CALIDAD:
    Saludo: {row["calidad"].get("saludo") or 0}
    Beneficios: {row["calidad"].get("beneficios") or 0}
    WhatsApp: {row["calidad"].get("whatsapp") or 0}
    Despedida: {row["calidad"].get("despedida") or 0}
    """

    # Contacto EFECTIVO (Resultado_Llamada): Contactado = se habló con la persona;
    # Sin Contacto = buzón/no disponible/número equivocado/no se habló. Es DISTINTO de
    # 'contactadas' (=calidad efectiva) y del estatus del marcador (contestada).
    # 'Saludo%' = (Sí+Parcial)/contactadas: casi ningún saludo es 'Sí' (completo); casi todos
    # 'Parcial'. Medirlo sobre contactadas (conversación real) es lo justo, no sobre todas.
    _col_pv = "" if ocultar_ventas else " | Posibles ventas"
    ctx += f"\nASESORES (Llamadas | TMO | Contactado | Sin Contacto | %Contactado | Saludo%{_col_pv}):\n"
    for a in row["asesores"]:
        ctx += (
            f"{a['Cuenta']} | Llamadas: {a['llamadas']} | TMO: {_fmt_tmo(a['tmo_seg'])} "
            f"| Contactado: {a['contactado']} | Sin Contacto: {a['sin_contacto']} "
            f"| %Contactado: {a['contactado_pct']}% | Saludo%: {a['saludo_ok_pct']}%"
        )
        if not ocultar_ventas:
            ctx += f" | Posibles ventas: {a['efectivas']}"
        ctx += "\n"

    if row["rechazos"]:
        ctx += "\nRECHAZOS:\n"
        for r in row["rechazos"]:
            ctx += f"{r['Motivo_Rechazo']}: {r['total']}\n"

    return ctx


def get_periodo_anterior_context(where, desde, hasta):
    """Agregados clave del período ANTERIOR (mismo largo, mismos filtros salvo fechas),
    para que el reporte se lea como continuación/comparación. Devuelve '' si no hay datos."""
    query = f"""
    WITH base AS (
        SELECT
            resultado_llamada,
            efectiva,
            ARRAY_LENGTH(REGEXP_EXTRACT_ALL(IFNULL(Transcripcion_V4, ''), r'\\[Cliente\\]')) cli,
            ARRAY_LENGTH(REGEXP_EXTRACT_ALL(IFNULL(Transcripcion_V4, ''), r'\\[(?:Asesor|Cliente)\\]')) tot,
            SAFE_CAST(SPLIT(Tiempo__de_Conversacion, ':')[SAFE_OFFSET(0)] AS INT64) * 3600
              + SAFE_CAST(SPLIT(Tiempo__de_Conversacion, ':')[SAFE_OFFSET(1)] AS INT64) * 60
              + SAFE_CAST(SPLIT(Tiempo__de_Conversacion, ':')[SAFE_OFFSET(2)] AS INT64) AS dur_seg
        FROM {TABLE}
        WHERE {where}
    )
    SELECT
        COUNT(*) total,
        SUM(CASE WHEN efectiva = 1.0 THEN 1 ELSE 0 END) calidad,
        SUM(CASE WHEN resultado_llamada = 'Venta' THEN 1 ELSE 0 END) posibles_ventas,
        CAST(ROUND(AVG(IF(dur_seg > 0, dur_seg, NULL))) AS INT64) tmo_seg,
        ROUND(SAFE_DIVIDE(SUM(cli), SUM(tot)) * 100, 1) participacion
    FROM base
    """
    row = dict(list(client.query(query).result())[0])
    total = row["total"]
    if not total:
        return ""

    calidad = row["calidad"] or 0
    pv = row["posibles_ventas"] or 0
    tmo = int(row["tmo_seg"]) if row["tmo_seg"] else 0
    tmo_fmt = f"{tmo // 60}:{tmo % 60:02d}" if tmo else "N/D"

    # Solo los DATOS del período anterior. La instrucción de comparar vive en el
    # prompt (REGLA DE COMPARACIÓN ENTRE PERÍODOS), para no duplicar.
    return (
        f"\n\nPERÍODO ANTERIOR (línea base de comparación — {desde} a {hasta}):\n"
        f"- Total llamadas: {total:,}\n"
        f"- Contactabilidad (llamadas de calidad): {calidad/total*100:.1f}% ({calidad})\n"
        f"- Posibles ventas: {pv} ({pv/total*100:.2f}%)\n"
        f"- TMO: {tmo_fmt}\n"
        f"- Participación del cliente: {row['participacion']}%\n"
    )


def get_asesor_context(where, asesor=""):

    query = f"""
    WITH base AS (
        SELECT
            efectiva,
            Resultado_Llamada,
            Duracion_Estimada,
            Plan_Mencionado,
            Saludo_Completo,
            ofrecimiento_solucion,
            Ofrecio_WhatsApp,
            cierre_servicio,
            Cuenta,
            Motivo_Rechazo
        FROM {TABLE}
        WHERE {where}
        AND Cuenta LIKE @asesor
    ),

    resumen AS (
        SELECT
            COUNT(*) total,
            SUM(CASE WHEN efectiva = 1.0 THEN 1 ELSE 0 END) contactadas,
            SUM(CASE WHEN Resultado_Llamada = 'Venta' THEN 1 ELSE 0 END) ventas
        FROM base
    ),

    calidad AS (
        SELECT
            SUM(CASE WHEN Saludo_Completo = 'Sí' THEN 1 ELSE 0 END) saludo,
            SUM(CASE WHEN ofrecimiento_solucion = 1 THEN 1 ELSE 0 END) beneficios,
            SUM(CASE WHEN Ofrecio_WhatsApp = 'Sí' THEN 1 ELSE 0 END) whatsapp,
            SUM(CASE WHEN cierre_servicio = 1 THEN 1 ELSE 0 END) despedida
        FROM base
    ),

    resultados AS (
        SELECT Resultado_Llamada, COUNT(*) total
        FROM base
        GROUP BY Resultado_Llamada
    ),

    duracion AS (
        SELECT Duracion_Estimada, COUNT(*) total
        FROM base
        GROUP BY Duracion_Estimada
    ),

    planes AS (
        SELECT Plan_Mencionado, COUNT(*) total
        FROM base
        GROUP BY Plan_Mencionado
    ),

    rechazos AS (
        SELECT Motivo_Rechazo, COUNT(*) total
        FROM base
        WHERE Motivo_Rechazo IS NOT NULL
        AND Motivo_Rechazo != 'N/A'
        GROUP BY Motivo_Rechazo
    )

    SELECT
        (SELECT AS STRUCT * FROM resumen) resumen,
        (SELECT AS STRUCT * FROM calidad) calidad,

        ARRAY(
            SELECT AS STRUCT *
            FROM resultados
            ORDER BY total DESC
        ) resultados,

        ARRAY(
            SELECT AS STRUCT *
            FROM duracion
            ORDER BY total DESC
        ) duracion,

        ARRAY(
            SELECT AS STRUCT *
            FROM planes
            ORDER BY total DESC
        ) planes,

        ARRAY(
            SELECT AS STRUCT *
            FROM rechazos
            ORDER BY total DESC
        ) rechazos
    """

    job = client.query(query, job_config=bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("asesor", "STRING", f"%{asesor}%")]))
    row = dict(list(job.result())[0])

    total = int(row["resumen"]["total"] or 0)
    contactadas = int(row["resumen"].get("contactadas") or 0)
    ventas = int(row["resumen"].get("ventas") or 0)

    tasa_contacto = (contactadas / total * 100) if total else 0
    tasa_venta = (ventas / total * 100) if total else 0

    ctx = f"""
    ASESOR ANALIZADO: {asesor}

    RESUMEN:
    - Total llamadas: {total:,}
    - Llamadas de calidad (efectiva >= 80%, score de calidad del asesor; NO es contacto): {contactadas:,} ({tasa_contacto:.1f}%)
    - Posibles ventas (inferidas de la transcripción, NO es venta cerrada real): {ventas:,} ({tasa_venta:.2f}%)

    RESULTADOS:
    """

    for r in row["resultados"]:
        ctx += f"{r['Resultado_Llamada']}: {r['total']}\n"

    ctx += "\nDURACIÓN:\n"
    for d in row["duracion"]:
        ctx += f"{d['Duracion_Estimada']}: {d['total']}\n"

    ctx += "\nPLANES MENCIONADOS:\n"
    for p in row["planes"]:
        ctx += f"{p['Plan_Mencionado']}: {p['total']}\n"

    ctx += f"""
    CALIDAD (conteos de detección heurística, NO juicios: no asumas que un conteo alto es bueno ni uno bajo malo salvo que calcules una tasa sobre un denominador):
    - Saludo detectado: {row["calidad"].get("saludo") or 0}
    - Beneficios expuestos: {row["calidad"].get("beneficios") or 0}
    - Ofreció WhatsApp: {row["calidad"].get("whatsapp") or 0}
    - Despedida detectada: {row["calidad"].get("despedida") or 0}
    """

    if row["rechazos"]:
        ctx += "\nMOTIVOS DE RECHAZO:\n"
        for r in row["rechazos"]:
            ctx += f"{r['Motivo_Rechazo']}: {r['total']}\n"

    return ctx


def get_ranking_context(where="1=1", es_servicio=False):

    orden = "efectividad_pct" if es_servicio else "exito_pct"

    query = f"""
    WITH base AS (
        SELECT
            Cuenta,
            Resultado_Llamada,
            efectiva,
            Duracion_Estimada,
            Saludo_Completo,
            ofrecimiento_solucion,
            Ofrecio_WhatsApp,
            cierre_servicio
        FROM {TABLE}
        WHERE {where}
    ),

    asesores AS (
        SELECT
            Cuenta,
            COUNT(*) llamadas,
            SUM(CASE WHEN efectiva = 1.0 THEN 1 ELSE 0 END) contactadas,
            SUM(CASE WHEN Resultado_Llamada = 'Venta' THEN 1 ELSE 0 END) ventas,
            SUM(CASE WHEN Saludo_Completo = 'Sí' THEN 1 ELSE 0 END) saludo,
            SUM(CASE WHEN ofrecimiento_solucion = 1 THEN 1 ELSE 0 END) beneficios,
            SUM(CASE WHEN Ofrecio_WhatsApp = 'Sí' THEN 1 ELSE 0 END) whatsapp,
            SUM(CASE WHEN cierre_servicio = 1 THEN 1 ELSE 0 END) despedida
        FROM base
        GROUP BY Cuenta
    )

    SELECT
        Cuenta,
        llamadas,
        contactadas,
        ventas,
        ROUND(SAFE_DIVIDE(ventas,llamadas)*100,2) exito_pct,
        ROUND(SAFE_DIVIDE(contactadas,llamadas)*100,2) efectividad_pct,
        saludo,
        beneficios,
        whatsapp,
        despedida
    FROM asesores
    ORDER BY {orden} DESC
    """

    job = client.query(query)
    rows = list(job.result())

    ctx = "RANKING DE ASESORES CALL CENTER CL TIENE SOLUCIONES\n\n"

    for r in rows:
        if es_servicio:
            ctx += f"""
        ASESOR: {r.Cuenta}
        - Llamadas: {r.llamadas}
        - Llamadas de calidad (efectiva >= 80%, calidad del asesor; NO es contacto): {r.contactadas}
        - Efectividad de servicio (llamadas de calidad / llamadas): {r.efectividad_pct}%

        CALIDAD (conteos de detección heurística, NO juicios):
        - Saludo detectado: {r.saludo}
        - Gestionó la solicitud: {r.beneficios}
        - Ofreció WhatsApp: {r.whatsapp}
        - Despedida detectada: {r.despedida}
        --------------------------------
        """
        else:
            ctx += f"""
        ASESOR: {r.Cuenta}
        - Llamadas: {r.llamadas}
        - Llamadas de calidad (efectiva >= 80%, calidad del asesor; NO es contacto): {r.contactadas}
        - Posibles ventas (inferidas de la transcripción, NO es venta cerrada real): {r.ventas}
        - Tasa de posibles ventas (posibles ventas / llamadas): {r.exito_pct}%

        CALIDAD (conteos de detección heurística, NO juicios):
        - Saludo detectado: {r.saludo}
        - Beneficios expuestos: {r.beneficios}
        - Ofreció WhatsApp: {r.whatsapp}
        - Despedida detectada: {r.despedida}
        --------------------------------
        """

    return ctx


def get_search_results_context(where="1=1", search_query=""):

    query = f"""
    SELECT
        Cuenta,
        Resultado_Llamada,
        Duracion_Estimada,
        Plan_Mencionado,
        Motivo_Rechazo,
        SUBSTR(transcripcion,1,500) transcripcion
    FROM {TABLE}
    WHERE {where}
    AND transcripcion IS NOT NULL
    AND LOWER(transcripcion) LIKE @q
    LIMIT 50
    """

    job = client.query(query, job_config=bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("q", "STRING", f"%{search_query.lower()}%")]))
    rows = list(job.result())

    ctx = f"""
    BUSQUEDA EN TRANSCRIPCIONES
    Término buscado: "{search_query}"

    Resultados encontrados: {len(rows)}

    """

    for r in rows:
        ctx += f"""
        ASESOR: {r.Cuenta}
        Resultado: {r.Resultado_Llamada}
        Duración: {r.Duracion_Estimada}
        Plan mencionado: {r.Plan_Mencionado}
        Motivo rechazo: {r.Motivo_Rechazo}

        Fragmento:
        {r.transcripcion}

        --------------------------------
        """

    return ctx


def get_llamada_context(filters, llamada_id):

    where = filters.get_query() if hasattr(filters, "get_query") else "1=1"

    query = f"""
    WITH numeradas AS (
        SELECT
            ROW_NUMBER() OVER (ORDER BY fecha ASC) AS id,
            Cuenta,
            Estado_de_la_LLamada      AS estado,
            Resultado_Llamada,
            Duracion_Estimada,
            Plan_Mencionado,
            Motivo_Rechazo,
            Saludo_Completo,
            saludo_inicial,
            ofrecimiento_solucion,
            cierre_servicio,
            Ofrecio_WhatsApp,
            Transcripcion_V4
        FROM {TABLE}
        WHERE COALESCE(Transcripcion_V4, transcripcion) IS NOT NULL
        AND {where}
    )
    SELECT * FROM numeradas
    WHERE id = @llamada_id
    LIMIT 1
    """

    job = client.query(query, job_config=bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("llamada_id", "INT64", int(llamada_id))]))
    rows = list(job.result())

    if not rows:
        return "No se encontró la llamada solicitada."

    r = rows[0]

    ctx = f"""
    ANÁLISIS DE LLAMADA #{llamada_id} – CALL CENTER CL TIENE SOLUCIONES

    ASESOR: {r.Cuenta}
    ESTADO: {r.estado}
    RESULTADO: {r.Resultado_Llamada}

    DETALLES OPERATIVOS:
    - Duración estimada: {r.Duracion_Estimada}
    - Plan mencionado: {r.Plan_Mencionado}
    - Motivo de rechazo: {r.Motivo_Rechazo}

    CALIDAD DE ATENCIÓN (escala 0–1):
    - Saludo inicial (CUN): {r.saludo_inicial}
    - Saludo completo (pipeline): {r.Saludo_Completo}
    - Ofreció solución: {r.ofrecimiento_solucion}
    - Cierre del servicio: {r.cierre_servicio}
    - Ofreció WhatsApp: {r.Ofrecio_WhatsApp}

    TRANSCRIPCIÓN:
    {r.Transcripcion_V4}
    """

    return ctx


def get_raw_calls_data(where="1=1", search_query=""):
    query = f"""
    with resultado as (
        SELECT
            CAST(ROW_NUMBER() OVER() AS STRING) as id,
            *
        FROM {TABLE}
        LIMIT 20
    ) select * from resultado WHERE {where}
    """

    try:
        query_job = client.query(query)
        results = query_job.result()
        return [dict(row) for row in results]
    except Exception as e:
        print(f"Error en BigQuery raw: {e}")
        return []


def get_history(where, query_parameters=None):
    query = f"""
    WITH resultado AS (
        SELECT
            CAST(ROW_NUMBER() OVER() AS STRING) AS id,
            transcripcion
        FROM {TABLE}
        WHERE transcripcion IS NOT NULL AND LENGTH(transcripcion) > 50
    )
    SELECT * FROM resultado WHERE {where}
    LIMIT 40
    """

    job = client.query(query, job_config=bigquery.QueryJobConfig(
        query_parameters=query_parameters or []))
    results = job.result()

    transcripciones = [
        row.transcripcion[:600]
        for row in results
        if row.transcripcion is not None
    ]

    return transcripciones

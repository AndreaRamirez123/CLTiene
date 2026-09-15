from api.database import calculo_fecha
from api.chat import api_chat_logic, ChatRequest
from api.filters.transcripcion.metricas import metricas
from api.filters.transcripcion.llamadas import llamadas
from api.filters.transcripcion.llamada import llamada
from api.filters.transcripcion.historial_telefono import historial_telefono
import pandas as pd
import numpy as np

from fastapi import APIRouter

from fastapi import APIRouter, Depends

from api.models import FilterModel
from pydantic import BaseModel

from api.filters.test import test
from api.database import option, result
from api.database import client

# --- usados por los endpoints de ranking/IA (antes en routes_new.py) ---
from fastapi import Body
import json
from helpers.utils import get_history
from google.cloud import bigquery
from IA.Open_AI import call


def fetch_bigquery_data(query: str):
    return client.query(query).to_dataframe()


from api.ia.analizar_patrones_dashboard import analizar_patrones_dashboard


from api.filters.resultado_llamada import resultado_llamada
from api.filters.plan_mencionado import plan_mencionado
from api.filters.duracion_llamada import duracion_llamada
from api.filters.saludo_asesor import saludo_asesor
from api.filters.nombre_asesor import nombre_asesor
from api.filters.nombre_atencion import nombre_atencion
from api.filters.clasificacion_sentimiento import clasificacion_sentimiento
from api.filters.modulo_atencion import modulo_atencion
from api.filters.tipo_llamada import tipo_llamada
from api.filters.asistencia_mencionada import asistencia_mencionada
from api.filters.seguimiento_llamada import seguimiento_llamada

from api.charts.transcripciones import transcripciones
from api.charts.tipo_vehiculo import tipo_vehiculo
from api.charts.tipo_mascota import tipo_mascota
from api.charts.rendimiento_agente import rendimiento_agente
from api.charts.planes_mencionados import planes_mencionados
from api.charts.distribucion_resultado import distribucion_resultado
from api.charts.motivo_rechazo import motivo_rechazo
from api.charts.duraccion_efectivo import duraccion_efectivo
from api.charts.embudo_conversacion import embudo_conversacion
from api.charts.estatus_llamadas import estatus_llamadas
from api.charts.kpi import kpi

from api.ia.generar_insights import generar_insights
from api.ia.analizar_asesor import analizar_asesor
from api.ia.analizar_patrones_ventas import analizar_patrones_ventas
from api.ia.analizar_inteligencia_operativa import analizar_inteligencia_operativa
from api.ia.analizar_llamada import analizar_llamada
from api.ia.chat_inteligente import chat_inteligente
from api.ia.analisis_automatico import analisis_automatico
from api.ia.analizar_busqueda_transcripciones import analizar_busqueda_transcripciones
from api.ia.resumir_llamada import resumir_llamada
from api.ia.analisis_comparativo_ranking import analisis_comparativo_ranking
from api.ia.generar_reporte_completo import generar_reporte_completo

import dotenv
from helpers.sql import TABLE

dotenv.load_dotenv()

router = APIRouter()

# ------------------------------------------------------- #
# -------------------- Transcripcion -------------------- #
# ------------------------------------------------------- #


@router.get("/api/transcripcion/llamadas")
def api_llamadas(filters: FilterModel = Depends()):
    return llamadas(filters)


@router.get("/api/transcripcion/llamada/{id}")
def api_llamada(id: int, buscar: str | None = None, filters: FilterModel = Depends()):
    return llamada(id, buscar, filters)


@router.get("/api/transcripcion/metricas/{id}")
def api_metricas(id, filters: FilterModel = Depends()):
    return metricas(id, filters)


@router.get("/api/transcripcion/historial/{telefono}")
def api_historial_telefono(telefono: str, filters: FilterModel = Depends()):
    return historial_telefono(telefono, filters)


# ------------------------------------------------------- #
# ----------------------- Filters ----------------------- #
# ------------------------------------------------------- #
@router.get("/api/test")
def api_test(filters: FilterModel = Depends()):
    return test(filters)


@router.get("/api/resultado_llamada")
def api_resultado_llamada(filters: FilterModel = Depends()):
    return resultado_llamada(filters)


@router.get("/api/plan_mencionado")
def api_plan_mencionado(filters: FilterModel = Depends()):
    return plan_mencionado(filters)


@router.get("/api/duracion_llamada")
def api_duracion_llamada(filters: FilterModel = Depends()):
    return duracion_llamada(filters)


@router.get("/api/saludo_asesor")
def api_saludo_asesor(filters: FilterModel = Depends()):
    return saludo_asesor(filters)


@router.get("/api/nombre_asesor")
def api_nombre_asesor(filters: FilterModel = Depends()):
    return nombre_asesor(filters)


@router.get("/api/nombre_atencion")
def api_nombre_atencion(filters: FilterModel = Depends()):
    return nombre_atencion(filters)


@router.get("/api/clasificacion_sentimiento")
def api_clasificacion_sentimiento(filters: FilterModel = Depends()):
    return clasificacion_sentimiento(filters)


@router.get("/api/modulo_atencion")
def api_modulo_atencion(filters: FilterModel = Depends()):
    return modulo_atencion(filters)


@router.get("/api/tipo_llamada")
def api_tipo_llamada(filters: FilterModel = Depends()):
    return tipo_llamada(filters)


@router.get("/api/seguimiento_llamada")
def api_seguimiento_llamada(filters: FilterModel = Depends()):
    return seguimiento_llamada(filters)


@router.get("/api/distribucion_resultado")
def api_distribucion_resultado(filters: FilterModel = Depends()):
    return distribucion_resultado(filters)


@router.get("/api/asistencia_mencionada")
def api_asistencia_mencionada(filters: FilterModel = Depends()):
    return asistencia_mencionada(filters)


# -------------------------------------------------- #
# ----------------------- IA ----------------------- #
# -------------------------------------------------- #


class AnalisisAutomaticoRequest(BaseModel):
    tipo_analisis: str
    filtros: dict | None = None


@router.post("/api/chat")
async def api_chat(request: ChatRequest, filters: FilterModel = Depends()):
    return await api_chat_logic(request, filters)


@router.post("/api/busqueda_inteligente")
async def api_busqueda_inteligente(query: str | None = None, filters: FilterModel = Depends()):
    return chat_inteligente(query, filters)


# ------------------------------------------------------ #
# ----------------------- Charts ----------------------- #
# ------------------------------------------------------ #
@router.get("/api/transcripciones")
def api_transcripciones(filters: FilterModel = Depends()):
    return transcripciones(filters)


@router.get("/api/tipo_vehiculo")
def api_tipo_vehiculo(filters: FilterModel = Depends()):
    return tipo_vehiculo(filters)


@router.get("/api/tipo_mascota")
def api_tipo_mascota(filters: FilterModel = Depends()):
    return tipo_mascota(filters)


@router.get("/api/rendimiento_agente")
def api_rendimiento_agente(filters: FilterModel = Depends()):
    return rendimiento_agente(filters)


@router.get("/api/estatus_llamadas")
def api_estatus_llamadas(filters: FilterModel = Depends()):
    return estatus_llamadas(filters)


@router.get("/api/planes_mencionados")
def api_planes_mencionados(filters: FilterModel = Depends()):
    return planes_mencionados(filters)


@router.get("/api/distribucion_resultado")
def api_distribucion_resultado(filters: FilterModel = Depends()):
    return distribucion_resultado(filters)


@router.get("/api/motivo_rechazo")
def api_motivo_rechazo(filters: FilterModel = Depends()):
    return motivo_rechazo(filters)


@router.get("/api/duraccion_efectivo")
def api_duraccion_efectivo(filters: FilterModel = Depends()):
    return duraccion_efectivo(filters)


@router.get("/api/embudo_conversacion")
def api_embudo_conversacion(filters: FilterModel = Depends()):
    return embudo_conversacion(filters)


@router.get("/api/kpi")
def api_kpi(filters: FilterModel = Depends()):
    return kpi(filters)


@router.get("/ia/generar_insights")
def api_generar_insights(filters: FilterModel = Depends()):
    return generar_insights(filters)


@router.get("/ia/analizar_asesor")
def api_analizar_asesor(asesor: str, filters: FilterModel = Depends()):
    return analizar_asesor(filters, asesor)


@router.get("/ia/inteligencia_operativa")
def api_inteligencia_operativa(filters: FilterModel = Depends()):
    return analizar_inteligencia_operativa(filters)


@router.get("/ia/analizar_llamada")
def api_analizar_llamada(llamada_id: str, filters: FilterModel = Depends()):
    return analizar_llamada(filters, llamada_id)


# @router.post("/ia/chat_inteligente")
# def api_chat_inteligente(pregunta: str | None = None, filters: FilterModel = Depends()):
#     return chat_inteligente(pregunta, filters)


@router.get("/ia/analisis_automatico")
def api_analisis_automatico(tipo_analisis: str, filters: FilterModel = Depends()):
    return analisis_automatico(filters, tipo_analisis)


@router.get("/ia/busqueda_transcripciones")
def api_busqueda_transcripciones(search_query: str, filters: FilterModel = Depends()):
    return analizar_busqueda_transcripciones(filters, search_query)


@router.get("/ia/resumir_llamada")
def api_resumir_llamada(asesor: str, filters: FilterModel = Depends()):
    return resumir_llamada(filters, asesor)


@router.get("/ia/analisis_ranking")
def api_analisis_ranking(filters: FilterModel = Depends()):
    return analisis_comparativo_ranking(filters)


@router.get("/ia/reporte_completo")
def api_reporte_completo(filters: FilterModel = Depends()):
    return generar_reporte_completo(filters)


@router.get("/limite-fecha")
def limite_fecha():
    job = client.query(f"""
        SELECT
            FORMAT_DATE('%Y-%m-%d', DATE(MIN({calculo_fecha()}))) AS primera_fecha,
            FORMAT_DATE('%Y-%m-%d', DATE(MAX({calculo_fecha()}))) AS ultima_fecha
        FROM {TABLE}
        WHERE Fecha IS NOT NULL
    """)
    row = list(job.result())[0]
    return {"primera_fecha": row.primera_fecha, "ultima_fecha": row.ultima_fecha}


# -------------------------------------------------- #
# ----------------------- IA ----------------------- #
# -------------------------------------------------- #


@router.get("/rendimiento-hora")
def x_rendimiento_hora(filters: FilterModel = Depends()):

    where = filters.get_query() or "1=1"

    query = f"""
    SELECT
    LPAD (
        CAST(
        EXTRACT(
            HOUR
            FROM
            {calculo_fecha()}
        ) AS STRING
        ),
        2,
        '0'
    ) name,
    COUNT(*) t,
    SUM(CAST(efectiva AS FLOAT64)) efectivas
    FROM
    {TABLE}
    WHERE {where}
    GROUP BY
    name
    ORDER BY
    name
    """

    job = client.query(query)
    df = job.to_dataframe()

    # % de efectividad (score de calidad de la CUN) por hora, no ventas
    df["ef"] = (df["efectivas"] / df["t"] * 100).round(1)

    return df[["name", "t", "ef"]].to_dict(orient="records")


# api/routes/inteligencia.py


@router.get("/rendimiento-dia")
def x_rendimiento_dia(filters: FilterModel = Depends()):

    where = filters.get_query()

    query = f"""
    SELECT
        FORMAT_DATE(
            '%A',
            DATE({calculo_fecha()})
        ) name,
        COUNT(*) t,
        SUM(CAST(efectiva AS FLOAT64)) efectivas
    FROM {TABLE}
    WHERE {where}
    GROUP BY name
    """

    job = client.query(query)
    df = job.to_dataframe()

    # % de efectividad (score de calidad) por día, no ventas
    df["ef"] = (
        (df["efectivas"] / df["t"] * 100)
        .replace([float("inf"), -float("inf")], 0)
        .fillna(0)
        .round(1)
    )

    # Reemplazar inf y -inf
    df = df.replace([np.inf, -np.inf], None)

    # Convertir NaN, NA y NaT a None
    df = df.where(pd.notnull(df), None)

    # Convertir columnas a tipos Python estándar
    df = df.astype(object)

    result = df[["name", "t", "ef"]].to_dict(orient="records")

    return result


@router.get("/ventas-vs-servicio")
def ventas_vs_servicio(filters: FilterModel = Depends()):

    where = filters.get_query()

    query = f"""
    SELECT
        tipo name,
        COUNT(*) total,
        SUM(CASE WHEN resultado_llamada = 'Venta' THEN 1 ELSE 0 END) efectivas
    FROM {TABLE}
    WHERE {where}
    GROUP BY tipo
    """

    job = client.query(query)
    df = job.to_dataframe()

    return df[["name", "total", "efectivas"]].to_dict(orient="records")


@router.get("/subjetividad-confianza-modulo")
def subjetividad_confianza_modulo(filters: FilterModel = Depends()):

    where = filters.get_query()

    query = f"""
    SELECT
        Nombre_del_Modulo name,
        AVG(subjectivity) x,
        AVG(confianza) y
    FROM {TABLE}
    WHERE {where}
    GROUP BY Nombre_del_Modulo
    """

    job = client.query(query)
    df = job.to_dataframe()

    colores = {"CRM": "#10b981", "ASISTENCIA": "#e11d48"}

    df["color"] = df["name"].map(colores).fillna("#94a3b8")

    return df[["x", "y", "name", "color"]].to_dict(orient="records")


@router.get("/desempeno-sentimiento-asesor")
def desempeno_sentimiento_asesor(filters: FilterModel = Depends()):

    where = filters.get_query()

    query = f"""
    WITH base AS (
        SELECT
            Cuenta,
            clasificacion
        FROM {TABLE}
        WHERE {where}
    ),

    agg AS (
        SELECT
            Cuenta,
            COUNTIF(clasificacion = 'negativo') neg,
            COUNTIF(clasificacion = 'neutro') neu,
            COUNTIF(clasificacion = 'positivo') pos,
            COUNT(*) total
        FROM base
        GROUP BY Cuenta
    )

    SELECT
        Cuenta n,
        SAFE_DIVIDE(neg,total)*100 negativo,
        SAFE_DIVIDE(neu,total)*100 neutro,
        SAFE_DIVIDE(pos,total)*100 positivo
    FROM agg
    ORDER BY total DESC
    """

    job = client.query(query)
    df = job.to_dataframe()

    return df.fillna(0).to_dict(orient="records")


@router.get("/evolucion-ventas")
def evolucion_ventas(filters: FilterModel = Depends()):

    where = filters.get_query()

    query = f"""
    WITH base AS (
        SELECT
            DATE_TRUNC(
                DATE({calculo_fecha()}),
                WEEK(MONDAY)
            ) semana,
            resultado_llamada
        FROM {TABLE}
        WHERE {where}
    )

    SELECT
        semana fecha,
        COUNT(*) llamadas,
        SUM(CASE WHEN resultado_llamada = 'Venta' THEN 1 ELSE 0 END) posibles_ventas
    FROM base
    GROUP BY semana
    ORDER BY semana
    """

    job = client.query(query)
    df = job.to_dataframe()

    df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")
    df["fecha"] = df["fecha"].dt.strftime("%b %d")

    df = df.replace([float("inf"), -float("inf")], None)
    df = df.where(pd.notnull(df), None)

    return df.to_dict(orient="records")


@router.get("/scorecard-asesores")
def scorecard_asesores(filters: FilterModel = Depends()):

    where = filters.get_query()

    query = f"""
    SELECT
        Cuenta nombre,
        COUNT(*) total,
        SUM(CAST(efectiva AS FLOAT64)) ventas,
        ROUND(
            SAFE_DIVIDE (SUM(CAST(efectiva AS FLOAT64)), COUNT(*)) * 100,
            1
        ) efectividad,
        ROUND(AVG(CAST(palabras AS FLOAT64)) / 15, 1) turnosAsesor,
        ROUND(AVG(CAST(palabras AS FLOAT64)) / 20, 1) turnosCliente,
        ROUND(AVG(CAST(palabras AS FLOAT64)), 0) palabras,
        ROUND(AVG(CAST(saludo_inicial AS FLOAT64)) * 100, 1) saludo,
        ROUND(AVG(CAST(identificacion_cliente AS FLOAT64)) * 100, 1) identificacion,
        ROUND(AVG(CAST(comprension_problema AS FLOAT64)) * 100, 1) comprension,
        ROUND(AVG(CAST(ofrecimiento_solucion AS FLOAT64)) * 100, 1) ofrecimiento,
        ROUND(AVG(CAST(manejo_inquietudes AS FLOAT64)) * 100, 1) manejo,
        ROUND(AVG(CAST(cierre_servicio AS FLOAT64)) * 100, 1) cierre,
        ROUND(AVG(CAST(proximo_paso AS FLOAT64)) * 100, 1) paso
    FROM
        {TABLE}
    WHERE {where}
    GROUP BY
        Cuenta
    ORDER BY
        efectividad DESC
    """

    job = client.query(query)
    df = job.to_dataframe()

    return df.to_dict(orient="records")


@router.get("/duracion-vs-efectividad")
def duracion_vs_efectividad(filters: FilterModel = Depends()):

    where = filters.get_query()

    query = f"""
    SELECT
        duracion_estimada name,
        COUNT(*) total,
        ROUND(
            SAFE_DIVIDE(
                SUM(CAST(efectiva AS FLOAT64)),
                COUNT(*)
            ) * 100,1
        ) efectividad
    FROM {TABLE}
    WHERE {where}
    GROUP BY duracion_estimada
    """

    job = client.query(query)
    df = job.to_dataframe()

    return df[["name", "total", "efectividad"]].to_dict(orient="records")


@router.get("/clasificacion-sentimiento")
def x_clasificacion_sentimiento(filters: FilterModel = Depends()):

    where = filters.get_query()

    query = f"""
    SELECT
        clasificacion AS name,
        COUNT(*) AS value
    FROM {TABLE}
    WHERE {where} and clasificacion IS NOT NULL
    GROUP BY clasificacion
    ORDER BY value DESC
    """

    job = client.query(query)
    df = job.to_dataframe()

    return df[["name", "value"]].to_dict(orient="records")


@router.get("/duracion_llamadas")
def api_duracion_llamadas(filters: FilterModel = Depends()):

    where = filters.get_query()

    query = f"""
    SELECT
        Duracion_Estimada as label,
        COUNT(*) as valor,
        CAST(AVG(
            SAFE.TIME_DIFF(
                SAFE.PARSE_TIME('%H:%M:%S', REGEXP_EXTRACT(Tiempo__de_Llamada, r'\\d+:\\d+:\\d+')),
                TIME '00:00:00',
                SECOND
            )
        ) AS INT64) as segundos_promedio
    FROM {TABLE}
    WHERE {where}
    GROUP BY Duracion_Estimada
    """

    job = client.query(query)
    rows = list(job.result())

    colores = {
        "Buzón": "#EE7553",
        "Muy Corta": "#EC635F",
        "Corta": "#EB526A",
        "Media": "#E94176",
        "Larga": "#E83081",
    }

    total = sum(r.valor for r in rows)

    def fmt_segundos(seg):
        if seg is None:
            return None
        m, s = divmod(int(seg), 60)
        return f"{m}m {s:02d}s" if m else f"{s}s"

    data = []

    for r in rows:
        data.append(
            {
                "label": r.label,
                "valor": r.valor,
                "porcentaje": f"{(r.valor/total)*100:.1f}%",
                "color": colores.get(r.label, "#8884d8"),
                "tiempo_promedio": fmt_segundos(r.segundos_promedio),
            }
        )

    return data


@router.get("/analisis-patrones")
def analisis_patrones(filters: FilterModel = Depends()):
    return analizar_patrones_dashboard(filters)


@router.get("/limite-fecha")
def limite_fecha():
    return result(
        f"""
        SELECT 
        date(min(fecha)) primera_fecha,
        date(max(fecha)) ultima_fecha,
        FROM {TABLE}
        """
    )


@router.get("/api/lista_llamadas")
def api_lista_llamadas(filters: FilterModel = Depends()):

    where = filters.get_query()

    return option(
        f"""
    SELECT
        ROW_NUMBER() OVER (ORDER BY fecha ASC) AS id,
        Resultado_Llamada,
        Duracion_Estimada,
        Telefono,
        Cuenta
    FROM {TABLE}
    WHERE {where}
    AND transcripcion IS NOT NULL
    """,
        "id",
        "concat('#', id, ' | ', Resultado_Llamada, ' | ', Duracion_Estimada, ' | ', Telefono, ' | ', Cuenta)",
    )


# ══════════════════════════════════════════════════════════════════════════
# Endpoints de ranking / IA (antes en routes_new.py, montados bajo /api).
# ══════════════════════════════════════════════════════════════════════════

@router.post("/api/analisis_automatico")
async def generar_reporte_ia(payload: dict = Body(...)):
    try:
        query = f"""
            SELECT cuenta, Resultado_Llamada, transcripcion
            FROM {TABLE}
            WHERE transcripcion IS NOT NULL AND length(transcripcion) > 100
            LIMIT 10
        """
        df = fetch_bigquery_data(query)

        texto_contexto = ""
        for _, row in df.iterrows():
            texto_contexto += f"Asesor: {row['cuenta']} | Resultado: {row['Resultado_Llamada']} | Transcripción: {row['transcripcion'][:300]}...\n\n"

        contenido, error = call(
            "Eres un Consultor de Calidad en Call Center. Responde únicamente en JSON.",
            f"Analiza estas llamadas y genera un JSON con exactamente estas 3 llaves: 'resumen' (string), 'hallazgos' (array de strings, cada elemento es una frase), 'recomendaciones' (array de strings, cada elemento es una frase). NO uses objetos dentro de los arrays, solo strings. Datos: {texto_contexto}",
            response_format={"type": "json_object"},
        )
        if error:
            return {"resultado": None, "error": error}

        return {"resultado": json.loads(contenido)}
    except Exception as e:
        return {"resultado": None, "error": str(e)}


@router.get("/api/resumir_llamada/{id}")
async def resumir_llamada(id: str):

    llamada_data = get_history("id = @id", [bigquery.ScalarQueryParameter("id", "STRING", id)])

    system_prompt = """
    Eres un analista experto en calidad de llamadas de servicio al cliente.
    Analiza conversaciones y genera evaluaciones claras y estructuradas.
    """

    user_prompt = f"""
    Analiza la siguiente transcripción de llamada de servicio al cliente:

    {llamada_data}

    Responde ESTRICTAMENTE en formato JSON con esta estructura:

    {{
        "info": {{
            "resultado": "Breve resumen de la llamada",
            "aciertos": ["Punto positivo 1", "Punto positivo 2"],
            "errores": ["Punto a mejorar 1", "Punto a mejorar 2"],
            "scorecard": {{
                "Saludo": 100,
                "Empatía": 80,
                "Resolución": 90,
                "Cierre": 70
            }}
        }},
        "chat": [
            {{"role": "Asesor", "text": "texto"}},
            {{"role": "Cliente", "text": "texto"}}
        ]
    }}

    No incluyas explicaciones adicionales.
    No uses markdown.
    Devuelve solo JSON válido.
    """

    respuesta, error = call(system_prompt, user_prompt)

    if error:
        return {"error": error}

    try:
        return json.loads(respuesta)
    except Exception:
        return {
            "error": "La IA devolvió un JSON inválido",
            "raw": respuesta
        }


@router.get("/api/ranking_ia")
async def ranking_ia():
    try:
        query = f"""
            SELECT cuenta,
                   AVG(saludo_inicial) * 100 as score_promedio,
                   COUNT(*) as total_llamadas
            FROM {TABLE}
            GROUP BY cuenta
            ORDER BY score_promedio DESC
            LIMIT 5
        """
        df = fetch_bigquery_data(query)
        ranking = df.to_dict(orient="records")
        return {"resultado": ranking}
    except Exception as e:
        return {"resultado": None, "error": str(e)}


@router.post("/api/chat_asistente")
async def chat_asistente(payload: dict = Body(...)):
    pregunta = payload.get("pregunta")
    try:
        contenido, error = call(
            "Eres un asistente de soporte para el dashboard de Call Center.",
            pregunta,
        )
        if error:
            return {"error": error}
        return {"respuesta": contenido}
    except Exception as e:
        return {"error": str(e)}


@router.get("/api/ranking_asesores")
async def ranking_asesores(filters: FilterModel = Depends()):
    try:
        where = filters.get_query() or "1=1"
        query = f"""
            SELECT
                cuenta as nombre,
                COUNT(*) as llamadas,
                SUM(CASE WHEN Resultado_Llamada = 'Venta' THEN 1 ELSE 0 END) as ventas,
                ROUND(AVG(saludo_inicial) * 100) as puntos
            FROM {TABLE}
            WHERE {where}
            GROUP BY cuenta
            ORDER BY puntos DESC
            LIMIT 10
        """
        df = fetch_bigquery_data(query)

        ranking = []
        for index, row in df.iterrows():
            ranking.append({
                "posicion": index + 1,
                "nombre": row['nombre'],
                "llamadas": int(row['llamadas']),
                "ventas": int(row['ventas']),
                "puntos": int(row['puntos'])
            })
        return ranking
    except Exception as e:
        print(f"Error en ranking_asesores: {e}")
        return []


@router.post("/api/analisis_ranking_ia")
async def analisis_ranking_ia(payload: dict = Body(...)):
    asesores = payload.get("asesores", [])
    try:
        if not asesores:
            return {"resultado": {"analisis_top": "", "mejoras": [], "mentoria": ""}}

        contexto = "\n".join([
            f"Asesor: {a['nombre']} | Posición: #{a['posicion']} | Puntos: {a['puntos']} | Ventas: {a['ventas']} | Llamadas: {a['llamadas']}"
            for a in asesores
        ])

        contenido, error = call(
            (
                "Eres un experto en Call Center. Tu respuesta DEBE ser un JSON con 3 llaves estrictas:\n"
                "1. 'analisis_top': Un string con el Informe del TOP 3, justificaciones y '¿Qué hacen bien?'.\n"
                "2. 'mejoras': Una LISTA DE STRINGS (Array) donde cada elemento sea un hallazgo o análisis individual.\n"
                "3. 'mentoria': Un string con Brechas, Plan de Mentoría, Metas a 30 días y Perfil Ganador.\n"
                "IMPORTANTE: 'mejoras' debe ser siempre una lista []. Usa emojis y Markdown."
            ),
            f"Genera el informe detallado para estos datos:\n{contexto}",
            response_format={"type": "json_object"},
        )
        if error:
            return {"resultado": {"analisis_top": "Error", "mejoras": ["Error al procesar"], "mentoria": error}}

        data = json.loads(contenido)

        if not isinstance(data.get("mejoras"), list):
            data["mejoras"] = [str(data.get("mejoras", ""))]

        return {"resultado": data}

    except Exception as e:
        print(f"Error crítico: {e}")
        return {"resultado": {"analisis_top": "Error", "mejoras": ["Error al procesar"], "mentoria": str(e)}}

from api.database import result
from api.models import FilterModel
from helpers.sql import TABLE


def rendimiento_agente(filters: FilterModel):
    return result(f"""
    SELECT
        cuenta AS n,
        COUNT(*) AS llamadas,
        ROUND(AVG(
            CAST((LENGTH(IFNULL(Transcripcion_V4,'')) - LENGTH(REPLACE(IFNULL(Transcripcion_V4,''), '[Asesor]:', ''))) / 9 AS INT64)
        ), 1) AS turnos,
        ROUND(AVG(
            IF(Saludo_Completo = "Sí", 25, 0) +
            IF(ofrecimiento_solucion = 1, 25, 0) +
            IF(Ofrecio_WhatsApp = "Sí", 20, 0) +
            IF(cierre_servicio = 1, 20, 0) +
            IF(Duracion_Estimada IN ('Media', 'Larga'), 10, 0) +
            IF(Duracion_Estimada = "Corta", 5, 0)
        ), 1) AS score_calidad,
        ROUND(SAFE_DIVIDE(SUM(efectiva), COUNT(*)) * 100, 2) AS contacto_pct,
        ROUND(SAFE_DIVIDE(COUNTIF(Resultado_Llamada IN ('Contactado', 'Rechazado', 'Venta')), COUNT(*)) * 100, 2) AS contacto_efectivo,
        ROUND(SAFE_DIVIDE(COUNTIF(Resultado_Llamada = 'Venta'), COUNT(*)) * 100, 2) AS tasa_venta,
        -- TMO (tiempo hablado promedio) en segundos; solo llamadas con tiempo > 0
        CAST(ROUND(AVG(IF(
            SAFE_CAST(SPLIT(Tiempo__de_Conversacion, ':')[SAFE_OFFSET(0)] AS INT64) * 3600
              + SAFE_CAST(SPLIT(Tiempo__de_Conversacion, ':')[SAFE_OFFSET(1)] AS INT64) * 60
              + SAFE_CAST(SPLIT(Tiempo__de_Conversacion, ':')[SAFE_OFFSET(2)] AS INT64) > 0,
            SAFE_CAST(SPLIT(Tiempo__de_Conversacion, ':')[SAFE_OFFSET(0)] AS INT64) * 3600
              + SAFE_CAST(SPLIT(Tiempo__de_Conversacion, ':')[SAFE_OFFSET(1)] AS INT64) * 60
              + SAFE_CAST(SPLIT(Tiempo__de_Conversacion, ':')[SAFE_OFFSET(2)] AS INT64),
            NULL))) AS INT64) AS tmo_seg,
        CONCAT('#', FORMAT('%06X', CAST(FLOOR(RAND() * 16777215) AS INT64))) AS color

    FROM
        {TABLE}
    WHERE {filters.get_query()}
    GROUP BY
        cuenta
    ORDER BY
        cuenta
    """)
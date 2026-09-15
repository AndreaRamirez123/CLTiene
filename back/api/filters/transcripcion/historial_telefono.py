from api.database import result
from api.models import FilterModel
from helpers.sql import TABLE
from google.cloud import bigquery


def historial_telefono(telefono: str, filters: FilterModel = None):
    # El historial telefónico reúne llamadas de cualquier asesor; solo respeta
    # los filtros temporales para mantener el contexto del período seleccionado.
    historial_filters = filters.model_copy(update={"nombre_asesor": None}) if filters else None
    filtro_query = historial_filters.get_query() if historial_filters else "TRUE"
    return result(
        f"""
        WITH todos AS (
            SELECT
                ROW_NUMBER() OVER (ORDER BY Fecha ASC) AS id_global,
                Fecha,
                Resultado_Llamada,
                Cuenta,
                Tiempo__de_Conversacion,
                Duracion_Estimada,
                Telefono,
                COALESCE(Transcripcion_V4, transcripcion) AS transcripcion_text
            FROM {TABLE}
                        WHERE COALESCE(Transcripcion_V4, transcripcion) IS NOT NULL
                            AND {filtro_query}
        )
        SELECT
            id_global AS id,
            FORMAT_DATETIME('%Y-%m-%d %H:%M', DATETIME(TIMESTAMP_MICROS(DIV(Fecha, 1000)))) AS fecha,
            IFNULL(Resultado_Llamada, '-') AS resultado,
            IFNULL(Cuenta, '-') AS asesor,
            IFNULL(Tiempo__de_Conversacion, '-') AS duracion,
            IFNULL(Duracion_Estimada, '-') AS duracion_est,
            CASE WHEN transcripcion_text IS NOT NULL AND transcripcion_text != '' THEN TRUE ELSE FALSE END AS tiene_transcripcion
        FROM todos
        WHERE CAST(CAST(Telefono AS INT64) AS STRING) = @telefono
        ORDER BY Fecha ASC
        """,
        [bigquery.ScalarQueryParameter("telefono", "STRING", str(telefono).strip())],
    )

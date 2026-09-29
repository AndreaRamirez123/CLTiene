"""
Lógica de procesamiento de transcripciones extraída del notebook.
Conecta a SQL Server, procesa y sube a BigQuery.
"""

import os
import re
import pandas as pd
from sqlalchemy import create_engine, text
from google.cloud import bigquery


# ─── Configuración ─────────────────────────────────────────────────────────────

SQL_HOST     = os.getenv("SQL_HOST", "172.16.1.33")
SQL_PORT     = os.getenv("SQL_PORT", "1433")
SQL_DATABASE = os.getenv("SQL_DATABASE", "CUN_REPOSITORIO")
SQL_USER     = os.getenv("SQL_USER", "")
SQL_PASSWORD = os.getenv("SQL_PASSWORD", "")

BQ_PROJECT = os.getenv("CLOUD_PROJECT", "desarrollo-investigaciones")
BQ_DATASET = "call_center"
BQ_TABLA   = "cltiene_llamadas_procesadas"


# ─── Conexión SQL Server ────────────────────────────────────────────────────────

def conectar_y_cargar():
    url = (
        f"mssql+pymssql://{SQL_USER}:{SQL_PASSWORD}"
        f"@{SQL_HOST}:{SQL_PORT}/{SQL_DATABASE}"
    )
    engine = create_engine(url)

    sql_query = text("""
        SELECT
            TRY_CONVERT(datetime, b.Fecha, 120) AS Fecha,
            b.[Contacto (Identificacion - Nombre],
            b.[Telefono],
            b.[Agente],
            b.[Cuenta],
            b.[Modulo],
            b.[Nombre del Modulo],
            b.[Motivo],
            b.[Estado de la LLamada],
            b.[Tiempo  de Llamada],
            b.[Tiempo  de Conversacion],
            b.[Estado de Registro],
            b.[Estado de Gestion],
            b.[Calificacion de la Llamada],
            b.[Direccion grabacion#1],
            b.[Direccion grabacion#2],
            b.[Direccion grabacion#3],
            b.[Direccion grabacion#4],
            b.[Direccion grabacion#5],
            b.[Direccion grabacion#6],
            b.[Direccion grabacion#7],
            b.[Comentario],
            b.[archivo],
            b.[saludo_inicial],
            b.[identificacion_cliente],
            b.[comprension_problema],
            b.[ofrecimiento_solucion],
            b.[manejo_inquietudes],
            b.[cierre_servicio],
            b.[proximo_paso],
            b.[efectiva],
            b.[polarity],
            b.[subjectivity],
            b.[clasificacion],
            b.[confianza],
            b.[palabras],
            b.[IDENTIFICACION],
            b.[fecha_carga],
            b.[transcripcion],
            b.[tipo] AS tipo
        FROM CUN_REPOSITORIO.coe.CLTIENE_LLAMADAS b
        WHERE TRY_CONVERT(datetime, b.Fecha, 120) IS NOT NULL
    """)

    with engine.connect() as conn:
        df = pd.read_sql_query(sql_query, conn)

    return df


# ─── Categorización ─────────────────────────────────────────────────────────────

def detectar_duracion_estimada(texto):
    if pd.isna(texto) or not texto:
        return "Sin Datos"
    n = len(str(texto).strip())
    if n < 50:    return "Buzón"
    if n < 200:   return "Muy Corta"
    if n < 500:   return "Corta"
    if n < 1500:  return "Media"
    return "Larga"


def detectar_plan(texto):
    if pd.isna(texto) or not texto:
        return "Sin transcripción"
    tl = str(texto).lower()
    planes = []
    if re.search(r'(?:plan\s+)?manad[aá]|plan\s+maná', tl):              planes.append("Plan Manada")
    if re.search(r'(?:plan\s+)?premium', tl):                             planes.append("Plan Premium")
    if re.search(r'mascota|perrit|gatit|perro|gato|veterinari|desparasita|chip\s+de\s+identificaci|refuerzo\s+de\s+vacunas|cremaci|limpieza\s+dental', tl):
        planes.append("Plan Mascotas")
    if re.search(r'salud|m[eé]dico\s+a\s+domicilio|pediatra|videollamada\s+con\s+m[eé]dico|orientaci[oó]n\s+m[eé]dica|psic[oó]logo\s+a\s+domicilio|acompa[nñ]ante\s+a\s+citas|urgencia\s+dental', tl):
        planes.append("Plan Salud")
    if re.search(r'movilidad|gr[uú]a|veh[ií]cul|\bcarro\b|\bmoto\b|cambio\s+de\s+llanta|reinicio\s+de\s+bater|conductor\s+elegido|cerrajer[ií]a\s+vial|paso\s+de\s+corriente', tl):
        planes.append("Plan Movilidad")
    if not planes:
        return "No identificado"
    for esp in ["Plan Manada", "Plan Premium"]:
        if esp in planes:
            return esp
    return planes[0]


def detectar_saludo_completo(texto):
    if pd.isna(texto) or not texto: return "No"
    tl = str(texto).lower()
    comp = sum([
        bool(re.search(r'tengo\s+el\s+gusto', tl)),
        bool(re.search(r'habl[aá]s?\s+con|me\s+llamo|soy\s+\w+\s+(?:de|desde)', tl)),
        bool(re.search(r'(?:cl[e ])?tiene\s*soluciones|cle[\s-]?cn', tl)),
        bool(re.search(r'registro\s+que\s+(?:hiciste|realizaste|hizo)|me\s+(?:estoy\s+)?comunic', tl)),
    ])
    if comp >= 3: return "Sí"
    if comp >= 1: return "Parcial"
    return "No"


def detectar_explico_beneficios(texto):
    if pd.isna(texto) or not texto: return "No"
    tl = str(texto).lower()
    patrones = [r'beneficios?\b', r'servicio\s+de\s+gr[uú]a', r'videollamada',
                r'cobertura\s+(?:a\s+nivel\s+)?nacional', r'conductor\s+elegido',
                r'cambio\s+de\s+llanta', r'reinicio\s+de\s+bater', r'asistencia\s+(?:24|las\s+24)',
                r'veterinari[oa]', r'cremaci[oó]n', r'vacunaci[oó]n']
    n = sum(1 for p in patrones if re.search(p, tl))
    if n >= 3: return "Sí"
    if n >= 1: return "Parcial"
    return "No"


def detectar_ofrecio_whatsapp(texto):
    if pd.isna(texto) or not texto: return "No"
    tl = str(texto).lower()
    if re.search(r'(?:te\s+)?(?:env[ií]o|mando|dejo)\s+(?:un\s+)?(?:mensaje|mensajito|informaci[oó]n)?\s*(?:por\s+)?whatsapp', tl): return "Sí"
    if re.search(r'por\s+whatsapp\s+(?:te|le)\s+(?:env[ií]o|mando|escribo)', tl): return "Sí"
    if re.search(r'whatsapp.*(?:env[ií]o|mando|escribo|informaci[oó]n)', tl): return "Sí"
    return "No"


def detectar_resultado_llamada(texto):
    if pd.isna(texto) or not texto: return "Sin Contacto"
    tl = str(texto).lower()
    n = len(str(texto).strip())
    if n < 50: return "Sin Contacto"
    if re.search(r'buz[oó]n\s+de\s+voz|correo\s+de\s+voz|deje\s+su\s+mensaje', tl): return "Buzón de Voz"
    if re.search(r'n[uú]mero\s+equivocado|no\s+(?:es\s+)?aqu[ií]|no\s+(?:lo\s+)?conozco|no\s+vive\s+aqu[ií]', tl): return "Número Equivocado"
    if re.search(r'no\s+se\s+encuentra|est[aá]\s+ocupad|llame\s+m[aá]s\s+tarde|no\s+puede\s+atender', tl): return "No Disponible"
    if re.search(r'procedemos|te\s+confirmo|queda\s+activ|te\s+env[ií]o\s+(?:la\s+)?informaci[oó]n', tl): return "Venta"
    if re.search(r's[ií]\s+(?:me\s+)?interesa|cu[eé]ntame\s+m[aá]s|env[ií]ame|quiero\s+(?:saber|informaci)', tl):
        if not re.search(r'no\s+(?:me\s+)?interesa|no\s+gracias', tl): return "Interesado"
    if re.search(r'no\s+(?:me\s+)?interesa|no[\s,]+(?:no[\s,]+)?gracias|no\s+estoy\s+interesad', tl): return "Rechazado"
    return "Contactado"


def detectar_motivo_rechazo(texto, resultado):
    if resultado != "Rechazado": return "N/A"
    if pd.isna(texto) or not texto: return "Sin Motivo"
    tl = str(texto).lower()
    if re.search(r'ya\s+tengo|ya\s+cuento\s+con', tl): return "Ya Tiene Servicio"
    if re.search(r'muy\s+caro|costoso|no\s+tengo\s+(?:plata|dinero)', tl): return "Precio"
    if re.search(r'yo\s+no\s+(?:hice|registr[eé])|no\s+(?:hice|realic[eé])\s+(?:ning[uú]n\s+)?registro', tl): return "No Recuerda Registro"
    if re.search(r'no\s+tengo\s+(?:mascota|perro|gato|carro|moto|veh[ií]culo)', tl): return "No Aplica Servicio"
    return "No Interesa"


def sanitizar_columnas(df):
    df = df.copy()
    df.columns = [re.sub(r'[^\w]', '_', col).strip('_') for col in df.columns]
    return df


# ─── Procesamiento principal ────────────────────────────────────────────────────

def procesar_dataframe(df, log=print):
    log(f"Filas cargadas: {len(df)}")

    # El origen trae 'venta' y 'servicios' como variantes de 'ventas'/'servicio'.
    df['tipo'] = df['tipo'].str.strip().str.lower().replace({'venta': 'ventas', 'servicios': 'servicio'})

    log("Detectando resultado de llamada...")
    df['Resultado_Llamada'] = df['transcripcion'].apply(detectar_resultado_llamada)

    log("Detectando motivo de rechazo...")
    df['Motivo_Rechazo'] = df.apply(
        lambda r: detectar_motivo_rechazo(r['transcripcion'], r['Resultado_Llamada']), axis=1
    )

    log("Detectando plan mencionado...")
    df['Plan_Mencionado'] = df['transcripcion'].apply(detectar_plan)

    log("Calculando duración estimada...")
    df['Duracion_Estimada'] = df['transcripcion'].apply(detectar_duracion_estimada)

    log("Evaluando calidad del asesor...")
    df['Saludo_Completo']    = df['transcripcion'].apply(detectar_saludo_completo)
    df['Explico_Beneficios'] = df['transcripcion'].apply(detectar_explico_beneficios)
    df['Ofrecio_WhatsApp']   = df['transcripcion'].apply(detectar_ofrecio_whatsapp)

    log("Procesamiento completo.")
    return df


# ─── Subida a BigQuery ──────────────────────────────────────────────────────────

def subir_a_bigquery(df, log=print):
    client = bigquery.Client(project=BQ_PROJECT)
    tabla = f"{BQ_PROJECT}.{BQ_DATASET}.{BQ_TABLA}"

    df = sanitizar_columnas(df)

    log(f"Subiendo {len(df)} filas a {tabla}...")

    job_config = bigquery.LoadJobConfig(
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        autodetect=True,
    )

    job = client.load_table_from_dataframe(df, tabla, job_config=job_config)
    job.result()

    log(f"Subida completa: {len(df)} filas en {BQ_TABLA}.")
    return len(df)


# ─── Pipeline completo ──────────────────────────────────────────────────────────

def ejecutar_pipeline(log=print):
    log("Conectando a SQL Server...")
    df = conectar_y_cargar()

    df = procesar_dataframe(df, log=log)

    filas = subir_a_bigquery(df, log=log)
    return filas
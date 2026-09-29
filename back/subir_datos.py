"""
Script autónomo: extrae datos del SQL Server de la CUN, procesa y sube a BigQuery.
Ejecutar desde un PC con sesión activa de la CUN (usa Windows Auth automáticamente).
"""

import sys
import os
import asyncio
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))

from sqlalchemy import create_engine, text
import pandas as pd
import re
import unicodedata
import hashlib
from google.cloud import bigquery
import openai

# ─── Configuración ───────────────────────────────────────────────────────────────

SQL_HOST     = "172.16.1.33"
SQL_PORT     = "1433"
SQL_DATABASE = "CUN_REPOSITORIO"

BQ_PROJECT = "desarrollo-investigaciones"
BQ_DATASET = "call_center"
BQ_TABLA   = "cltiene_llamadas_procesadas"

# Re-proceso completo: ignora el cache y vuelve a pasar TODAS las
# transcripciones por OpenAI con el prompt actual (v16).
# Activar con `python subir_datos.py --full` o env REPROCESO_COMPLETO=1
REPROCESO_COMPLETO = ("--full" in sys.argv) or (os.getenv("REPROCESO_COMPLETO") == "1")

# Modelo para la detección de hablantes (separación Asesor/Cliente).
# gpt-4o es ~5-6x más preciso que gpt-4o-mini en llamadas con STT deforme
# (validado: ~2% vs ~7% de error de atribución). Override con env MODELO_HABLANTES.
MODELO_HABLANTES = os.getenv("MODELO_HABLANTES") or "gpt-4o"

LOG_FILE = os.path.join(os.path.dirname(__file__), "subir_datos.log")


# ─── Logger ──────────────────────────────────────────────────────────────────────

def log(msg):
    linea = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(linea)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(linea + "\n")


# ─── SQL Server con Windows Auth ─────────────────────────────────────────────────

def _crear_engine():
    """Prueba drivers ODBC modernos primero (Driver 18/17) y cae al viejo 'SQL Server'.
    Los modernos usan TCP + TrustServerCertificate (el viejo 'SQL Server' falla en
    algunas máquinas con DBNETLIB)."""
    import urllib.parse
    drivers = ["ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server", "SQL Server"]
    ultimo = None
    for drv in drivers:
        try:
            params = urllib.parse.quote_plus(
                f"DRIVER={{{drv}}};SERVER={SQL_HOST},{SQL_PORT};DATABASE={SQL_DATABASE};"
                f"Trusted_Connection=yes;TrustServerCertificate=yes;Encrypt=optional;"
            )
            engine = create_engine(f"mssql+pyodbc:///?odbc_connect={params}")
            with engine.connect() as c:
                c.execute(text("SELECT 1"))
            log(f"  SQL Server conectado con driver: {drv}")
            return engine
        except Exception as e:
            ultimo = e
            continue
    raise RuntimeError(f"No se pudo conectar a SQL Server con ningún driver ODBC: {ultimo}")


def parse_fecha_es(s):
    """Parsea el formato de fecha español de Windows que TRY_CONVERT(...,120) NO soporta:
    'DD/MM/YYYY h:mm:ss a. m./p. m.' con espacios Unicode (U+202F/U+00A0) y '.' en a.m./p.m.
    Devuelve datetime o None. (El formato ISO 120 se maneja en SQL; esto es solo el fallback
    para el lote viejo de oct-2025, cuando la fuente usaba la config regional es-CO.)"""
    if s is None:
        return None
    # Normaliza cualquier espacio Unicode (incl. U+202F angosto) a espacio normal
    t = "".join(" " if unicodedata.category(ch) == "Zs" else ch for ch in str(s))
    m = re.match(r"^\s*(\d{1,2})/(\d{1,2})/(\d{4})\s+(\d{1,2}):(\d{2}):(\d{2})\s*([ap])\W*m\W*$", t, re.I)
    ap = None
    if m:
        d, mo, y, h, mi, se, ap = m.groups()
    else:  # sin marcador a.m./p.m. → asume 24h
        m = re.match(r"^\s*(\d{1,2})/(\d{1,2})/(\d{4})\s+(\d{1,2}):(\d{2}):(\d{2})\s*$", t)
        if not m:
            return None
        d, mo, y, h, mi, se = m.groups()
    d, mo, y, h, mi, se = int(d), int(mo), int(y), int(h), int(mi), int(se)
    if ap:
        ap = ap.lower()
        if ap == "p" and h != 12:
            h += 12
        if ap == "a" and h == 12:
            h = 0
    try:
        return datetime(y, mo, d, h, mi, se)
    except ValueError:
        return None


# Columnas de la tabla origen (menos `Fecha`, cuya variante ISO/es-CO se resuelve
# en el query principal y en el fallback). Se comparten para no duplicar la lista.
_COLS_MEDIO = """
            b.[Contacto (Identificacion - Nombre],
            b.[Telefono], b.[Agente], COALESCE(b.[Cuenta], b.[Agente]) AS Cuenta,
            b.[Modulo], b.[Nombre del Modulo], b.[Motivo],
            b.[Estado de la LLamada],
            b.[Tiempo  de Llamada],
            b.[Tiempo  de Conversacion],
            b.[Estado de Registro], b.[Estado de Gestion],
            b.[Calificacion de la Llamada],
            b.[Direccion grabacion#1], b.[Direccion grabacion#2],
            b.[Direccion grabacion#3], b.[Direccion grabacion#4],
            b.[Direccion grabacion#5], b.[Direccion grabacion#6],
            b.[Direccion grabacion#7],
            b.[Comentario], b.[archivo],
            b.[saludo_inicial], b.[identificacion_cliente],
            b.[comprension_problema], b.[ofrecimiento_solucion],
            b.[manejo_inquietudes], b.[cierre_servicio], b.[proximo_paso],
            b.[efectiva], b.[polarity], b.[subjectivity],
            b.[clasificacion], b.[confianza], b.[palabras],
            b.[IDENTIFICACION], b.[fecha_carga], b.[transcripcion],
            b.[Tipo_Llamada]"""


def cargar_desde_sql():
    engine = _crear_engine()

    # Query principal: filas con fecha en formato ISO 120 (la mayoría).
    # `tipo` se toma tal cual del origen. Antes un CTE contaba filas por
    # (cuenta, timestamp) y marcaba 'mixto' cuando había más de una (~21% de las
    # llamadas), lo que escondía esas filas de los filtros por tipo. El tipo del
    # origen ya es el dato bueno; el JOIN además solo servía para ese conteo
    # (devuelve exactamente las mismas filas que el WHERE).
    sql = text(f"""
        SELECT
            TRY_CONVERT(datetime, b.Fecha, 120)          AS Fecha,
            {_COLS_MEDIO},
            b.[tipo] AS tipo
        FROM CUN_REPOSITORIO.coe.CLTIENE_LLAMADAS b
        WHERE TRY_CONVERT(datetime, b.Fecha, 120) IS NOT NULL
    """)

    # Fallback: filas cuya fecha NO parsea con 120 (formato español de Windows, lote
    # oct-2025). Se traen crudas y se parsea la fecha en Python (SQL no lo logra por el
    # espacio U+202F). Sin esto se perdían ~7k llamadas en silencio.
    sql_fb = text(f"""
        SELECT
            b.[fecha] AS Fecha_raw,
            {_COLS_MEDIO},
            b.[tipo] AS tipo
        FROM CUN_REPOSITORIO.coe.CLTIENE_LLAMADAS b
        WHERE TRY_CONVERT(datetime, b.fecha, 120) IS NULL
          AND b.[fecha] LIKE '%/%/%'
    """)

    with engine.connect() as conn:
        df = pd.read_sql_query(sql, conn)
        df_fb = pd.read_sql_query(sql_fb, conn)

    log(f"  Filas formato ISO (120): {len(df):,}")
    if len(df_fb):
        df_fb["Fecha"] = df_fb["Fecha_raw"].apply(parse_fecha_es)
        no_parse = int(df_fb["Fecha"].isna().sum())
        df_fb = df_fb[df_fb["Fecha"].notna()].drop(columns=["Fecha_raw"]).reset_index(drop=True)
        log(f"  Filas formato español recuperadas: {len(df_fb):,} (lote oct-2025)")
        if no_parse:
            log(f"  ⚠️ Filas con fecha no parseable descartadas: {no_parse:,}")
        df = pd.concat([df, df_fb], ignore_index=True)
        df["Fecha"] = pd.to_datetime(df["Fecha"], errors="coerce")

    # Deduplicación: la tabla origen (CUN) trae ~10% de filas duplicadas
    # (el mismo audio cargado más de una vez → inflaba los conteos del dashboard).
    # Clave: fecha + cuenta + teléfono + transcripción + archivo.
    # `archivo` (nombre del audio) es lo que identifica la llamada: sin él se
    # borraban por error llamadas distintas sin transcripción que comparten
    # fecha+cuenta+teléfono. Con él solo se quitan audios idénticos repetidos.
    antes = len(df)
    subset = [c for c in ["Fecha", "Cuenta", "Telefono", "transcripcion", "archivo"] if c in df.columns]
    if subset:
        df = df.drop_duplicates(subset=subset, keep="first").reset_index(drop=True)
    quitadas = antes - len(df)
    if quitadas:
        log(f"  Duplicados eliminados: {quitadas:,} ({quitadas/antes*100:.1f}%) → {len(df):,} filas únicas")

    return df


# ─── Patrones V4 ─────────────────────────────────────────────────────────────────

P_ASESOR = [
    r'tengo\s+(?:el\s+gusto|la\s+oportunidad|la\s+opción)\s+de\s+(?:comunicarme|contactarme|contactar)',
    r'(?:me\s+)?(?:estoy|estamos)\s+comunic(?:ando|o)',
    r'nos\s+(?:estamos\s+)?comunic(?:ando|amos)',
    r'habl[aá][rs]?\s+(?:con|nuevamente)',
    r'(?:sele?|cl|ese\s*le|cle)\s*tiene',
    r'(?:soy|mi\s+nombre\s+es)\s+[A-ZÁ-Úa-zá-ú]+\s+(?:[A-ZÁ-Ú]|de\s+)',
    r'mucho\s+gusto\.?\s+(?:soy|mi\s+nombre)',
    r'nuestro[as]?\s+(?:plan|servicio|parámetro|asistencia|línea)',
    r'el\s+motivo\s+de\s+(?:mi|la)\s+llamada',
    r'registro\s+(?:que\s+)?(?:hiciste|realizaste|hizo|realizó)',
    r'solicitud\s+que\s+(?:hiciste|realizaste|hizo)',
    r'te\s+(?:contacto|llamo|comunico)\s+(?:ya\s+)?(?:con|para|porque|por)',
    r'queremos\s+validar', r'quisi[eé]ramos\s+validar',
    r'te\s+(?:explico|comento|indico)',
    r'lo\s+que\s+(?:nosotros|te)\s+(?:hacemos|ofrecemos|brindamos)',
    r'me\s+confirmas?\s+(?:por\s+favor\s+)?(?:tu|el|la|los|su)',
    r'permíteme', r'vamos\s+a\s+validar',
    r'(?:con\s+gusto)\s+(?:que\s+)?tengas?\s+(?:un\s+)?(?:buen|excelente)\s+día',
    r'feliz\s+(?:día|tarde|noche)',
    r'te\s+(?:voy\s+a\s+)?(?:generar|enviar|compartir|escribir)',
    r'estaré\s+contactando',
    r'(?:señora?|señorita)\s+[A-ZÁ-Ú][a-zá-ú]+,?\s+(?:mucho\s+gusto|necesito|quería)',
    r'de\s+pronto\s+(?:algún|alguna)',
    r'el\s+día\s+de\s+ayer\s+realizaste',
    r'^(?:te|le)\s+(?:entiendo|comprendo)',
    r'(?:ya\s+)?te\s+(?:escribí|envié|mandé|compartí)',
    r'(?:entonces\s+)?(?:ya\s+)?te\s+(?:escribo|envío|mando|comparto)',
    r'te\s+(?:voy\s+a\s+)?(?:dejar|enviar|mandar|compartir|escribir)\s+(?:un\s+)?(?:mensaj|whatsapp|link|enlace)',
    r'^se\s+(?:le|te)\s+agradece',
    r'^nosotros\s+(?:manejamos|ofrecemos|brindamos|somos|tenemos)',
    r'(?:no\s+)?somos\s+un\s+servicio',
    r'(?:manejamos|ofrecemos|brindamos)\s+(?:cobertura|servicio|asistencia|plan)',
    r'(?:algún|alg[uú]n)\s+motivo\s+(?:por\s+(?:el\s+)?cual|de\s+pronto)',
    r'^(?:ah[,\s]+)?listo[,\s]+perfecto[,\s]+(?:sí\s+)?(?:señor|señora|don)',
    r'(?:ya\s+)?(?:dejo|queda)\s+(?:la\s+)?(?:constancia|registro|nota|anotación)',
    r'^(?:disculp[ea]me|perdón|perdona)\s+(?:por|la\s+molestia)',
    r'^qué\s+pena\b',
]

P_ASESOR_FUERTE = [
    r'habl[aá][rs]?\s+con', r'tiene\s*soluciones', r'me\s+estoy\s+comunic',
    r'tengo\s+(?:el\s+gusto|la\s+opción)', r'nuestro[as]?\s+(?:plan|servicio|asistencia)',
    r'queremos\s+validar', r'realizaste\s+(?:un\s+)?registro',
    r'(?:no\s+)?somos\s+un\s+servicio',
    r'^nosotros\s+(?:manejamos|ofrecemos|brindamos|somos|tenemos)',
    r'(?:algún|alg[uú]n)\s+motivo\s+(?:por\s+(?:el\s+)?cual|de\s+pronto)',
]

P_CLIENTE = [
    r'^aló\b', r'^hola\b(?!\s*[,.]?\s*(?:muy\s+)?(?:buenos?|buenas?))',
    r'^no[\s,]+no\b', r'^sí[\s,]+señora?\b(?!\s*\.?\s*(?:mira|habla|estoy|me\s+estoy|soy|de))',
    r'^no[\s,]+señora?\b',
    r'^¿(?:de\s+parte\s+de\s+quién|quién\s+(?:habla|llama|lo\s+llama))',
    r'^¿(?:y\s+eso|eso)\s+(?:de\s+)?qué\s+(?:se\s+trata|es)',
    r'^(?:con\s+ella?\s+(?:habla|hablo))',
    r'^soy\s+yo\b', r'^no\s+(?:gracias|me\s+interesa|estoy\s+interesad)',
    r'^yo\s+no\s+(?:hice|realicé|pedí|registré)',
    r'^¿cuánto\s+(?:es|cuesta|vale)', r'^¿cómo\s+(?:sería|es|hago|funciona)',
    r'(?:está|numero)\s+equivocad', r'no\s+(?:lo|la)\s+conozco', r'no\s+vive\s+(?:aquí|acá)',
]

P_RESPUESTA_CLIENTE = [
    r'^sí[\s,\.]+', r'^no[\s,\.]+', r'^ah[\s,]+no', r'^bueno[\s,\.]*$',
    r'^bueno[\s,]+gracias', r'^es\s+que\s+', r'^pues\s+',
    r'^¿de\s+', r'^¿y\s+', r'^ya[\s,\.]*$', r'^listo[\s,\.]*$',
    r'^dale[\s,\.]*$', r'^ok[\s,\.]*$', r'^claro[\s,\.]*', r'^ajá[\s,\.]*',
    r'^a\s+mí\s+no\s+me', r'^yo\s+no\s+', r'^están\s+equivocad',
    r'no\s+(?:era|es)\s+eso',
]

P_RESPUESTA_INFORMATIVA = [
    r'^(?:eh[,\s]+)?no\s+se\s+encuentra',
    r'^(?:eh[,\s]+)?(?:ella?|él)\s+no\s+(?:se\s+encuentra|está)',
    r'^(?:no\s+)?está\s+(?:ocupad[oa]|trabaj|fuera|enferm)',
    r'^(?:por\s+ahí|como|más\s+o\s+menos|aproximadamente)\s+(?:en|a\s+las?|de|después)',
    r'^(?:en|como\s+en)\s+(?:unas?\s+)?(?:\d+|dos|tres|cuatro|cinco)\s+horas?',
    r'^más\s+(?:tarde|tardesito|temprano)',
    r'^(?:a\s+las?\s+)?\d+\s*(?:de\s+la\s+(?:mañana|tarde|noche))',
    r'^se\s+llama\s+',
    r'^(?:ella?|él)\s+(?:tiene|es|vive|trabaja|llega|sale)',
    r'^(?:yo\s+)?(?:vivo|estoy|trabajo|soy)\s+',
    r'^yo\s+(?:me\s+)?(?:vine|fui|vengo|voy|necesit|quer[ií]a|estaba|estoy|tengo)',
    r'no\s+tengo\s+(?:animal|mascot|perr|gat)',
    r'no\s+tengo\s+(?:carro|moto|vehículo)',
    r'^para\s+(?:el\s+)?(?:perrit|gatit|perr[oa]\b|gat[oa]\b|carro|moto|hogar)',
    r'(?:env[ií][ae]|mand[ae]).*(?:whatsapp|mensaje|correo)',
]

P_DESPEDIDA_CLIENTE = [
    r'(?:que\s+)?(?:te|le|les)\s+vaya\s+(?:bien|muy\s+bien)',
    r'(?:que\s+)?tengas?\s+(?:un\s+)?(?:buen|bonito|lindo|excelente)\s+(?:día|tarde|noche)',
    r'^hasta\s+(?:luego|pronto|la\s+(?:próxima|vista)|mañana)',
    r'^chao\b', r'^chau\b', r'^adiós\b',
    r'^(?:muchas?\s+)?gracias(?:\s+(?:igualmente|también|a\s+(?:ti|usted|ustedes)))?\s*[\.!]?$',
    r'^igualmente\s*[\.!]?$',
    r'^(?:muy\s+)?amable(?:\s+gracias)?\s*[\.!]?$',
    r'^bueno[\s,]+(?:muchas?\s+)?gracias',
]

P_DESPEDIDA_ASESOR = [
    r'con\s+gusto\s+(?:que\s+)?tengas?\s+(?:un\s+)?(?:buen|excelente)\s+día',
    r'feliz\s+(?:día|tarde|noche|resto)\s+(?:de\s+)?(?:día|tarde)',
    r'estaré\s+(?:contactando|llamando|pendiente)',
    r'(?:fue|ha\s+sido)\s+un\s+(?:gusto|placer)',
    r'quedamos?\s+(?:atentos?|pendientes?)',
    r'feliz\s+(?:día|tarde|noche)\s*[\.!]?$',
]

P_AGRADECIMIENTO_ASESOR = [
    r'^(?:no[\s,]+)?s[ií][\s,]+(?:dale|claro|señora?)',
    r'^dale[\s,]+(?:much[ao]s?\s+)?gracias',
    r'^(?:listo|bueno|dale)[\s,]+(?:te\s+)?agradez',
    r'^(?:muchas?\s+)?gracias[\s,]+(?:te|le)\s+(?:agradezco|agradecemos)',
    r'(?:te|le)\s+agradezco',
]


# ─── Catálogo de asistencias ──────────────────────────────────────────────────────

CATALOGO_ASISTENCIAS = [
    ('Grúa para carro',                    r'gr[uú]a\s+(?:para\s+)?(?:el\s+)?carro|servicio\s+de\s+gr[uú]a(?!\s+(?:para\s+)?moto)'),
    ('Grúa para moto',                     r'gr[uú]a\s+(?:para\s+)?(?:la\s+)?moto'),
    ('Cambio de llanta',                   r'cambio\s+de\s+llanta'),
    ('Reinicio de batería',                r'reinicio\s+de\s+bater[ií]a|paso\s+de\s+corriente'),
    ('Conductor elegido',                  r'conductor\s+elegido'),
    ('Cerrajería vial',                    r'cerrajer[ií]a\s+vial'),
    ('Cerrajería por urgencia',            r'cerrajer[ií]a\s+(?:por\s+)?urgencia|cerrajero\s+(?:urgente|de\s+urgencia)'),
    ('Plomería por urgencia',              r'plomer[ií]a\s+(?:por\s+)?urgencia|plomero\s+(?:urgente|de\s+urgencia)'),
    ('Electricista por urgencia',          r'electricist[ao]\s+(?:por\s+)?urgencia'),
    ('Armado de muebles a domicilio',      r'armado\s+de\s+muebles'),
    ('Handyman o todero',                  r'handyman|todero'),
    ('Instalación de duchas',              r'instalaci[oó]n\s+de\s+duchas'),
    ('Instalación de electrodomésticos',   r'instalaci[oó]n\s+de\s+electrodom[eé]sticos'),
    ('Mantenimiento de calentador',        r'mantenimiento\s+de\s+calentador'),
    ('Mantenimiento de estufas',           r'mantenimiento\s+de\s+estufas?'),
    ('Mantenimiento de lavadoras',         r'mantenimiento\s+de\s+lavadoras?'),
    ('Mantenimiento de nevera',            r'mantenimiento\s+de\s+nevera'),
    ('Mantenimiento de bicicletas',        r'mantenimiento\s+de\s+bicicletas?'),
    ('Veterinario en casa o en clínica',   r'veterinario\s+(?:en\s+casa|a\s+domicilio|en\s+cl[ií]nica)'),
    ('Atención veterinaria telefónica',    r'atenci[oó]n\s+veterinaria\s+telef[oó]nica'),
    ('Desparasitación',                    r'desparasita'),
    ('Refuerzo de vacunas',                r'refuerzo\s+de\s+vacunas|vacunaci[oó]n'),
    ('Chip de identificación',             r'chip\s+de\s+identificaci[oó]n'),
    ('Limpieza dental',                    r'limpieza\s+dental'),
    ('Valoración por urgencia dental',     r'valoraci[oó]n\s+(?:por\s+)?urgencia\s+dental|urgencia\s+dental'),
    ('Médico a domicilio',                 r'm[eé]dico\s+a\s+domicilio'),
    ('Pediatra a domicilio',               r'pediatra\s+a\s+domicilio'),
    ('Psicólogo a domicilio',              r'psic[oó]logo\s+a\s+domicilio'),
    ('Videollamada con médico general',    r'videollamada\s+con\s+m[eé]dico\s+general|videollamada\s+m[eé]dic'),
    ('Videollamada con médico pediatra',   r'videollamada\s+con\s+(?:m[eé]dico\s+)?pediatra'),
    ('Orientación médica telefónica',      r'orientaci[oó]n\s+m[eé]dica\s+telef[oó]nica'),
    ('Orientación nutricional telefónica', r'orientaci[oó]n\s+nutricional'),
    ('Orientación psicológica telefónica', r'orientaci[oó]n\s+psicol[oó]gica'),
    ('Acompañante a citas médicas',        r'acompa[nñ]ante\s+(?:a\s+)?citas\s+m[eé]dicas?'),
    ('Declaración de renta',               r'declaraci[oó]n\s+de\s+renta'),
]


# ─── Funciones de estructuración V4 ──────────────────────────────────────────────

def detectar_hablante(oracion, hablante_prev, prev_pregunta_asesor, es_final=False,
                      prev_agradecimiento_asesor=False, prev_despedida_cliente=False):
    o_lower = oracion.lower().strip()
    longitud = len(oracion.strip())

    es_asesor = any(re.search(p, o_lower, re.IGNORECASE) for p in P_ASESOR)
    es_cliente = any(re.search(p, o_lower) for p in P_CLIENTE)

    if es_asesor and not es_cliente: return 'Asesor'
    if es_cliente and not es_asesor: return 'Cliente'
    if es_asesor and es_cliente:
        return 'Asesor' if any(re.search(p, o_lower, re.IGNORECASE) for p in P_ASESOR_FUERTE) else 'Cliente'

    if any(re.search(p, o_lower) for p in P_AGRADECIMIENTO_ASESOR):
        return 'Asesor'

    if es_final or hablante_prev == 'Asesor':
        es_despedida_cliente = any(re.search(p, o_lower) for p in P_DESPEDIDA_CLIENTE)
        es_despedida_asesor = any(re.search(p, o_lower) for p in P_DESPEDIDA_ASESOR)
        if es_despedida_cliente and not es_despedida_asesor:
            return 'Cliente'
        if es_despedida_asesor and not es_despedida_cliente:
            return 'Asesor'

    if longitud <= 60:
        if any(re.search(p, o_lower) for p in P_RESPUESTA_CLIENTE):
            return 'Cliente'
        if any(re.search(p, o_lower) for p in P_RESPUESTA_INFORMATIVA):
            return 'Cliente'
        if prev_pregunta_asesor and longitud < 45:
            return 'Cliente'

    if prev_pregunta_asesor and longitud < 80:
        if any(re.search(p, o_lower) for p in P_RESPUESTA_INFORMATIVA):
            return 'Cliente'

    if longitud < 100:
        if any(re.search(p, o_lower) for p in P_RESPUESTA_INFORMATIVA):
            if not any(re.search(p, o_lower, re.IGNORECASE) for p in P_ASESOR):
                return 'Cliente'

    if hablante_prev == 'Cliente' and longitud > 60:
        if not any(re.search(p, o_lower) for p in P_DESPEDIDA_CLIENTE):
            return 'Asesor'

    return None


def split_oraciones_v4(texto):
    oraciones = re.split(r'(?<=[.!?])\s+', texto)
    resultado = []
    resp_patterns = [
        r'^(?:eh[,\s]+)?(?:no\s+se\s+encuentra|no\s+está|está\s+ocupad)',
        r'^(?:por\s+ahí|como|más\s+o\s+menos)',
        r'^(?:sí|no|bueno|claro|dale|ok|ajá|listo)[\s,\.]',
        r'^(?:ella?|él)\s+(?:no\s+)?(?:se\s+encuentra|está|salió|tiene)',
    ]
    for oracion in oraciones:
        oracion = oracion.strip()
        if not oracion:
            continue
        match = re.search(r'\?\s+(.+)$', oracion)
        if match:
            respuesta = match.group(1).strip()
            if len(respuesta) < 60 and any(re.search(p, respuesta.lower()) for p in resp_patterns):
                pregunta = oracion[:match.start() + 1]
                if pregunta.strip():
                    resultado.append(pregunta.strip())
                    resultado.append(respuesta)
                    continue
        resultado.append(oracion)
    return resultado


def estructurar_dialogo(texto):
    if pd.isna(texto) or not texto:
        return None
    texto = str(texto).strip()
    if len(texto) < 10:
        return None

    oraciones = split_oraciones_v4(texto)
    total_oraciones = len(oraciones)
    asignaciones = []
    hablante_prev = None
    prev_pregunta = False
    prev_agradecimiento = False
    prev_despedida_cli = False

    for i, oracion in enumerate(oraciones):
        oracion = oracion.strip()
        if not oracion:
            continue

        es_final = (i >= total_oraciones - 3)
        hablante = detectar_hablante(oracion, hablante_prev, prev_pregunta, es_final,
                                     prev_agradecimiento, prev_despedida_cli)

        if i == 0 and hablante is None:
            fl = oracion.lower()
            if re.match(r'^(?:muy\s+)?(?:buenos?|buenas?)\s+(?:días|tardes|noches)', fl):
                hablante = 'Asesor'
            elif re.match(r'^aló', fl):
                hablante = 'Cliente'
            else:
                hablante = 'Asesor'

        if hablante:
            hablante_prev = hablante
        else:
            hablante = hablante_prev

        o_lower_check = oracion.lower().strip()
        es_pregunta = '?' in oracion or bool(re.search(
            r'(?:validar|confirmar|saber|verificar)\s+si\s+', o_lower_check))

        if hablante == 'Asesor' and es_pregunta:
            prev_pregunta = True
        else:
            prev_pregunta = False

        prev_agradecimiento = (hablante == 'Asesor' and
            any(re.search(p, o_lower_check) for p in P_AGRADECIMIENTO_ASESOR))
        prev_despedida_cli = (hablante == 'Cliente' and
            any(re.search(p, o_lower_check) for p in P_DESPEDIDA_CLIENTE))
        asignaciones.append({'texto': oracion, 'hablante': hablante})

    if not asignaciones:
        return None
    if asignaciones[0]['hablante'] is None:
        asignaciones[0]['hablante'] = 'Asesor'
    for i in range(1, len(asignaciones)):
        if asignaciones[i]['hablante'] is None:
            asignaciones[i]['hablante'] = asignaciones[i-1]['hablante']

    bloques = []
    bloque = {'hablante': asignaciones[0]['hablante'], 'textos': [asignaciones[0]['texto']]}
    for i in range(1, len(asignaciones)):
        if asignaciones[i]['hablante'] == bloque['hablante']:
            bloque['textos'].append(asignaciones[i]['texto'])
        else:
            bloques.append(bloque)
            bloque = {'hablante': asignaciones[i]['hablante'], 'textos': [asignaciones[i]['texto']]}
    bloques.append(bloque)

    return '\n'.join(f"[{b['hablante']}]: {' '.join(b['textos'])}" for b in bloques)


# ─── Cache incremental ───────────────────────────────────────────────────────────

def _hash_tx(texto):
    if pd.isna(texto) or not str(texto).strip():
        return '__empty__'
    return hashlib.md5(str(texto).strip().encode('utf-8')).hexdigest()

def cargar_cache_bigquery():
    """Devuelve {hash_transcripcion: Transcripcion_V4} de los datos ya procesados en BQ."""
    try:
        client = bigquery.Client(project=BQ_PROJECT)
        query = f"""
            SELECT transcripcion, Transcripcion_V4
            FROM `{BQ_PROJECT}.{BQ_DATASET}.{BQ_TABLA}`
            WHERE Transcripcion_V4 IS NOT NULL AND Transcripcion_V4 != ''
        """
        df_bq = client.query(query).to_dataframe()
        cache = {_hash_tx(r['transcripcion']): r['Transcripcion_V4'] for _, r in df_bq.iterrows()}
        log(f"  Cache BigQuery: {len(cache):,} transcripciones ya procesadas")
        return cache
    except Exception as e:
        log(f"  (cache no disponible: {e})")
        return {}


# ─── Estructuración V4 con OpenAI ────────────────────────────────────────────────

_PROMPT_HABLANTES = """Eres un analizador experto de transcripciones de call center colombiano.
Tu tarea: separar el diálogo entre ASESOR y CLIENTE.

════════════════════════════════════════════════════════════
REGLA #1 — MÁXIMA PRIORIDAD (por encima de cualquier otra):
El CLIENTE JAMÁS pronuncia un nombre propio como vocativo.
Si una frase contiene "señora [Nombre]" o "señor [Nombre]"
dirigiéndose a alguien → el hablante es SIEMPRE el ASESOR.

Esto aplica AUNQUE la frase empiece con una confirmación:
  "Correcto, señora Rosalía"       → ASESOR (NO cliente)
  "Exacto, señor Pedro"            → ASESOR
  "Perfecto, señora Ana, entonces" → ASESOR
  "Vale, correcto, señora María"   → ASESOR
La palabra Correcto/Sí/Exacto/Perfecto/Vale NO convierte la
frase en cliente si va acompañada del nombre propio del
interlocutor. EL NOMBRE MANDA sobre la palabra de confirmación.
Única excepción cliente: "Sí, señora" / "Sí, señor" SOLOS
(2-3 palabras y se detiene, SIN nombre propio).
════════════════════════════════════════════════════════════

DEFINICIONES:
- ASESOR: agente del call center (ofrece servicios de asistencia: grúa, médico, etc.)
- CLIENTE: persona natural que recibe o hace la llamada

TIPO DE LLAMADA (se indica al inicio del texto del usuario):
- [Tipo: saliente] → el ASESOR llamó al CLIENTE. El cliente contesta primero:
  "Aló", "Hola", "Buenas tardes", etc. Si la transcripción empieza directamente
  con frases del asesor (sin "Aló" previo), el "Aló" del cliente fue cortado por
  el sistema y la llamada IGUAL es saliente — el primer hablante completo que ves
  puede ser el Asesor presentándose.
- [Tipo: entrante] → el CLIENTE llamó al call center. El ASESOR contesta primero:
  "Bienvenido a la línea de asistencia", "Hablas con [Nombre]", etc.

CASO ESPECIAL — BUZÓN DE VOZ:
Si el texto comienza con "Este es el servicio de contestador" / "Por favor deja tu mensaje" /
"deja tu mensaje después del tono" → es un buzón automático, NO hay diálogo real.
En ese caso devuelve: [Asesor]: (toda la transcripción sin dividir)

SEÑALES INEQUÍVOCAS DEL ASESOR:
- "Mi nombre es [Nombre]" / "Mucho gusto, soy [Nombre]" seguido de empresa/servicio
- "Me comunico con / nos comunicamos con / nos estamos pasando de la línea de..."
- "Hablas con [Nombre]" / "Te habla [Nombre]" / "Le habla [Nombre]" presentándose
- "Buenas tardes/días con [Nombre]" o "Buenas tardes/días, [Nombre]" al buscar al cliente → ASESOR
- "Me gustaría/me gusta/quisiera/quiero hablar con [Nombre]" → ASESOR buscando al cliente
- "Tengo el gusto de comunicarme / contactarme con [Nombre]" → ASESOR
- "¿Con quién tengo el gusto de hablar?" / "¿Con quién hablo?" → SIEMPRE ASESOR
- "Por favor, la señora/señor [Nombre]" / "Con la señora/señor [Nombre], por favor" → ASESOR
- "Qué pena [Nombre], veo que se cortó" / "Qué pena la molestia" + nombre cliente → ASESOR
- "El motivo de mi llamada/contacto es...", "Te llamo de parte de...", "Te contacto porque..."
- "Bienvenido/a a la línea de...", "Bienvenidos con las asistencias de..."
- "Te voy a explicar", "Te comento que", "Nosotros ofrecemos/manejamos/brindamos"
- "¿Puedo hablar con [Nombre]?", "¿Me comunicas con [Nombre]?", "¿Se encuentra [Nombre]?"
- "Señora/Señor [Nombre], mucho gusto" (saluda al cliente por nombre)
- "Correcto/Exacto/Entendido/Perfecto, señora/señor [Nombre]" → ASESOR confirmando y dirigiéndose al cliente
- "Con todo gusto [Nombre]" / "Con mucho gusto" respondiendo a un "gracias" → ASESOR
- REGLA GENERAL: el CLIENTE NUNCA se dirige a sí mismo por su propio nombre.
  Si aparece "señora X" o "señor X" como vocativo en una frase, el hablante es el ASESOR.
- "nuestro plan asistencial", "se le tiene soluciones", "CL Tiene / CLTiene" → ASESOR
- "Es un placer saludarte/saludarle", "Somos una empresa/servicio de asistencias"

SEÑALES INEQUÍVOCAS DEL CLIENTE:
- "Aló", "Aló aló", "Diga", "Aquí es", "Aquí hola" → SIEMPRE Cliente contestando
- Múltiples "Aló" repetidos seguidos → todos son del CLIENTE
- "No me interesa", "No necesito eso", "No hice ningún registro", "Yo no pedí eso"
- "¿De qué se trata?", "¿Quién habla?", "¿De dónde llaman?"
- "Con ella/él habla", "Soy yo", "Con el/ella"
- "No lo entiendo bien" / "No entendí" / "¿Qué pena, no escuché?" → CLIENTE
- "Perfecto, muchas gracias" / "Gracias" sola al final de turno → CLIENTE
- "Sí señora" / "Sí señor" solos (2-3 palabras, sin continuar hablando) → CLIENTE confirmando
- "¿Cómo?" solo → CLIENTE (no escuchó, pide repetir)
- "No, [nombre/corrección]" → CLIENTE corrigiendo un dato (p.ej. "No, Rosalía" cuando el asesor dijo mal el nombre)
- "¿[nombre]?" sola como pregunta → CLIENTE repreguntando el nombre que dijo el asesor
- "¿De dónde?" / "¿De dónde llaman?" / "¿De qué empresa?" → CLIENTE preguntando la procedencia
- "¿Quién es?" / "¿Con quién habló?" → CLIENTE identificando al llamante
- Respuestas muy cortas (Sí / No / Ok / Dale / Claro / Bien / Ya) tras pregunta del asesor

TRANSCRIPCIÓN INICIADA EN MEDIO DE CONVERSACIÓN:
Si el texto empieza con una conjunción ("y", "pero", "entonces"), minúscula, o fragmento sin
contexto → es una transcripción cortada. Usa el CONTENIDO del texto para identificar hablantes:
busca señales de asesor/cliente en el resto del texto y asigna en consecuencia.

TEXTO MUY REPETITIVO (falla de STT):
Si una frase corta se repite 5 o más veces seguidas ("bueno bueno bueno...", "Hola ¿cómo estás?
Hola ¿cómo estás?...") → es un error del sistema de transcripción. Trata el bloque repetido como
UN SOLO turno y asígnalo al hablante que corresponda por contexto. Si luego aparecen señales
claras de asesor/cliente, divide normalmente. No dejes la llamada como irreconocible.

PATRÓN SALIENTE (asesor llama al cliente — el más común):
[Cliente]: Aló  ← cliente contesta primero
[Asesor]: Hola señora [Nombre], le habla [Asesor] de [Empresa]...
[Cliente]: Sí / ¿De qué se trata?
[Asesor]: El motivo de mi llamada...

PATRÓN ENTRANTE (cliente llama al call center):
[Asesor]: Bienvenido a la línea de asistencia, hablas con [Nombre]
[Cliente]: Hola, necesito coordinar una asistencia...

REGLA CRÍTICA OBLIGATORIA — analiza frase por frase, NO bloque por bloque:
Aunque el texto comience con "Hola" o "Buenos días" (→ Cliente), la SIGUIENTE FRASE
que contenga señal de ASESOR DEBE comenzar un nuevo bloque [Asesor] inmediatamente.
NUNCA acumules frases de asesor dentro de un bloque de cliente por inercia.

Frases que SIEMPRE cortan el bloque actual e inician [Asesor]:
  • "Me estoy comunicando", "estamos comunicando", "estamos hablando con [Nombre]"
  • "Me comunico con", "Tengo el gusto de comunicarme/contactarme"
  • "Mi nombre es", "Te habla", "Le habla", "Mucho gusto" + nombre propio
  • "me gusta/quisiera/quiero hablar con [Nombre]"
  • "Por favor, la señora/señor [Nombre]"
  • "nuestro plan asistencial", "tiene soluciones", "CL Tiene"

Frases que SIEMPRE cortan el bloque actual e inician [Cliente]:
  • "Aló" (incluso en medio del texto), PERO si DESPUÉS del Aló aparece señal de asesor → corta de nuevo
  • "No me interesa", "Soy yo", "Con ella/él habla"
  • "Qué pena, no entendí", "No lo entiendo bien"
  • "¿Cómo?" solo (1 palabra) → cliente no escuchó
  • "No, [nombre]" cuando el asesor pronunció mal un nombre → cliente corrige

ERROR TÍPICO A EVITAR:
❌ [Cliente]: Hola, buenas tardes. Me estoy comunicando con la señora María.
✅ [Cliente]: Hola, buenas tardes.
   [Asesor]: Me estoy comunicando con la señora María.

EJEMPLOS CONCRETOS (úsalos como referencia):

Entrada: "¿Aló? ¿Aló? Buenas. Mucho gusto, es que hace poco nos comunicamos con el señor Rodrigo."
Salida correcta:
[Cliente]: ¿Aló? ¿Aló? Buenas.
[Asesor]: Mucho gusto, es que hace poco nos comunicamos con el señor Rodrigo.

Entrada: "¿De dónde? ¿De dónde? ¿De dónde? ¿De dónde? Buenos días, bienvenida a la línea de asistencias, le habla Daniela, ¿en qué le colaboro?"
Salida correcta:
[Cliente]: ¿De dónde? ¿De dónde? ¿De dónde? ¿De dónde?
[Asesor]: Buenos días, bienvenida a la línea de asistencias, le habla Daniela, ¿en qué le colaboro?

Entrada: "Hola, ¿cómo estás? Hola, ¿cómo estás? Hola, ¿cómo estás? Hola, ¿cómo estás? Hola, ¿cómo estás? Hola, ¿cómo estás? Muy bien, señora, le llamo de CL Tiene soluciones."
Salida correcta:
[Cliente]: Hola, ¿cómo estás? (repetido por falla STT)
[Asesor]: Muy bien, señora, le llamo de CL Tiene soluciones.

Entrada: "Me estoy comunicando, por favor, con Rodalia. ¿Cómo? Me estoy contactando, por favor, con Rodalia. ¿Rodalia? No, Rosalía. ¿Qué pena? Rosalía Ángel. Sí. Mucho gusto, señora Rosalía."
Salida correcta:
[Asesor]: Me estoy comunicando, por favor, con Rodalia.
[Cliente]: ¿Cómo?
[Asesor]: Me estoy contactando, por favor, con Rodalia.
[Cliente]: ¿Rodalia? No, Rosalía.
[Asesor]: ¿Qué pena? Rosalía Ángel. Sí. Mucho gusto, señora Rosalía.

Entrada: "Muy buenos días. Muy buenos días. Me estoy comunicando nuevamente. Bien. ¿De dónde?"
Salida correcta:
[Cliente]: Muy buenos días.
[Asesor]: Muy buenos días. Me estoy comunicando nuevamente.
[Cliente]: Bien. ¿De dónde?

Entrada: "¿Tengo el gusto de comunicarme a la línea del señor Jarros? No. ¿Esta línea no le corresponde a él? No."
Salida correcta:
[Asesor]: ¿Tengo el gusto de comunicarme a la línea del señor Jarros?
[Cliente]: No.
[Asesor]: ¿Esta línea no le corresponde a él?
[Cliente]: No.

Entrada: "Hola, buenas tardes. Hola, muy buenas tardes. Me estoy comunicando con la señora Indira. Sí, con ella. Señora Indira, te habla Andrés."
Salida correcta:
[Cliente]: Hola, buenas tardes.
[Asesor]: Hola, muy buenas tardes. Me estoy comunicando con la señora Indira.
[Cliente]: Sí, con ella.
[Asesor]: Señora Indira, te habla Andrés.

Entrada: "Hola, buenas tardes. Estamos hablando con Liana, estamos comunicando para el médico de domicilio. Bien, ¿cómo estás?"
Salida correcta:
[Cliente]: Hola, buenas tardes.
[Asesor]: Estamos hablando con Liana, estamos comunicando para el médico de domicilio. ¿Cómo estás?

Entrada: "Hola, buenas tardes. Me estoy comunicando a la universidad de Lacuna. Sí, somos una empresa aliada."
Salida correcta:
[Cliente]: Hola, buenas tardes.
[Asesor]: Me estoy comunicando a la universidad de Lacuna. Sí, somos una empresa aliada.

Entrada: "¿Cómo? ¿Cómo? que se encontraba interesada en nuestro Plan Asistencial para Salud, ¿es correcto? No lo entiendo bien, qué pena."
Salida correcta:
[Cliente]: ¿Cómo?
[Asesor]: ¿Cómo? que se encontraba interesada en nuestro Plan Asistencial para Salud, ¿es correcto?
[Cliente]: No lo entiendo bien, qué pena.

Entrada: "y comunicarse, ¿listo? Perfecto, muchas gracias. No, con todo gusto, Cristian. De todas maneras en unos minutos el profesional se comunicará."
Salida correcta:
[Asesor]: y comunicarse, ¿listo?
[Cliente]: Perfecto, muchas gracias.
[Asesor]: No, con todo gusto, Cristian. De todas maneras en unos minutos el profesional se comunicará.

Entrada: "Aló. Muy buenas tardes. ¿Me comunico con la señora Sandra? Con ella. Señora Sandra, le habla Nicolás de CL Tiene."
Salida correcta:
[Cliente]: Aló.
[Asesor]: Muy buenas tardes. ¿Me comunico con la señora Sandra?
[Cliente]: Con ella.
[Asesor]: Señora Sandra, le habla Nicolás de CL Tiene.

Entrada: "Buenos días. Muy buenos días. Por favor, la señora Luz Adriana. Sí, señora. ¿Con ella hablan? Mi nombre es Melanie."
Salida correcta:
[Cliente]: Buenos días.
[Asesor]: Muy buenos días. Por favor, la señora Luz Adriana.
[Cliente]: Sí, señora. ¿Con ella hablan?
[Asesor]: Mi nombre es Melanie.

Entrada: "Buenas tardes. Buenas tardes, María Andrés. Sí, hablo por Andrés. Es que apenas me traté de comunicar contigo."
Salida correcta:
[Cliente]: Buenas tardes.
[Asesor]: Buenas tardes, María Andrés.
[Cliente]: Sí, hablo por Andrés.
[Asesor]: Es que apenas me traté de comunicar contigo.

Entrada: "A lo buenos días con Ana Celza Valencia. Ana, qué pena, veo que se nos cortó la llamada. ¿Puedes confirmar si estás interesada?"
Salida correcta:
[Cliente]: Aló, buenos días con Ana Celza Valencia.
[Asesor]: Ana, qué pena, veo que se nos cortó la llamada. ¿Puedes confirmar si estás interesada?

Entrada: "Aló. Aló. Aló. Buenas tardes. Señor Marvin, le habla Nicolás de CL Tiene."
Salida correcta:
[Cliente]: Aló. Aló. Aló. Buenas tardes.
[Asesor]: Señor Marvin, le habla Nicolás de CL Tiene.

Entrada: "¿vale? Correcto, señora Rosalía. Soy Jennifer, me contacto por este medio para brindarte la información, ¿vale? Sí."
Salida correcta:
[Asesor]: ¿vale? Correcto, señora Rosalía. Soy Jennifer, me contacto por este medio para brindarte la información, ¿vale?
[Cliente]: Sí.

REGLA ABSOLUTA — NUNCA INVENTES TEXTO:
Solo usa las palabras que aparecen literalmente en la transcripción.
Si la transcripción empieza con el cliente (sin texto del asesor antes), empieza con [Cliente]:
No agregues frases como "[Asesor]: Bienvenido a la línea..." si eso no está en el texto.

Formato de salida EXACTO (sin texto adicional, sin explicaciones):
[Asesor]: texto
[Cliente]: texto
[Asesor]: texto

Agrupa oraciones consecutivas del mismo hablante en UN solo bloque."""


async def _estructurar_ia_async(texto, client, sem, tipo='saliente'):
    if pd.isna(texto) or not texto or len(str(texto).strip()) < 10:
        return None
    texto = str(texto).strip()
    tipo_str = str(tipo).lower() if pd.notna(tipo) else 'saliente'
    user_content = f"[Tipo: {tipo_str}]\n{texto[:3000]}"
    async with sem:
        try:
            resp = await client.chat.completions.create(
                model=MODELO_HABLANTES,
                messages=[
                    {"role": "system", "content": _PROMPT_HABLANTES},
                    {"role": "user",   "content": user_content},
                ],
                temperature=0,
                max_tokens=2000,
            )
            return resp.choices[0].message.content.strip()
        except Exception:
            return estructurar_dialogo(texto)  # fallback a regex


async def _batch_ia(textos, tipos=None, concurrencia=25):
    # Soporte para dos API keys (dobla la concurrencia)
    keys = [k for k in [
        os.getenv("OPENAI_API_MUNDIAL"),
        os.getenv("OPENAI_API_MUNDIAL_2"),
    ] if k]
    clients = [openai.AsyncOpenAI(api_key=k) for k in keys]
    sem = asyncio.Semaphore(concurrencia * len(clients))
    if tipos is None:
        tipos = ['saliente'] * len(textos)
    tasks = [
        _estructurar_ia_async(t, clients[i % len(clients)], sem, tp)
        for i, (t, tp) in enumerate(zip(textos, tipos))
    ]
    return await asyncio.gather(*tasks)


def estructurar_dialogos_ia(textos, tipos=None, cache=None):
    """Procesa transcripciones con OpenAI, reutilizando cache para las ya procesadas."""
    t_list  = list(textos)
    tp_list = list(tipos) if tipos is not None else ['saliente'] * len(t_list)

    if not cache:
        return asyncio.run(_batch_ia(t_list, tipos=tp_list))

    hashes          = [_hash_tx(t) for t in t_list]
    idx_nuevos      = [i for i, h in enumerate(hashes) if h not in cache]
    log(f"  Nuevas/cambiadas: {len(idx_nuevos):,} | Reutilizadas: {len(t_list)-len(idx_nuevos):,}")

    resultados = [cache.get(h) for h in hashes]  # None donde no hay cache

    if idx_nuevos:
        tx_nuevas  = [t_list[i]  for i in idx_nuevos]
        tp_nuevas  = [tp_list[i] for i in idx_nuevos]
        procesadas = asyncio.run(_batch_ia(tx_nuevas, tipos=tp_nuevas))
        for pos, i in enumerate(idx_nuevos):
            resultados[i] = procesadas[pos]

    return resultados


# ─── Funciones de detección ───────────────────────────────────────────────────────

def detectar_duracion_estimada(tiempo_str):
    if pd.isna(tiempo_str) or not tiempo_str:
        return "Sin Datos"
    try:
        partes = str(tiempo_str).strip().split(':')
        if len(partes) == 3:
            segundos = int(partes[0]) * 3600 + int(partes[1]) * 60 + int(partes[2])
        elif len(partes) == 2:
            segundos = int(partes[0]) * 60 + int(partes[1])
        else:
            return "Sin Datos"
    except Exception:
        return "Sin Datos"
    if segundos <= 30:  return "Buzón"
    if segundos <= 60:  return "Muy Corta"
    if segundos <= 120: return "Corta"
    if segundos <= 300: return "Media"
    return "Larga"


def detectar_plan(texto):
    if pd.isna(texto) or not texto:
        return 'Sin transcripción'
    tl = str(texto).lower()
    planes = []
    if re.search(r'(?:plan\s+)?manad[aá]|plan\s+maná', tl):
        planes.append('Plan Manada')
    if re.search(r'(?:plan\s+)?premium', tl):
        planes.append('Plan Premium')
    if re.search(r'(?:plan\s+(?:de\s+)?)?mascota|asistencia\s+(?:de\s+)?mascota'
                 r'|(?:perrit[oa]|gatit[oa]|perro|gato)\b'
                 r'|veterinari[oa]|desparasita|chip\s+de\s+identificaci[oó]n'
                 r'|refuerzo\s+de\s+vacunas|cremaci[oó]n'
                 r'|atenci[oó]n\s+veterinaria|limpieza\s+dental', tl):
        planes.append('Plan Mascotas')
    if re.search(r'(?:plan\s+(?:de\s+)?)?salud|m[eé]dico\s+a\s+domicilio|pediatra\s+a\s+domicilio'
                 r'|videollamada\s+con\s+m[eé]dico|orientaci[oó]n\s+m[eé]dica'
                 r'|orientaci[oó]n\s+(?:nutricional|psicol[oó]gica)'
                 r'|psic[oó]logo\s+a\s+domicilio|acompa[nñ]ante\s+a\s+citas'
                 r'|urgencia\s+dental|valoraci[oó]n\s+dental', tl):
        planes.append('Plan Salud')
    if re.search(r'(?:plan\s+(?:de\s+)?)?movilidad|gr[uú]a|veh[ií]cul|\bcarro\b|\bmoto\b'
                 r'|cambio\s+de\s+llanta|reinicio\s+de\s+bater[ií]a'
                 r'|conductor\s+elegido|cerrajer[ií]a\s+vial|paso\s+de\s+corriente', tl):
        planes.append('Plan Movilidad')
    if not planes:
        return 'No identificado'
    for esp in ['Plan Manada', 'Plan Premium']:
        if esp in planes:
            return esp
    return planes[0]


def detectar_asistencia(texto, plan_mencionado):
    if pd.isna(texto) or not texto:
        return 'No identificado'
    tl = str(texto).lower()
    detectadas = [nombre for nombre, patron in CATALOGO_ASISTENCIAS if re.search(patron, tl)]
    return ', '.join(detectadas) if detectadas else 'No identificado'


def detectar_resultado_llamada(texto, transcripcion_v4):
    if pd.isna(texto) or not texto:
        return "Sin Contacto"
    tl = str(texto).lower()
    if len(tl.strip()) < 50:
        return "Sin Contacto"
    if re.search(r'buz[oó]n\s+de\s+voz|correo\s+de\s+voz|deje\s+su\s+mensaje|deja\s+tu\s+mensaje|servicio\s+de\s+contestador', tl):
        return "Buzón de Voz"
    turnos_cliente = transcripcion_v4.count('[Cliente]') if transcripcion_v4 else 0
    if turnos_cliente == 0 and len(tl.strip()) < 200:
        return "Buzón de Voz"
    if re.search(r'n[uú]mero\s+equivocado|no\s+(?:es\s+)?aqu[ií]|no\s+(?:lo\s+)?conozco|no\s+vive\s+aqu[ií]', tl):
        return "Número Equivocado"
    if re.search(r'no\s+se\s+encuentra|est[aá]\s+ocupad|llame\s+m[aá]s\s+tarde|no\s+puede\s+atender', tl):
        return "No Disponible"
    if re.search(r'procedemos|te\s+confirmo|queda\s+activ|listo[\s,]+(?:entonces\s+)?(?:queda|procedemos)', tl):
        return "Venta"
    if re.search(r'no\s+(?:me\s+)?interesa|no[\s,]+(?:no[\s,]+)?gracias|no\s+estoy\s+interesad'
                 r'|no\s+(?:quiero|necesito)', tl):
        return "Rechazado"
    if turnos_cliente >= 2:
        return "Contactado"
    return "Sin Clasificar"


def detectar_motivo_rechazo(texto, resultado_llamada):
    if resultado_llamada != "Rechazado":
        return "N/A"
    if pd.isna(texto) or not texto:
        return "Sin Motivo"
    tl = str(texto).lower()
    if re.search(r'ya\s+tengo|ya\s+cuento\s+con|ya\s+(?:estoy|tenemos)\s+(?:con|afiliado)', tl):
        return "Ya Tiene Servicio"
    if re.search(r'muy\s+caro|costoso|no\s+tengo\s+(?:plata|dinero)|no\s+(?:me\s+)?alcanza', tl):
        return "Precio"
    if re.search(r'yo\s+no\s+(?:hice|registr[eé])|no\s+(?:hice|realic[eé])\s+(?:ning[uú]n\s+)?registro', tl):
        return "No Recuerda Registro"
    if re.search(r'pens[eé]\s+que\s+era|cre[ií]\s+que|no\s+era\s+(?:eso|lo\s+que)', tl):
        return "Confusión"
    if re.search(r'no\s+tengo\s+(?:mascota|perro|gato|carro|moto|veh[ií]culo)', tl):
        return "No Aplica Servicio"
    return "No Interesa"


def detectar_tipo_mascota(texto, plan_mencionado):
    if plan_mencionado not in ["Plan Mascotas", "Plan Manada"]:
        return "N/A"
    if pd.isna(texto) or not texto:
        return "No especificado"
    tl = str(texto).lower()
    tiene_perro = bool(re.search(r'\bperr(?:o|ito|a|ita)s?\b|\bcachorro\b', tl))
    tiene_gato = bool(re.search(r'\bgat(?:o|ito|a|ita)s?\b|\bfelino\b', tl))
    if tiene_perro and tiene_gato: return "Ambos"
    if tiene_perro: return "Perro"
    if tiene_gato: return "Gato"
    return "No especificado"


def detectar_tipo_vehiculo(texto, plan_mencionado):
    if plan_mencionado != "Plan Movilidad":
        return "N/A"
    if pd.isna(texto) or not texto:
        return "No especificado"
    tl = str(texto).lower()
    es_moto = bool(re.search(r'\bmoto(?:cicleta|s)?\b|yamaha|bajaj|pulsar|\bakt\b', tl))
    es_carro = bool(re.search(r'\bcarro\b|\bcoche\b|\bveh[ií]culo\b|\bcamioneta\b'
                              r'|toyota|chevrolet|renault|mazda|hyundai|\bkia\b|nissan', tl))
    if es_moto and es_carro: return "Ambos"
    if es_moto: return "Moto"
    if es_carro: return "Carro"
    return "No especificado"


def detectar_saludo_completo(texto):
    if pd.isna(texto) or not texto:
        return "No"
    tl = str(texto).lower()
    n = sum([
        bool(re.search(r'tengo\s+el\s+gusto', tl)),
        bool(re.search(r'habl[aá]s?\s+con|me\s+llamo|soy\s+\w+\s+(?:de|desde)', tl)),
        bool(re.search(r'(?:cl[e ])?tiene\s*soluciones', tl)),
        bool(re.search(r'registro\s+que\s+(?:hiciste|realizaste|hizo)|me\s+(?:estoy\s+)?comunic', tl)),
    ])
    return "Sí" if n >= 3 else ("Parcial" if n >= 1 else "No")


def detectar_explico_beneficios(texto):
    if pd.isna(texto) or not texto:
        return "No"
    tl = str(texto).lower()
    beneficios = [
        r'beneficios?\b', r'servicio\s+de\s+gr[uú]a', r'videollamada',
        r'conductor\s+elegido', r'cambio\s+de\s+llanta', r'reinicio\s+de\s+bater[ií]a',
        r'asistencia\s+(?:24|las\s+24)', r'veterinari[oa]', r'cremaci[oó]n',
        r'cobertura\s+(?:a\s+nivel\s+)?nacional',
    ]
    matches = sum(1 for b in beneficios if re.search(b, tl))
    if matches >= 3: return "Sí"
    if matches >= 1: return "Parcial"
    return "No"


def detectar_ofrecio_whatsapp(texto):
    if pd.isna(texto) or not texto:
        return "No"
    tl = str(texto).lower()
    if re.search(r'(?:te\s+)?(?:env[ií]o|mando|dejo)\s+(?:un\s+)?(?:mensaje|informaci[oó]n)?\s*(?:por\s+)?whatsapp', tl):
        return "Sí"
    if re.search(r'whatsapp.*(?:env[ií]o|mando|escribo|informaci[oó]n)', tl):
        return "Sí"
    return "No"


def detectar_despedida_correcta(transcripcion_v4):
    if pd.isna(transcripcion_v4) or not transcripcion_v4:
        return "No"
    lineas = str(transcripcion_v4).strip().split('\n')
    ultimas = '\n'.join(lineas[-3:]).lower()
    for patron in [
        r'\[asesor\].*(?:que\s+)?(?:tenga|tengas)\s+(?:un\s+)?(?:buen|excelente)\s+(?:d[ií]a|tarde|noche)',
        r'\[asesor\].*feliz\s+(?:d[ií]a|tarde|noche)',
        r'\[asesor\].*hasta\s+(?:luego|pronto)',
        r'\[asesor\].*quedamos?\s+(?:atent[oa]s?|pendientes?)',
    ]:
        if re.search(patron, ultimas):
            return "Sí"
    return "No"


def contar_objeciones(texto):
    if pd.isna(texto) or not texto:
        return 0
    tl = str(texto).lower()
    patrones = [
        r'no\s+(?:me\s+)?interesa', r'no[\s,]+gracias',
        r'no\s+tengo\s+(?:tiempo|dinero|plata)', r'ya\s+tengo',
        r'muy\s+caro', r'no\s+puedo', r'no\s+(?:quiero|necesito)',
        r'ahora\s+no',
    ]
    return sum(len(re.findall(p, tl)) for p in patrones)


# ─── Procesamiento ────────────────────────────────────────────────────────────────

def procesar(df):
    df['Tipo_Llamada'] = df['Tipo_Llamada'].str.strip().replace({'Salientes': 'Saliente', 'Entrantes': 'Entrante'})
    # El origen trae las dos cosas con variantes: 'Salientes'/'Entrantes' (dirección) y
    # 'venta'/'servicios' (tipo). Sin esto el dropdown 'Tipo de Llamada' y la gráfica
    # 'Ventas vs Servicio' offered 4 opciones en vez de 2.
    df['tipo'] = df['tipo'].str.strip().str.lower().replace({'venta': 'ventas', 'servicios': 'servicio'})

    if REPROCESO_COMPLETO:
        log("  ⚠️ RE-PROCESO COMPLETO: ignorando cache; se re-procesan TODAS con el prompt actual (v15)")
        cache = {}
    else:
        log("  Cargando cache de BigQuery...")
        cache = cargar_cache_bigquery()
    log("  Estructurando transcripciones V4 con IA (async)...")
    df['Transcripcion_V4'] = estructurar_dialogos_ia(df['transcripcion'], df.get('Tipo_Llamada'), cache=cache)
    df['Num_Turnos_V4']     = df['Transcripcion_V4'].apply(
        lambda x: x.count('[Asesor]') + x.count('[Cliente]') if pd.notna(x) else 0)
    df['Turnos_Asesor_V4']  = df['Transcripcion_V4'].apply(
        lambda x: x.count('[Asesor]') if pd.notna(x) else 0)
    df['Turnos_Cliente_V4'] = df['Transcripcion_V4'].apply(
        lambda x: x.count('[Cliente]') if pd.notna(x) else 0)

    log("  Detectando planes y asistencias...")
    df['Plan_Mencionado'] = df['transcripcion'].apply(detectar_plan)
    df['Asistencia']      = df.apply(
        lambda r: detectar_asistencia(r['transcripcion'], r['Plan_Mencionado']), axis=1)

    log("  Analizando resultados y calidad...")
    df['Resultado_Llamada'] = df.apply(
        lambda r: detectar_resultado_llamada(r['transcripcion'], r['Transcripcion_V4']), axis=1)
    df['Motivo_Rechazo']    = df.apply(
        lambda r: detectar_motivo_rechazo(r['transcripcion'], r['Resultado_Llamada']), axis=1)
    df['Tipo_Mascota']      = df.apply(
        lambda r: detectar_tipo_mascota(r['transcripcion'], r['Plan_Mencionado']), axis=1)
    df['Tipo_Vehiculo']     = df.apply(
        lambda r: detectar_tipo_vehiculo(r['transcripcion'], r['Plan_Mencionado']), axis=1)

    df['Duracion_Estimada']   = df['Tiempo  de Conversacion'].apply(detectar_duracion_estimada)
    df['Saludo_Completo']     = df['transcripcion'].apply(detectar_saludo_completo)
    df['Explico_Beneficios']  = df['transcripcion'].apply(detectar_explico_beneficios)
    df['Ofrecio_WhatsApp']    = df['transcripcion'].apply(detectar_ofrecio_whatsapp)
    df['Despedida_Correcta']  = df['Transcripcion_V4'].apply(detectar_despedida_correcta)
    df['Num_Objeciones']      = df['transcripcion'].apply(contar_objeciones)

    return df


# ─── Subida a BigQuery ────────────────────────────────────────────────────────────

def sanitizar_columnas(df):
    df = df.copy()
    df.columns = [re.sub(r'[^\w]', '_', c).strip('_') for c in df.columns]
    return df


def subir_bigquery(df):
    client = bigquery.Client(project=BQ_PROJECT)
    tabla  = f"{BQ_PROJECT}.{BQ_DATASET}.{BQ_TABLA}"
    df = sanitizar_columnas(df)
    # Fechas como INTEGER en nanosegundos (contrato con el backend: el SQL usa
    # DATETIME(TIMESTAMP_MICROS(DIV(Fecha, 1000))) y los filtros UNIX_MICROS*1000).
    # pandas las trae como datetime64 y el autodetect de BigQuery las escribiría
    # como TIMESTAMP según la versión de pandas/pyarrow — da igual la versión:
    # convertirlas explícitamente a int64 (epoch en ns) mantiene el tipo estable.
    # Ojo: pandas >= 3.0 usa datetime64[us] por defecto; se fuerza [ns] sobre el
    # array numpy antes de verlo como int64 (si no, se guardarían µs y el backend
    # quedaría 1000x corto). Series no tiene `.view` en pandas 3, por eso `.to_numpy()`.
    for col in ("Fecha", "fecha_carga"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col]).astype("datetime64[ns]").to_numpy().view("int64")
    job_config = bigquery.LoadJobConfig(
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        autodetect=True,
    )
    job = client.load_table_from_dataframe(df, tabla, job_config=job_config)
    job.result()
    return len(df)


# ─── Pipeline ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    log("=" * 60)
    log("INICIO DE CARGA AUTOMÁTICA")
    log(f"  Modelo hablantes: {MODELO_HABLANTES} | Re-proceso completo: {REPROCESO_COMPLETO}")
    log("=" * 60)

    try:
        log("Conectando a SQL Server con cuenta CUN (Windows Auth)...")
        df = cargar_desde_sql()
        log(f"Filas cargadas: {len(df):,}")

        log("Procesando transcripciones...")
        df = procesar(df)

        log("Subiendo a BigQuery...")
        n = subir_bigquery(df)
        log(f"COMPLETADO: {n:,} filas subidas a {BQ_TABLA}")

    except Exception as e:
        log(f"ERROR: {e}")
        sys.exit(1)

    log("=" * 60)

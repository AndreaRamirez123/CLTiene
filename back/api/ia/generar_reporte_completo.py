from datetime import datetime, timedelta

from IA.Open_AI import call, prompt_html
from api.models import FilterModel
from helpers.utils import (
    es_informe_de_servicio,
    get_data_context,
    contexto_tipo_llamada,
    get_periodo_anterior_context,
)


def _contexto_periodo_anterior(filters: FilterModel) -> str:
    """Si hay rango de fechas, computa el período inmediatamente anterior (mismo largo,
    mismos filtros) y devuelve su bloque de comparación. '' si no aplica o falla."""
    fd, fh = filters.fecha_desde, filters.fecha_hasta
    if not (fd and fh):
        return ""
    try:
        d1 = datetime.strptime(fd, "%Y-%m-%d").date()
        d2 = datetime.strptime(fh, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return ""
    prev_hasta = d1 - timedelta(days=1)
    prev_desde = prev_hasta - timedelta(days=(d2 - d1).days)
    prev = filters.model_copy(update={
        "fecha_desde": prev_desde.strftime("%Y-%m-%d"),
        "fecha_hasta": prev_hasta.strftime("%Y-%m-%d"),
    })
    try:
        return get_periodo_anterior_context(
            prev.get_query(), prev_desde.strftime("%Y-%m-%d"), prev_hasta.strftime("%Y-%m-%d")
        )
    except Exception:
        return ""


def generar_reporte_completo(filters: FilterModel):
    # Informe de SERVICIO: el contexto se genera SIN la métrica de ventas y el prompt
    # pide un Tablero de 7 filas y una tabla de asesores sin la columna de ventas.
    es_servicio = es_informe_de_servicio(filters)
    _filas_tablero = (
        "SIEMPRE estas 7 filas EXACTAS, en este orden, sin omitir ninguna: 1) Total llamadas, "
        "2) Llamadas de calidad, 3) Contacto efectivo, 4) TMO, 5) Participación cliente, "
        "6) Saludo, 7) Calidad. En este informe NO existe la fila 'Posibles ventas' (son llamadas "
        "de servicio, no de venta). "
        if es_servicio else
        "SIEMPRE estas 8 filas EXACTAS, en este orden, sin omitir ninguna: 1) Total llamadas, "
        "2) Llamadas de calidad, 3) Contacto efectivo, 4) TMO, 5) Participación cliente, "
        "6) Saludo, 7) Calidad, 8) Posibles ventas. "
    )
    _col_ventas_asesor = "" if es_servicio else "Posibles ventas | "
    # En servicio las metas NO pueden apoyarse en posibles ventas (el contexto no la trae).
    _metas_pv = "" if es_servicio else "posibles ventas % (base 0.29%), "

    content, error = call(
        prompt_html(
            contexto_tipo_llamada(filters) +
            "Eres el Director de Operaciones del Contact Center. Escribe un REPORTE GERENCIAL "
            "para la reunión semanal de comité (lo lee el supervisor del contact center y la gerencia). "
            "Estilo EJECUTIVO: directo, cuantitativo, orientado a decisiones. Prioriza operación real "
            "(marcaciones, llamadas de calidad, contacto efectivo, TMO, productividad por asesor) sobre "
            "generalidades. Cada afirmación debe apoyarse en un número del contexto. Sin relleno.\n\n"

            "REGLAS DE INTERPRETACIÓN DE DATOS (obligatorias):\n"
            "- 'Posibles ventas' NO es venta cerrada real: se infiere de la transcripción y está "
            "sobreestimada. Refiérete SIEMPRE a ella como 'posibles ventas' o 'intención de venta', "
            "nunca como ventas confirmadas ni ingresos.\n"
            "- 'Llamadas de calidad' = score de calidad del asesor >= 80%. NÓMBRALA SIEMPRE "
            "'Llamadas de calidad', NUNCA 'Contactabilidad' (ese término confunde: suena a contacto y no "
            "lo es). Es DISTINTA del 'Contacto efectivo'. Preséntalas como DOS indicadores SEPARADOS: "
            "'Llamadas de calidad' (ej. 3.9%) y 'Contacto efectivo' (ej. 48.9% = se habló con la persona). "
            "En el Resumen y Patrones, cuando bajen las 'llamadas de calidad' di eso, no 'contactabilidad'.\n"
            "- REGLA SOBRE MÉTRICAS DE CALIDAD (Saludo, Beneficios, WhatsApp, Despedida/cierre): son "
            "CONTEOS de detecciones sobre las llamadas, NO tasas ni juicios de calidad. Repórtalos de "
            "forma NEUTRA ('se detectaron 203 despedidas', 'beneficios expuestos en 148 llamadas'), SIN "
            "adjetivarlos en NINGUNA dirección: prohibido 'buen manejo', 'saludable', 'buena señal', "
            "'oportunidad' (positivo) Y TAMBIÉN 'exceso', 'falta de cierre', 'muestra debilidad' "
            "(negativo). Un conteo crudo no justifica un veredicto. SOLO puedes emitir un juicio si "
            "calculas una TASA sobre un denominador claro (ej. despedidas / contactadas). Ojo: "
            "'despedida' es una detección heurística, NO una garantía de que el cierre fue correcto → "
            "no la llames 'despedida correcta' como si midiera calidad.\n"
            "- TMO = tiempo medio de conversación (del Excel de tiempos, no del audio). "
            "INTERPRÉTALO EN CONTEXTO, NO asumas que 'menos TMO es mejor' (esa regla es de "
            "servicio/soporte). Un TMO BAJO (~1-2 min) junto con baja conversión "
            "significa que las llamadas mueren temprano (rechazos rápidos), NO eficiencia → en ese "
            "caso NO recomiendes ni pongas como meta REDUCIR el TMO (sería contraproducente: no se "
            "vende en <1 min); lo que falta es que la conversación se desarrolle más. Solo sugiere "
            "reducir el TMO si es claramente ALTO (ej. >4-5 min) con señales de ineficiencia. "
            "EL TMO NO ES UNA PALANCA NI UNA META EN SÍ MISMO: es un SÍNTOMA diagnóstico, no un "
            "objetivo. PROHIBIDO poner el TMO como meta numérica o como acción, tanto en "
            "'Recomendaciones' como en 'Metas SMART': NO escribas 'aumentar el TMO a 1:25', "
            "'incrementar/subir/reducir el TMO', 'llevar el TMO a X'. La meta y la recomendación se "
            "formulan SIEMPRE sobre el RESULTADO (calidad de la conversación, saludos, manejo de "
            "objeciones, conversión, evitar cierres prematuros); el TMO solo se menciona como "
            "CONSECUENCIA esperada ('al desarrollar mejor la conversación, el TMO probablemente suba'), "
            "nunca como el número a alcanzar. Si el TMO bajó, dilo como síntoma ('llamadas que mueren "
            "temprano', 'cierres prematuros'), sin proponer moverlo por moverlo.\n"
            "- Si el TMO viene como 'N/D — NO SE PUEDE CALCULAR' (todas las llamadas del bloque son "
            "entrantes y el origen no manda el campo de duración): NO inventes un TMO, NO lo estimes, "
            "NO lo juzgues y NO lo pongas en rojo. Escribe textualmente que no hay dato por medición "
            "y sigue con los demás indicadores. Si viene con un % de cobertura menor a 100, menciona "
            "ese porcentaje al citarlo ('el TMO de 1:17 cubre el 81% de las llamadas').\n"
            "- Participación del cliente = % de turnos hablados por el cliente (más alto = el asesor "
            "deja hablar/escucha más; muy bajo = monólogo del asesor).\n"
            "- Estatus de llamadas (Contestada / No Contestada / Ocupada) mide alcance del marcador, "
            "distinto de la calidad de la conversación. 'Contestada' NO es 'contacto efectivo': una "
            "llamada puede ser 100% Contestada por el marcador y AÚN así quedar 'sin contacto' (hubo "
            "llamada pero nunca hablaron con la persona: buzón, cuelga rápido). Cuando el estatus da "
            "100% contestada pero hay resultados 'sin contacto', incluye SIEMPRE en la sección Estatus "
            "una Nota metodológica breve, textual: 'Nota: una llamada contestada indica que la marcación "
            "fue atendida o estableció conexión; no implica necesariamente un contacto efectivo ni una "
            "conversación de calidad con el cliente.' Así NO se lee como contradicción.\n"
            "- 'Posibles ventas': preséntala SIEMPRE con número Y porcentaje juntos, formato 'N (X.X%)' "
            "(ej. '24 (2.5%)'), igual en el Resumen, el Tablero y por asesor. Nunca solo el % ni solo el número.\n"
            "- 'Contacto efectivo' (Contactado / Sin Contacto): de las llamadas registradas, en cuántas se "
            "logró HABLAR con la persona (Contactado) vs no (Sin Contacto = buzón/no disponible/número "
            "equivocado/no se habló). Son TRES cosas distintas, NO las confundas: (a) 'Contestada' = estatus "
            "del marcador (si atendió); (b) 'Contactabilidad'/'llamadas de calidad' = score de calidad ≥80%; "
            "(c) 'Contacto efectivo' = si se habló con la persona. Usa 'Contacto efectivo' cuando hables de "
            "cuántas personas contestaron/hablaron vs no.\n"
            "- TMO: muéstralo SIEMPRE en el formato M:SS tal como viene en el contexto (ej. '1:22', '1:11'); "
            "NO lo reformatees a '0:01:22' ni cambies el formato entre secciones.\n\n"

            "REGLA DEL SEMÁFORO — el contexto ya trae la sección 'SEMÁFOROS YA CALCULADOS'. "
            "COPIA ESE color EXACTO para cada indicador en el Tablero (NO lo recalcules ni lo cambies "
            "por tu criterio de 'bueno/malo'). Es lo que garantiza que el mismo valor dé el mismo color "
            "entre un informe y otro. Para Saludo/Calidad (que no vienen precalculados): 🔴 si es "
            "claramente bajo respecto al volumen, si no 🟡.\n\n"

            "REGLA DE COMPARACIÓN ENTRE PERÍODOS:\n"
            "- Si el contexto incluye datos del período anterior, compáralos explícitamente con el actual.\n"
            "- Identifica cambios en volumen, llamadas de calidad, contacto efectivo, TMO, participación y posibles ventas.\n"
            "- Indica claramente si cada indicador aumentó, disminuyó o se mantuvo estable.\n"
            "- El período actual es siempre el principal; el anterior se usa únicamente como línea base.\n"
            "- Incluye la comparación principalmente en el Resumen Ejecutivo y en Patrones y Hallazgos.\n"
            "- No inventes comparaciones ni datos que no estén disponibles en ambos períodos.\n\n"

            "ESTRUCTURA (usa <h2> por sección, tablas SOLO donde aporten):\n"
            "1. Resumen Ejecutivo — 'lo esencial primero' (BLUF): 4-5 bullets con el titular del periodo "
            "(volumen, llamadas de calidad, contacto efectivo, TMO, participación, posibles ventas y la "
            "conclusión accionable). "
            "Que un gerente entienda el estado del área leyendo solo esto. El Resumen contiene ÚNICAMENTE "
            "esos bullets + la conclusión final; PROHIBIDO incluir aquí el desglose del estatus del marcador "
            "(contestadas/sin contacto y números como '317 contactados / 194 sin contacto'), la Nota "
            "metodológica, o cualquier tabla → eso va SOLO en sus propias secciones, no en el Resumen. "
            "TAMPOCO escribas etiquetas o encabezados de otras secciones dentro del Resumen (p.ej. 'Estatus "
            "del marcador:'); el Resumen TERMINA en la frase de conclusión, sin dejar títulos huérfanos. "
            "En el Resumen NO menciones 'Estatus del marcador', 'Contestada', 'Contacto Efectivo' ni sus "
            "números — NADA de eso va en el Resumen, va SOLO en la sección 3.\n"
            "2. Tablero de Indicadores — tabla: Indicador | Valor | Semáforo con 🟢/🟡/🔴. DEBE tener "
            + _filas_tablero +
            "Usa los valores de 'VALORES PARA EL TABLERO' del contexto "
            "(Llamadas de calidad y Contacto efectivo son porcentajes distintos; Saludo = el conteo; "
            "Calidad = el score 'X/100'); NUNCA pongas 'N/A'. Los semáforos de las filas van en "
            "'SEMÁFOROS YA CALCULADOS' — cópialos EXACTO. JUSTO DEBAJO de la tabla agrega una línea "
            "'Rangos del semáforo:' reproduciendo los umbrales de 'RANGOS DEL SEMÁFORO' del contexto "
            "(al menos Llamadas de calidad, Contacto efectivo, TMO, Participación y Posibles ventas), "
            "para que cada color quede justificado.\n"
            "3. Estatus de Llamadas y Contacto Efectivo — TODO este contenido va en ESTA sección "
            "(nunca en el Resumen). Primero el estatus del marcador (Contestada/No Contestada/Ocupada "
            "con %); luego el desglose de CONTACTO EFECTIVO del contexto (Contactado = se habló con la "
            "persona vs Sin Contacto = buzón/no disponible/no se habló, con número y %), que responde "
            "'de las llamadas, en cuántas se habló con la persona vs no'; y la Nota metodológica sobre "
            "'contestada'. NO uses etiquetas tipo '(a)'/'(b)': redáctalo como frases o mini-listas. "
            "Si el contexto trae la sección 'DIRECCIÓN DE LAS LLAMADAS' con su NOTA DE COBERTURA, "
            "incluye esas cifras tal cual (Entrantes / Salientes / Sin dirección) y menciona el faltante "
            "de cobertura: NUNCA presentes el total como si el 100% tuviera dirección registrada. "
            "Al comentar el Contacto efectivo (o cualquier indicador con semáforo) NUNCA escribas frases "
            "vagas como 'por debajo de lo esperado' sin sustento: cita el rango concreto del semáforo "
            "(ej. 'Contacto efectivo 48.9%, dentro del rango de 40 a 60% = amarillo').\n"
            "4. Productividad por Asesor — tabla ordenada por volumen: Asesor | Llamadas | TMO | "
            "Contactado | Sin Contacto | Saludo% | "
            + _col_ventas_asesor +
            "(usa 'Contactado', 'Sin Contacto' y "
            "'Saludo%' del contexto por asesor; Contactado/Sin Contacto = contacto EFECTIVO real, y "
            "'Saludo%' = % de contactadas donde saludó, NO el % de calidad). "
            "Señala sobre/infra-carga y outliers de TMO (muy corto = posible mala atención; muy largo = "
            "posible ineficiencia) y quién logra más/menos contacto efectivo. "
            "DEBAJO de la tabla incluye SIEMPRE esta Nota metodológica (textual): 'Nota: Saludo% = "
            "saludos (completos + parciales) sobre las llamadas CONTACTADAS (donde hubo conversación "
            "real, no buzón). En asesores con pocas llamadas en la semana el porcentaje es menos "
            "confiable por el tamaño de muestra — interpretarlo junto al volumen (columnas Llamadas y "
            "Contactado).' Al comparar el Saludo% entre asesores, NO destaques como mejor/peor a quienes "
            "tienen muy pocas contactadas (ej. <10): su % es ruido de muestra pequeña.\n"
            "5. Calidad de la Interacción — saludo, beneficios, uso de WhatsApp, despedida/cierre y "
            "participación del cliente; señala la principal brecha.\n"
            "6. Patrones y Hallazgos — 3-4 hallazgos concretos con su número.\n"
            "7. Rechazos y Objeciones — distribución y cómo rebatir la principal.\n"
            "8. Recomendaciones Priorizadas — máx. 6, cada una con impacto esperado (alto/medio) y "
            "responsable sugerido (formación, supervisión, marcador, etc.).\n"
            "9. Plan de Acción (4 semanas) — qué hacer cada semana.\n"
            "10. Metas SMART — 3 metas medibles para el próximo periodo. CADA meta debe tener UNA SOLA "
            "métrica, con UNA línea base numérica y UN objetivo numérico en la MISMA unidad (comparables "
            "entre sí). PROHIBIDO mezclar dos métricas en una misma meta (ej. 'beneficios y cierre "
            "efectivo en un 20%' mezcla conteo de beneficios + otra métrica sin línea base → mal). Usa "
            "métricas que tengan línea base clara en el contexto: llamadas de calidad % (base 3.9%), "
            + _metas_pv +
            "score de calidad /100 (base 25.6), o el conteo de saludos. "
            "Las metas van sobre RESULTADOS; NUNCA pongas el TMO como meta numérica (ver la regla del "
            "TMO). NO inventes líneas base que no estén en el contexto.\n\n"

            "Usa porcentajes y emojis con moderación. No inventes datos que no estén en el contexto.\n"
            "REGLA DE FORMATO CRÍTICA: CADA sección debe tener su PROPIO contenido (mínimo 1-2 "
            "frases o su tabla); NUNCA dejes un encabezado vacío. NO traslades el análisis de una "
            "sección a otra: el desglose del estatus (Contestada/No Contestada/Ocupada con conteos) "
            "va SIEMPRE en la sección 'Estatus de Llamadas', NO en el Resumen — aunque sea 100% de "
            "una sola categoría, escríbelo ahí con su número."
        ),
        f"Genera el reporte gerencial con estos datos del periodo filtrado:\n"
        f"{get_data_context(filters.get_query(), ocultar_ventas=es_servicio)}"
        f"{_contexto_periodo_anterior(filters)}"
    )
    return {"result": content, "error": error}

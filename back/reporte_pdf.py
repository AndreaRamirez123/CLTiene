"""Generación del PDF del Reporte Ejecutivo en el backend (WeasyPrint).

Reemplaza la generación con jsPDF que hoy hace el frontend (ReporteCompleto.jsx)
cuando se genera el PDF a mano. Recibe el FRAGMENTO HTML que produce la IA en
/ia/reporte_completo, lo normaliza (tema claro + emojis del semáforo a palabras,
igual que el clean() del frontend) y lo envuelve en un documento HTML con el
branding de CL Tiene para renderizarlo a PDF con WeasyPrint.

El diseño replica EXACTAMENTE el del frontend (jsPDF): banda rosa a sangre con
título + logo, línea de período, títulos de sección con regla rosa, panel de
Resumen Ejecutivo, badges de semáforo a color y pie con numeración.

Sin dependencias de red ni de la red CUN: solo procesa el HTML en memoria.
"""
import base64
import os
import re
from datetime import date

# Sanitización de EMOCIONES del semáforo y caracteres problemáticos: mapeado a
# palabras (igual que el clean() de ReporteCompleto.jsx), porque la fuente
# estándar de PDF no renderiza emojis de color. WeasyPrint sí soporta Unicode,
# así que NO se hace el strip de Latin-1 (eso era una limitación de jsPDF).
_EMOJI_REPLACES = [
    ("🟢", "Verde"), ("🟡", "Amarillo"), ("🟠", "Amarillo"),
    ("🔴", "Rojo"), ("⚪", "N/D"), ("🔵", "Azul"),
    ("→", "&rarr;"), ("★", "&star;"), ("“", "&ldquo;"), ("”", "&rdquo;"),
    ("‘", "&lsquo;"), ("’", "&rsquo;"), ("–", "-"), ("—", "-"), ("…", "&hellip;"),
]

# Badges de semáforo: misma paleta que STATUS en ReporteCompleto.jsx.
_BADGES = {
    "verde": "#16a34a", "amarillo": "#d97706", "naranja": "#d97706",
    "rojo": "#dc2626", "n/d": "#94a3b8", "azul": "#2563eb",
}


def _limpiar_fondo_oscuro(html: str) -> str:
    """Pasa los estilos oscuros que emite la IA a tema claro (igual que
    limpiarHTML del frontend) para que el PDF sea legible sin fondo negro."""
    replacements = [
        (r"background-color\s*:\s*rgb\(\s*15\s*,\s*23\s*,\s*42\s*\)", "background-color: #ffffff"),
        (r"color\s*:\s*rgb\(\s*203\s*,\s*213\s*,\s*225\s*\)", "color: #334155"),
        (r"color\s*:\s*rgb\(\s*148\s*,\s*163\s*,\s*184\s*\)", "color: #64748b"),
        (r"border(?:-bottom)?\s*:\s*1px solid rgb\(\s*30\s*,\s*41\s*,\s*59\s*\)", "border-bottom: 1px solid #e2e8f0"),
    ]
    out = html
    for patron, reemplazo in replacements:
        out = re.sub(patron, reemplazo, out, flags=re.IGNORECASE)
    return out


def _emojis_a_texto(html: str) -> str:
    for emoji, palabra in _EMOJI_REPLACES:
        html = html.replace(emoji, palabra)
    return html


def _texto_celda(inner: str) -> str:
    t = re.sub(r"<[^>]+>", "", inner)
    return re.sub(r"\s+", " ", t).strip()


def _badges_tablas(html: str) -> str:
    """Convierte el semáforo de las TABLAS en pills de color con texto blanco
    (igual que el renderRow con badges de ReporteCompleto.jsx) y centra la
    columna de semáforo. El resto: col 0 a la izquierda, numéricas a la derecha
    (CSS). Detecta por el texto limpio (Verde/Amarillo/Rojo/N/D/Azul) ya
    normalizado por _emojis_a_texto."""

    def _merge_class(attrs: str, extra: str) -> str:
        mkl = re.search(r"class\s*=\s*[\"']([^\"']*)[\"']", attrs)
        if mkl:
            return attrs[:mkl.start()] + f'class="{mkl.group(1)} {extra}"' + attrs[mkl.end():]
        sep = "" if (not attrs or attrs[-1] in " \t") else " "
        return f"{attrs}{sep}class=\"{extra}\""

    def _procesar(tbl: str) -> str:
        filas = list(re.finditer(r"<tr\b[^>]*>.*?</tr>", tbl, re.DOTALL | re.IGNORECASE))
        if not filas:
            return tbl

        # Fase 1: columnas que son semáforo (alguna celda de datos con badge)
        status_cols: set[int] = set()
        for m in filas:
            celdas = list(re.finditer(r"<(td|th)\b([^>]*)>(.*?)</\1>", m.group(0), re.DOTALL | re.IGNORECASE))
            for idx, cm in enumerate(celdas):
                if cm.group(1).lower() == "td" and _texto_celda(cm.group(3)).lower() in _BADGES:
                    status_cols.add(idx)
        if not status_cols:
            return tbl

        # Fase 2: reescribir celdas (de atrás hacia adelante para no romper indices)
        out = tbl
        for m in reversed(filas):
            fila = m.group(0)
            celdas = list(re.finditer(r"<(td|th)\b([^>]*)>(.*?)</\1>", fila, re.DOTALL | re.IGNORECASE))
            nueva = fila
            for idx, cm in reversed(list(enumerate(celdas))):
                tag, attrs, inner = cm.group(1).lower(), cm.group(2), cm.group(3)
                txt = _texto_celda(inner)
                key = txt.lower()
                if tag == "td" and key in _BADGES:
                    inner = f'<span class="badge" style="background:{_BADGES[key]}">{txt}</span>'
                else:
                    inner = cm.group(3)
                if idx in status_cols:
                    attrs = _merge_class(attrs, "sc")
                nueva = nueva[:cm.start()] + f"<{tag}{attrs}>{inner}</{tag}>" + nueva[cm.end():]
            out = out[:m.start()] + nueva + out[m.end():]
        return out

    return re.sub(
        r"<table\b.*?</table>",
        lambda m: _procesar(m.group(0)),
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )


def _panelizar_resumen(html: str) -> str:
    """Envuelve el bloque del Resumen Ejecutivo (hasta el siguiente encabezado)
    en un panel destacado (fondo claro + barra rosa), igual al panelResumen del
    frontend."""
    m = re.search(
        r"(<h[12]\b[^>]*>\s*Resumen\s*Ejecutivo\s*</h[12]>)(.*?)(?=<h[1-3]\b)",
        html, re.DOTALL | re.IGNORECASE,
    )
    if not m or not re.search(r"<\w+", m.group(2)):
        return html
    panel = f"{m.group(1)}\n<div class=\"panel\">{m.group(2)}</div>\n"
    return html[:m.start()] + panel + html[m.end():]


def _logo_data_uri(ruta=None):
    """Devuelve la imagen del logo como data URI (embebida, sin depender del FS
    al renderizar). Si no existe, devuelve None (el header sale sin logo)."""
    ruta = ruta or os.path.join(os.path.dirname(__file__), "assets", "logo_cl_tiene.png")
    if not os.path.exists(ruta):
        return None
    with open(ruta, "rb") as f:
        return "data:image/png;base64," + base64.b64encode(f.read()).decode("ascii")


_CSS = """
@page {
    size: A4;
    margin: 46pt 44pt 56pt 44pt;
    @bottom-left {
        content: "CL Tiene Soluciones - DivergencyAI SAS  |  Confidencial";
        color: #969696; font: 8pt 'DejaVu Sans', sans-serif;
        border-top: 0.5pt solid #e4e4e4; padding-top: 4pt;
    }
    @bottom-center { content: ""; border-top: 0.5pt solid #e4e4e4; }
    @bottom-right {
        content: "Página " counter(page) " de " counter(pages);
        color: #969696; font: 8pt 'DejaVu Sans', sans-serif;
        border-top: 0.5pt solid #e4e4e4; padding-top: 4pt;
    }
}
* { box-sizing: border-box; }
body { font-family: 'DejaVu Sans', Arial, sans-serif; color: #334155; font-size: 10pt; line-height: 1.6; margin: 0; }

/* Banda rosa a sangre (igual al encabezado del frontend) */
.band {
    display: flex; align-items: center; justify-content: space-between;
    margin: -46pt -44pt 14pt -44pt;
    background: #FC3276; padding: 16pt 44pt;
}
.band-title { color: #ffffff; font-size: 16pt; font-weight: bold; }
.band-sub { color: #ffffff; font-size: 10pt; }
.band-logo img { height: 28pt; width: auto; }
.meta { font-size: 9pt; color: #787878; margin: 0 0 8pt; }

/* Títulos de sección: regla rosa corta + línea gris larga (igual seccion() del frontend) */
h1,h2,h3 { color: #1e293b; font-weight: bold; }
h1 { font-size: 14pt; margin: 16pt 0 4pt; padding-bottom: 6pt; }
h2 { font-size: 13pt; margin: 16pt 0 4pt; padding-bottom: 6pt; }
h3 { font-size: 12pt; margin: 12pt 0 4pt; padding-bottom: 6pt; }
h1, h2, h3 {
    background: linear-gradient(to right, #FC3276 0pt, #FC3276 46pt, #e2e8f0 46pt);
    background-size: 100% 1.2pt; background-repeat: no-repeat;
    background-position: 0 100%; border-bottom: none;
}
p, ul, ol { margin: 4pt 0 8pt; }
ul, ol { padding-left: 20pt; }
li { margin: 2pt 0; }
strong, b { color: #1e293b; }
blockquote { border-left: 3pt solid #FC3276; margin: 8pt 0; padding: 4pt 12pt; color: #475569; background: #fff5f9; }

/* Panel de Resumen Ejecutivo */
.panel {
    background: #f8fafc; border: 1pt solid #e2e8f0; border-radius: 7px;
    border-left: 4pt solid #FC3276; padding: 10pt 14pt; margin: 6pt 0 14pt;
}
.panel ul, .panel ol { padding-left: 20pt; margin: 6pt 0; }
.panel li::marker { color: #FC3276; }
.panel p { margin: 6pt 0; }
.panel ul + p, .panel ol + p { font-weight: bold; color: #1e293b; }

/* Segmentación por dirección (informes segmentados): cada bloque arranca en página
   nueva y lleva su encabezado. El script solo marca los bloques 2..N. */
.bloque { break-before: page; }
.bloque h1.portadilla {
    font-size: 15pt; margin: 0 0 2pt; padding: 0 0 6pt; background: none;
    border-bottom: 2.5pt solid #FC3276;
}
.bloque p.portadilla-sub {
    font-size: 9pt; color: #787878; margin: 0 0 12pt; font-style: italic;
}
.bloque-nota {
    background: #f8fafc; border: 1pt solid #e2e8f0; border-radius: 7px;
    padding: 8pt 12pt; margin: 0 0 12pt; font-size: 9pt; color: #475569;
}

/* Tablas: encabezado rosa, zebra, col0 izquierda, numéricas derecha, semáforo centrado */
table { width: 100%; border-collapse: collapse; margin: 6pt 0 14pt; font-size: 9pt; }
th { background: #FC3276; color: #ffffff; font-weight: bold; padding: 7pt 10pt; }
td { padding: 6pt 10pt; border-bottom: 1pt solid #e2e8f0; vertical-align: top; }
th, td { text-align: right; }
tr > :first-child { text-align: left; }
th.sc, td.sc { text-align: center; }
tr:nth-child(even) td { background: #f8fafc; }
.badge {
    display: inline-block; color: #ffffff; font-weight: bold;
    padding: 2pt 9pt; border-radius: 5px;
}
"""


def html_a_pdf(
    html_fragmento: str,
    periodo: str = "",
    logo_path: str | None = None,
    titulo: str = "Reporte Estratégico de Operaciones",
    subtitulo: str = "CL Tiene Soluciones - Agente IA PRO (DivergencyAI SAS)",
) -> bytes:
    """Convierte el fragmento HTML del reporte a bytes PDF (WeasyPrint).

    Diseño idéntico al PDF del frontend (ReporteCompleto.jsx): banda rosa con
    título + logo, línea de período, panel de resumen, badges y pie numerado.

    `titulo`/`subtitulo` son opcionales: con los valores por defecto la salida es
    idéntica a la del reporte semanal (los usa el informe segmentado para
    distinguir "Reporte de VENTAS" de "Reporte de SERVICIO").
    """
    from weasyprint import HTML

    cuerpo = _emojis_a_texto(_limpiar_fondo_oscuro(str(html_fragmento or "")))
    cuerpo = _panelizar_resumen(cuerpo)
    cuerpo = _badges_tablas(cuerpo)

    logo = _logo_data_uri(logo_path)
    img_html = f'<div class="band-logo"><img src="{logo}" alt="CL Tiene" /></div>' if logo else ""

    hoy = date.today().strftime("%d/%m/%Y")
    periodo_label = f"Período: {periodo}" if periodo else "Período: todo el histórico"

    doc = f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8"/>
<title>Reporte Ejecutivo CLTiene</title>
<style>{_CSS}</style>
</head><body>
<div class="band">
  <div>
    <div class="band-title">{titulo}</div>
    <div class="band-sub">{subtitulo}</div>
  </div>
  {img_html}
</div>
<div class="meta">Generado: {hoy}  |  {periodo_label}</div>
{cuerpo}
</body></html>"""

    return HTML(string=doc).write_pdf()
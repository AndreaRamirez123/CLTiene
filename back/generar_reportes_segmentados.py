#!/usr/bin/env python3
"""Genera los 2 INFORMES SEGMENTADOS en PDF (Ventas / Servicio) a disco local.

Por qué segmentar: el reporte semanal único mezclaba las dos líneas de negocio y no
separaba por DIRECCIÓN de llamada. Este script produce EXACTAMENTE 2 archivos:

  1. reporte_ventas_<desde>_<hasta>.pdf
  2. reporte_servicio_<desde>_<hasta>.pdf

y cada uno contiene 2 BLOQUES (apartados), uno por dirección:

  A. ENTRANTES      (Tipo_Llamada = 'Entrante')
  B. SALIENTES      (Tipo_Llamada = 'Saliente')

El bucket "Sin dirección" (Tipo_Llamada IS NULL, ~49% del histórico) existe en la
tabla pero se EXCLUYÓ de los informes a pedido del usuario: es un hueco del origen,
no una categoría de negocio, y el corte que importa es Ventas vs Servicio.

Cada bloque es un reporte completo independiente: `generar_reporte_completo()`
con los filtros del tipo (ventas/servicio) + la dirección override, su propio
contexto de datos y su propio PDF-render (portadilla + salto de página).

El bloque de SERVICIO se genera SIN la métrica de ventas: `get_data_context(
ocultar_ventas=True)` no la incluye en el contexto y el prompt pide un Tablero de
7 filas y la tabla de asesores sin esa columna (ver `contexto_tipo_llamada()`).

AUDITORÍA DE SOLO LECTURA — este script NO envía correo, NO registra en
`cltiene_reportes_enviados` y NO toca el Cloud Run Job ni el Cloud Scheduler.
Solo lee BigQuery y escribe archivos en `--outdir`.

Flags:
  --fecha-desde X     override del período (YYYY-MM-DD). Por defecto se toma la
  --fecha-hasta Y     última semana COMPLETA que existe en la BD (lunes→domingo).
  --tipos a,b         qué informes generar (default: ventas,servicio).
  --direcciones a,b   qué bloques incluir (default: entrantes,salientes).
  --outdir PATH       carpeta de salida (default: ./reportes_segmentados).
  --solo-html         escribe el HTML y NO rasteriza el PDF (revisión rápida).
  --forzar            genera el bloque aunque tenga 0 filas (por defecto se omite).

Exit codes: 0 ok · 1 error de proceso (modelo/argumentos/periodo sin datos).
"""

import argparse
import os
import re
import sys
from datetime import date, datetime

os.environ.setdefault("CLOUD_PROJECT", os.getenv("GOOGLE_CLOUD_PROJECT", "desarrollo-investigaciones"))

from dotenv import load_dotenv

load_dotenv()

from api.database import client
from api.models import FilterModel
from api.ia.generar_reporte_completo import generar_reporte_completo
from helpers.sql import TABLE
from reporte_pdf import html_a_pdf
from enviar_reporte_semanal import _max_fecha_bd, _semana_desde_max

# (etiqueta para el informe, valor del filtro seguimiento_llamada, slug)
# Solo Entrantes/Salientes: el bucket "Sin dirección" (Tipo_Llamada vacío en el
# origen) se excluyó a pedido del usuario; el corte que importa es Ventas vs Servicio.
DIRECCIONES = [
    ("Entrantes", "Entrante", "entrantes"),
    ("Salientes", "Saliente", "salientes"),
]
DIRECCIONES_POR_SLUG = {slug: (etiqueta, valor) for etiqueta, valor, slug in DIRECCIONES}

# (tipo en la columna `tipo`, etiqueta para el informe)
TIPOS = [("ventas", "Ventas"), ("servicio", "Servicio")]


def _validar_fecha(texto: str) -> date:
    try:
        return datetime.strptime(texto, "%Y-%m-%d").date()
    except ValueError:
        sys.exit(f"Fecha inválida: {texto!r} (espera YYYY-MM-DD)")


def nombre_archivo(tipo: str, desde: date, hasta: date) -> str:
    return f"reporte_{tipo}_{desde.isoformat()}_{hasta.isoformat()}.pdf"


def _filtros(tipo: str, desde: date, hasta: date, valor_direccion: str) -> FilterModel:
    """FilterModel del bloque. `valor_direccion='null'` es el centinela que
    `filters()` traduce a `Tipo_Llamada IS NULL` (bucket 'Sin dirección')."""
    return FilterModel(
        fecha_desde=desde.isoformat(),
        fecha_hasta=hasta.isoformat(),
        tipo_llamada=tipo,
        seguimiento_llamada=valor_direccion,
    )


def _portadilla(etiqueta_tipo: str, etiqueta_direccion: str, filas: int, total_tipo: int, con_datos: bool) -> str:
    """Encabezado del bloque: a qué informe y a qué dirección pertenece, con su peso."""
    pct = filas / total_tipo * 100 if total_tipo else 0
    sub = (
        f"{etiqueta_tipo} · {etiqueta_direccion} · {filas:,} llamadas ({pct:.1f}% del frente {etiqueta_tipo.lower()})"
    )
    return (
        f'<h1 class="portadilla">{etiqueta_tipo} — {etiqueta_direccion}</h1>\n'
        f'<p class="portadilla-sub">{sub}</p>'
    )


def _bloque_vacio(etiqueta_tipo: str, etiqueta_direccion: str) -> str:
    return (
        f'<h1 class="portadilla">{etiqueta_tipo} — {etiqueta_direccion}</h1>'
        f'<p class="portadilla-sub">Sin llamadas en el período para esta combinación</p>'
        f'<div class="bloque-nota">No hay llamadas de tipo {etiqueta_tipo.lower()} con esta '
        f'dirección en el período analizado, por lo que no se genera análisis para este bloque.</div>'
    )


def _limpiar(html: str) -> str:
    """Quita el encabezado de nivel superior que emite la IA si lo hubiera (el
    bloque ya tiene su portadilla) y normaliza saltos de línea excessive."""
    html = re.sub(r"<h1\b[^>]*>.*?</h1>", "", html, count=1, flags=re.DOTALL | re.IGNORECASE)
    return re.sub(r"\n{3,}", "\n\n", html).strip()


def generar_un_informe(tipo: str, etiqueta_tipo: str, desde: date, hasta: date,
                       direcciones: list, forzar: bool = False) -> tuple[str, list]:
    """Genera el cuerpo HTML del informe de UN tipo (3 bloques) y devuelve
    (html, resumen_por_bloque). No escribe archivos."""
    bloques, resumen = [], []
    print(f"\n=== Informe {etiqueta_tipo.upper()} ({desde} a {hasta}) ===")

    for etiqueta_dir, valor_dir, slug in direcciones:
        filtros = _filtros(tipo, desde, hasta, valor_dir)
        n = _contar_filas(filtros)
        total_tipo = _total_tipo(tipo, desde, hasta)
        pct = n / total_tipo * 100 if total_tipo else 0
        resumen.append((etiqueta_dir, n, pct))

        if n == 0 and not forzar:
            print(f"  [OMITE] {etiqueta_dir}: 0 filas")
            # Aunque esté vacío es un apartado del informe: si no es el primero
            # abre página para que la nota no quede pegada al bloque anterior.
            clase = ' class="bloque"' if bloques else ""
            bloques.append(f"<div{clase}>\n{_bloque_vacio(etiqueta_tipo, etiqueta_dir)}\n</div>")
            continue

        print(f"  [BLOQUE] {etiqueta_dir}: {n} llamadas ({pct:.1f}% del frente) · generando…", flush=True)
        resp = generar_reporte_completo(filtros)
        if resp.get("error") or not resp.get("result"):
            sys.exit(f"[ERROR] {etiqueta_tipo}/{etiqueta_dir}: {resp.get('error') or 'respuesta vacía'}")

        cuerpo = _limpiar(resp["result"])
        # Solo los bloques 2..N llevan `class="bloque"` (salto de página); el primero
        # va pegado a la banda del encabezado.
        clase = ' class="bloque"' if bloques else ""
        bloques.append(
            f"<div{clase}>\n{_portadilla(etiqueta_tipo, etiqueta_dir, n, total_tipo, True)}\n{cuerpo}\n</div>"
        )
        print(f"           listo ({len(cuerpo):,} chars de HTML)")

    html = "\n".join(bloques)
    return html, resumen


def _contar_filas(filters: FilterModel) -> int:
    q = f"""
    SELECT COUNT(*) AS n
    FROM {TABLE}
    WHERE {filters.get_query()}
    """
    row = dict(list(client.query(q).result())[0])
    return int(row["n"] or 0)


def _total_tipo(tipo: str, desde: date, hasta: date) -> int:
    q = f"""
    SELECT COUNT(*) AS n
    FROM {TABLE}
    WHERE tipo = '{tipo}'
      AND Fecha >= UNIX_MICROS(TIMESTAMP('{desde.isoformat()}')) * 1000
      AND Fecha <= UNIX_MICROS(TIMESTAMP('{hasta.isoformat()} 23:59:59')) * 1000
    """
    row = dict(list(client.query(q).result())[0])
    return int(row["n"] or 0)


def main():
    ap = argparse.ArgumentParser(description="Genera los 2 informes segmentados (Ventas/Servicio) en PDF.")
    ap.add_argument("--fecha-desde", type=str, default=None, help="override período (YYYY-MM-DD)")
    ap.add_argument("--fecha-hasta", type=str, default=None, help="override período (YYYY-MM-DD)")
    ap.add_argument("--tipos", type=str, default="ventas,servicio", help="ventas,servicio")
    ap.add_argument("--direcciones", type=str, default="entrantes,salientes",
                    help="entrantes,salientes")
    ap.add_argument("--outdir", type=str, default="reportes_segmentados", help="carpeta de salida")
    ap.add_argument("--solo-html", action="store_true", help="escribe el HTML y no rasteriza el PDF")
    ap.add_argument("--solo-pdf", action="store_true",
                    help="re-rasteriza el PDF desde el HTML ya generado (no llama al modelo)")
    ap.add_argument("--forzar", action="store_true", help="genera el bloque aunque tenga 0 filas")
    args = ap.parse_args()

    if args.fecha_desde and args.fecha_hasta:
        desde, hasta = _validar_fecha(args.fecha_desde), _validar_fecha(args.fecha_hasta)
        print(f"[INICIO] Período manual: {desde} a {hasta}")
    else:
        max_fecha = _max_fecha_bd()
        if max_fecha is None:
            sys.exit("[ERROR] BigQuery sin datos.")
        desde, hasta = _semana_desde_max(max_fecha)
        print(f"[AUTO] MAX(Fecha)={max_fecha} → última semana completa: {desde} a {hasta}")

    tipos = [t.strip().lower() for t in args.tipos.split(",") if t.strip()]
    etiquetas = dict(TIPOS)
    for t in tipos:
        if t not in etiquetas:
            sys.exit(f"[ERROR] tipo desconocido: {t!r} (usa ventas,servicio)")

    dirs_slugs = [d.strip().lower() for d in args.direcciones.split(",") if d.strip()]
    for d in dirs_slugs:
        if d not in DIRECCIONES_POR_SLUG:
            sys.exit(f"[ERROR] dirección desconocida: {d!r} (usa entrantes,salientes)")
    direcciones = [(etiqueta, valor, slug) for etiqueta, valor, slug in DIRECCIONES
                    if slug in dirs_slugs]

    os.makedirs(args.outdir, exist_ok=True)
    periodo_txt = f"{desde.strftime('%d/%m/%Y')} al {hasta.strftime('%d/%m/%Y')}"
    resumen_global = []

    for tipo in tipos:
        etiqueta_tipo = etiquetas[tipo]
        ruta_html = os.path.join(args.outdir, nombre_archivo(tipo, desde, hasta).replace(".pdf", ".html"))

        if args.solo_pdf:
            # Re-rasteriza el HTML ya generado (iterar maquetación sin gastar tokens).
            if not os.path.exists(ruta_html):
                sys.exit(f"[ERROR] --solo_pdf requiere el HTML previo: {ruta_html}")
            with open(ruta_html, encoding="utf-8") as f:
                html = f.read()
            print(f"\n=== Informe {etiqueta_tipo.upper()}: re-rasterizando HTML existente ===")
            resumen = [(etiqueta_dir, 0, 0.0) for etiqueta_dir, _, _ in direcciones]
        else:
            html, resumen = generar_un_informe(tipo, etiqueta_tipo, desde, hasta, direcciones, args.forzar)
            with open(ruta_html, "w", encoding="utf-8") as f:
                f.write(html)
            print(f"[HTML] {ruta_html} ({os.path.getsize(ruta_html):,} bytes)")

        if args.solo_html:
            print("[SKIP] --solo-html: no se rasterizó el PDF.")
            continue

        resumen_global.append((etiqueta_tipo, resumen))
        pdf = html_a_pdf(
            html,
            periodo_txt,
            titulo=f"Reporte de {etiqueta_tipo.upper()} — Segmentado por dirección",
            subtitulo="CL Tiene Soluciones - Agente IA PRO (DivergencyAI SAS)",
        )
        ruta_pdf = os.path.join(args.outdir, nombre_archivo(tipo, desde, hasta))
        with open(ruta_pdf, "wb") as f:
            f.write(pdf)
        print(f"[PDF]  {ruta_pdf} ({len(pdf):,} bytes)")

    if not args.solo_pdf:
        print("\n=== RESUMEN DE BLOQUES ===")
        for etiqueta_tipo, resumen in resumen_global:
            total = sum(n for _, n, _ in resumen) or 1
            for etiqueta_dir, n, pct in resumen:
                print(f"  {etiqueta_tipo:9s} · {etiqueta_dir:13s}: {n:5d}  ({n/total*100:5.1f}% del informe)")
    print("[OK] Informes segmentados generados a disco. NO se envió ningún correo.")


if __name__ == "__main__":
    main()

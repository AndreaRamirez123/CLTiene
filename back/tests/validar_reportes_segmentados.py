"""Validador de los 3 PDF (general + ventas + servicio); no destructivo, solo lectura.

Uso:  python tests/validar_reportes_segmentados.py [carpeta]
"""
import io
import os
import re
import sys

from pypdf import PdfReader

CARPETA = sys.argv[1] if len(sys.argv) > 1 else "reportes_segmentados"

MALES = [r"\bNone\b", r"\bnan\b", r"\bN/A\b", r"\bundefined\b", r"\bnull\b", r"\{[a-z_]+\}",
         r"rgb\(", r"Segun", r"NaN", r"0 (100)?\.[0-9]% \u0000"]
EXPECTED = {
    "reporte_ventas": [r"Ventas\s*.{0,3}\s*Entrantes", r"Ventas\s*.{0,3}\s*Salientes"],
    "reporte_servicio": [r"Servicio\s*.{0,3}\s*Entrantes", r"Servicio\s*.{0,3}\s*Salientes"],
    # El general es el que va por correo: un solo informe, sin portadillas por bloque,
    # pero con el desglose de DIRECCIÓN.
    "reporte_general": [r"ntrantes", r"alientes"],
}
# El bucket "Sin dirección" se excluyó de los 3 informes: no debe aparecer en ninguno.
PROHIBIDO_TODOS = ["Sin dirección", "sin dirección", "Sin direcci"]
# En el informe de SERVICIO no debe aparecer la m\u00e9trica de ventas.
PROHIBIDO_SERVICIO = ["Posibles ventas", "posibles ventas", "oportunidades de venta"]


def texto_pdf(ruta):
    lector = PdfReader(ruta)
    return [p.extract_text() or "" for p in lector.pages]


def revisar(frente):
    base = os.path.join(CARPETA, f"{frente}_2026-09-14_2026-09-20")
    pdf, html = base + ".pdf", base + ".html"
    print(f"\n=== {frente.upper()} ===")
    for f in (base + ".pdf", html):
        if os.path.exists(f):
            print(f"  {os.path.basename(f):58s} {os.path.getsize(f):>8,} bytes")
        else:
            print(f"  {os.path.basename(f):58s} {'(no existe)':>13s}")

    paginas = texto_pdf(pdf)
    completo = "\n".join(paginas)
    print(f"  p\u00e1ginas PDF: {len(paginas)}")

    # El em-dash se extrae como guion corto desde el PDF: se busca con tolerancia.
    bloques = [(i + 1, m.group(0)) for i, p in enumerate(paginas)
               for pat in EXPECTED[frente]
               for m in [re.search(pat, p)] if m]
    if bloques:
        print("  p\u00e1gina de cada bloque: "
              + ", ".join(f"{h}={i}" for i, h in bloques))

    # Los residuos/nulos se miden SIEMPRE en el PDF (el general no tiene sidecar HTML).
    def residuos(texto):
        return sorted({m for pat in MALES for m in re.findall(pat, texto)})

    hallados = residuos(completo)
    print(f"  PDF residuos/nulos: {hallados if hallados else 'ninguno'}")
    for h in EXPECTED[frente]:
        print(f"  PDF contiene '{h}': {bool(re.search(h, completo))}")

    if os.path.exists(html):
        texto_html = io.open(html, encoding="utf-8").read()
        hallados = residuos(texto_html)
        print(f"  HTML residuos/nulos: {hallados if hallados else 'ninguno'}")
        for h in EXPECTED[frente]:
            print(f"  HTML contiene '{h}': {bool(re.search(h, texto_html))}")
    else:
        texto_html = ""

    if frente == "reporte_servicio":
        for term in PROHIBIDO_SERVICIO:
            n_pdf = completo.lower().count(term.lower())
            n_html = texto_html.lower().count(term.lower())
            print(f"  SERVICIO sin '{term}': PDF={n_pdf} HTML={n_html}"
                  + ("" if n_pdf == n_html == 0 else "   <-- REVISAR"))
    elif frente == "reporte_ventas":
        print(f"  VENTAS conserva 'Posibles ventas': "
              f"{completo.lower().count('posibles ventas')} menciones en PDF")
    else:
        # El general conserva la métrica de ventas y trae el desglose de DIRECCIÓN.
        print(f"  GENERAL conserva 'Posibles ventas': "
              f"{completo.lower().count('posibles ventas')} menciones en PDF")
        for term in ("entrantes", "salientes"):
            print(f"  GENERAL declara '{term}': {term in completo.lower()}")

    for term in PROHIBIDO_TODOS:
        n_pdf = completo.count(term)
        n_html = texto_html.count(term)
        print(f"  sin '{term}': PDF={n_pdf} HTML={n_html}"
              + ("" if n_pdf == n_html == 0 else "   <-- REVISAR"))

    if not os.path.exists(html):
        return
    # Las cifras de cabecera de cada bloque deben cuadrar con el resumen de bloques.
    for m in re.finditer(r"(\d+) llamadas \(([\d.]+)% del frente (\w+)\)", texto_html):
        print(f"  bloque {m.group(3):14s} {m.group(1):>4} llamadas  ({m.group(2)}% del frente)")


if __name__ == "__main__":
    for f in EXPECTED:
        revisar(f)
    print("\nOK: validaci\u00f3n terminada.")

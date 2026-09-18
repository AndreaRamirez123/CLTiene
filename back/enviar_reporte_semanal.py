#!/usr/bin/env python3
"""Envío automático del Reporte Ejecutivo semanal (a Steven / CL Tiene).

Cloud Run Job disparado por Cloud Scheduler cada lunes:

  1. Calcula el período = semana pasada (lunes → domingo). Override con
     --fecha-desde / --fecha-hasta.
  2. PREFLIGHT A (BD actualizada): consulta MAX(Fecha) y el conteo del período.
     Falla (exit 1, NO envía) si la tabla no llegó al domingo de la semana
     pasada o si el período está vacío.
  3. PREFLIGHT B (no duplicado): hash MD5 del contexto de datos del período
     (determinista) + consulta en cltiene_reportes_enviados. Falla (exit 1) si
     ese [fecha_desde, fecha_hasta] ya fue enviado con el MISMO hash (data no
     cambió). Si el hash cambió, re-envía (data actualizada = informe nuevo).
  4. Genera el reporte con gpt-4o (generar_reporte_completo) → PDF con
     WeasyPrint → cuerpo con el Resumen Ejecutivo → envía por SMTP.
  5. Tras envío OK inserta el registro en cltiene_reportes_enviados.

Solo lee BigQuery (NO toca el SQL Server de la CUN). SMTP configurado por env.

Flags:
  --dry-run           genera el PDF en disco y NO envía ni registra.
  --fecha-desde X     override del período (YYYY-MM-DD).
  --fecha-hasta Y     override del período (YYYY-MM-DD).
  --no-preflight      salta los preflight A/B (solo debug).
  --outdir PATH       carpeta de salida para --dry-run (default: .)

Exit codes: 0 ok · 1 preflight (BD desactualizada / ya enviado) · 2 error de proceso.
"""

import argparse
import hashlib
import json
import os
import smtplib
import sys
import re
from datetime import date, datetime, timedelta
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate

os.environ.setdefault("CLOUD_PROJECT", os.getenv("GOOGLE_CLOUD_PROJECT", "desarrollo-investigaciones"))

from dotenv import load_dotenv

load_dotenv()

from api.database import client
from api.models import FilterModel
from api.ia.generar_reporte_completo import generar_reporte_completo
from helpers.utils import get_data_context
from helpers.sql import TABLE
from reporte_pdf import html_a_pdf

TABLA_ESTADO = "`desarrollo-investigaciones.call_center.cltiene_reportes_enviados`"

_PINK = "#FC3276"


def calcular_semana_pasada() -> tuple[date, date]:
    """Lunes y domingo de la semana pasada (respecto a hoy)."""
    hoy = date.today()
    lunes_esta = hoy - timedelta(days=hoy.weekday())
    return lunes_esta - timedelta(days=7), lunes_esta - timedelta(days=1)


def _validar_fecha(texto: str) -> date:
    try:
        return datetime.strptime(texto, "%Y-%m-%d").date()
    except ValueError:
        sys.exit(f"Fecha inválida: {texto!r} (espera YYYY-MM-DD)")


def _preflight_bd(desde: date, hasta: date) -> None:
    """PREFLIGHT A: la BD (BigQuery) debe tener la semana pasada COMPLETA."""
    q = f"""
    SELECT
        MAX(DATE(TIMESTAMP_MICROS(DIV(Fecha, 1000)))) AS max_fecha,
        COUNTIF(Fecha >= UNIX_MICROS(TIMESTAMP('{desde}')) * 1000
                AND Fecha <= UNIX_MICROS(TIMESTAMP('{hasta} 23:59:59')) * 1000) AS filas_periodo
    FROM {TABLE}
    """
    row = dict(list(client.query(q).result())[0])
    max_fecha = row["max_fecha"]
    filas = int(row["filas_periodo"] or 0)

    if max_fecha is None:
        sys.exit(f"[PREFLIGHT A] BD sin datos. No se envía el reporte. Requerido MAX(Fecha) >= {hasta}.")

    print(f"[PREFLIGHT A] MAX(Fecha)={max_fecha} · filas del período {desde}..{hasta} = {filas}")
    if max_fecha < hasta:
        sys.exit(
            f"[PREFLIGHT A] BD desactualizada: última fecha {max_fecha}, se requiere >= {hasta} "
            f"(semana pasada completa). No se envía el reporte."
        )
    if filas == 0:
        sys.exit(f"[PREFLIGHT A] El período {desde}..{hasta} no tiene filas. No se envía el reporte.")


def _hash_datos(desde: date, hasta: date) -> str:
    """Hash MD5 determinista del contexto de datos del período (refleja si la
    data cambió). Usa el MISMO contexto que alimenta el reporte."""
    filters = FilterModel(fecha_desde=desde.isoformat(), fecha_hasta=hasta.isoformat())
    contexto = get_data_context(filters.get_query())
    return hashlib.md5(contexto.encode("utf-8")).hexdigest()


def _preflight_duplicado(desde: date, hasta: date, hash_datos: str) -> None:
    """PREFLIGHT B: no reenviar el mismo informe para el mismo período."""
    q = f"""
    SELECT fecha_desde, fecha_hasta, hash_datos, enviado_at
    FROM {TABLA_ESTADO}
    WHERE fecha_desde = DATE('{desde}') AND fecha_hasta = DATE('{hasta}')
    ORDER BY enviado_at DESC
    LIMIT 1
    """
    rows = list(client.query(q).result())
    if not rows:
        print(f"[PREFLIGHT B] Sin envío previo para {desde}..{hasta}. Se procede.")
        return
    previo = dict(rows[0])
    print(f"[PREFLIGHT B] Envío previo en {previo['enviado_at']} · hash_previo={previo['hash_datos'][:12]}…")
    if previo["hash_datos"] == hash_datos:
        sys.exit(
            f"[PREFLIGHT B] El informe de {desde}..{hasta} ya se envió y la data no cambió "
            f"(hash {hash_datos[:12]}…, enviado {previo['enviado_at']}). No se reenvía."
        )
    print("[PREFLIGHT B] La data del período cambió respecto al envío previo. Se re-envía (legítimo).")


def _crear_tabla_estado() -> None:
    q = f"""
    CREATE TABLE IF NOT EXISTS {TABLA_ESTADO} (
        fecha_desde DATE, fecha_hasta DATE, hash_datos STRING, enviado_at TIMESTAMP
    )
    """
    client.query(q).result()
    print("[SETUP] Tabla de estado lista (o ya existía).")


def _registrar_envio(desde: date, hasta: date, hash_datos: str) -> None:
    q = f"""
    INSERT INTO {TABLA_ESTADO} (fecha_desde, fecha_hasta, hash_datos, enviado_at)
    VALUES (DATE('{desde}'), DATE('{hasta}'), '{hash_datos}', CURRENT_TIMESTAMP())
    """
    client.query(q).result()
    print(f"[ENVÍO] Registrado en {TABLA_ESTADO}: {desde}..{hasta} hash={hash_datos[:12]}…")


def _extraer_resumen(html: str) -> str:
    """Extrae los bullets del Resumen Ejecutivo (sección <h2>Resumen…) como
    texto plano para el cuerpo del correo. Lista acotada (primeros ~6)."""
    m = re.search(r"<h2[^>]*>\s*Resumen\s*Ejecutivo\s*</h2>(.*?)<h2[^>]*>", html, re.IGNORECASE | re.DOTALL)
    seccion = m.group(1) if m else ""
    items = re.findall(r"<li[^>]*>(.*?)</li>", seccion, re.DOTALL | re.IGNORECASE)
    limpio = []
    for it in items:
        texto = re.sub(r"<[^>]+>", "", it)
        texto = re.sub(r"\s+", " ", texto).strip()
        if texto:
            limpio.append("- " + texto)
    return "\n".join(limpio[:8])


def _enviar_correo(pdf_bytes: bytes, resumen: str, desde: date, hasta: date) -> None:
    to = os.getenv("EMAIL_TO", "supervisor_contact@cltiene.com")
    frm = os.getenv("SMTP_USER", os.getenv("EMAIL_FROM", ""))
    frm_nombre = os.getenv("EMAIL_FROM_NAME", "Diego Ojeda — DivergencyAI")
    subject = f"Reporte Ejecutivo Semanal CL Tiene — {desde.strftime('%d/%m/%Y')} a {hasta.strftime('%d/%m/%Y')}"

    cuerpo = (
        f"Hola Steven,\n\n"
        f"Te comparto el Reporte Ejecutivo semanal del Contact Center "
        f"({desde.strftime('%d/%m/%Y')} al {hasta.strftime('%d/%m/%Y')}).\n\n"
        f"RESUMEN EJECUTIVO\n"
        f"-----------------------------------------------\n"
        f"{resumen or '(sin resumen disponible)'}\n\n"
        f"El informe completo va adjunto en PDF.\n\n"
        f"Quedo atento.\n\n"
        f"Diego Ojeda\nDivergencyAI SAS\n"
        f"Dashboard: https://cltiene-dashboard.web.app"
    )

    msg = MIMEMultipart()
    msg["From"] = formataddr((frm_nombre, frm))
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg.attach(MIMEText(cuerpo, "plain", "utf-8"))
    msg.attach(MIMEApplication(pdf_bytes, _subtype="pdf", Name="reporte_semanal.pdf"))
    msg.attach(MIMEApplication(
        json.dumps({"fecha_desde": desde.isoformat(), "fecha_hasta": hasta.isoformat()}).encode(),
        _subtype="json", Name="periodo.json",
    ))

    host = os.getenv("SMTP_HOST", "smtp.office365.com")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = frm
    pwd = os.getenv("SMTP_PASS", "")

    with smtplib.SMTP(host, port, timeout=60) as server:
        server.starttls()
        server.login(user, pwd)
        server.sendmail(user, [to], msg.as_string())
    print(f"[ENVÍO] Correo enviado a {to} (host {host}:{port})")


def main():
    ap = argparse.ArgumentParser(description="Envío semanal del reporte ejecutivo a CL Tiene.")
    ap.add_argument("--dry-run", action="store_true", help="genera el PDF en disco sin enviar ni registrar")
    ap.add_argument("--fecha-desde", type=str, default=None, help="override período (YYYY-MM-DD)")
    ap.add_argument("--fecha-hasta", type=str, default=None, help="override período (YYYY-MM-DD)")
    ap.add_argument("--no-preflight", action="store_true", help="salta preflight A/B (solo debug)")
    ap.add_argument("--outdir", type=str, default=".", help="carpeta de salida para --dry-run")
    args = ap.parse_args()

    desde, hasta = calcular_semana_pasada()
    if args.fecha_desde:
        desde = _validar_fecha(args.fecha_desde)
    if args.fecha_hasta:
        hasta = _validar_fecha(args.fecha_hasta)

    print(f"[INICIO] Período del reporte: {desde} a {hasta} · dry_run={args.dry_run}")

    # 1) Preflights
    if not args.no_preflight:
        _preflight_bd(desde, hasta)
    else:
        print("[WARN] Preflight A/B DESACTIVADOS (--no-preflight). Modo debug.")

    filters = FilterModel(fecha_desde=desde.isoformat(), fecha_hasta=hasta.isoformat())
    hash_datos = _hash_datos(desde, hasta)
    print(f"[HASH] datos del período: {hash_datos[:16]}…")

    if not args.no_preflight:
        _crear_tabla_estado()
        _preflight_duplicado(desde, hasta, hash_datos)

    # 2) Generar reporte (gpt-4o)
    print("[REPORTE] Generando reporte con generar_reporte_completo…")
    resp = generar_reporte_completo(filters)
    if resp.get("error") or not resp.get("result"):
        sys.exit(f"[REPORTE] Error del modelo o sin contenido: {resp.get('error') or 'vacio'}")
    html = resp["result"]

    # 3) PDF
    periodo_txt = f"{desde.strftime('%d/%m/%Y')} al {hasta.strftime('%d/%m/%Y')}"
    pdf = html_a_pdf(html, periodo_txt)
    print(f"[PDF] Generado: {len(pdf)} bytes")

    # 4) Resumen para el cuerpo
    resumen = _extraer_resumen(html)

    # 5) Envío / dry-run
    if args.dry_run:
        os.makedirs(args.outdir, exist_ok=True)
        ruta = os.path.join(args.outdir, "reporte_semanal_dryrun.pdf")
        with open(ruta, "wb") as f:
            f.write(pdf)
        print(f"[DRY-RUN] PDF guardado en {ruta} — NO se envió correo ni se registró.")
        print("--- RESUMEN (cuerpo del correo) ---")
        print(resumen[:1500])
        return

    if os.getenv("REPORTE_ENABLED", "0") != "1":
        sys.exit(
            "[ENVÍO] REPORTE_ENABLED != 1 → NO se envió el correo (kill-switch). "
            "PDF generado OK. Revisar logs."
        )

    _enviar_correo(pdf, resumen, desde, hasta)

    # 6) Registrar envío (solo tras éxito)
    _registrar_envio(desde, hasta, hash_datos)
    print("[OK] Envío semanal completado.")


if __name__ == "__main__":
    main()
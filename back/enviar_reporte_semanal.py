#!/usr/bin/env python3
"""Envío automático del Reporte Ejecutivo semanal (a Steven / CL Tiene).

Cloud Run Job disparado por Cloud Scheduler (cada hora L-V, detecta solo):

  0. DETECCIÓN AUTOMÁTICA: si no se pasa --fecha-desde/--fecha-hasta, el período
     es la última semana completa (lunes→domingo) que existe en BigQuery.
     - Sin datos en BD → skip limpio (exit 0).
     - Semana no "fresca" (terminó hace más de 7 días) → skip limpio + ALERTA
       de BD desactualizada a EMAIL_ALERT_TO (una vez por día) → exit 0.
       La alerta lleva su propio kill-switch: ALERTA_ENABLED=1 (default 0).
  1. PREFLIGHT A (período con datos): si el período no tiene filas → skip
     limpio (exit 0). [antes: exigía que MAX(Fecha) llegara al domingo pasado]
  2. PREFLIGHT B (no se repite): hash MD5 del contexto de datos (determinista)
     contra cltiene_reportes_enviados. Si [fecha_desde, fecha_hasta] ya se
     envió con el MISMO hash → skip limpio (exit 0). Si el hash cambió,
     re-envía (data actualizada = informe nuevo).
  3. Genera el reporte con gpt-4o (generar_reporte_completo) → PDF con
     WeasyPrint → cuerpo con el Resumen Ejecutivo → envía por SMTP.
  4. Tras envío OK inserta el registro en cltiene_reportes_enviados
     (a menos que --no-registrar).

Solo lee BigQuery (NO toca el SQL Server de la CUN). SMTP configurado por env.

Flags:
  --dry-run           genera el PDF en disco y NO envía ni registra.
  --fecha-desde X     override del período (YYYY-MM-DD) — desactiva la
                      detección automática y el guard de frescura.
  --fecha-hasta Y     override del período (YYYY-MM-DD).
  --no-preflight      salta los preflight A/B (solo debug).
  --no-registrar      envía pero NO registra en la tabla de estado (test).
  --outdir PATH       carpeta de salida para --dry-run (default: .)

Exit codes: 0 ok o skip (BD desactualizada / ya enviado / sin novedad → se
reintentará en el próximo tick) · 1 error de proceso (SMTP/modelo/arg).
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
TABLA_ALERTAS = "`desarrollo-investigaciones.call_center.cltiene_stale_alertas`"

_PINK = "#FC3276"

DIAS_FRESCURA = 7


def calcular_semana_pasada() -> tuple[date, date]:
    """Lunes y domingo de la semana pasada (respecto a hoy). Leyenda (antigua
    forma de período); la detección automática usa _ultima_semana_completa_bd."""
    hoy = date.today()
    lunes_esta = hoy - timedelta(days=hoy.weekday())
    return lunes_esta - timedelta(days=7), lunes_esta - timedelta(days=1)


def _validar_fecha(texto: str) -> date:
    try:
        return datetime.strptime(texto, "%Y-%m-%d").date()
    except ValueError:
        sys.exit(f"Fecha inválida: {texto!r} (espera YYYY-MM-DD)")


def _max_fecha_bd() -> date | None:
    """Última fecha con datos en BigQuery (o None si la tabla está vacía)."""
    q = f"""
    SELECT MAX(DATE(TIMESTAMP_MICROS(DIV(Fecha, 1000)))) AS max_fecha
    FROM {TABLE}
    """
    row = dict(list(client.query(q).result())[0])
    return row["max_fecha"]


def _semana_desde_max(max_fecha: date) -> tuple[date, date]:
    """Lunes y domingo de la última semana completa que hay en la BD:
    retrocede desde max_fecha hasta el domingo más cercano y toma esa semana."""
    ultimo_dom = max_fecha - timedelta(days=(max_fecha.weekday() - 6) % 7)
    return ultimo_dom - timedelta(days=6), ultimo_dom


def _es_fresca(hasta: date, hoy: date) -> bool:
    """La semana completada en `hasta` es lo suficientemente reciente para
    enviarse (terminó hace <= DIAS_FRESCURA días)."""
    return hasta >= hoy - timedelta(days=DIAS_FRESCURA)


def _destinatarios(csv: str) -> list[str]:
    return [x.strip() for x in csv.split(",") if x.strip()]


def _filas_periodo(desde: date, hasta: date) -> int:
    """Filas de BigQuery dentro del período [desde, hasta]."""
    q = f"""
    SELECT COUNTIF(Fecha >= UNIX_MICROS(TIMESTAMP('{desde}')) * 1000
            AND Fecha <= UNIX_MICROS(TIMESTAMP('{hasta} 23:59:59')) * 1000) AS n
    FROM {TABLE}
    """
    row = dict(list(client.query(q).result())[0])
    return int(row["n"] or 0)


def _hash_datos(desde: date, hasta: date) -> str:
    """Hash MD5 determinista del contexto de datos del período (refleja si la
    data cambió). Usa el MISMO contexto que alimenta el reporte."""
    filters = FilterModel(fecha_desde=desde.isoformat(), fecha_hasta=hasta.isoformat())
    contexto = get_data_context(filters.get_query())
    return hashlib.md5(contexto.encode("utf-8")).hexdigest()


def _preflight_duplicado(desde: date, hasta: date, hash_datos: str) -> None:
    """PREFLIGHT B: no reenviar el mismo informe para el mismo período (skip limpio)."""
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
        print(
            f"[SKIP] El informe de {desde}..{hasta} ya se envió y la data no cambió "
            f"(hash {hash_datos[:12]}…, enviado {previo['enviado_at']}). No se reenvía. (exit 0)"
        )
        sys.exit(0)
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


def _enviar_smtp(to_list: list[str], subject: str, cuerpo: str, attachments=()) -> None:
    frm = os.getenv("SMTP_USER", os.getenv("EMAIL_FROM", ""))
    frm_nombre = os.getenv("EMAIL_FROM_NAME", "Diego Ojeda — DivergencyAI")

    msg = MIMEMultipart()
    msg["From"] = formataddr((frm_nombre, frm))
    msg["To"] = ", ".join(to_list)
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg.attach(MIMEText(cuerpo, "plain", "utf-8"))
    for nombre, payload, subtipo in attachments:
        msg.attach(MIMEApplication(payload, _subtype=subtipo, Name=nombre))

    host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = frm
    pwd = os.getenv("SMTP_PASS", "")

    with smtplib.SMTP(host, port, timeout=60) as server:
        server.starttls()
        server.login(user, pwd)
        server.sendmail(user, to_list, msg.as_string())
    print(f"[ENVÍO] Correo enviado a {', '.join(to_list)} (host {host}:{port})")


def _enviar_reporte(pdf_bytes: bytes, resumen: str, desde: date, hasta: date) -> None:
    to_list = _destinatarios(os.getenv("EMAIL_TO", "supervisor_contact@cltiene.com"))
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

    attachments = [
        ("reporte_semanal.pdf", pdf_bytes, "pdf"),
        ("periodo.json", json.dumps(
            {"fecha_desde": desde.isoformat(), "fecha_hasta": hasta.isoformat()}).encode(), "json"),
    ]
    _enviar_smtp(to_list, subject, cuerpo, attachments)


def _crear_tabla_alertas() -> None:
    q = f"""
    CREATE TABLE IF NOT EXISTS {TABLA_ALERTAS} (
        fecha_aviso DATE, max_fecha DATE
    )
    """
    client.query(q).result()
    print("[SETUP] Tabla de alertas lista (o ya existía).")


def _alerta_enviada_hoy() -> bool:
    q = f"""
    SELECT COUNT(*) AS n FROM {TABLA_ALERTAS}
    WHERE fecha_aviso = CURRENT_DATE('America/Bogota')
    """
    row = dict(list(client.query(q).result())[0])
    return int(row["n"] or 0) > 0


def _registrar_alerta(max_fecha: date) -> None:
    q = f"""
    INSERT INTO {TABLA_ALERTAS} (fecha_aviso, max_fecha)
    VALUES (CURRENT_DATE('America/Bogota'), DATE('{max_fecha}'))
    """
    client.query(q).result()
    print(f"[ALERTA] Registrada en {TABLA_ALERTAS}: hoy, max_fecha={max_fecha}")


def _enviar_alerta_stale(max_fecha: date) -> None:
    to_list = _destinatarios(
        os.getenv("EMAIL_ALERT_TO", "Juan_ganicac@cun.edu.co,Juan_marin@cun.edu.co"))
    subject = f"⚠️ CL Tiene: BD sin datos nuevos (máx {max_fecha})"
    cuerpo = (
        f"Hola,\n\n"
        f"El sistema de envío del reporte semanal de CL Tiene detectó que la base de datos "
        f"NO se ha actualizado: la última fecha registrada es {max_fecha}.\n\n"
        f"Mientras la BD no tenga la semana completa reciente, el reporte a CL Tiene no se "
        f"envía (por diseño). Por favor, actualizar la base de datos (SQL Server → BigQuery).\n\n"
        f"El sistema reintenta automáticamente cada hora y enviará el reporte en cuanto la "
        f"data esté al día.\n\n"
        f"Saludos,\nDivergencyAI SAS\nDashboard: https://cltiene-dashboard.web.app"
    )
    _enviar_smtp(to_list, subject, cuerpo)
    print(f"[ALERTA] Aviso enviado a {', '.join(to_list)} (BD con máx {max_fecha})")


def _alertar_stale(max_fecha: date) -> None:
    """Alerta de BD desactualizada a los dueños de los datos (una por día).

    Kill-switch INDEPENDIENTE del envío del reporte: ALERTA_ENABLED=1 la
    activa (default 0). El reporte a CL Tiene depende SOLO de REPORTE_ENABLED.
    """
    if os.getenv("ALERTA_ENABLED", "0") != "1":
        print("[ALERTA] ALERTA_ENABLED != 1 → alerta omitida (kill-switch). Solo log.")
        return
    _crear_tabla_alertas()
    if _alerta_enviada_hoy():
        print("[ALERTA] Aviso ya enviado hoy → se omite (dedupe diario).")
        return
    _enviar_alerta_stale(max_fecha)  # si SMTP falla, lanza → no se registra → reintento mañana
    _registrar_alerta(max_fecha)


def main():
    ap = argparse.ArgumentParser(description="Envío semanal del reporte ejecutivo a CL Tiene.")
    ap.add_argument("--dry-run", action="store_true", help="genera el PDF en disco sin enviar ni registrar")
    ap.add_argument("--fecha-desde", type=str, default=None, help="override período (YYYY-MM-DD)")
    ap.add_argument("--fecha-hasta", type=str, default=None, help="override período (YYYY-MM-DD)")
    ap.add_argument("--no-preflight", action="store_true", help="salta preflight A/B (solo debug)")
    ap.add_argument("--no-registrar", action="store_true", help="envía pero NO registra en la tabla de estado")
    ap.add_argument("--outdir", type=str, default=".", help="carpeta de salida para --dry-run")
    args = ap.parse_args()

    hoy = date.today()

    # 0) Período: manual (flags) o detectado automáticamente desde la BD
    if args.fecha_desde and args.fecha_hasta:
        desde = _validar_fecha(args.fecha_desde)
        hasta = _validar_fecha(args.fecha_hasta)
        automatico = False
        print(f"[INICIO] Período manual: {desde} a {hasta}")
    else:
        max_fecha = _max_fecha_bd()
        if max_fecha is None:
            print("[SKIP] BigQuery sin datos. Se reintentará en el próximo tick. (exit 0)")
            sys.exit(0)
        desde, hasta = _semana_desde_max(max_fecha)
        automatico = True
        print(f"[AUTO] MAX(Fecha)={max_fecha} → última semana completa detectada: {desde} a {hasta}")
        if not _es_fresca(hasta, hoy):
            print(
                f"[SKIP] BD desactualizada: la última semana completa {desde}..{hasta} no es "
                f"reciente (requiere terminar >= {hoy - timedelta(days=DIAS_FRESCURA)}). "
                f"No se envía y se reintentará. (exit 0)"
            )
            _alertar_stale(max_fecha)
            sys.exit(0)

    print(f"[INICIO] Período del reporte: {desde} a {hasta} · dry_run={args.dry_run} · auto={automatico}")

    # 1) Preflight A: el período tiene filas
    if not args.no_preflight:
        filas = _filas_periodo(desde, hasta)
        print(f"[PREFLIGHT A] filas del período {desde}..{hasta} = {filas}")
        if filas == 0:
            print("[SKIP] El período no tiene filas. Se reintentará en el próximo tick. (exit 0)")
            sys.exit(0)
    else:
        print("[WARN] Preflight A/B DESACTIVADOS (--no-preflight). Modo debug.")

    filters = FilterModel(fecha_desde=desde.isoformat(), fecha_hasta=hasta.isoformat())
    hash_datos = _hash_datos(desde, hasta)
    print(f"[HASH] datos del período: {hash_datos[:16]}…")

    # 2) Preflight B: no repetir envío (hash comparado)
    if not args.no_preflight:
        _crear_tabla_estado()
        _preflight_duplicado(desde, hasta, hash_datos)

    # 3) Generar reporte (gpt-4o)
    print("[REPORTE] Generando reporte con generar_reporte_completo…")
    resp = generar_reporte_completo(filters)
    if resp.get("error") or not resp.get("result"):
        sys.exit(f"[REPORTE] Error del modelo o sin contenido: {resp.get('error') or 'vacio'}")

    html = resp["result"]

    # 4) PDF
    periodo_txt = f"{desde.strftime('%d/%m/%Y')} al {hasta.strftime('%d/%m/%Y')}"
    pdf = html_a_pdf(html, periodo_txt)
    print(f"[PDF] Generado: {len(pdf)} bytes")

    # 5) Resumen para el cuerpo
    resumen = _extraer_resumen(html)

    # 6) Envío / dry-run
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

    _enviar_reporte(pdf, resumen, desde, hasta)

    # 7) Registrar envío (solo tras éxito, salvo --no-registrar)
    if args.no_registrar:
        print("[TEST] --no-registrar: el envío NO se registró en la tabla de estado.")
    else:
        _registrar_envio(desde, hasta, hash_datos)
    print("[OK] Envío semanal completado.")


if __name__ == "__main__":
    main()
"""Tests de los informes segmentados (Ventas/Servicio × Entrantes/Salientes).

Sin red: prueban el contexto de servicio (que quita la métrica de ventas) y la
lógica pura del plan de bloques / nombres de archivo del script. BigQuery se mockea
donde haría falta.

El bucket 'Sin dirección' (Tipo_Llamada IS NULL, ~49% del histórico) se EXCLUYÓ de
los informes a pedido del usuario, pero el centinela de `filters()` se conserva como
mecanismo genérico del filtro `seguimiento_llamada`; por eso sigue having tests.
"""
import os
os.environ.setdefault("CLOUD_PROJECT", "test-project")

import unittest
from datetime import date
from unittest import mock

from helpers.utils import (
    _SIN_DIRECCION,
    contexto_tipo_llamada,
    es_informe_de_servicio,
    filters,
)


class _F:
    """FilterModel mínimo (no requiere pydantic para estos tests)."""

    def __init__(self, tipo=None, seguimiento=None):
        self.tipo_llamada = tipo
        self.seguimiento_llamada = seguimiento


class TestBucketSinDireccion(unittest.TestCase):
    """'Sin dirección' = Tipo_Llamada IS NULL (~49% del histórico). Ya NO se
    reporta en los informes, pero el centinela de `filters()` se conserva."""

    def test_sentinela_produce_is_null(self):
        for valor in sorted(_SIN_DIRECCION):
            r = filters({"seguimiento_llamada": valor})["filter_string"]
            self.assertEqual(r, "Tipo_Llamada IS NULL", valor)

    def test_sentinela_en_mayusculas_iguales(self):
        r = filters({"seguimiento_llamada": "NULL"})["filter_string"]
        self.assertEqual(r, "Tipo_Llamada IS NULL")

    def test_valores_reales_no_cambian(self):
        for valor in ("Entrante", "Saliente"):
            r = filters({"seguimiento_llamada": valor})["filter_string"]
            self.assertEqual(r, f"Tipo_Llamada = '{valor}'")

    def test_se_puede_combinar_con_tipo(self):
        r = filters({"tipo_llamada": "servicio", "seguimiento_llamada": "null"})["filter_string"]
        self.assertIn("tipo = 'servicio'", r)
        self.assertIn("AND", r)
        self.assertIn("Tipo_Llamada IS NULL", r)

    def test_otros_filtros_no_afectados(self):
        # El cambio NO debe tocar los demás filtros del WHERE.
        r = filters({"resultado_llamada": "Venta", "nombre_asesor": "Jimmy"})["filter_string"]
        self.assertIn("resultado_llamada = 'Venta'", r)
        self.assertIn("cuenta", r)
        self.assertNotIn("IS NULL", r)


class TestInformeDeServicio(unittest.TestCase):
    """El informe de servicio no debe llevar NADA de la métrica de ventas."""

    def test_detecta_servicio(self):
        self.assertTrue(es_informe_de_servicio(_F(tipo="servicio")))
        self.assertFalse(es_informe_de_servicio(_F(tipo="ventas")))
        self.assertFalse(es_informe_de_servicio(_F()))
        self.assertFalse(es_informe_de_servicio(None))

    def test_contexto_servicio_prohibe_ventas(self):
        ctx = contexto_tipo_llamada(_F(tipo="servicio"))
        self.assertIn("PROHIBIDO", ctx)
        self.assertIn("Posibles ventas", ctx)          # lo nombra para PROHIBIRLO
        self.assertIn("7 filas", ctx)
        self.assertIn("columna 'Posibles ventas'", ctx)

    def test_contexto_ventas_vacio(self):
        self.assertEqual(contexto_tipo_llamada(_F(tipo="ventas")), "")
        self.assertEqual(contexto_tipo_llamada(None), "")


class TestPlanDeBloques(unittest.TestCase):
    """El plan 2 tipos × 2 direcciones y el nombre de los archivos (lógica pura)."""

    def test_solo_dos_direcciones_en_orden(self):
        """El bucket 'Sin dirección' se excluyó de los informes a pedido del usuario."""
        from generar_reportes_segmentados import DIRECCIONES

        self.assertEqual([slug for _, _, slug in DIRECCIONES],
                         ["entrantes", "salientes"])
        self.assertEqual([valor for _, valor, _ in DIRECCIONES],
                         ["Entrante", "Saliente"])
        self.assertEqual([et for et, _, _ in DIRECCIONES],
                         ["Entrantes", "Salientes"])

    def test_nombre_archivo(self):
        from generar_reportes_segmentados import nombre_archivo

        self.assertEqual(
            nombre_archivo("ventas", date(2026, 9, 14), date(2026, 9, 20)),
            "reporte_ventas_2026-09-14_2026-09-20.pdf",
        )
        self.assertEqual(
            nombre_archivo("servicio", date(2026, 9, 14), date(2026, 9, 20)),
            "reporte_servicio_2026-09-14_2026-09-20.pdf",
        )

    def test_filtros_del_bloque(self):
        from generar_reportes_segmentados import _filtros

        f = _filtros("servicio", date(2026, 9, 14), date(2026, 9, 20), "Entrante")
        self.assertEqual(f.tipo_llamada, "servicio")
        self.assertEqual(f.seguimiento_llamada, "Entrante")
        self.assertIn("2026-09-14", f.get_query())

    def test_portadilla_no_lleva_nota_de_cobertura(self):
        """Ya no se reporta el bucket 'Sin dirección', así que tampoco su nota."""
        from generar_reportes_segmentados import _portadilla

        html = _portadilla("Ventas", "Entrantes", 100, 600, True)
        self.assertIn("Ventas", html)
        self.assertIn("Entrantes", html)
        self.assertNotIn("No se deben sumar", html)
        self.assertNotIn("SIN dirección", html)

    def test_bloque_vacio_no_llama_al_modelo(self):
        from generar_reportes_segmentados import generar_un_informe

        with mock.patch("generar_reportes_segmentados._contar_filas", return_value=0), \
                mock.patch("generar_reportes_segmentados._total_tipo", return_value=0), \
                mock.patch("generar_reportes_segmentados.generar_reporte_completo") as gen:
            html, resumen = generar_un_informe(
                "ventas", "Ventas", date(2026, 9, 14), date(2026, 9, 20),
                [("Entrantes", "Entrante", "entrantes")],
            )
        gen.assert_not_called()          # 0 filas → no se gasta llamada al modelo
        self.assertIn("Sin llamadas en el período", html)
        self.assertEqual(resumen[0][1], 0)

    def test_bloque_vacio_siempre_abre_pagina_sino_es_el_primero(self):
        """Regresión: el div del bloque vacío debe llevar `class="bloque"` si ya
        hubo un bloque antes; si no, la nota queda pegada al bloque anterior y los
        apartados no se leen."""
        from generar_reportes_segmentados import generar_un_informe

        with mock.patch("generar_reportes_segmentados._contar_filas", side_effect=[7, 0]), \
                mock.patch("generar_reportes_segmentados._total_tipo", return_value=7), \
                mock.patch("generar_reportes_segmentados.generar_reporte_completo",
                           return_value={"result": "<h2>x</h2>", "error": None}):
            html, _ = generar_un_informe(
                "ventas", "Ventas", date(2026, 9, 14), date(2026, 9, 20),
                [("Entrantes", "Entrante", "entrantes"), ("Salientes", "Saliente", "salientes")],
            )
        # 2 portadillas, y la 2ª (la vacía) abre página.
        self.assertEqual(html.count('class="portadilla"'), 2)
        self.assertEqual(html.count('class="bloque"'), 1)
        vacio = html[html.find("Salientes", html.find("portadilla-sub")) - 200:html.find("Sin llamadas en el período")]
        self.assertIn('class="bloque"', vacio)

    def test_primer_bloque_vacio_no_lleva_salto(self):
        from generar_reportes_segmentados import generar_un_informe

        with mock.patch("generar_reportes_segmentados._contar_filas", return_value=0), \
                mock.patch("generar_reportes_segmentados._total_tipo", return_value=0), \
                mock.patch("generar_reportes_segmentados.generar_reporte_completo"):
            html, _ = generar_un_informe(
                "ventas", "Ventas", date(2026, 9, 14), date(2026, 9, 20),
                [("Salientes", "Saliente", "salientes")],
            )
        # Va pegado a la banda del encabezado → no debe abrir una página en blanco.
        self.assertEqual(html.count('class="bloque"'), 0)

    def test_solo_el_segundo_bloque_lleva_salto_de_pagina(self):
        from generar_reportes_segmentados import generar_un_informe

        with mock.patch("generar_reportes_segmentados._contar_filas", return_value=5), \
                mock.patch("generar_reportes_segmentados._total_tipo", return_value=10), \
                mock.patch("generar_reportes_segmentados.generar_reporte_completo",
                           return_value={"result": "<h2>x</h2><p>y</p>", "error": None}):
            html, _ = generar_un_informe(
                "ventas", "Ventas", date(2026, 9, 14), date(2026, 9, 20),
                [("Entrantes", "Entrante", "entrantes"), ("Salientes", "Saliente", "salientes")],
            )
        self.assertEqual(html.count('class="bloque"'), 1)   # solo el 2º bloque
        self.assertEqual(html.count('class="portadilla"'), 2)

    def test_modo_servicio_no_reintroduce_ventas(self):
        """Modo servicio: get_data_context se llama con ocultar_ventas=True."""
        from api.ia import generar_reporte_completo as grc

        with mock.patch.object(grc, "get_data_context", return_value="CTX") as gdc, \
                mock.patch.object(grc, "call", return_value=("HTML", None)):
            f = _F(tipo="servicio")
            from api.models import FilterModel
            fm = FilterModel(fecha_desde="2026-09-14", fecha_hasta="2026-09-20", tipo_llamada="servicio")
            grc.generar_reporte_completo(fm)
        self.assertTrue(gdc.call_args.kwargs.get("ocultar_ventas") is True)

        with mock.patch.object(grc, "get_data_context", return_value="CTX") as gdc, \
                mock.patch.object(grc, "call", return_value=("HTML", None)):
            grc.generar_reporte_completo(
                FilterModel(fecha_desde="2026-09-14", fecha_hasta="2026-09-20"))
        self.assertFalse(gdc.call_args.kwargs.get("ocultar_ventas"))


class _FilaVacia(dict):
    """Fila que devuelve NULL en cada clave (como el agregado de BigQuery sobre 0 filas)."""

    def __getitem__(self, k):
        return self.get(k)


class TestContextoSinFilas(unittest.TestCase):
    """Regresión: un bucket de filtro puede quedar vacío (p.ej. ventas + 'Sin
    dirección' = 0 filas). Antes `SUM()` devolvía NULL y el formateo del contexto
    reventaba con 'unsupported format string passed to NoneType'."""

    FILA = {
        "resumen": {"total": 0, "contactadas": None, "ventas": None,
                    "tmo_seg": None, "participacion_cliente": None, "calidad_score": 0},
        "calidad": {"saludo": None, "beneficios": None, "whatsapp": None, "despedida": None},
        "estatus": [], "direccion": [], "resultados": [], "duracion": [],
        "planes": [], "asesores": [], "rechazos": [],
    }

    def _ctx(self, ocultar_ventas=False):
        from helpers import utils

        with mock.patch.object(utils, "client") as cli:
            cli.query.return_value.result.return_value = [dict(self.FILA)]
            return utils.get_data_context("1=1", ocultar_ventas=ocultar_ventas)

    def test_no_revienta_con_cero_filas(self):
        ctx = self._ctx()
        self.assertIn("Total llamadas (marcaciones): 0", ctx)

    def test_porcentajes_cero_y_no_none(self):
        ctx = self._ctx()
        for prohibido in ("None", "nan", "None%", "None %"):
            self.assertNotIn(prohibido, ctx)
        self.assertIn("(0.0%)", ctx)

    def test_modo_servicio_tampoco_revierte(self):
        ctx = self._ctx(ocultar_ventas=True)
        self.assertNotIn("Posibles ventas", ctx)
        self.assertIn("Total llamadas (marcaciones): 0", ctx)

    def test_sql_usa_coalesce_en_los_agregados(self):
        """El COALESCE en SQL evita el NULL; la guarda en Python es la segunda red."""
        from helpers import utils

        with mock.patch.object(utils, "client") as cli:
            cli.query.return_value.result.return_value = [dict(self.FILA)]
            utils.get_data_context("1=1")
        sql = cli.query.call_args[0][0]
        self.assertIn("COALESCE(SUM(CASE WHEN efectiva = 1.0", sql)
        self.assertIn("COALESCE(ROUND(SAFE_DIVIDE(SUM(cli_turns)", sql)


class TestPdfSegmentado(unittest.TestCase):
    """html_a_pdf acepta título configurable sin romper el reporte semanal."""

    def test_titulo_por_defecto_no_cambia(self):
        import reporte_pdf

        src = __import__("inspect").getsource(reporte_pdf.html_a_pdf)
        self.assertIn('titulo: str = "Reporte Estratégico de Operaciones"', src)

    def test_css_de_bloques_agregado(self):
        import reporte_pdf

        self.assertIn(".bloque { break-before: page; }", reporte_pdf._CSS)
        self.assertIn(".bloque h1.portadilla", reporte_pdf._CSS)


class TestSemaforoTmoSinDato(unittest.TestCase):
    """Regresión: el origen NO manda 'Tiempo de Conversacion' para las ENTRANTES
    (0 de 189 en la semana del 14-20 sep; 0% en todos los meses). Antes el NULL se
    coercionaba a 0 y caía en la rama 🔴, así que el tablero decía 'TMO N/D — Rojo':
    le comunicaba al cliente un TMO malo cuando en realidad no hay medición."""

    def _ctx(self, tmo_seg, tmo_n):
        from helpers import utils

        fila = {
            "resumen": {"total": 100, "contactadas": 10, "ventas": 3,
                        "tmo_seg": tmo_seg, "tmo_n": tmo_n,
                        "participacion_cliente": 50, "calidad_score": 35},
            "calidad": {"saludo": 1, "beneficios": 2, "whatsapp": 3, "despedida": 4},
            "estatus": [], "direccion": [], "resultados": [], "duracion": [],
            "planes": [], "asesores": [], "rechazos": [],
        }
        with mock.patch.object(utils, "client") as cli:
            cli.query.return_value.result.return_value = [fila]
            return utils.get_data_context("1=1")

    def test_tmo_sin_dato_no_rojo(self):
        ctx = self._ctx(None, 0)
        linea = [l for l in ctx.splitlines() if l.strip().startswith("- TMO:")][0]
        self.assertIn("⚪", linea)
        self.assertNotIn("🔴", linea)

    def test_tmo_sin_dato_lo_dice_explicitamente(self):
        ctx = self._ctx(None, 0)
        self.assertIn("N/D — NO SE PUEDE CALCULAR", ctx)
        self.assertIn("no hay dato", ctx)

    def test_tmo_con_dato_sigue_semáforo_normal(self):
        """Con dato (salientes) el semáforo NO cambia: 77s = 1:17 -> 🟡."""
        ctx = self._ctx(77, 81)
        linea = [l for l in ctx.splitlines() if l.strip().startswith("- TMO:")][0]
        self.assertIn("🟡", linea)
        self.assertNotIn("⚪", linea)

    def test_tmo_parcial_declara_cobertura(self):
        """Con dato parcial se declara sobre cuántas llamadas se midió, para que
        1:17 no se lea como el TMO de las 998."""
        ctx = self._ctx(77, 81)
        self.assertIn("cobertura", ctx)
        self.assertIn("81.0%", ctx)

    def test_sql_cuenta_llamadas_con_duracion(self):
        from helpers import utils

        fila = {
            "resumen": {"total": 100, "contactadas": 10, "ventas": 3, "tmo_seg": 77,
                        "tmo_n": 81, "participacion_cliente": 50, "calidad_score": 35},
            "calidad": {"saludo": 1}, "estatus": [], "direccion": [], "resultados": [],
            "duracion": [], "planes": [], "asesores": [], "rechazos": [],
        }
        with mock.patch.object(utils, "client") as cli:
            cli.query.return_value.result.return_value = [fila]
            utils.get_data_context("1=1")
        sql = cli.query.call_args[0][0]
        self.assertIn("COALESCE(COUNTIF(dur_seg > 0), 0) tmo_n", sql)


if __name__ == "__main__":
    unittest.main()

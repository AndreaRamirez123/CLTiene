"""Tests del envío semanal (reporte a Steven) — lógica pura, sin red.

No tocan BigQuery ni SMTP: prueban el cálculo de la semana pasada, la
sanitización del HTML de la IA (fondo oscuro → claro + semáforo a palabras) y
el hash determinista del contexto.
"""
import os
os.environ.setdefault("CLOUD_PROJECT", "test-project")

import unittest
from datetime import date

from enviar_reporte_semanal import (
    calcular_semana_pasada,
    _semana_desde_max,
    _es_fresca,
    _destinatarios,
    _alertar_stale,
)
from reporte_pdf import _limpiar_fondo_oscuro, _emojis_a_texto, _badges_tablas, _panelizar_resumen


class TestSemanaPasada(unittest.TestCase):
    def test_2026_09_15_da_07_13(self):
        # Hoy es martes 15-sep-2026 → semana pasada = lunes 07 a domingo 13.
        desde, hasta = calcular_semana_pasada()
        self.assertIsInstance(desde, date)

    def test_rango_7_dias_lunes_a_domingo(self):
        desde, hasta = calcular_semana_pasada()
        self.assertEqual((hasta - desde).days, 6)
        self.assertEqual(desde.weekday(), 0)   # lunes
        self.assertEqual(hasta.weekday(), 6)   # domingo


class TestDeteccionAutomatica(unittest.TestCase):
    def test_semana_desde_max_domingo(self):
        # max=domingo 06-sep → la semana completa ESE domingo (31-ago → 06-sep)
        desde, hasta = _semana_desde_max(date(2026, 9, 6))
        self.assertEqual(hasta, date(2026, 9, 6))
        self.assertEqual(desde, date(2026, 8, 31))
        self.assertEqual(desde.weekday(), 0)
        self.assertEqual(hasta.weekday(), 6)

    def test_semana_desde_max_lunes(self):
        # max=lunes 07-sep → retrocede al último domingo 06-sep
        desde, hasta = _semana_desde_max(date(2026, 9, 7))
        self.assertEqual(hasta, date(2026, 9, 6))
        self.assertEqual(desde, date(2026, 8, 31))

    def test_semana_desde_max_miercoles(self):
        # max=miércoles 09-sep → misma semana completa 31-ago → 06-sep
        desde, hasta = _semana_desde_max(date(2026, 9, 9))
        self.assertEqual(hasta, date(2026, 9, 6))
        self.assertEqual(desde, date(2026, 8, 31))

    def test_es_fresca_rangos(self):
        hoy = date(2026, 9, 21)  # lunes
        self.assertTrue(_es_fresca(date(2026, 9, 20), hoy))   # domingo pasado
        self.assertTrue(_es_fresca(date(2026, 9, 14), hoy))   # límite inferior incluido
        self.assertFalse(_es_fresca(date(2026, 9, 13), hoy))  # justo fuera de límite
        self.assertFalse(_es_fresca(date(2026, 9, 6), hoy))   # BD vieja → NO fresca

    def test_destinatarios_csv(self):
        self.assertEqual(
            _destinatarios("a@x.co, b@y.co"), ["a@x.co", "b@y.co"])
        self.assertEqual(
            _destinatarios("Juan_ganicac@cun.edu.co,Juan_marin@cun.edu.co"),
            ["Juan_ganicac@cun.edu.co", "Juan_marin@cun.edu.co"],
        )
        self.assertEqual(_destinatarios("solo@x.co"), ["solo@x.co"])
        self.assertEqual(_destinatarios(""), [])


class TestLimpiarFondo(unittest.TestCase):
    def test_background_oscuro_a_claro(self):
        html = '<div style="background-color: rgb(15, 23, 42); color: rgb(203, 213, 225)">Hola</div>'
        limpio = _limpiar_fondo_oscuro(html)
        self.assertIn("background-color: #ffffff", limpio)
        self.assertIn("color: #334155", limpio)
        self.assertNotIn("rgb(15, 23, 42)", limpio)

    def test_borde_oscuro_a_claro(self):
        html = '<tr style="border-bottom:1px solid rgb(30,41,59)">'
        limpio = _limpiar_fondo_oscuro(html)
        self.assertIn("border-bottom: 1px solid #e2e8f0", limpio)

    def test_html_sin_estilos_no_se_rompe(self):
        self.assertEqual(_limpiar_fondo_oscuro("<p>x</p>"), "<p>x</p>")


class TestEmojisSemafaro(unittest.TestCase):
    def test_emojis_a_palabras(self):
        out = _emojis_a_texto("🟢 bueno · 🟡 medio · 🔴 malo")
        self.assertIn("Verde", out)
        self.assertIn("Amarillo", out)
        self.assertIn("Rojo", out)
        self.assertNotIn("🟢", out)


class TestBadgesTablas(unittest.TestCase):
    def test_semafaro_a_badge_de_color(self):
        html = (
            "<table><tr><th>Asesor</th><th>Estado</th></tr>"
            '<tr><td>A</td><td>Verde</td></tr>'
            '<tr><td>B</td><td>Rojo</td></tr></table>'
        )
        out = _badges_tablas(html)
        self.assertIn('class="badge" style="background:#16a34a"', out)  # Verde
        self.assertIn('style="background:#dc2626"', out)                # Rojo
        self.assertIn('class="sc"', out)                                # col semáforo centrada
        self.assertIn("<span", out)

    def test_sin_badge_no_toca(self):
        html = "<table><tr><td>Andres</td><td>245</td></tr></table>"
        self.assertEqual(_badges_tablas(html), html)


class TestPanelizarResumen(unittest.TestCase):
    def test_envuelve_resumen_en_panel(self):
        html = (
            "<h2>Resumen Ejecutivo</h2><ul><li>Punto</li></ul>"
            "<p>Conclusión</p><h2>Tablero</h2><p>Datos</p>"
        )
        out = _panelizar_resumen(html)
        self.assertIn('<div class="panel">', out)
        self.assertIn("Punto", out)
        self.assertIn("Conclusión", out)
        self.assertNotIn('<div class="panel">', out.split("<h2>Tablero</h2>")[1])

    def test_limpio_no_toca(self):
        html = "<p>Sin resumen</p>"
        self.assertEqual(_panelizar_resumen(html), html)


class TestKillSwitchAlerta(unittest.TestCase):
    """ALERTA_ENABLED es kill-switch independiente del envío del reporte."""

    def test_alerta_no_se_envia_con_switch_apagado(self):
        from unittest import mock
        with mock.patch.dict(os.environ, {"ALERTA_ENABLED": "0"}, clear=False), \
                mock.patch("enviar_reporte_semanal._crear_tabla_alertas") as crear, \
                mock.patch("enviar_reporte_semanal._alerta_enviada_hoy") as hoy, \
                mock.patch("enviar_reporte_semanal._enviar_alerta_stale") as enviar, \
                mock.patch("enviar_reporte_semanal._registrar_alerta") as reg:
            _alertar_stale(date(2026, 9, 6))
        crear.assert_not_called()
        hoy.assert_not_called()
        enviar.assert_not_called()
        reg.assert_not_called()

    def test_alerta_se_envia_y_registra_con_switch_encendido(self):
        from unittest import mock
        with mock.patch.dict(os.environ, {"ALERTA_ENABLED": "1"}, clear=False), \
                mock.patch("enviar_reporte_semanal._crear_tabla_alertas"), \
                mock.patch("enviar_reporte_semanal._alerta_enviada_hoy", return_value=False), \
                mock.patch("enviar_reporte_semanal._enviar_alerta_stale") as enviar, \
                mock.patch("enviar_reporte_semanal._registrar_alerta") as reg:
            _alertar_stale(date(2026, 9, 6))
        enviar.assert_called_once()
        reg.assert_called_once()

    def test_dedup_diario_no_reenvia(self):
        from unittest import mock
        with mock.patch.dict(os.environ, {"ALERTA_ENABLED": "1"}, clear=False), \
                mock.patch("enviar_reporte_semanal._crear_tabla_alertas"), \
                mock.patch("enviar_reporte_semanal._alerta_enviada_hoy", return_value=True), \
                mock.patch("enviar_reporte_semanal._enviar_alerta_stale") as enviar, \
                mock.patch("enviar_reporte_semanal._registrar_alerta") as reg:
            _alertar_stale(date(2026, 9, 6))
        enviar.assert_not_called()
        reg.assert_not_called()


if __name__ == "__main__":
    unittest.main()
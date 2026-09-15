import React, { useEffect, useState, useMemo } from 'react';
import { jsPDF } from 'jspdf';
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';
import { API_BASE, apiFetch } from '../config';
import ChatVisor from '../components/Transcripciones/ChatVisor';
import MetricasGrid from '../components/Transcripciones/MetricasGrid';
import Chat from '../components/Chat';
import SendMessage from '../components/ui/SendMessage';
import logoCLTiene from '../assets/logo_cl_tiene.png';

/**
 * PROTOTIPO — "Mi Desempeño" (vista individual del asesor).
 * Página aparte, aislada del dashboard de supervisor. Reutiliza endpoints que ya
 * existen (rendimiento_agente + analizar_asesor). El asesor se elige con un
 * selector ("simular como…"); en la versión real saldría del token autenticado
 * (identidad parametrizada — ver regla de seguridad).
 */
const MiDesempeno = () => {
  const [asesores, setAsesores] = useState([]);      // rendimiento_agente (periodo)
  const [sel, setSel] = useState("");                 // asesor simulado
  const [desde, setDesde] = useState("");             // filtro de fecha
  const [hasta, setHasta] = useState("");
  const [coach, setCoach] = useState("");             // HTML del Coach IA
  const [cargandoCoach, setCargandoCoach] = useState(false);
  const [evol, setEvol] = useState([]);               // evolución semanal
  const [llamadas, setLlamadas] = useState([]);       // lista de llamadas del asesor
  const [llamadaSel, setLlamadaSel] = useState("");   // llamada elegida
  const [chat, setChat] = useState([]);               // mensajes de la transcripción
  const [historial, setHistorial] = useState([]);     // historial del teléfono elegido
  const [cargandoHistorial, setCargandoHistorial] = useState(false);
  const [metricas, setMetricas] = useState([]);
  const [modoChat, setModoChat] = useState('general');
  const [chatMensajes, setChatMensajes] = useState([
    { role: 'ai', content: 'Soy tu agente de desempeño. Puedes preguntarme sobre tus métricas o, al seleccionar una llamada, sobre esa conversación.' },
  ]);
  const [chatInput, setChatInput] = useState('');
  const [chatCargando, setChatCargando] = useState(false);
  const [cargandoPDF, setCargandoPDF] = useState(false);

  // ?nombre_asesor=..&fecha_desde=..&fecha_hasta=.. (incluye el asesor solo si se pide)
  const qp = (conAsesor) => {
    const p = new URLSearchParams();
    if (conAsesor && sel) p.set('nombre_asesor', sel);
    if (desde) p.set('fecha_desde', desde);
    if (hasta) p.set('fecha_hasta', hasta);
    const s = p.toString();
    return s ? `?${s}` : '';
  };

  // Rendimiento de todos los asesores en el periodo (KPIs del asesor + benchmark)
  useEffect(() => {
    apiFetch(`${API_BASE}/api/rendimiento_agente${qp(false)}`)
      .then(r => r.json())
      .then(data => {
        const arr = Array.isArray(data) ? data.filter(a => (a.llamadas || 0) > 0) : [];
        setAsesores(arr);
        setSel(prev => (!arr.length || (prev && arr.some(a => a.n === prev))) ? prev : arr[0].n);
      })
      .catch(() => setAsesores([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [desde, hasta]);

  const yo = useMemo(() => asesores.find(a => a.n === sel) || null, [asesores, sel]);

  // Benchmark anónimo: posición por contacto efectivo (1 = mejor)
  const bench = useMemo(() => {
    if (!yo || !asesores.length) return null;
    const orden = [...asesores].sort((a, b) => (b.contacto_efectivo ?? b.contacto_pct ?? 0) - (a.contacto_efectivo ?? a.contacto_pct ?? 0));
    const rank = orden.findIndex(a => a.n === sel) + 1;
    const total = orden.length;
    const topPct = Math.max(1, Math.round((rank / total) * 100));
    return { rank, total, topPct, fill: Math.max(6, 100 - Math.round(((rank - 1) / total) * 100)) };
  }, [yo, asesores, sel]);

  const fmtTMO = (seg) => {
    const s = Math.round(Number(seg) || 0);
    const m = Math.floor(s / 60), ss = s % 60;
    return `${m}:${String(ss).padStart(2, '0')}`;
  };

  const cargarLogo = () =>
    new Promise((resolve) => {
      const img = new Image();
      img.onload = () => {
        const c = document.createElement('canvas');
        c.width = img.naturalWidth;
        c.height = img.naturalHeight;
        c.getContext('2d').drawImage(img, 0, 0);
        resolve({ dataUrl: c.toDataURL('image/png'), w: img.naturalWidth, h: img.naturalHeight });
      };
      img.onerror = () => resolve(null);
      img.src = logoCLTiene;
    });

  const fetchCoachRaw = async () => {
    if (!sel) return '';
    const extra = new URLSearchParams();
    if (desde) extra.set('fecha_desde', desde);
    if (hasta) extra.set('fecha_hasta', hasta);
    const res = await apiFetch(`${API_BASE}/ia/analizar_asesor?asesor=${encodeURIComponent(sel)}${extra.toString() ? '&' + extra.toString() : ''}`);
    const result = await res.json();
    return result.result || '';
  };

  const parseEjemploLlamada = async (llamada) => {
    try {
      const r = await apiFetch(`${API_BASE}/api/transcripcion/llamada/${llamada.id}${qp(true)}`);
      const d = await r.json();
      return { llamada, mensajes: Array.isArray(d?.mensajes) ? d.mensajes : [] };
    } catch {
      return { llamada, mensajes: [] };
    }
  };

  const generarPDF = async () => {
    if (!yo || cargandoPDF) return;
    setCargandoPDF(true);
    try {
      const logo = await cargarLogo();

      // Coach IA: si no se generó en pantalla, se genera aquí para que el PDF sea completo.
      const coachTexto = (coach && coach.trim() && !coach.includes('No se pudo generar'))
        ? coach
        : await fetchCoachRaw().catch(() => '');

      // Limpia ecos/reps del STT antes de imprimir (solo elimina repeticiones idénticas).
      const normSTT = (s) => clean(s).toLowerCase().replace(/[^\w\sáéíóúñ]/gi, '').replace(/\s+/g, ' ').trim();
      const limpiaSTT = (lista) => {
        const out = [];
        lista.forEach((m) => {
          const partes = clean(m.text).match(/[^.!?]+[.!?]*/g) || [];
          const unicos = [];
          partes.forEach((p) => {
            const np = normSTT(p);
            if (np && unicos.length && normSTT(unicos[unicos.length - 1]) === np) return;
            unicos.push(p);
          });
          const text = unicos.join(' ').trim();
          if (!text) return;
          const ant = out[out.length - 1];
          if (ant && ant.speaker === m.speaker && normSTT(ant.text) === normSTT(text)) return;
          out.push({ ...m, text });
        });
        return out;
      };

      // Análisis heurístico de por qué la llamada es un buen ejemplo (señales positivas).
      const analizarTranscripcion = (mensajes) => {
        const texto = mensajes.map((m) => clean(m.text)).join(' ').toLowerCase();
        if (!texto) return [];
        const hallazgos = [];
        if (/\b(buenos?\s*d[ií]as|buenas?\s*(tardes|noches)|hola|al[oó])\b/.test(texto)) {
          hallazgos.push('Saluda e inicia la llamada con tono cordial, generando un buen primer contacto.');
        }
        if (/\bse[nñ]or(ita|a)?\s+[a-záéíóúñ]/.test(texto)) {
          hallazgos.push('Se dirige al cliente por su nombre o tratamiento, personalizando la atención.');
        }
        if (/\b(correo|celular|tel[eé]fono|n[úu]mero|direcci[oó]n|identificaci[oó]n)\b/.test(texto)) {
          hallazgos.push('Confirma y registra datos del cliente de forma clara (correo o teléfono).');
        }
        if (/\b(rep[ií]t|aclaro|aclari|le explico|esc[uú]ch|como le dije|insist|pregunta|el ipc)\b/.test(texto)) {
          hallazgos.push('Atiende las preguntas del cliente y aclara las inquietudes sin impacientarse.');
        }
        if (/\b(48 horas|le llegar|le llega|activamos|activaci[oó]n|enviamos|estaremos|disponible)\b/.test(texto)) {
          hallazgos.push('Explica los próximos pasos de forma concreta (activación, envío o seguimiento).');
        }
        if (/\b(tranquil|no se preocupe|le entiendo|te entiendo)\b/.test(texto)) {
          hallazgos.push('Maneja las dudas del cliente con calma y empatía.');
        }
        if (/\b(24\s*[-/ ]?7|soporte|le vamos a acompa[nñ]ar|estaremos pendiente)\b/.test(texto)) {
          hallazgos.push('Deja claro que el equipo queda disponible para apoyar al cliente.');
        }
        if (/\b(gracias por su tiempo|buen d[ií]a|que tenga|hasta luego|muchas gracias|bendiciones)\b/.test(texto)) {
          hallazgos.push('Cierra la llamada con cortesía y un mensaje positivo.');
        }
        return hallazgos;
      };

      // --- Ejemplos reales: llamadas Venta + las contactadas más largas ---
      const sepRes = (l) => String((l.name || '').split(' | ')[1] || '').trim();
      const llVentas = llamadas.filter(l => sepRes(l) === 'Venta');
      const llContactos = llamadas.filter(l => ['Contactado', 'Rechazado'].includes(sepRes(l)));
      const ejemplos = [];
      for (const l of llVentas.slice(0, 2)) {
        const e = await parseEjemploLlamada(l);
        if (e.mensajes.length) ejemplos.push(e);
      }
      const candidatos = [];
      for (const l of llContactos.slice(0, 4)) {
        candidatos.push(await parseEjemploLlamada(l));
      }
      candidatos.sort((a, b) => b.mensajes.length - a.mensajes.length);
      for (const e of candidatos.slice(0, 2)) {
        if (e.mensajes.length) ejemplos.push(e);
      }
      const ejemplosFinal = ejemplos.slice(0, 4);
      const ventasReales = llVentas.length; // posibles ventas con transcripción en el período

      // --- Posiciones en el equipo (comparación con los demás asesores) ---
      const nEq = asesores.length;
      const vals = (k) => asesores.map(a => Number(a[k]) || 0);
      const resumir = (k, dir = 'desc') => {
        const vv = vals(k);
        const v = Number(yo[k]) || 0;
        const rank = dir === 'desc'
          ? vv.filter(x => x > v).length + 1
          : vv.filter(x => x < v).length + 1;
        return {
          v,
          rank,
          prom: vv.reduce((s, x) => s + x, 0) / nEq,
          mejor: dir === 'desc' ? Math.max(...vv) : Math.min(...vv),
          total: nEq,
        };
      };
      const pos = {
        llamadas: resumir('llamadas'),
        contacto: resumir('contacto_efectivo'),
        contacto_pct: resumir('contacto_pct'),
        tmo: resumir('tmo_seg', 'asc'),
        calidad: resumir('score_calidad'),
        venta: resumir('tasa_venta'),
      };
      const pct1 = (x) => `${Number(x).toFixed(1)}%`;
      const pct2 = (x) => `${Number(x).toFixed(2)}%`;

      const doc = new jsPDF({ unit: 'pt', format: 'a4' });
      const margin = 40;
      const pageW = doc.internal.pageSize.getWidth();
      const maxW = pageW - margin * 2;

      const clean = (s) => String(s ?? '')
        .replace(/→/g, '->')
        .replace(/[“”]/g, '"')
        .replace(/[‘’]/g, "'")
        .replace(/[–—]/g, '-')
        .replace(/…/g, '...')
        .split('').filter((ch) => ch.charCodeAt(0) <= 255).join('')
        .replace(/\s+/g, ' ')
        .trim();

      const PINK = [252, 50, 118];
      const GRAY = [71, 85, 105];
      const SLATE = [30, 41, 59];

      let y;
      const salto = (h = 13) => { y += h; if (y > 790) { doc.addPage(); y = 56; } };
      const ensure = (h) => { if (y + h > 790) { doc.addPage(); y = 56; } };
      const seccion = (txt, size = 13) => {
        salto(10); ensure(28);
        doc.setFont('helvetica', 'bold'); doc.setFontSize(size); doc.setTextColor(...SLATE);
        doc.splitTextToSize(clean(txt), maxW).forEach((line) => { ensure(18); doc.text(line, margin, y); salto(18); });
        doc.setDrawColor(...PINK); doc.setLineWidth(1.2); doc.line(margin, y, margin + 46, y);
        doc.setDrawColor(226, 232, 240); doc.setLineWidth(0.6); doc.line(margin + 46, y, margin + maxW, y);
        salto(12);
        doc.setFont('helvetica', 'normal'); doc.setTextColor(...GRAY);
      };
      const parrafo = (txt, size = 10.5, color = GRAY, bold = false, indent = 0) => {
        const t = clean(txt);
        if (!t) return;
        doc.setFont('helvetica', bold ? 'bold' : 'normal'); doc.setFontSize(size); doc.setTextColor(...color);
        doc.splitTextToSize(t, maxW - indent).forEach((line) => { ensure(size + 4); doc.text(line, margin + indent, y); salto(size + 4); });
        doc.setFont('helvetica', 'normal');
      };
      const vineta = (txt, indent = 16, size = 10.5) => {
        const t = clean(txt);
        if (!t) return;
        doc.setFont('helvetica', 'normal'); doc.setFontSize(size); doc.setTextColor(...GRAY);
        doc.splitTextToSize(t, maxW - indent).forEach((line, i) => {
          ensure(size + 4);
          if (i === 0) { doc.setFillColor(...PINK); doc.circle(margin + 6, y - 3, 1.7, 'F'); }
          doc.text(line, margin + indent, y); salto(size + 4);
        });
      };
      const subseccion = (txt) => {
        salto(8);
        ensure(24);
        doc.setFont('helvetica', 'bold'); doc.setFontSize(11); doc.setTextColor(...SLATE);
        const lines = doc.splitTextToSize(clean(txt), maxW);
        lines.forEach((line) => { ensure(16); doc.text(line, margin, y); salto(16); });
        const ry = y - 16 + 5;
        doc.setDrawColor(...PINK); doc.setLineWidth(1); doc.line(margin, ry, margin + 26, ry);
        doc.setDrawColor(226, 232, 240); doc.setLineWidth(0.5); doc.line(margin + 26, ry, margin + maxW, ry);
        salto(12);
        doc.setFont('helvetica', 'normal'); doc.setTextColor(...GRAY);
      };
      const grabarHTML = (html, opt = {}) => {
        const holder = document.createElement('div');
        holder.innerHTML = html;
        holder.querySelectorAll('br').forEach((b) => b.replaceWith(document.createTextNode(' ')));
        const render = (node) => {
          if (!node || node.nodeType !== 1) return;
          const tag = node.tagName;
          if (/^H[1-6]$/.test(tag)) {
            subseccion(node.textContent);
          } else if (tag === 'P') {
            parrafo(node.textContent, opt.size || 10, GRAY);
          } else if (tag === 'UL' || tag === 'OL') {
            node.querySelectorAll(':scope > li').forEach((li) => vineta(li.textContent));
          } else if (tag === 'TABLE') {
            node.querySelectorAll(':scope > tr, :scope > tbody > tr, :scope > thead > tr').forEach((tr) => {
              const celdas = Array.from(tr.children).map((td) => clean(td.textContent)).filter(Boolean);
              if (celdas.length) parrafo(celdas.join('   |   '), 9, GRAY);
            });
          } else if (tag === 'LI') {
            vineta(node.textContent);
          } else {
            Array.from(node.children).forEach(render);
          }
        };
        render(holder);
      };
      const panelPerfil = (items) => {
        const pad = 12, rowH = 19;
        const boxH = pad * 2 + items.length * rowH;
        ensure(boxH + 8);
        const top = y;
        doc.setFillColor(248, 250, 252); doc.setDrawColor(226, 232, 240); doc.setLineWidth(0.6);
        doc.roundedRect(margin, top, maxW, boxH, 7, 7, 'FD');
        doc.setFillColor(...PINK); doc.rect(margin, top + 3, 4, boxH - 6, 'F');
        let ty = top + pad + 8;
        items.forEach((it) => {
          doc.setFont('helvetica', 'bold'); doc.setFontSize(9); doc.setTextColor(100, 116, 139);
          doc.text(clean(it.label), margin + 18, ty);
          doc.setFont('helvetica', 'bold'); doc.setFontSize(12); doc.setTextColor(...SLATE);
          doc.text(clean(it.value), margin + maxW - 18, ty, { align: 'right' });
          ty += rowH;
        });
        y = top + boxH; salto(12);
      };
      const drawTable = (headers, rows, widthsPct, { bestCol = -1, bestRows = [] } = {}) => {
        const W = widthsPct.map(p => p * maxW);
        const lineH = 11, padX = 7, padY = 5, fs = 9;
        const renderRow = (cells, { head = false, idx = -1 } = {}) => {
          doc.setFont('helvetica', head ? 'bold' : 'normal'); doc.setFontSize(fs);
          let maxLines = 1;
          const wrapped = cells.map((cell, c) => {
            const lines = doc.splitTextToSize(clean(String(cell ?? '')), W[c] - 2 * padX);
            maxLines = Math.max(maxLines, lines.length);
            return lines;
          });
          const h = maxLines * lineH + 2 * padY;
          if (y + h > 790) { doc.addPage(); y = 56; renderRow(headers, { head: true }); }
          doc.setFillColor(...(head ? PINK : idx % 2 ? [248, 250, 252] : [255, 255, 255]));
          doc.rect(margin, y, maxW, h, 'F');
          let x = margin;
          wrapped.forEach((lines, c) => {
            const esBest = !head && c === bestCol && bestRows.includes(idx);
            doc.setFont('helvetica', head || esBest ? 'bold' : 'normal');
            doc.setTextColor(...(head ? [255, 255, 255] : esBest ? [22, 163, 74] : c === 0 ? SLATE : GRAY));
            const tx = c === 0 ? x + padX : x + W[c] - padX;
            const align = c === 0 ? 'left' : 'right';
            lines.forEach((ln, i) => doc.text(ln, tx, y + padY + lineH * (i + 1) - 2, { align }));
            x += W[c];
          });
          doc.setDrawColor(226, 232, 240); doc.setLineWidth(0.5);
          doc.rect(margin, y, maxW, h, 'S');
          y += h;
          doc.setFont('helvetica', 'normal');
        };
        renderRow(headers, { head: true });
        rows.forEach((r, idx) => renderRow(r, { idx }));
        salto(10);
      };

      // Banda de encabezado ejecutivo
      doc.setFillColor(...PINK);
      doc.rect(0, 0, pageW, 76, 'F');
      if (logo?.dataUrl) {
        const lw = 130, lh = lw * (logo.h / logo.w);
        doc.addImage(logo.dataUrl, 'PNG', pageW - margin - lw, (76 - lh) / 2, lw, lh);
      }
      doc.setTextColor(255, 255, 255);
      doc.setFont('helvetica', 'bold');
      doc.setFontSize(16);
      doc.text('Reporte de Desempeño Individual', margin, 36);
      doc.setFont('helvetica', 'normal');
      doc.setFontSize(10);
      doc.text('CL Tiene Soluciones - Mi Desempeño (DivergencyAI SAS)', margin, 56);

      y = 98;
      doc.setTextColor(120, 120, 120);
      doc.setFontSize(9);
      const periodoTexto = (desde || hasta) ? `${desde || 'inicio'} -> ${hasta || 'hoy'}` : 'Histórico';
      doc.text(`Generado: ${new Date().toLocaleDateString()}   |   Asesor: ${clean(sel || '')}   |   Período: ${clean(periodoTexto)}`, margin, y);
      salto(16);

      // 1. Resumen del período (panel destacado)
      seccion('1. Resumen del período');
      panelPerfil([
        { label: 'LLAMADAS GESTIONADAS', value: String(yo.llamadas ?? 0) },
        { label: 'CONTACTO EFECTIVO', value: pct1(yo.contacto_efectivo ?? 0) },
        { label: 'LLAMADAS DE CALIDAD', value: pct1(yo.contacto_pct ?? 0) },
        { label: 'TMO PROMEDIO', value: fmtTMO(yo.tmo_seg) },
        { label: 'CALIDAD DE ATENCIÓN', value: `${Math.round(yo.score_calidad ?? 0)}/100` },
        { label: 'TASA DE POSIBLES VENTAS', value: pct2(yo.tasa_venta ?? 0) },
        { label: 'POSIBLES VENTAS CON TRANSCRIPCIÓN', value: String(ventasReales) },
      ]);

      // 2. Posición en el equipo
      seccion('2. Posición en el equipo');
      const filasTabla = [
        { met: 'Llamadas gestionadas', val: String(yo.llamadas ?? 0), prom: String(Math.round(pos.llamadas.prom)), mejor: String(pos.llamadas.mejor), rank: pos.llamadas.rank, esMejor: pos.llamadas.rank === 1 },
        { met: 'Contacto efectivo', val: pct1(yo.contacto_efectivo ?? 0), prom: pct1(pos.contacto.prom), mejor: pct1(pos.contacto.mejor), rank: pos.contacto.rank, esMejor: pos.contacto.rank === 1 },
        { met: 'Llamadas de calidad', val: pct1(yo.contacto_pct ?? 0), prom: pct1(pos.contacto_pct.prom), mejor: pct1(pos.contacto_pct.mejor), rank: pos.contacto_pct.rank, esMejor: pos.contacto_pct.rank === 1 },
        { met: 'TMO (conversación)', val: fmtTMO(yo.tmo_seg), prom: fmtTMO(pos.tmo.prom), mejor: fmtTMO(pos.tmo.mejor), rank: '—', esMejor: false },
        { met: 'Calidad de atención', val: `${Math.round(yo.score_calidad ?? 0)}/100`, prom: `${Math.round(pos.calidad.prom)}/100`, mejor: `${Math.round(pos.calidad.mejor)}/100`, rank: pos.calidad.rank, esMejor: pos.calidad.rank === 1 },
        { met: 'Tasa posibles ventas', val: pct2(yo.tasa_venta ?? 0), prom: pct2(pos.venta.prom), mejor: pct2(pos.venta.mejor), rank: pos.venta.rank, esMejor: pos.venta.rank === 1 },
      ];
      const bestRows = [];
      filasTabla.forEach((f, i) => { if (f.esMejor) bestRows.push(i); });
      drawTable(
        ['Métrica', 'Usted', 'Prom. equipo', 'Mejor', 'Puesto'],
        filasTabla.map(f => [f.met, f.val, f.prom, f.mejor, typeof f.rank === 'number' ? `${f.rank} / ${nEq}` : f.rank]),
        [0.30, 0.16, 0.18, 0.16, 0.20],
        { bestCol: 4, bestRows }
      );
      parrafo('El TMO es un síntoma, no una meta: el rango sano está entre 2 y 4 minutos de conversación; un valor muy bajo puede indicar cierres apurados y uno muy alto, menor productividad. Por eso el TMO no tiene puesto de equipo en la tabla (ordenarlo de menor a mayor tiempo parecería premiar llamadas cortas, lo que no refleja calidad). Se lee junto con contacto efectivo y calidad.', 8.5, [100, 116, 139]);
      salto(6);

      // 3. Lo que lo/la destaca
      seccion('3. Lo que lo/la destaca');
      const dest = [];
      if (pos.venta.rank === 1) {
        dest.push(`Es el/la #1 del equipo en posibles ventas (${pct2(yo.tasa_venta)} de tasa sobre ${yo.llamadas} llamadas; el promedio del equipo es ${pct2(pos.venta.prom)}).`);
      } else if (Number(yo.tasa_venta) > pos.venta.prom * 1.3) {
        dest.push(`Destaca en posibles ventas: puesto ${pos.venta.rank} de ${pos.venta.total} (${pct2(yo.tasa_venta)} vs ${pct2(pos.venta.prom)} promedio del equipo).`);
      } else {
        dest.push(`Posibles ventas: puesto ${pos.venta.rank} de ${pos.venta.total} en tasa de posibles ventas (${pct2(yo.tasa_venta)}; mejor del equipo ${pct2(pos.venta.mejor)}).`);
      }
      if (pos.contacto.rank === 1) {
        dest.push(`Logra el mejor contacto efectivo del equipo (${pct1(yo.contacto_efectivo ?? 0)} vs ${pct1(pos.contacto.prom)} promedio), es decir, de cada 100 llamadas habla de verdad con ${pct1(yo.contacto_efectivo ?? 0)} personas.`);
      } else if (pos.contacto.rank <= 3) {
        dest.push(`Contacto efectivo en el top ${pos.contacto.rank} del equipo (${pct1(yo.contacto_efectivo ?? 0)}; promedio del equipo ${pct1(pos.contacto.prom)}).`);
      } else {
        dest.push(`Contacto efectivo: ${pct1(yo.contacto_efectivo ?? 0)} (puesto ${pos.contacto.rank} de ${pos.contacto.total}; promedio del equipo ${pct1(pos.contacto.prom)}).`);
      }
      if (pos.contacto_pct.rank <= 2) {
        dest.push(`Llamadas de calidad en el top ${pos.contacto_pct.rank} del equipo (${pct1(yo.contacto_pct ?? 0)} vs ${pct1(pos.contacto_pct.prom)} promedio).`);
      }
      if (pos.calidad.rank <= 2) {
        dest.push(`Calidad de atención sobresaliente: puesto ${pos.calidad.rank} de ${pos.calidad.total} (${Math.round(yo.score_calidad ?? 0)}/100 vs ${Math.round(pos.calidad.prom)}/100 promedio).`);
      }
      if (pos.llamadas.rank <= 2) {
        dest.push(`Alto volumen de gestión: puesto ${pos.llamadas.rank} de ${pos.llamadas.total} en llamadas (${yo.llamadas}; promedio del equipo ${Math.round(pos.llamadas.prom)}).`);
      }
      const tmoS = Number(yo.tmo_seg) || 0;
      if (tmoS >= 120 && tmoS <= 240) {
        dest.push(`Su TMO de ${fmtTMO(yo.tmo_seg)} está dentro del rango sano de 2 a 4 minutos de conversación efectiva.`);
      }
      dest.forEach(d => vineta(d));
      if (ejemplosFinal.length) {
        vineta(`Se complementa con ${ejemplosFinal.length} ejemplo(s) real(es) analizado(s) en la sección 5.`);
      }

      // 4. Posibles ventas
      seccion('4. Posibles ventas');
      const transRate = llamadas.length ? (ventasReales / llamadas.length) * 100 : 0;
      if (pos.venta.rank === 1) {
        parrafo(`En el período analizado es el/la asesor(a) #1 del equipo en posibles ventas: ${ventasReales} cierre(s) detectado(s) en sus ${llamadas.length} llamada(s) con transcripción (${pct2(transRate)} de tasa transcrita).`, 11, SLATE, true);
      } else {
        parrafo(`En el período analizado ocupa el puesto ${pos.venta.rank} de ${pos.venta.total} en posibles ventas: ${ventasReales} cierre(s) detectado(s) en sus ${llamadas.length} llamada(s) con transcripción (${pct2(transRate)} de tasa transcrita).`, 11, SLATE, true);
      }
      salto(3);
      vineta(`Posibles ventas con transcripción: ${ventasReales} (sobre ${llamadas.length} transcritas, ${pct2(transRate)})`);
      vineta(`Tasa de posibles ventas (KPI, sobre todas sus ${yo.llamadas} llamadas): ${pct2(yo.tasa_venta)}  -  promedio del equipo: ${pct2(pos.venta.prom)}  -  mejor del equipo: ${pct2(pos.venta.mejor)}`);
      vineta(`Volumen usado para el puesto: ${yo.llamadas} llamadas en el período.`);
      parrafo('Nota: las posibles ventas se infieren de la transcripción (llamada que cierra, precio u orden confirmada). La venta cerrada real (CRM/Zoho) se mide aparte y entra cuando CL Tiene la publique en la base.', 8.5, [100, 116, 139]);
      salto(6);

      // 5. Ejemplos reales
      seccion('5. Ejemplos reales de sus llamadas');
      if (!ejemplosFinal.length) {
        parrafo('No hay llamadas con transcripción en el período para mostrar ejemplos reales. Trata con un rango de fechas con más actividad.');
      } else {
        parrafo('El análisis se basa en la transcripción del audio, que puede contener errores del reconocimiento de voz (STT). Estos son posibles ventas; la venta cerrada real se confirma en el CRM (Zoho).', 8.5, [100, 116, 139]);
        salto(4);
        ejemplosFinal.forEach((ej, idx) => {
          const partes = String(ej.llamada.name || '').split(' | ');
          const resLabel = String(partes[1] || '').trim() === 'Venta' ? 'Posible venta' : String(partes[1] || '').trim();
          ensure(30);
          doc.setFont('helvetica', 'bold');
          doc.setFontSize(10.5);
          doc.setTextColor(...SLATE);
          doc.text(`Ejemplo ${idx + 1} - ${clean(partes[0] || '')} · ${clean(resLabel)} · ${clean(partes[3] || 'sin teléfono')}`, margin, y);
          salto(16);
          const mensajes = limpiaSTT(ej.mensajes);

          const hallazgos = analizarTranscripcion(mensajes);
          doc.setFont('helvetica', 'bold');
          doc.setFontSize(8);
          doc.setTextColor(...PINK);
          doc.text('ANÁLISIS: POR QUÉ ES UN BUEN EJEMPLO', margin, y);
          salto(11);
          if (hallazgos.length) {
            hallazgos.forEach((h) => vineta(h, 14, 9.5));
          } else {
            vineta('Cumple el objetivo de la llamada y deja registro de conversación; el detalle se pierde por la deformación del audio (STT).', 14, 9.5);
          }
          salto(10);
        });
      }

      // 6. Evolución semanal
      if (evol.length) {
        seccion('6. Evolución semanal');
        const data = evol.slice(-12);
        drawTable(
          ['Semana', 'Llamadas', 'Posibles ventas'],
          data.map(fila => [fila.fecha, String(fila.llamadas ?? 0), String(fila.posibles_ventas ?? 0)]),
          [0.34, 0.33, 0.33]
        );
      }

      // 7. Coach IA
      seccion('7. Coach IA');
      if (coachTexto) {
        grabarHTML(coachTexto);
      } else {
        parrafo('No se pudo generar el coach IA en esta sesión. Intenta de nuevo desde la vista.');
      }

      // Compañeros anónimos que pueden copiar sus fortalezas
      const fortalezas = [
        { key: 'contacto', campo: 'contacto_efectivo', nombre: 'Contacto efectivo', fmt: pct1, accion: 'copiar su forma de iniciar y sostener la conversación' },
        { key: 'venta', campo: 'tasa_venta', nombre: 'Tasa de posibles ventas', fmt: pct2, accion: 'replicar su manejo de objeciones y cierre' },
        { key: 'contacto_pct', campo: 'contacto_pct', nombre: 'Llamadas de calidad', fmt: pct1, accion: 'seguir su estructura de las 7 categorías de calidad (saludo, comprensión del problema, cierre)' },
        { key: 'calidad', campo: 'score_calidad', nombre: 'Calidad de atención', fmt: (v) => `${Math.round(v)}/100`, accion: 'estructurar mejor cada llamada para acercarse a su puntaje' },
      ];
      const rankDe = (nom, campo) => {
        const vv = vals(campo);
        const v = Number(asesores.find((a) => a.n === nom)?.[campo]) || 0;
        return vv.filter((x) => x > v).length + 1;
      };
      const copiar = fortalezas
        .map((f) => {
          const prom = vals(f.campo).reduce((s, x) => s + x, 0) / nEq;
          const val = Number(yo[f.campo]) || 0;
          if (!(pos[f.key].rank <= 2 || (prom > 0 && val >= prom * 1.2))) return null;
          const peores = [...asesores]
            .filter((a) => a.n !== sel)
            .sort((a, b) => (Number(a[f.campo]) || 0) - (Number(b[f.campo]) || 0))
            .slice(0, 2);
          if (!peores.length) return null;
          const frases = peores.map((p) => `puesto ${rankDe(p.n, f.campo)} de ${pos[f.key].total} (${f.fmt(p[f.campo])})`);
          return { ...f, val, frases };
        })
        .filter(Boolean);
      if (copiar.length) {
        subseccion('Compañeros que pueden copiar estas fortalezas');
        parrafo('Lista anónima: se muestran los puestos más bajos del equipo en cada fortaleza suya, sin identificar a nadie.', 8.5, [100, 116, 139]);
        copiar.forEach((f) => {
          vineta(`${f.nombre}: usted (${f.fmt(f.val)}, puesto ${pos[f.key].rank} de ${pos[f.key].total}) — los compañeros de ${f.frases.join(' y ')} pueden ${f.accion}.`);
        });
      } else {
        parrafo('Su perfil está alineado con el promedio del equipo en las métricas clave, así que aún no hay compañeros que deban tomar de referencia sus cifras.');
      }

      // Nota metodológica
      seccion('Nota metodológica');
      parrafo('Contacto efectivo = se habló de verdad con la persona (Contactado + Rechazado + Venta). Calidad = score de la CUN (efectiva >= 80%). Posibles ventas = inferidas de la transcripción, no son ventas cerradas reales. Fuente: BigQuery CL Tiene.', 8.5, [100, 116, 139]);

      // Pie de página ejecutivo (todas las páginas)
      const totalPaginas = doc.getNumberOfPages();
      for (let p = 1; p <= totalPaginas; p++) {
        doc.setPage(p);
        doc.setDrawColor(228, 228, 228); doc.setLineWidth(0.5); doc.line(margin, 816, margin + maxW, 816);
        doc.setFont('helvetica', 'normal');
        doc.setFontSize(8);
        doc.setTextColor(150, 150, 150);
        doc.text('CL Tiene Soluciones - DivergencyAI SAS   |   Confidencial', margin, 830);
        doc.text(`Página ${p} de ${totalPaginas}`, margin + maxW, 830, { align: 'right' });
      }

      doc.save(`mi-desempeno-${clean(sel || yo.n || 'asesor')}.pdf`);
    } finally {
      setCargandoPDF(false);
    }
  };

  const generarCoach = async () => {
    if (!sel) return;
    setCargandoCoach(true);
    try {
      const raw = await fetchCoachRaw();
      setCoach(raw
        .replace(/background-color\s*:\s*rgb\(15,\s*23,\s*42\)[^;"']*/g, 'background-color: #f8fafc')
        .replace(/color\s*:\s*rgb\(203,\s*213,\s*225\)[^;"']*/g, 'color: #334155')
        .replace(/border-bottom\s*:\s*1px solid rgb\(30,\s*41,\s*59\)[^;"']*/g, 'border-bottom: 1px solid #e2e8f0'));
    } catch {
      setCoach("<p style='color:#dc2626'>No se pudo generar el coach. Intenta de nuevo.</p>");
    }
    setCargandoCoach(false);
  };

  // Al cambiar de asesor, limpiar el coach anterior
  useEffect(() => { setCoach(""); }, [sel]);

  useEffect(() => {
    setModoChat('general');
    setChatMensajes([{ role: 'ai', content: 'Soy tu agente de desempeño. Puedes preguntarme sobre tus métricas o, al seleccionar una llamada, sobre esa conversación.' }]);
  }, [sel]);

  const enviarPregunta = async (textOverride) => {
    const texto = (textOverride || chatInput).trim();
    if (!texto || chatCargando) return;
    if (modoChat === 'llamada' && !llamadaSel) {
      setChatMensajes(prev => [...prev, { role: 'ai', content: 'Selecciona una llamada para activar el agente específico.' }]);
      return;
    }
    setChatMensajes(prev => [...prev, { role: 'user', content: texto }]);
    setChatInput('');
    setChatCargando(true);
    try {
      const res = await apiFetch(`${API_BASE}/api/chat${qp(true)}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_message: texto, llamada_id: modoChat === 'llamada' ? Number(llamadaSel) : null }),
      });
      const data = await res.json();
      setChatMensajes(prev => [...prev, { role: 'ai', content: data.respuesta || 'No se obtuvo respuesta.' }]);
    } catch (error) {
      setChatMensajes(prev => [...prev, { role: 'ai', content: `Error: ${error.message}` }]);
    } finally {
      setChatCargando(false);
    }
  };

  // Evolución semanal del asesor seleccionado
  useEffect(() => {
    if (!sel) return;
    apiFetch(`${API_BASE}/evolucion-ventas${qp(true)}`)
      .then(r => r.json())
      .then(d => setEvol(Array.isArray(d) ? d : []))
      .catch(() => setEvol([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sel, desde, hasta]);

  // Lista de llamadas del asesor (selector de transcripción)
  useEffect(() => {
    if (!sel) { setLlamadas([]); return; }
    setLlamadaSel(""); setChat([]); setHistorial([]);
    apiFetch(`${API_BASE}/api/transcripcion/llamadas${qp(true)}`)
      .then(r => r.json())
      .then(d => setLlamadas(Array.isArray(d) ? d : []))
      .catch(() => setLlamadas([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sel, desde, hasta]);

  // Transcripción de la llamada elegida
  useEffect(() => {
    if (!llamadaSel) { setChat([]); setMetricas([]); return; }
    const llamada = llamadas.find(l => String(l.id) === String(llamadaSel));
    const telefono = llamada?.telefono;
    setCargandoHistorial(Boolean(telefono));
    if (telefono && telefono !== '-') {
      apiFetch(`${API_BASE}/api/transcripcion/historial/${telefono}${qp(true)}`)
        .then(r => r.json())
        .then(d => setHistorial(Array.isArray(d) ? d : []))
        .catch(() => setHistorial([]))
        .finally(() => setCargandoHistorial(false));
    } else {
      setHistorial([]);
      setCargandoHistorial(false);
    }
    apiFetch(`${API_BASE}/api/transcripcion/llamada/${llamadaSel}${qp(true)}`)
      .then(r => r.json())
      .then(d => setChat(Array.isArray(d?.mensajes) ? d.mensajes : []))
      .catch(() => setChat([]));
    apiFetch(`${API_BASE}/api/transcripcion/metricas/${llamadaSel}${qp(true)}`)
      .then(r => r.json())
      .then(d => setMetricas(Array.isArray(d) ? d : []))
      .catch(() => setMetricas([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [llamadaSel, llamadas]);

  const colorResultado = (resultado) => {
    const valor = String(resultado || '').toLowerCase();
    if (valor.includes('venta')) return '#16a34a';
    if (valor.includes('contact')) return '#2563eb';
    if (valor.includes('rechazo') || valor.includes('sin contacto')) return '#dc2626';
    return '#64748b';
  };

  const llamadaActiva = llamadas.find(l => String(l.id) === String(llamadaSel));

  const fmtSemana = (f) => {
    const d = new Date(f);
    return isNaN(d) ? String(f).slice(5) : `${d.getUTCDate()}/${d.getUTCMonth() + 1}`;
  };

  const kpi = (label, value, sub) => (
    <div style={{ flex: 1, minWidth: 150, background: '#fff', borderRadius: 14, padding: '18px 20px', border: '1px solid #e2e8f0', boxShadow: '0 1px 4px rgba(0,0,0,0.04)' }}>
      <div style={{ fontSize: 10, fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 8 }}>{label}</div>
      <div style={{ fontSize: 26, fontWeight: 800, color: '#0f172a', lineHeight: 1 }}>{value}</div>
      {sub && <div style={{ fontSize: 11, color: '#64748b', marginTop: 6 }}>{sub}</div>}
    </div>
  );

  return (
    <div style={{ minHeight: '100vh', background: '#f1f5f9', padding: '0 0 60px' }}>
      {/* Banner prototipo */}
      <div style={{ background: '#fef3c7', borderBottom: '1px solid #fcd34d', color: '#92400e', fontSize: 12, padding: '8px 24px', display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <strong>🧪 Modo prototipo</strong>
        <span>Vista de ejemplo del panel personal del asesor. En la versión real, el asesor entra con su usuario y ve solo lo suyo.</span>
        <span style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: 4 }}>Desde
            <input type="date" value={desde} onChange={e => setDesde(e.target.value)} style={{ padding: '4px 8px', borderRadius: 8, border: '1px solid #fcd34d', fontSize: 12 }} />
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: 4 }}>Hasta
            <input type="date" value={hasta} onChange={e => setHasta(e.target.value)} style={{ padding: '4px 8px', borderRadius: 8, border: '1px solid #fcd34d', fontSize: 12 }} />
          </label>
          {(desde || hasta) && <button onClick={() => { setDesde(""); setHasta(""); }} style={{ padding: '4px 10px', borderRadius: 8, border: '1px solid #fcd34d', background: '#fff', cursor: 'pointer', fontSize: 11 }}>Limpiar</button>}
          <button onClick={generarPDF} disabled={cargandoPDF} style={{ padding: '7px 12px', borderRadius: 8, border: 'none', background: '#FC3276', color: '#fff', fontWeight: 700, cursor: cargandoPDF ? 'wait' : 'pointer', fontSize: 11, opacity: cargandoPDF ? 0.7 : 1 }}>{cargandoPDF ? '📄 Generando…' : '📄 PDF'}</button>
          Simular como:
          <select value={sel} onChange={e => setSel(e.target.value)}
            style={{ padding: '5px 10px', borderRadius: 8, border: '1px solid #fcd34d', background: '#fff', color: '#0f172a', fontWeight: 600, fontSize: 12 }}>
            {asesores.map(a => <option key={a.n} value={a.n}>{a.n}</option>)}
          </select>
        </span>
      </div>

      <div style={{ maxWidth: 1080, margin: '0 auto', padding: '28px 24px' }}>
        {/* Header personal */}
        <div style={{ background: 'linear-gradient(120deg, #FC3276 0%, #9333ea 100%)', borderRadius: 18, padding: '28px 32px', color: '#fff', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 12, marginBottom: 22 }}>
          <div>
            <div style={{ fontSize: 26, fontWeight: 800, marginBottom: 4 }}>Mi Desempeño</div>
            <div style={{ fontSize: 14, opacity: 0.9 }}>{yo ? yo.n : '—'}</div>
          </div>
          <div style={{ textAlign: 'right', fontSize: 12, opacity: 0.9 }}>{(desde || hasta) ? `${desde || '…'} → ${hasta || '…'}` : 'Histórico'}<br />Solo mis llamadas</div>
        </div>

        {!yo ? (
          <div style={{ color: '#64748b', padding: 40, textAlign: 'center' }}>Cargando…</div>
        ) : (
          <>
            {/* KPIs personales */}
            <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', marginBottom: 22 }}>
              {kpi('Mis llamadas', yo.llamadas ?? '—')}
              {kpi('Contacto efectivo', (yo.contacto_efectivo ?? yo.contacto_pct ?? 0) + '%')}
              {kpi('Mi TMO', fmtTMO(yo.tmo_seg), 'tiempo hablado prom.')}
              {kpi('Calidad', (yo.score_calidad ?? 0) + '/100')}
              {kpi('Posibles ventas', (yo.tasa_venta ?? 0) + '%')}
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 18, alignItems: 'start' }}>
              {/* Benchmark anónimo */}
              <div style={{ background: '#fff', borderRadius: 16, padding: '22px 24px', border: '1px solid #e2e8f0' }}>
                <div style={{ fontSize: 14, fontWeight: 700, color: '#0f172a', marginBottom: 14 }}>📊 Mi posición en el equipo <span style={{ color: '#94a3b8', fontWeight: 500 }}>(anónima)</span></div>
                {bench && (
                  <>
                    <div style={{ height: 12, borderRadius: 8, background: 'linear-gradient(90deg,#fbcfe8,#f9a8d4)', position: 'relative', marginBottom: 12 }}>
                      <div style={{ position: 'absolute', left: `calc(${bench.fill}% - 3px)`, top: -3, width: 6, height: 18, borderRadius: 3, background: '#0f172a' }} />
                    </div>
                    <div style={{ fontSize: 13, color: '#334155' }}>
                      Estás en el <strong style={{ color: '#FC3276' }}>top {bench.topPct}%</strong> del equipo en contacto efectivo (posición {bench.rank} de {bench.total}) — <span style={{ color: '#64748b' }}>sin ver nombres de nadie.</span>
                    </div>
                  </>
                )}
              </div>

              {/* Coach IA */}
              <div style={{ background: '#fff', borderRadius: 16, padding: '22px 24px', border: '1px solid #e2e8f0' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14, gap: 10, flexWrap: 'wrap' }}>
                  <div style={{ fontSize: 14, fontWeight: 700, color: '#0f172a' }}>🧠 Mi Coach IA</div>
                  <button onClick={generarCoach} disabled={cargandoCoach}
                    style={{ padding: '8px 16px', borderRadius: 10, border: 'none', cursor: cargandoCoach ? 'not-allowed' : 'pointer', fontSize: 12, fontWeight: 700, color: '#fff', background: cargandoCoach ? '#cbd5e0' : 'linear-gradient(135deg,#FC3276,#db2777)' }}>
                    {cargandoCoach ? '⌛ Generando…' : coach ? '↻ Regenerar' : '🧠 Generar mi coach'}
                  </button>
                </div>
                {coach
                  ? <div style={{ lineHeight: 1.7, color: '#334155', fontSize: 13 }} dangerouslySetInnerHTML={{ __html: coach }} />
                  : <div style={{ color: '#94a3b8', fontSize: 13 }}>Genera un diagnóstico personal con tus fortalezas, puntos a mejorar y una meta — con IA sobre tus propias llamadas.</div>}
              </div>
            </div>

            {/* Evolución semanal */}
            <div style={{ background: '#fff', borderRadius: 16, padding: '22px 24px', border: '1px solid #e2e8f0', marginTop: 18 }}>
              <div style={{ fontSize: 14, fontWeight: 700, color: '#0f172a', marginBottom: 14 }}>📈 Mi evolución semanal <span style={{ color: '#94a3b8', fontWeight: 500 }}>(últimas 12 semanas)</span></div>
              {evol.length ? (
                <ResponsiveContainer width="100%" height={260}>
                  <AreaChart data={evol.slice(-12)} margin={{ top: 8, right: 20, left: -10, bottom: 4 }}>
                    <defs>
                      <linearGradient id="gLlam" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#FC3276" stopOpacity={0.25} />
                        <stop offset="95%" stopColor="#FC3276" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#eef2f7" />
                    <XAxis dataKey="fecha" tickFormatter={fmtSemana} fontSize={10} tick={{ fill: '#94a3b8' }} tickLine={false} axisLine={{ stroke: '#e2e8f0' }} />
                    <YAxis fontSize={11} tick={{ fill: '#94a3b8' }} tickLine={false} axisLine={false} allowDecimals={false} />
                    <Tooltip labelFormatter={fmtSemana} />
                    <Legend verticalAlign="top" align="left" height={30} iconType="circle" />
                    <Area type="monotone" dataKey="llamadas" name="Mis llamadas" stroke="#FC3276" strokeWidth={2} fill="url(#gLlam)" dot={{ r: 3, fill: '#FC3276' }} activeDot={{ r: 5 }} />
                    <Area type="monotone" dataKey="posibles_ventas" name="Posibles ventas" stroke="#10b981" strokeWidth={2} fill="transparent" dot={{ r: 3, fill: '#10b981' }} activeDot={{ r: 5 }} />
                  </AreaChart>
                </ResponsiveContainer>
              ) : (
                <div style={{ color: '#94a3b8', fontSize: 13, padding: '20px 0' }}>Sin datos de evolución para este asesor.</div>
              )}
            </div>

            {/* Mis transcripciones */}
            <div style={{ background: '#fff', borderRadius: 16, padding: '22px 24px', border: '1px solid #e2e8f0', marginTop: 18 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10, marginBottom: 14, flexWrap: 'wrap' }}>
                <div style={{ fontSize: 14, fontWeight: 700, color: '#0f172a' }}>
                  💬 Mis transcripciones <span style={{ color: '#94a3b8', fontWeight: 500 }}>({llamadas.length} en el período)</span>
                </div>
                <select value={llamadaSel} onChange={e => setLlamadaSel(e.target.value)}
                  style={{ padding: '8px 12px', borderRadius: 10, border: 'none', background: '#FC3276', color: '#fff', fontWeight: 700, fontSize: 12, cursor: 'pointer', maxWidth: 460 }}>
                  <option value="">Selecciona una de mis llamadas…</option>
                  {llamadas.map(l => <option key={l.id} value={l.id}>{l.name}</option>)}
                </select>
              </div>
              {llamadaSel && (
                <div style={{ borderTop: '1px solid #f1f5f9', paddingTop: 15, marginBottom: 18 }}>
                  <div style={{ fontSize: 10, fontWeight: 700, color: '#64748b', marginBottom: 8 }}>
                    📋 HISTORIAL DE LLAMADAS{llamadaActiva?.telefono && llamadaActiva.telefono !== '-' ? ` — ${llamadaActiva.telefono}` : ''}
                  </div>
                  {cargandoHistorial ? (
                    <div style={{ color: '#94a3b8', fontSize: 12 }}>Cargando historial...</div>
                  ) : historial.length === 0 ? (
                    <div style={{ color: '#94a3b8', fontSize: 12 }}>No se encontraron llamadas para este número.</div>
                  ) : (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxHeight: 380, overflowY: 'auto' }}>
                      {historial.map((h, i) => (
                        <div key={`${h.id}-${i}`} style={{ padding: '10px 12px', borderRadius: 8, border: '1px solid #e2e8f0', background: h.tiene_transcripcion ? '#fff' : '#f8fafc' }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                            <span style={{ fontSize: 11, fontWeight: 700, color: '#1e293b' }}>#{h.id} · {h.fecha}</span>
                            <span style={{ fontSize: 10, fontWeight: 700, color: '#fff', background: colorResultado(h.resultado), padding: '2px 7px', borderRadius: 20 }}>{h.resultado}</span>
                          </div>
                          <div style={{ fontSize: 11, color: '#64748b' }}>{h.asesor}</div>
                          <div style={{ fontSize: 10, color: '#94a3b8', marginTop: 2 }}>
                            ⏱ {h.duracion} · {h.duracion_est}
                            {!h.tiene_transcripcion && <span style={{ color: '#f59e0b', marginLeft: 6 }}>sin transcripción</span>}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
                {metricas.length > 0 && (
                  <div style={{ marginBottom: 18 }}>
                    <MetricasGrid data={metricas} llamadaId={llamadaSel} queryOverride={qp(true).slice(1)} />
                  </div>
                )}
                {chat.length
                ? <ChatVisor chat={chat} resaltar="" />
                : <div style={{ color: '#94a3b8', fontSize: 13, padding: '20px 0' }}>Elige una llamada para revisar la conversación (cliente / asesor) y autoevaluarte.</div>}
            </div>

            {/* Agentes personales: contexto general o llamada seleccionada */}
            <div style={{ background: '#fff', borderRadius: 16, padding: '22px 24px', border: '1px solid #e2e8f0', marginTop: 18 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, flexWrap: 'wrap', marginBottom: 14 }}>
                <div style={{ fontSize: 14, fontWeight: 700, color: '#0f172a' }}>🤖 Mis agentes IA</div>
                <div style={{ display: 'flex', gap: 8 }}>
                  {[['general', 'Agente general'], ['llamada', 'Sobre esta llamada']].map(([modo, etiqueta]) => (
                    <button key={modo} onClick={() => setModoChat(modo)} style={{ padding: '8px 12px', borderRadius: 9, border: '1px solid #e2e8f0', background: modoChat === modo ? '#FC3276' : '#fff', color: modoChat === modo ? '#fff' : '#475569', fontWeight: 700, fontSize: 12, cursor: 'pointer' }}>{etiqueta}</button>
                  ))}
                </div>
              </div>
              <div style={{ color: '#64748b', fontSize: 12, marginBottom: 12 }}>
                {modoChat === 'general' ? 'Pregunta sobre tus métricas, evolución y oportunidades de mejora.' : llamadaSel ? 'Pregunta sobre la llamada seleccionada, su conversación y calidad.' : 'Selecciona una llamada para usar este agente.'}
              </div>
              <Chat messages={chatMensajes} />
              <SendMessage inputValue={chatInput} setInputValue={setChatInput} onSend={enviarPregunta} onClear={() => setChatMensajes([])} />
              {chatCargando && <div style={{ color: '#94a3b8', fontSize: 12, marginTop: 8 }}>Analizando...</div>}
            </div>

            <div style={{ marginTop: 22, fontSize: 12, color: '#94a3b8', textAlign: 'center' }}>
              Prototipo — datos reales del asesor seleccionado. En la versión real, el asesor entra con su usuario y esto se filtra solo a él.
            </div>
          </>
        )}
      </div>
    </div>
  );
};

export default MiDesempeno;

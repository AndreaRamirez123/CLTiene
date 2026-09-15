import { API_BASE, apiFetch } from '../../config';
import React, { useState } from 'react';
import { useFilters } from '../../FiltersContext';

const MetricasGrid = ({ data, llamadaId, queryOverride = '' }) => {
    const filterContext = useFilters();
    const [mostrar, setMostrar] = useState(false);
    const [cargando, setCargando] = useState(false);
    const [analisis, setAnalisis] = useState('');

    const getStatusColor = (val) => {
        const lowerVal = val.toString().toLowerCase();
        if (['sí', 'venta', 'excelente'].some(k => lowerVal.includes(k))) return '#2ecc71';
        if (['no', 'bajo'].some(k => lowerVal.includes(k))) return '#FC3276';
        return '#1e293b';
    };

    const handleClick = async () => {
        if (mostrar) {
            setMostrar(false);
            setAnalisis('');
            return;
        }
        setMostrar(true);
        setCargando(true);
        try {
            const params = queryOverride || filterContext?.buildQuery?.() || '';
            const query = params ? `?${params}` : '';
            const sep = params ? '&' : '?';
            const url = llamadaId && llamadaId !== 0
                ? `${API_BASE}/ia/analizar_llamada${query}${sep}llamada_id=${llamadaId}`
                : `${API_BASE}/ia/inteligencia_operativa${query}`;
            const response = await apiFetch(url);
            const result = await response.json();
            const raw = result.result || 'No se obtuvo un análisis válido';
            const limpio = raw
                .replace(/background-color\s*:\s*rgb\(15,\s*23,\s*42\)[^;"']*/g, 'background-color: #f8fafc')
                .replace(/color\s*:\s*rgb\(203,\s*213,\s*225\)[^;"']*/g, 'color: #334155')
                .replace(/border-bottom\s*:\s*1px solid rgb\(30,\s*41,\s*59\)[^;"']*/g, 'border-bottom: 1px solid #e2e8f0');
            setAnalisis(limpio);
        } catch (error) {
            console.error('Error consultando IA:', error);
            setAnalisis('Error al conectar con la IA.');
        }
        setCargando(false);
    };

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>

            {/* GRID */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '25px' }}>
                {data.map((item, index) => (
                    <div key={index} style={{ borderLeft: '4px solid #e2e8f0', paddingLeft: '15px' }}>
                        <p style={{ fontSize: '10px', color: '#94a3b8', fontWeight: '700', textTransform: 'uppercase' }}>{item.label}</p>
                        <p style={{ fontSize: '15px', fontWeight: '700', color: getStatusColor(item.val) }}>{item.val}</p>
                    </div>
                ))}
            </div>

            {/* BOTÓN */}
            <div style={{ display: 'flex', justifyContent: 'flex-start' }}>
                <button
                    onClick={handleClick}
                    disabled={cargando}
                    style={{
                        padding: '14px 22px',
                        background: cargando
                            ? '#cbd5e0'
                            : mostrar
                                ? 'linear-gradient(135deg, #64748b 0%, #475569 100%)'
                                : 'linear-gradient(135deg, #FC3276 0%, #db2777 100%)',
                        color: 'white',
                        border: 'none',
                        borderRadius: '12px',
                        fontSize: '14px',
                        fontWeight: '700',
                        letterSpacing: '0.5px',
                        cursor: cargando ? 'not-allowed' : 'pointer',
                        boxShadow: cargando ? 'none' : mostrar
                            ? '0 4px 18px rgba(100,116,139,0.25)'
                            : '0 4px 18px rgba(252,50,118,0.35)',
                    }}
                >
                    {cargando ? '⌛ Analizando...' : mostrar ? '✕ Ocultar Análisis' : 'Analizar llamada con IA'}
                </button>
            </div>

            {/* RESULTADO */}
            {mostrar && (
                <div style={{
                    backgroundColor: '#ffffff',
                    borderRadius: '16px',
                    padding: '36px 40px',
                    border: '1px solid #e2e8f0',
                    boxShadow: '0 2px 10px rgba(0,0,0,0.05)',
                }}>
                    <div style={{
                        borderLeft: '5px solid #FC3276',
                        background: 'linear-gradient(90deg, #fff5f9 0%, transparent 80%)',
                        borderRadius: '0 10px 10px 0',
                        padding: '14px 20px',
                        marginBottom: '28px',
                    }}>
                        <span style={{ display: 'block', fontSize: '18px', fontWeight: '700', color: '#FC3276', marginBottom: '4px' }}>
                            🎧 Análisis de la Llamada #{llamadaId}
                        </span>
                        <span style={{ fontSize: '12px', color: '#94a3b8' }}>
                            Resumen, aciertos, errores, scorecard y coaching
                        </span>
                    </div>

                    {cargando ? (
                        <p style={{ color: '#94a3b8', fontSize: '14px' }}>⌛ Generando análisis con IA...</p>
                    ) : (
                        <div style={{ lineHeight: '1.8', color: '#334155', fontSize: '14px' }}
                            dangerouslySetInnerHTML={{ __html: analisis }} />
                    )}
                </div>
            )}
        </div>
    );
};

export default MetricasGrid;

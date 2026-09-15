import React, { useState, useEffect } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { auth } from './firebase';
import { onAuthStateChanged } from 'firebase/auth';

import Login from './pages/Login';
import Dashboard from './pages/Dashboard';
import MiDesempeno from './pages/MiDesempeno';
import "./css/style.css";
import { FiltersProvider } from './FiltersContext';

class ErrorBoundary extends React.Component {
    constructor(props) {
        super(props);
        this.state = { error: false };
    }
    static getDerivedStateFromError() {
        return { error: true };
    }
    componentDidCatch() {
        this.setState({ error: false });
    }
    render() {
        if (this.state.error) return null;
        return this.props.children;
    }
}

function App() {
    const [usuario, setUsuario] = useState(null);
    const [cargando, setCargando] = useState(true);

    useEffect(() => {
        const desubscribir = onAuthStateChanged(auth, (user) => {
            setUsuario(user);
            setCargando(false);
        });
        return () => desubscribir();
    }, []);

    if (cargando) return <div className="loading">Cargando...</div>;

    return (
        <Router>
            <Routes>
                <Route path="/login" element={!usuario ? <Login /> : <Navigate to="/" />} />
                <Route path="/" element={usuario ? <FiltersProvider>
                    <ErrorBoundary><Dashboard /></ErrorBoundary>
                </FiltersProvider> : <Navigate to="/login" />} />
                {/* PROTOTIPO — vista individual del asesor (aislada del dashboard) */}
                <Route path="/mi-desempeno" element={usuario
                    ? <FiltersProvider><ErrorBoundary><MiDesempeno /></ErrorBoundary></FiltersProvider>
                    : <Navigate to="/login" />} />
            </Routes>
        </Router>
    );
}
export default App;
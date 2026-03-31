import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import IkshanApp from './components/ikshan/IkshanApp';
import ErrorBoundary from './components/ErrorBoundary';
import { phase2OutletChildren } from './phase2/childRoutes';
import Phase2Layout from './phase2/Phase2Layout';

function App() {
  return (
    <ErrorBoundary>
      <BrowserRouter>
        <Routes>
          <Route path="/phase2" element={<Phase2Layout />}>
            {phase2OutletChildren}
          </Route>
          <Route path="/" element={<IkshanApp />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </ErrorBoundary>
  );
}

export default App;

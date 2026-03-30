import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import Phase2Layout from './Phase2Layout';
import { phase2OutletChildren } from './childRoutes';

/**
 * Standalone Phase 2 (e.g. alternate entry). Same route tree as main `App` under `/phase2`.
 */
export default function App({ basename = '/phase2' }: { basename?: string }) {
  return (
    <BrowserRouter basename={basename || '/phase2'}>
      <Routes>
        <Route path="/" element={<Phase2Layout />}>
          {phase2OutletChildren}
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}

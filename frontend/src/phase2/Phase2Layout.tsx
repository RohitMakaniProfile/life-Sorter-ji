import { Outlet } from 'react-router-dom';
import { UiAgentsProvider } from './context/UiAgentsContext';

/**
 * Shell for all `/phase2/*` routes: auth context + outlet.
 * Matches development `App.tsx` (login routes are siblings of `Layout`, not inside it).
 */
export default function Phase2Layout() {
  return (
    <UiAgentsProvider>
      <Outlet />
    </UiAgentsProvider>
  );
}

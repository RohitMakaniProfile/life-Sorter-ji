import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { getIsSuperAdmin, getJwtPayload } from '../api/authSession';

export default function RequireSuperAdmin() {
  const location = useLocation();
  const payload = getJwtPayload();
  const hasToken = Boolean(payload);
  const isSuperAdmin = getIsSuperAdmin();

  if (!hasToken) {
    return (
      <Navigate
        to={`/admin/login?mode=admin&next=${encodeURIComponent(location.pathname + location.search)}`}
        replace
      />
    );
  }

  if (!isSuperAdmin) {
    const next = encodeURIComponent(location.pathname + location.search);
    return (
      <div className="min-h-screen w-full flex items-center justify-center bg-zinc-950 text-zinc-100 p-6">
        <div className="w-full max-w-md rounded-xl border border-red-900/60 bg-red-950/30 p-6">
          <div className="text-sm uppercase tracking-wide text-red-200">Access denied</div>
          <h1 className="text-xl font-semibold mt-2">Super-admin only</h1>
          <p className="text-sm text-zinc-300 mt-2">
            Your account does not have the required super-admin permissions.
          </p>
          <div className="mt-5 flex flex-col sm:flex-row gap-3">
            <a
              href={`/admin/login?mode=admin&force=1&next=${next}`}
              className="inline-flex items-center justify-center text-sm font-semibold rounded-lg px-4 py-2 bg-violet-600 text-white hover:bg-violet-700"
            >
              Login as super-admin
            </a>
            <a
              href="/chat"
              className="inline-flex items-center justify-center text-sm font-semibold rounded-lg px-4 py-2 border border-slate-700 text-slate-200 hover:bg-slate-800"
            >
              Back to chat
            </a>
          </div>
        </div>
      </div>
    );
  }

  return <Outlet />;
}


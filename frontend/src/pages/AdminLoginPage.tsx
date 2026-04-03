import { useSearchParams } from 'react-router-dom';
import InternalGoogleLoginPage from './ai/InternalGoogleLoginPage';

export default function AdminLoginPage() {
  const [params] = useSearchParams();
  const modeRaw = String(params.get('mode') || '').trim().toLowerCase();
  const mode = modeRaw === 'internal' ? 'internal' : 'admin';
  return <InternalGoogleLoginPage mode={mode} />;
}


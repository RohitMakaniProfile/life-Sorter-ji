import type { ProgressEvent } from '../../../api/types';

type UrlState = 'discovered' | 'scraping' | 'summarizing' | 'done';

interface UrlEntry {
  url: string;
  state: UrlState;
}

function trimUrl(url: string): string {
  try {
    const u = new URL(url);
    const path = (u.pathname + u.search).replace(/\/$/, '') || '/';
    return u.hostname + path;
  } catch {
    return url.length > 60 ? url.slice(0, 60) + '…' : url;
  }
}

const STATE_CONFIG: Record<UrlState, { dot: string; label: string }> = {
  discovered:  { dot: 'bg-slate-500',                     label: 'queued'      },
  scraping:    { dot: 'bg-violet-400 animate-pulse',       label: 'scraping'    },
  summarizing: { dot: 'bg-amber-400 animate-pulse',        label: 'summarizing' },
  done:        { dot: 'bg-emerald-400',                    label: 'done'        },
};

interface CrawlUrlListProps {
  progressEvents: ProgressEvent[];
}

export default function CrawlUrlList({ progressEvents }: CrawlUrlListProps) {
  // Build ordered URL list from progress events
  const entries = (() => {
    const map = new Map<string, UrlState>();
    const ORDER: UrlState[] = ['discovered', 'scraping', 'summarizing', 'done'];
    const rank = (s: UrlState) => ORDER.indexOf(s);

    const advance = (url: string, next: UrlState) => {
      const cur = map.get(url);
      if (!cur || rank(next) > rank(cur)) map.set(url, next);
    };

    for (const ev of progressEvents) {
      const meta = ev.meta as Record<string, unknown> | undefined;
      if (!meta) continue;
      const event = String(meta.event ?? '');
      const url = String(meta.url ?? '').trim().replace(/\/+$/, '');
      if (!url) continue;

      // discovered → queued | scraping (goto) → scraping | summarizing → summarizing | page_data → done
      if (event === 'discovered')              { if (!map.has(url)) map.set(url, 'discovered'); }
      else if (event === 'scraping')           { advance(url, 'scraping');    }
      else if (event === 'summarizing')        { advance(url, 'summarizing'); }
      else if (event === 'page_data')          { advance(url, 'done');        }
    }

    const result: UrlEntry[] = [];
    map.forEach((state, url) => result.push({ url, state }));
    return result;
  })();

  if (entries.length === 0) return null;

  const done = entries.filter(e => e.state === 'done').length;

  return (
    <div className="mt-3 rounded-lg border border-slate-700 overflow-hidden">
      <div className="flex items-center gap-2 px-3 py-1.5 bg-slate-800 border-b border-slate-700">
        <div className="w-1.5 h-1.5 bg-violet-400 rounded-full animate-pulse flex-shrink-0" />
        <span className="text-[10px] font-semibold uppercase tracking-widest text-slate-400">
          Analysis progress
        </span>
        <span className="ml-auto text-[10px] text-slate-500 tabular-nums">
          {done}/{entries.length}
        </span>
      </div>
      <div className="max-h-40 overflow-y-auto divide-y divide-slate-800">
        {entries.map(({ url, state }) => {
          const cfg = STATE_CONFIG[state];
          return (
            <div key={url} className="flex items-center gap-2.5 px-3 py-1.5">
              <div className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${cfg.dot}`} />
              <span className="text-[11px] text-slate-300 truncate flex-1 font-mono">
                {trimUrl(url)}
              </span>
              <span className="text-[10px] text-slate-500 flex-shrink-0">
                {cfg.label}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
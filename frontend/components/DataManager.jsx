import React, { useState, useEffect } from 'react';
import {
  Database, Trash2, RefreshCw,
  Clock, DollarSign, Activity, Users, AlertTriangle,
  Wifi, Cpu, HardDrive,
} from 'lucide-react';

// Defensive wrapper — catches any render crash so the panel never goes blank
class DataManagerBoundary extends React.Component {
  constructor(props) { super(props); this.state = { crashed: false, msg: '' }; }
  static getDerivedStateFromError(e) { return { crashed: true, msg: e?.message || 'Unknown error' }; }
  render() {
    if (this.state.crashed) return (
      <div className="p-4 bg-red-500/10 border border-red-500/30 rounded-lg text-xs text-red-400">
        <div className="flex items-center gap-2 mb-1"><AlertTriangle className="w-3.5 h-3.5" /> Data Management failed to render</div>
        <div className="text-slate-500">{this.state.msg}</div>
        <button onClick={() => this.setState({ crashed: false, msg: '' })}
          className="mt-2 px-2 py-1 bg-slate-700 hover:bg-slate-600 text-slate-300 rounded text-xs">Retry</button>
      </div>
    );
    return this.props.children;
  }
}

const RetentionEditor = ({ base, authHeaders, retention, onSaved }) => {
  const defaults = retention.defaults || {};
  const current  = retention.retention || {};

  // Local editable state — initialised from current retention values
  const [values, setValues]     = useState({ ...current });
  const [saving, setSaving]     = useState(false);
  const [saveStatus, setSaveStatus] = useState(null); // null | 'ok' | 'error'
  const [errorMsg, setErrorMsg] = useState('');

  const labels = {
    earnings: 'Earnings',
    sessions: 'Sessions',
    traffic:  'Traffic',
    quality:  'Quality',
    system:   'System',
    services: 'Services',
    uptime:   'Uptime',
  };

  const handleSave = async () => {
    setSaving(true);
    setSaveStatus(null);
    try {
      const res = await fetch(`${base}/data/retention`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json', ...(authHeaders || {}) },
        body:    JSON.stringify({ retention: values }),
      });
      const d = await res.json();
      if (d.success) {
        setSaveStatus('ok');
        if (d.retention) onSaved(d.retention);
        setTimeout(() => setSaveStatus(null), 4000);
      } else {
        setSaveStatus('error');
        setErrorMsg(d.error || 'Save failed');
      }
    } catch (e) {
      setSaveStatus('error');
      setErrorMsg(e.message);
    } finally {
      setSaving(false);
    }
  };

  const isDirty = Object.keys(values).some(k => values[k] !== current[k]);

  return (
    <div className="p-3 bg-slate-900/30 rounded-lg border border-slate-700">
      <div className="flex items-center justify-between mb-2">
        <div className="text-xs text-slate-400 font-semibold tracking-wide uppercase">
          Auto-retention (days kept)
        </div>
        <div className="text-[10px] text-slate-600">Pruned daily · edit and save to apply</div>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-3">
        {Object.entries(labels).map(([key, label]) => (
          <div key={key} className="flex flex-col gap-0.5">
            <label className="text-[10px] text-slate-500 capitalize">{label}</label>
            <input
              type="number"
              min="1"
              max="3650"
              value={values[key] ?? defaults[key] ?? 30}
              onChange={e => setValues(v => ({ ...v, [key]: parseInt(e.target.value) || 1 }))}
              className="w-full px-2 py-0.5 bg-slate-800 border border-slate-600 rounded text-xs text-white font-mono focus:border-emerald-500 focus:outline-none"
            />
          </div>
        ))}
      </div>
      <div className="flex items-center gap-3">
        <button
          onClick={handleSave}
          disabled={saving || !isDirty}
          className={`px-3 py-1 text-xs rounded border font-semibold transition
            ${isDirty
              ? 'bg-emerald-500/20 border-emerald-500/50 text-emerald-300 hover:bg-emerald-500/30'
              : 'bg-slate-800 border-slate-700 text-slate-600 cursor-not-allowed'
            } disabled:opacity-50`}
        >
          {saving ? 'Saving…' : 'Save retention'}
        </button>
        {isDirty && !saving && (
          <button
            onClick={() => setValues({ ...current })}
            className="text-[10px] text-slate-500 hover:text-slate-300 transition"
          >
            Reset
          </button>
        )}
        {saveStatus === 'ok' && (
          <span className="text-[10px] text-emerald-400">✓ Saved — takes effect on next daily prune</span>
        )}
        {saveStatus === 'error' && (
          <span className="text-[10px] text-red-400">✗ {errorMsg}</span>
        )}
      </div>
      {retention.last_prune && (
        <div className="text-[10px] text-slate-600 mt-2">Last pruned: {retention.last_prune}</div>
      )}
    </div>
  );
};

const DataManagerInner = ({ nodeId, isFleetMode = false, authHeaders = {} }) => {
  const [stats, setStats]               = useState(null);
  const [loading, setLoading]           = useState(false);
  const [deleteDone, setDeleteDone]      = useState(false);
  const [selectedType, setSelectedType] = useState('all');
  const [deleteMode, setDeleteMode]     = useState('keep_days');
  const [keepDays, setKeepDays]         = useState(90);
  const [showConfirm, setShowConfirm]   = useState(false);
  const [error, setError]               = useState(null);
  const [expanded, setExpanded]         = useState(true);
  const [retention, setRetention]       = useState(null);

  const dataTypes = [
    { id: 'earnings', label: 'Earnings', icon: DollarSign },
    { id: 'traffic',  label: 'Traffic',  icon: Activity   },
    { id: 'sessions', label: 'Sessions', icon: Users      },
    { id: 'quality',  label: 'Quality',  icon: Wifi       },
    { id: 'system',   label: 'System',   icon: Cpu        },
    { id: 'services', label: 'Services', icon: HardDrive  },
    { id: 'uptime',   label: 'Uptime',   icon: Clock      },
  ];

  const fetchStats = async () => {
    setLoading(true);
    try {
      const base = isFleetMode ? `/fleet/node/${nodeId}/proxy` : '';
      const res  = await fetch(`${base}/data/stats`, { headers: authHeaders || {} });
      const data = await res.json();
      if (!res.ok) throw new Error(data?.error || `HTTP ${res.status}`);
      setStats(data);
      setError(null);
      // Fetch retention config in parallel — non-blocking
      fetch(`${base}/data/retention`, { headers: authHeaders || {} })
        .then(r => r.ok ? r.json() : null)
        .then(d => { if (d?.retention) setRetention(d); })
        .catch(() => {});
    } catch (err) {
      setError(`Failed to load: ${err.message}`);
      setStats(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchStats(); }, [nodeId]);

  const handleDelete = async () => {
    setLoading(true);
    try {
      const base = isFleetMode ? `/fleet/node/${nodeId}/proxy` : '';
      const url = `${base}/data/delete`;
      const payload = {
        type: selectedType,
        ...(deleteMode === 'keep_days' ? { keep_days: keepDays } : {}),
      };
      const res  = await fetch(url, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json', ...(authHeaders || {}) },
        body:    JSON.stringify(payload),
      });
      const data = await res.json();
      if (data?.success) {
        await fetchStats();
        setShowConfirm(false);
        setDeleteDone(true);
        setTimeout(() => setDeleteDone(false), 8000);
        // Signal the dashboard to force-refresh metrics on next poll
        window.dispatchEvent(new CustomEvent('myst-data-deleted', { detail: { type: selectedType } }));
      }
      else setError(data?.error || 'Delete failed');
    } catch (err) {
      setError(`Delete failed: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const fmt = (d) => {
    if (!d) return '—';
    try { return new Date(d).toLocaleDateString(); } catch { return String(d); }
  };

  // SAFE: always returns a plain object — NEVER null, NEVER undefined
  const getDB = (typeId) => {
    try {
      if (!stats || typeof stats !== 'object') return { total: 0, exists: false };
      const dbs = stats.databases;
      if (!dbs || typeof dbs !== 'object') return { total: 0, exists: false };
      const entry = dbs[typeId];
      if (!entry || typeof entry !== 'object') return { total: 0, exists: false };
      return entry;
    } catch {
      return { total: 0, exists: false };
    }
  };

  const totalRecords = () => {
    try {
      if (!stats?.databases) return 0;
      return Object.values(stats.databases).reduce((s, db) => s + (Number(db?.total) || 0), 0);
    } catch { return 0; }
  };

  if (!expanded) return (
    <div className="p-3 bg-slate-800/30 rounded-lg border border-slate-700">
      <button onClick={() => setExpanded(true)}
        className="w-full flex items-center justify-between text-slate-300 hover:text-white transition-colors">
        <div className="flex items-center gap-2">
          <Database className="w-4 h-4 text-emerald-400" />
          <span className="text-sm">Data Management</span>
          <span className="text-xs text-slate-500">{totalRecords().toLocaleString()} records</span>
        </div>
        <span className="text-slate-500 text-xs">▼ expand</span>
      </button>
    </div>
  );

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          {isFleetMode && nodeId && (
            <span className="px-2 py-0.5 text-xs bg-slate-700 text-slate-300 rounded border border-slate-600">
              Node: {String(nodeId).slice(0, 10)}…
            </span>
          )}
          <span className="text-xs text-slate-400">
            Total: <span className="text-white font-mono font-semibold">{totalRecords().toLocaleString()}</span> records
          </span>
        </div>
        <div className="flex items-center gap-1">
          <button onClick={fetchStats} disabled={loading} title="Refresh"
            className="p-1.5 text-slate-400 hover:text-white transition-colors rounded hover:bg-slate-700">
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          </button>
          <button onClick={() => setExpanded(false)} title="Collapse"
            className="p-1.5 text-slate-400 hover:text-white transition-colors rounded hover:bg-slate-700 text-xs">▲</button>
        </div>
      </div>

      {/* Delete done notice */}
      {deleteDone && (
        <div className="p-3 bg-emerald-500/10 border border-emerald-500/30 rounded-lg text-xs text-emerald-400">
          ✓ Data deleted. <span className="text-slate-400">Restart the backend (menu option 5 → 1) to clear in-memory caches and update all charts.</span>
          <div className="text-slate-600 mt-1 text-[10px]">Session analytics reflects what the Mysterium node has in memory — unaffected by DB deletes until node restarts.</div>
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="p-3 bg-red-500/10 border border-red-500/30 rounded-lg flex items-center gap-2 text-red-400 text-xs">
          <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0" />{error}
          <button onClick={() => { setError(null); fetchStats(); }} className="ml-auto underline hover:text-red-300">Retry</button>
        </div>
      )}

      {/* DB cards grid */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        {dataTypes.map(({ id, label, icon: Icon }) => {
          const db         = getDB(id);
          const isSelected = selectedType === id;
          const isEmpty    = !db.exists || (db.total || 0) === 0;
          return (
            <button key={id} onClick={() => setSelectedType(isSelected ? 'all' : id)}
              className={`p-3 rounded-lg border transition-all text-left ${
                isSelected
                  ? 'border-emerald-500/50 bg-emerald-500/10 ring-1 ring-emerald-500/20'
                  : 'border-slate-700 bg-slate-800/50 hover:border-slate-600'
              } ${isEmpty ? 'opacity-50' : ''}`}
            >
              <div className="flex items-center gap-1.5 mb-1">
                <Icon className={`w-3 h-3 ${isSelected ? 'text-emerald-400' : 'text-slate-400'}`} />
                <span className="text-xs text-slate-300">{label}</span>
              </div>
              <div className={`text-base font-mono font-semibold ${isSelected ? 'text-emerald-300' : 'text-white'}`}>
                {(db.total || 0).toLocaleString()}
              </div>
              {db.oldest && (
                <div className="text-xs text-slate-500 mt-0.5 truncate">from {fmt(db.oldest)}</div>
              )}
            </button>
          );
        })}
      </div>

      {/* Detail for selected type */}
      {selectedType !== 'all' && (() => {
        const db       = getDB(selectedType);
        const typeInfo = dataTypes.find(t => t.id === selectedType);
        if (!typeInfo) return null;
        const Icon = typeInfo.icon;
        return (
          <div className="p-3 bg-slate-900/50 rounded-lg border border-slate-700 text-xs space-y-2">
            <div className="flex items-center gap-2 text-slate-300">
              <Icon className="w-3.5 h-3.5 text-emerald-400" />
              <span className="font-semibold">{typeInfo.label} — detail</span>
              <span className={`ml-auto px-1.5 py-0.5 rounded font-semibold ${
                db.exists
                  ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                  : 'bg-slate-700 text-slate-400 border border-slate-600'
              }`}>{db.exists ? 'EXISTS' : 'EMPTY'}</span>
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-x-4 gap-y-1 text-slate-400">
              <div><span className="text-slate-500">Records:</span> <span className="text-white font-mono">{(db.total || 0).toLocaleString()}</span></div>
              <div><span className="text-slate-500">Oldest:</span>  <span className="text-slate-300">{fmt(db.oldest)}</span></div>
              <div><span className="text-slate-500">Newest:</span>  <span className="text-slate-300">{fmt(db.newest)}</span></div>
              {db.avg_quality   != null && <div><span className="text-slate-500">Avg quality:</span>   <span className="text-slate-300">{db.avg_quality}</span></div>}
              {db.avg_latency   != null && <div><span className="text-slate-500">Avg latency:</span>   <span className="text-slate-300">{db.avg_latency} ms</span></div>}
              {db.avg_bandwidth != null && <div><span className="text-slate-500">Avg bandwidth:</span> <span className="text-slate-300">{db.avg_bandwidth} Mbps</span></div>}
              {db.avg_cpu  != null && <div><span className="text-slate-500">Avg CPU:</span>  <span className="text-slate-300">{db.avg_cpu}%</span></div>}
              {db.max_cpu  != null && <div><span className="text-slate-500">Peak CPU:</span> <span className="text-slate-300">{db.max_cpu}%</span></div>}
              {db.avg_ram  != null && <div><span className="text-slate-500">Avg RAM:</span>  <span className="text-slate-300">{db.avg_ram}%</span></div>}
              {db.avg_temp != null && <div><span className="text-slate-500">Avg temp:</span> <span className="text-slate-300">{db.avg_temp}°C</span></div>}
              {db.max_temp != null && <div><span className="text-slate-500">Peak temp:</span><span className="text-slate-300">{db.max_temp}°C</span></div>}
              {db.starts   != null && <div><span className="text-slate-500">Starts:</span>   <span className="text-slate-300">{db.starts}</span></div>}
              {db.stops    != null && <div><span className="text-slate-500">Stops:</span>    <span className="text-slate-300">{db.stops}</span></div>}
            </div>
          </div>
        );
      })()}

      {/* Delete controls */}
      <div className="p-3 bg-slate-900/30 rounded-lg border border-slate-700 space-y-3">
        <div className="text-xs text-slate-400 font-semibold tracking-wide uppercase">Delete data</div>
        <div className="flex flex-wrap gap-1.5">
          {['all', ...dataTypes.map(t => t.id)].map(id => (
            <button key={id} onClick={() => setSelectedType(id)}
              className={`px-2.5 py-1 text-xs rounded border transition-all capitalize ${
                selectedType === id
                  ? 'border-emerald-500/50 bg-emerald-500/10 text-emerald-300'
                  : 'border-slate-700 bg-slate-800/50 text-slate-400 hover:border-slate-600'
              }`}
            >{id}</button>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-4">
          <label className="flex items-center gap-2 cursor-pointer">
            <input type="radio" value="keep_days" checked={deleteMode === 'keep_days'}
              onChange={() => setDeleteMode('keep_days')} className="accent-emerald-500" />
            <span className="text-sm text-slate-300">Keep last</span>
            <input type="number" min="1" max="730" value={keepDays}
              onChange={e => setKeepDays(parseInt(e.target.value) || 90)}
              disabled={deleteMode !== 'keep_days'}
              className="w-16 px-2 py-0.5 bg-slate-800 border border-slate-600 rounded text-white text-sm disabled:opacity-40" />
            <span className="text-sm text-slate-300">days</span>
            {deleteMode === 'keep_days' && (
              <div className="flex gap-1 ml-1">
                {[7, 30, 90, 365].map(p => (
                  <button key={p} onClick={() => setKeepDays(p)}
                    className={`px-1.5 py-0.5 text-[10px] rounded border transition ${keepDays === p
                      ? 'border-emerald-500/50 bg-emerald-500/10 text-emerald-300'
                      : 'border-slate-700 text-slate-500 hover:text-slate-300'}`}>{p}d</button>
                ))}
              </div>
            )}
          </label>
          <label className="flex items-center gap-2 cursor-pointer">
            <input type="radio" value="all" checked={deleteMode === 'all'}
              onChange={() => setDeleteMode('all')} className="accent-red-500" />
            <span className="text-sm text-red-400">Delete everything</span>
          </label>
        </div>
        <button onClick={() => setShowConfirm(true)} disabled={loading}
          className="w-full px-4 py-2 bg-red-600/80 hover:bg-red-600 disabled:bg-slate-700
                     text-white rounded-lg transition-colors text-sm flex items-center justify-center gap-2 font-semibold">
          <Trash2 className="w-4 h-4" />
          Delete {selectedType === 'all' ? 'All Data' : dataTypes.find(t => t.id === selectedType)?.label || selectedType}
          {deleteMode === 'keep_days' && ` older than ${keepDays}d`}
        </button>
      </div>

      {/* Confirm modal */}
      {showConfirm && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-[60]">
          <div className="bg-slate-900 border border-slate-700 rounded-lg p-6 max-w-sm w-full mx-4 shadow-2xl">
            <h3 className="text-base font-semibold text-white mb-2 flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 text-red-400" /> Confirm Delete
            </h3>
            <p className="text-slate-300 mb-4 text-sm">
              Permanently delete{' '}
              <span className="text-white font-semibold">
                {selectedType === 'all' ? 'ALL data' : dataTypes.find(t => t.id === selectedType)?.label || selectedType}
              </span>
              {deleteMode === 'keep_days' && ` older than ${keepDays} days`}.{' '}
              This cannot be undone.
            </p>
            <div className="flex gap-3">
              <button onClick={() => setShowConfirm(false)}
                className="flex-1 px-4 py-2 bg-slate-700 hover:bg-slate-600 text-white rounded-lg text-sm transition-colors">Cancel</button>
              <button onClick={handleDelete} disabled={loading}
                className="flex-1 px-4 py-2 bg-red-600 hover:bg-red-700 disabled:bg-slate-700 text-white rounded-lg text-sm transition-colors">
                {loading ? 'Deleting…' : 'Delete'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Retention settings — editable */}
      {retention?.retention && (
        <RetentionEditor
          base={isFleetMode ? `/fleet/node/${nodeId}/proxy` : ''}
          authHeaders={authHeaders}
          retention={retention}
          onSaved={(updated) => setRetention(r => ({ ...r, retention: updated }))}
        />
      )}
    </div>
  );
};

const DataManager = (props) => (
  <DataManagerBoundary>
    <DataManagerInner {...props} />
  </DataManagerBoundary>
);

export default DataManager;

import React, { useState, useEffect, useCallback, useRef } from 'react';
import { AlertCircle, CheckCircle2, Zap, Activity, Shield, Terminal, Wifi, Database, RefreshCw, Eye, Heart } from 'lucide-react';
import DataManager from './components/DataManager';

// ============ ERROR BOUNDARY ============
// Catches any render crash in child components and shows a recoverable error screen
// instead of a blank white page. Critical for production server deployments.
class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null, info: null };
  }
  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }
  componentDidCatch(error, info) {
    this.setState({ info });
    console.error('[Mysterium Dashboard] Render error:', error, info);
  }
  render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen bg-gradient-to-br from-slate-950 via-slate-900 to-slate-800 text-white flex items-center justify-center p-6">
          <div className="max-w-lg text-center">
            <div className="inline-block p-4 rounded-lg bg-red-500/10 border border-red-500/30 mb-6">
              <AlertCircle className="w-8 h-8 text-red-400" />
            </div>
            <h1 className="text-2xl font-bold mb-3">Dashboard Error</h1>
            <p className="text-slate-400 mb-4 text-sm">
              A component failed to render. This is usually caused by unexpected data
              from the backend or a connection issue.
            </p>
            {this.state.error && (
              <div className="bg-slate-900/60 border border-slate-700 rounded p-3 mb-6 text-left">
                <p className="text-xs font-mono text-red-300 break-all">{String(this.state.error)}</p>
              </div>
            )}
            <div className="flex gap-3 justify-center">
              <button
                onClick={() => { this.setState({ hasError: false, error: null, info: null }); }}
                className="px-5 py-2 bg-emerald-500 hover:bg-emerald-600 text-white rounded font-semibold transition text-sm"
              >
                Try Again
              </button>
              <button
                onClick={() => window.location.reload()}
                className="px-5 py-2 bg-slate-700 hover:bg-slate-600 text-white rounded font-semibold transition text-sm"
              >
                Reload Page
              </button>
            </div>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}


// Semantic colors are NEVER overridden by any theme:
//   green / red / yellow / amber  →  ok / error / warning / caution (health, temps, scores)
//   rose                          →  System Health section identity (heart icon)
//
// Themed color families (3 distinct roles per theme):
//   accent    → primary identity    (replaces emerald) — main metrics, primary buttons, badges
//   secondary → supporting data     (replaces blue)    — month panels, session counts, persist
//   highlight → live / active       (replaces cyan)    — tunnels, consumer IDs, live counters
//   fleet     → fleet section       (replaces violet + purple)
//
// Each slot uses a DIFFERENT color family so the dashboard has visual depth, not a flat palette.

const THEMES = {
  // ── Default ─ emerald green ──────────────────────────────────────────────
  emerald: {
    name: 'Emerald',
    dot:  '#34d399',
    accent:    null,
    secondary: { c200:'226 232 240', c300:'203 213 225', c400:'148 163 184', c500:'100 116 139', c600:' 71  85 105' },
    highlight: null,
    fleet:     null,
    bg: null,
  },

  // ── Cyber ─ deep-space synthwave ─ cyan / sky / blue / indigo ───────────
  cyber: {
    name: 'Cyber',
    dot:  '#22d3ee',
    accent:    { c200:'165 243 252', c300:'103 232 249', c400:' 34 211 238', c500:'  6 182 212', c600:'  8 145 178' }, // cyan
    secondary: { c200:'186 230 253', c300:'125 211 252', c400:' 56 189 248', c500:' 14 165 233', c600:'  2 132 199' }, // sky
    highlight: { c200:'191 219 254', c300:'147 197 253', c400:' 96 165 250', c500:' 59 130 246', c600:' 37  99 235' }, // blue
    fleet:     { c200:'199 210 254', c300:'165 180 252', c400:'129 140 248', c500:' 99 102 241', c600:' 79  70 229' }, // indigo
    bg: ['#050e18','#0a1628','#06101e'],
  },

  // ── Sunset ─ desert dusk ─ orange / amber / yellow / red-orange ─────────
  sunset: {
    name: 'Sunset',
    dot:  '#fb923c',
    accent:    { c200:'254 215 170', c300:'253 186 116', c400:'251 146  60', c500:'249 115  22', c600:'234  88  12' }, // orange
    secondary: { c200:'254 240 138', c300:'253 224  71', c400:'250 204  21', c500:'234 179   8', c600:'202 138   4' }, // yellow
    highlight: { c200:'254 226 226', c300:'252 165 165', c400:'248 113 113', c500:'239  68  68', c600:'220  38  38' }, // red
    fleet:     { c200:'217 249 157', c300:'190 242 100', c400:'163 230  53', c500:'132 204  22', c600:'101 163  13' }, // lime
    bg: ['#170c05','#1c1008','#120a04'],
  },

  // ── Violet ─ deep purple ─ violet / purple / indigo / blue ──────────────
  violet: {
    name: 'Violet',
    dot:  '#a78bfa',
    accent:    { c200:'221 214 254', c300:'196 181 253', c400:'167 139 250', c500:'139  92 246', c600:'124  58 237' }, // violet
    secondary: { c200:'233 213 255', c300:'216 180 254', c400:'192 132 252', c500:'168  85 247', c600:'147  51 234' }, // purple
    highlight: { c200:'199 210 254', c300:'165 180 252', c400:'129 140 248', c500:' 99 102 241', c600:' 79  70 229' }, // indigo
    fleet:     { c200:'191 219 254', c300:'147 197 253', c400:' 96 165 250', c500:' 59 130 246', c600:' 37  99 235' }, // blue
    bg: ['#0f0a1a','#110c1f','#0d0917'],
  },

  // ── Crimson ─ deep red ─ red / rose-dark / orange-red / amber ───────────
  crimson: {
    name: 'Crimson',
    dot:  '#ef4444',
    accent:    { c200:'254 202 202', c300:'252 165 165', c400:'248 113 113', c500:'239  68  68', c600:'220  38  38' }, // red
    secondary: { c200:'254 215 170', c300:'253 186 116', c400:'251 146  60', c500:'249 115  22', c600:'234  88  12' }, // orange
    highlight: { c200:'254 240 138', c300:'253 224  71', c400:'250 204  21', c500:'234 179   8', c600:'202 138   4' }, // amber
    fleet:     { c200:'254 226 226', c300:'252 165 165', c400:'248 113 113', c500:'239  68  68', c600:'220  38  38' }, // red
    bg: ['#1a0505','#1c0606','#180404'],
  },

  // ── Matrix ─ terminal hacker ─ bright-green / teal / green / cyan ───────
  matrix: {
    name: 'Matrix',
    dot:  '#00ff41',
    accent:    { c200:'180 255 190', c300:' 80 255 110', c400:'  0 255  65', c500:'  0 210  55', c600:'  0 170  45' }, // matrix green
    secondary: { c200:'153 246 228', c300:' 94 234 212', c400:' 45 212 191', c500:' 20 184 166', c600:' 13 148 136' }, // teal
    highlight: { c200:'187 247 208', c300:'134 239 172', c400:' 74 222 128', c500:' 34 197  94', c600:' 22 163  74' }, // green
    fleet:     { c200:'165 243 252', c300:'103 232 249', c400:' 34 211 238', c500:'  6 182 212', c600:'  8 145 178' }, // cyan
    bg: ['#000a00','#001200','#000800'],
  },

  // ── Phosphor ─ retro CRT amber/gold ─ gold / orange / amber / lime ──────
  phosphor: {
    name: 'Phosphor',
    dot:  '#ffb000',
    accent:    { c200:'255 236 100', c300:'255 214   0', c400:'255 191   0', c500:'220 160   0', c600:'180 120   0' }, // gold
    secondary: { c200:'254 215 170', c300:'253 186 116', c400:'251 146  60', c500:'249 115  22', c600:'234  88  12' }, // orange
    highlight: { c200:'254 240 138', c300:'253 224  71', c400:'250 204  21', c500:'234 179   8', c600:'202 138   4' }, // yellow
    fleet:     { c200:'217 249 157', c300:'190 242 100', c400:'163 230  53', c500:'132 204  22', c600:'101 163  13' }, // lime
    bg: ['#0a0800','#0d0a00','#080600'],
  },

  // ── Ghost ─ monochrome ─ slate / zinc ────────────────────────────────────
  ghost: {
    name: 'Ghost',
    dot:  '#94a3b8',
    accent:    { c200:'226 232 240', c300:'203 213 225', c400:'148 163 184', c500:'100 116 139', c600:' 71  85 105' }, // slate
    secondary: { c200:'212 212 216', c300:'161 161 170', c400:'113 113 122', c500:' 82  82  91', c600:' 63  63  70' }, // zinc
    highlight: { c200:'241 245 249', c300:'226 232 240', c400:'203 213 225', c500:'148 163 184', c600:'100 116 139' }, // slate bright
    fleet:     { c200:'228 228 231', c300:'212 212 216', c400:'161 161 170', c500:'113 113 122', c600:' 82  82  91' }, // zinc
    bg: ['#080808','#0a0a0a','#060606'],
  },

  // ── Midnight ─ steel blue dark ─ steel / slate-blue / cobalt / navy ──────
  midnight: {
    name: 'Midnight',
    dot:  '#60a5fa',
    accent:    { c200:'191 219 254', c300:'147 197 253', c400:' 96 165 250', c500:' 59 130 246', c600:' 37  99 235' }, // blue-400
    secondary: { c200:'199 210 254', c300:'165 180 252', c400:'129 140 248', c500:' 99 102 241', c600:' 79  70 229' }, // indigo
    highlight: { c200:'186 230 253', c300:'125 211 252', c400:' 56 189 248', c500:' 14 165 233', c600:'  2 132 199' }, // sky
    fleet:     { c200:'165 243 252', c300:'103 232 249', c400:' 34 211 238', c500:'  6 182 212', c600:'  8 145 178' }, // cyan
    bg: ['#020818','#030c20','#010612'],
  },

  // ── Steel ─ industrial metal ─ zinc / slate / stone / neutral ────────────
  steel: {
    name: 'Steel',
    dot:  '#a1a1aa',
    accent:    { c200:'212 212 216', c300:'161 161 170', c400:'113 113 122', c500:' 82  82  91', c600:' 63  63  70' }, // zinc
    secondary: { c200:'214 211 209', c300:'168 162 158', c400:'120 113 108', c500:' 87  83  78', c600:' 68  64  60' }, // stone
    highlight: { c200:'226 232 240', c300:'203 213 225', c400:'148 163 184', c500:'100 116 139', c600:' 71  85 105' }, // slate
    fleet:     { c200:'191 219 254', c300:'147 197 253', c400:' 96 165 250', c500:' 59 130 246', c600:' 37  99 235' }, // blue accent
    bg: ['#080808','#0c0c0e','#060608'],
  },

  // ── Military ─ olive / army green ─ olive / stone / amber / lime ─────────
  military: {
    name: 'Military',
    dot:  '#84cc16',
    accent:    { c200:'217 249 157', c300:'190 242 100', c400:'163 230  53', c500:'132 204  22', c600:'101 163  13' }, // lime
    secondary: { c200:'254 240 138', c300:'253 224  71', c400:'250 204  21', c500:'234 179   8', c600:'202 138   4' }, // yellow-amber
    highlight: { c200:'214 211 209', c300:'168 162 158', c400:'120 113 108', c500:' 87  83  78', c600:' 68  64  60' }, // stone
    fleet:     { c200:'187 247 208', c300:'134 239 172', c400:' 74 222 128', c500:' 34 197  94', c600:' 22 163  74' }, // green
    bg: ['#060800','#080a00','#050700'],
  },
};

const THEME_KEYS = Object.keys(THEMES);

// ─── Service type labels ────────────────────────────────────────────────────
// Global so any component can use fmtType() without scope issues.
const SERVICE_LABELS = {
  wireguard:     'Public',          // NodeUI: Public service type = wireguard
  dvpn:          'VPN',
  public:        'Public',          // fallback if node ever uses this label
  data_transfer: 'B2B VPN and data transfer',
  scraping:      'B2B Data Scraping',
  quic_scraping: 'QUIC Scraping',
  noop:          'Noop',
  monitoring:    'Monitoring',
};
const fmtType = (t) => SERVICE_LABELS[t] || t;

// ─── CSS generator ─────────────────────────────────────────────────────────
// Maps each Tailwind color class family → the theme slot that replaces it.
// amber / red / green / yellow / rose are NEVER in this map — they are semantic.
function generateThemeCSS(key) {
  if (key === 'emerald') return ''; // emerald IS the base — no overrides
  const t = THEMES[key];
  if (!t.accent) return '';        // safety guard

  const s = `[data-theme="${key}"]`;

  // Each entry: [tailwindFamily, themeSlot]
  const map = [
    ['emerald', t.accent],
    ['sky',     t.secondary],
    ['cyan',    t.highlight],
    ['violet',  t.fleet],
    ['purple',  t.fleet],
  ];

  // Helper: emit all variants for one color family
  const emit = (fam, slot) => {
    const {c200,c300,c400,c500,c600} = slot;
    return `
  ${s} .text-${fam}-100{color:rgb(${c200})!important}
  ${s} .text-${fam}-200{color:rgb(${c200})!important}
  ${s} .text-${fam}-300{color:rgb(${c300})!important}
  ${s} .text-${fam}-400{color:rgb(${c400})!important}
  ${s} .text-${fam}-400\\/60{color:rgb(${c400}/0.6)!important}
  ${s} .text-${fam}-400\\/80{color:rgb(${c400}/0.8)!important}
  ${s} .hover\\:text-${fam}-100:hover{color:rgb(${c200})!important}
  ${s} .hover\\:text-${fam}-400:hover{color:rgb(${c400})!important}
  ${s} .bg-${fam}-400{background-color:rgb(${c400})!important}
  ${s} .bg-${fam}-500{background-color:rgb(${c500})!important}
  ${s} .bg-${fam}-600{background-color:rgb(${c600})!important}
  ${s} .bg-${fam}-500\\/5{background-color:rgb(${c500}/0.05)!important}
  ${s} .bg-${fam}-500\\/10{background-color:rgb(${c500}/0.1)!important}
  ${s} .bg-${fam}-500\\/20{background-color:rgb(${c500}/0.2)!important}
  ${s} .bg-${fam}-500\\/30{background-color:rgb(${c500}/0.3)!important}
  ${s} .hover\\:bg-${fam}-500\\/5:hover{background-color:rgb(${c500}/0.05)!important}
  ${s} .hover\\:bg-${fam}-500\\/10:hover{background-color:rgb(${c500}/0.1)!important}
  ${s} .hover\\:bg-${fam}-500\\/20:hover{background-color:rgb(${c500}/0.2)!important}
  ${s} .hover\\:bg-${fam}-500\\/30:hover{background-color:rgb(${c500}/0.3)!important}
  ${s} .hover\\:bg-${fam}-600:hover{background-color:rgb(${c600})!important}
  ${s} .border-${fam}-400{border-color:rgb(${c400})!important}
  ${s} .border-${fam}-500\\/15{border-color:rgb(${c500}/0.15)!important}
  ${s} .border-${fam}-500\\/20{border-color:rgb(${c500}/0.2)!important}
  ${s} .border-${fam}-500\\/30{border-color:rgb(${c500}/0.3)!important}
  ${s} .border-${fam}-500\\/40{border-color:rgb(${c500}/0.4)!important}
  ${s} .border-${fam}-500\\/50{border-color:rgb(${c500}/0.5)!important}
  ${s} .hover\\:border-${fam}-400:hover{border-color:rgb(${c400})!important}
  ${s} .hover\\:border-${fam}-500\\/30:hover{border-color:rgb(${c500}/0.3)!important}
  ${s} .hover\\:border-${fam}-500\\/40:hover{border-color:rgb(${c500}/0.4)!important}
  ${s} .hover\\:border-${fam}-500\\/50:hover{border-color:rgb(${c500}/0.5)!important}
  ${s} .focus\\:border-${fam}-400:focus{border-color:rgb(${c400})!important}
  ${s} .focus\\:border-${fam}-500\\/60:focus{border-color:rgb(${c500}/0.6)!important}
  ${s} .ring-${fam}-500\\/20{--tw-ring-color:rgb(${c500}/0.2)!important}
  ${s} .ring-${fam}-500\\/30{--tw-ring-color:rgb(${c500}/0.3)!important}
  ${s} .from-${fam}-500\\/10{--tw-gradient-from:rgb(${c500}/0.1)!important}
  ${s} .accent-${fam}-500{accent-color:rgb(${c500})!important}`;
  };

  let css = '';
  for (const [fam, slot] of map) {
    css += emit(fam, slot);
  }

  // Background gradient
  const [from, via, to] = t.bg;
  css += `
  ${s}.min-h-screen{background:linear-gradient(to bottom right,${from},${via},${to})!important}
  ${s}{--panel-bg:${t.bg[0]}}`;

  return css;
}

// ─── MobileSortBar ────────────────────────────────────────────────────────────
// ─── CopyableId ────────────────────────────────────────────────────────────
// Displays a full Ethereum address with copy-to-clipboard.
// Click the abbreviated form on ANY device → overlay with full address + copy button.
// Unified behaviour — no hidden hover-only icons.
const CopyableId = ({ id, className = '' }) => {
  const [copied, setCopied] = useState(false);
  const [open, setOpen] = useState(false);
  if (!id) return <span className={`text-slate-500 font-mono text-xs ${className}`}>—</span>;
  const short = id.length > 16 ? id.slice(0, 10) + '…' + id.slice(-4) : id;
  const doCopy = (e) => {
    e && e.stopPropagation();
    try { navigator.clipboard.writeText(id); } catch (_) {}
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  return (
    <>
      {/* ── Trigger: same on all screen sizes ── */}
      <button
        className={`font-mono text-xs text-cyan-300 text-left truncate hover:text-cyan-200 transition-colors ${className}`}
        onClick={(e) => { e.stopPropagation(); setOpen(true); }}
        title="Click to view & copy full ID"
      >{short}</button>
      {/* ── Overlay: shown on all screen sizes ── */}
      {open && (
        <div className="fixed inset-0 z-[300] flex items-center justify-center p-5 bg-black/70 backdrop-blur-sm" onClick={() => setOpen(false)}>
          <div className="bg-slate-900 border border-slate-700 rounded-xl p-4 w-full max-w-sm shadow-2xl" onClick={e => e.stopPropagation()}>
            <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-1.5">Consumer ID</div>
            <div className="font-mono text-xs text-cyan-300 break-all leading-relaxed mb-3 select-all">{id}</div>
            <div className="flex gap-2">
              <button onClick={doCopy} className="flex-1 py-2 text-xs bg-slate-800 border border-slate-600/40 rounded-lg hover:bg-slate-700 transition font-semibold text-slate-200">
                {copied ? '✓ Copied!' : '⎘ Copy'}
              </button>
              <button onClick={() => setOpen(false)} className="flex-1 py-2 text-xs bg-slate-800 border border-slate-600/40 rounded-lg hover:bg-slate-700 transition text-slate-400">
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
};

// Compact pill-button sort bar for mobile card views.
// keys = [{ key: 'field_name', label: 'Display' }, ...]
const MobileSortBar = ({ state, setState, keys }) => (
  <div className="sm:hidden flex flex-wrap gap-1.5 mb-2.5 pb-2 border-b border-slate-700/40">
    <span className="text-[10px] text-slate-500 self-center mr-0.5 uppercase tracking-wider">Sort</span>
    {keys.map(({ key, label }) => {
      const active = state.key === key;
      return (
        <button
          key={key}
          onClick={() => setState(prev => ({
            key,
            dir: prev.key === key && prev.dir === 'desc' ? 'asc' : 'desc'
          }))}
          className={`px-2 py-0.5 rounded text-[11px] font-semibold border transition-colors flex items-center gap-1 ${
            active
              ? 'bg-slate-600/70 border-slate-500 text-slate-100'
              : 'bg-slate-800/40 border-slate-700/40 text-slate-400 active:bg-slate-700/50'
          }`}
        >
          {label}
          {active && <span className="text-[9px] leading-none">{state.dir === 'desc' ? '▼' : '▲'}</span>}
        </button>
      );
    })}
  </div>
);

const MysteriumDashboard = () => {
  // ============ STATE ============
  const [setupMode, setSetupMode] = useState('loading'); // loading | config | connected | error
  const [config, setConfig] = useState(null);
  const [isConnected, setIsConnected] = useState(false);
  const [connectionError, setConnectionError] = useState(null);

  // Auth state
  const [apiKey, setApiKey] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');

  // Metrics
  const [metrics, setMetrics] = useState({
    nodeStatus: { status: 'offline', uptime: '0s' },
    earnings: { balance: 0, unsettled: 0, lifetime: 0, daily: 0, weekly: 0, monthly: 0, earnings_source: 'sessions', wallet_address: '', channel_address: '' },
    bandwidth: { in: 0, out: 0, total: 0, paid_in: 0, paid_out: 0, paid_total: 0, vpn_today_in: 0, vpn_today_out: 0, vpn_today_total: 0, vpn_month_in: 0, vpn_month_out: 0, vpn_month_total: 0, vnstat_available: false, vnstat_nic_name: 'NIC', vnstat_today_total: 0, vnstat_month_total: 0, has_vpn_vnstat: false, vpn_interfaces: {}, data_source: 'none' },
    services: { items: [], total: 0, active: 0 },
    sessions: { items: [], total: 0, active: 0 },
    live_connections: { peers: [], active: 0, total: 0, svc_connections: 0 },
    clients: { connected: 0, peak: 0 },
    performance: { latency: 0, packet_loss: 0, speed_in: 0, speed_out: 0, speed_total: 0, sys_speed_in: 0, sys_speed_out: 0, sys_speed_total: 0, sys_nic: 'NIC', idle: false },
    resources: { cpu: 0, ram: 0, disk: 0, cpu_temp: null, cpu_temp_source: '', all_temps: [] },
    firewall: { status: 'unconfigured', rules: 0, blocked: 0, rule_details: [], ufw_rules: [] },
    systemHealth: { overall: 'unknown', subsystems: [] },
    nodeQuality: { available: false, quality_score: null, latency_ms: null, bandwidth_mbps: null, uptime_24h_net: null, packet_loss_net: null, uptime_24h_local: null, uptime_30d_local: null, tracking_since: null, tracking_days: 0, monitoring_failed: null, services: [], error: null },
    logs: [],
    nodeConnected: false
  });

  const [updateInterval, setUpdateInterval] = useState(5000);
  const [toolkitVersion, setToolkitVersion] = useState('...');
  const [updateInfo, setUpdateInfo]         = useState(null);
  const [nodeUpdateInfo, setNodeUpdateInfo] = useState(null);
  const [healthToast, setHealthToast] = useState(null);  // {msg, level} — degraded-state notification

  // Fleet Node Manager state — must be at top level to survive fetchMetrics re-renders
  const [fleetModalOpen, setFleetModalOpen] = React.useState(false);
  const [fleetEditNode, setFleetEditNode] = React.useState(null);
  const [fleetForm, setFleetForm] = React.useState({ label: '', toolkit_url: '', toolkit_api_key: '' });
  const [fleetProbing, setFleetProbing] = React.useState(false);
  const [fleetProbeResult, setFleetProbeResult] = React.useState(null);
  const [fleetSaving, setFleetSaving] = React.useState(false);
  const [fleetSaveError, setFleetSaveError] = React.useState('');
  const [fleetConfigNodes, setFleetConfigNodes] = React.useState([]);
  const [healthBusy, setHealthBusy] = useState(false);   // scan in progress
  const [fixResults, setFixResults] = useState({});       // subsystem name → actions[]
  const [lastUpdate, setLastUpdate] = useState(null);
  const [tickCount, setTickCount] = useState(0); // 1s counter for live countdown
  const [activePanel, setActivePanel] = useState(null); // 'services' | 'sessions' | 'firewall' | 'health' | 'data' | 'fleet' | null
  const [sessionTab, setSessionTab] = useState('live'); // 'live' | 'history'
  const [consumerSort, setConsumerSort] = useState({ key: 'total_earnings', dir: 'desc' });
  const [historySort, setHistorySort] = useState({ key: 'started', dir: 'desc' });
  const [archiveSessions, setArchiveSessions] = useState([]);
  const [archiveTotal, setArchiveTotal] = useState(0);
  const [archiveLoading, setArchiveLoading] = useState(false);
  const [archiveOffset, setArchiveOffset] = useState(0);
  const ARCHIVE_PAGE = 100;
  const [activeSort, setActiveSort] = useState({ key: 'earnings_myst', dir: 'desc' });
  const [tunnelSort, setTunnelSort] = useState({ key: 'total_mb', dir: 'desc' });
  const [fleetSort, setFleetSort] = useState({ key: 'unsettled', dir: 'desc' });
  const [selectedNodeId, setSelectedNodeId] = useState(() => {
    // Restore selected node from URL on page load/refresh
    try {
      const params = new URLSearchParams(window.location.search);
      return params.get('node') || null;
    } catch { return null; }
  });
  const selectedNodeRef = useRef(null); // keep ref in sync for fetchMetrics
  // healthBackendUrl: returns the correct URL base for health fix/scan/persist requests.
  // For fleet nodes: routes via /fleet/node/<id>/proxy/<endpoint> on the central backend.
  // This keeps the remote API key server-side and never exposes it to the browser.
  const healthFixUrl = (endpoint) => {
    if (metrics._fleet_node && metrics._node_id) {
      return `${backendUrlRef.current}/fleet/node/${encodeURIComponent(metrics._node_id)}/proxy/${endpoint}`;
    }
    return `${backendUrlRef.current}/${endpoint}`;
  };

  // nodeAwareUrl: when viewing a fleet node, route card API calls via proxy
  // so each card fetches data from the correct remote node, not the central VPS
  const getNodeAwareUrl = () => {
    if (metrics._fleet_node && metrics._node_id) {
      return `${backendUrlRef.current}/fleet/node/${encodeURIComponent(metrics._node_id)}/proxy`;
    }
    return backendUrlRef.current;
  };

  // Sync selectedNodeId to URL so browser back/forward works
  useEffect(() => {
    try {
      if (selectedNodeId) {
        const url = `${window.location.pathname}?node=${encodeURIComponent(selectedNodeId)}`;
        window.history.pushState({ node: selectedNodeId }, '', url);
      } else {
        window.history.pushState({ node: null }, '', window.location.pathname);
      }
    } catch {}
  }, [selectedNodeId]);

  // Handle browser back/forward button
  useEffect(() => {
    const onPop = (e) => {
      const nodeId = e.state?.node || null;
      setSelectedNodeId(nodeId);
      selectedNodeRef.current = nodeId;
      setTimeout(fetchMetrics, 50);
    };
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, []);

  const mkSort = (setState) => (key) => setState(prev => ({
    key, dir: prev.key === key && prev.dir === 'desc' ? 'asc' : 'desc'
  }));
  const sortIcon = (state, key) => state.key === key ? (state.dir === 'desc' ? '▼' : '▲') : '⇅';
  const hdrCls = (state, key) => `cursor-pointer select-none flex items-center gap-1 hover:text-slate-200 transition${state.key === key ? ' text-slate-200' : ''}`;
  const sortRows = (rows, state) => [...rows].sort((a, b) => {
    const mul = state.dir === 'desc' ? -1 : 1;
    const av = a[state.key] ?? '';
    const bv = b[state.key] ?? '';
    return av > bv ? -mul : av < bv ? mul : 0;
  });
  const [showLogs, setShowLogs] = useState(false);
  const [showHelp, setShowHelp] = useState(false);
  const [theme, setTheme] = useState(() => {
    try { return localStorage.getItem('myst-theme') || 'emerald'; } catch { return 'emerald'; }
  });

  // Darkest background for fullscreen panels and modals — follows theme bg[0], falls back to neutral black
  const panelBg = THEMES[theme]?.bg?.[0] ?? '#0a0a0a';

  // Persist theme
  useEffect(() => {
    try { localStorage.setItem('myst-theme', theme); } catch {}
  }, [theme]);

  // Refs for stable access in callbacks
  const backendUrlRef = useRef('');
  const authHeaderRef = useRef({});

  // ============ HELPERS ============
  const safeNum = (val, fallback = 0) => {
    const n = Number(val);
    return Number.isFinite(n) ? n : fallback;
  };

  const formatDataSize = (mb) => {
    const v = safeNum(mb);
    if (v >= 1024 * 1024) return `${(v / 1024 / 1024).toFixed(2)} TiB`;
    if (v >= 1024)        return `${(v / 1024).toFixed(2)} GiB`;
    if (v >= 1)           return `${v.toFixed(1)} MB`;
    if (v > 0)            return `${(v * 1024).toFixed(0)} KB`;
    return '0 MB';
  };

  // Convert 2-letter country code to flag emoji
  const countryFlag = (code) => {
    if (!code || code.length !== 2) return '';
    const offset = 127397;
    return String.fromCodePoint(...[...code.toUpperCase()].map(c => c.charCodeAt(0) + offset));
  };

  // Format speed in MB/s with auto-scale + bits
  const formatSpeed = (mbps) => {
    const v = safeNum(mbps);
    if (v <= 0) return '0 B/s';
    const Bps = v * 1024 * 1024;
    if (v >= 1) return `${v.toFixed(2)} MB/s`;
    if (Bps >= 1024) return `${(Bps / 1024).toFixed(1)} KB/s`;
    return `${Bps.toFixed(0)} B/s`;
  };

  // Short speed for subtitles
  const formatSpeedShort = (mbps) => {
    const v = safeNum(mbps);
    if (v <= 0) return '0 B/s';
    const Bps = v * 1024 * 1024;
    if (v >= 1) return `${v.toFixed(2)} MB/s`;
    if (Bps >= 1024) return `${(Bps / 1024).toFixed(1)} KB/s`;
    return `${Bps.toFixed(0)} B/s`;
  };

  const getBackendUrl = useCallback(() => {
    if (backendUrlRef.current) return backendUrlRef.current;
    const port = config?.dashboard_port || 5000;
    const host = window.location.hostname || 'localhost';
    // If accessed from another device (not localhost), use Vite proxy to avoid
    // needing port 5000 open in firewall. Proxy routes /api → localhost:5000.
    if (host !== 'localhost' && host !== '127.0.0.1') {
      return `${window.location.protocol}//${window.location.host}`;
    }
    return `http://${host}:${port}`;
  }, [config]);

  // ============ INITIALIZATION ============
  useEffect(() => {
    loadConfig();
    // Fetch toolkit version from backend (no auth required)
    fetch('/api/version').then(r => r.ok ? r.json() : null).then(d => {
      if (d?.version) setToolkitVersion(d.version);
    }).catch(() => {});
    // Check for available update (cached 1h on backend)
    fetch('/api/update-check').then(r => r.ok ? r.json() : null).then(d => {
      if (d) setUpdateInfo(d);
    }).catch(() => {});
    // Check for available Mysterium node update (cached 1h on backend)
    fetch('/api/node-update-check').then(r => r.ok ? r.json() : null).then(d => {
      if (d) setNodeUpdateInfo(d);
    }).catch(() => {});
  }, []);

  const loadConfig = async () => {
    // Try restoring previous session first (survives page refresh)
    try {
      const savedAuth = localStorage.getItem('myst-auth');
      const savedUrl = localStorage.getItem('myst-backend-url');
      if (savedAuth && savedUrl) {
        const headers = JSON.parse(savedAuth);
        const resp = await fetch(`${savedUrl}/metrics`, { headers, signal: AbortSignal.timeout(5000) });
        if (resp.ok) {
          backendUrlRef.current = savedUrl;
          authHeaderRef.current = headers;
          setIsConnected(true);
          setSetupMode('connected');
          return;
        }
      }
    } catch {}

    try {
      const response = await fetch('/config/setup.json');
      if (response.ok) {
        const data = await response.json();
        setConfig(data);

        // Determine backend URL — use proxy for remote access (phone/LAN)
        const host = window.location.hostname || 'localhost';
        let backendUrl;
        if (host !== 'localhost' && host !== '127.0.0.1') {
          backendUrl = `${window.location.protocol}//${window.location.host}`;
        } else {
          backendUrl = `http://${data.node_host || 'localhost'}:${data.dashboard_port || 5000}`;
        }
        backendUrlRef.current = backendUrl;

        // Show appropriate auth UI based on setup
        if (data.dashboard_auth_method === 'apikey') {
          setSetupMode('apikey_input');
        } else if (data.dashboard_auth_method === 'userpass') {
          setSetupMode('userpass_input');
        } else {
          attemptAutoConnect(backendUrl, {});
        }
      } else {
        // No config file — try auto-connect anyway (proxy or localhost)
        const host = window.location.hostname || 'localhost';
        let backendUrl;
        if (host !== 'localhost' && host !== '127.0.0.1') {
          backendUrl = `${window.location.protocol}//${window.location.host}`;
        } else {
          backendUrl = `http://localhost:5000`;
        }
        backendUrlRef.current = backendUrl;
        attemptAutoConnect(backendUrl, {});
      }
    } catch (e) {
      // Network error — still try auto-connect
      const host = window.location.hostname || 'localhost';
      let backendUrl;
      if (host !== 'localhost' && host !== '127.0.0.1') {
        backendUrl = `${window.location.protocol}//${window.location.host}`;
      } else {
        backendUrl = `http://localhost:5000`;
      }
      backendUrlRef.current = backendUrl;
      attemptAutoConnect(backendUrl, {});
    }
  };

  const attemptAutoConnect = useCallback(async (backendUrl, headers) => {
    try {
      const response = await fetch(`${backendUrl}/metrics`, {
        headers,
        signal: AbortSignal.timeout(5000)
      });

      if (response.ok) {
        backendUrlRef.current = backendUrl;
        authHeaderRef.current = headers;
        setIsConnected(true);
        setSetupMode('connected');
        setConnectionError(null);
        // Persist auth so page refresh doesn't lose session
        try {
          localStorage.setItem('myst-auth', JSON.stringify(headers));
          localStorage.setItem('myst-backend-url', backendUrl);
        } catch {}
        return true;
      } else if (response.status === 401) {
        // 401 → show correct login screen based on configured auth method
        setConnectionError('');
        const cfg = await fetch('/config/setup.json').then(r=>r.ok?r.json():null).catch(()=>null);
        const method = cfg?.dashboard_auth_method || 'apikey';
        setSetupMode(method === 'userpass' ? 'userpass_input' : 'apikey_input');
        return false;
      } else {
        setConnectionError(`Backend returned HTTP ${response.status}. Is the toolkit running?`);
        setSetupMode('no_config');
        return false;
      }
    } catch (err) {
      // Cannot reach backend at all — show actionable error, never stay on loading screen
      const msg = err.name === 'TimeoutError'
        ? 'Connection timed out — backend not reachable. Start the toolkit with ./start.sh'
        : `Cannot connect to backend: ${err.message}. Run ./start.sh to start the toolkit.`;
      setConnectionError(msg);
      setSetupMode('no_config');
      return false;
    }
  }, []);

  const connectWithApiKey = useCallback((key) => {
    const url = getBackendUrl();
    const headers = key ? { 'Authorization': `Bearer ${key}` } : {};
    attemptAutoConnect(url, headers);
  }, [getBackendUrl, attemptAutoConnect]);

  const connectWithCredentials = useCallback((user, pass) => {
    const url = getBackendUrl();
    const headers = (user && pass)
      ? { 'Authorization': `Basic ${btoa(`${user}:${pass}`)}` }
      : {};
    attemptAutoConnect(url, headers);
  }, [getBackendUrl, attemptAutoConnect]);

  // ============ DATA FETCHING ============
  const fetchMetrics = useCallback(async () => {
    if (!isConnected) return;

    try {
      // When a remote node is selected, fetch from fleet endpoint and map to metrics shape
      const nodeId = selectedNodeRef.current;
      const metricsUrl = nodeId
        ? `${backendUrlRef.current}/fleet/node/${encodeURIComponent(nodeId)}`
        : `${backendUrlRef.current}/metrics`;

      const response = await fetch(metricsUrl, {
        headers: authHeaderRef.current,
        signal: AbortSignal.timeout(10000)
      });
      if (response.ok) {
        const raw = await response.json();

        // Map fleet/node/<id> response to the same metrics shape used by /metrics
        const data = nodeId ? {
          nodeStatus: {
            status:    raw.status || 'unknown',
            version:   raw.version || '',
            uptime:    raw.uptime || '',
            nat_type:  raw.nat || '',
            public_ip: raw.ip || '',
            identity:  raw.identity || raw.wallet || '',
          },
          earnings:        raw.earnings || {},
          sessions:        {
            ...raw.sessions,
            active_items: (raw.sessions?.items || []).filter(s => s.is_active),
            // Use pre-computed analytics from remote node — no re-computation on fleet master
            service_breakdown: raw.analytics?.service_breakdown || raw.sessions?.service_breakdown || [],
            country_breakdown: raw.analytics?.country_breakdown || raw.sessions?.country_breakdown || [],
            lifetime_totals:   raw.analytics?.lifetime_totals   || raw.sessions?.lifetime_totals   || {},
            monitoring_sessions: raw.analytics?.monitoring_sessions ?? raw.sessions?.monitoring_sessions ?? 0,
          },
          services:        raw.services || {},
          resources:       raw.resources || {},
          nodeQuality:     raw.node_quality || {},
          bandwidth:       raw.traffic || {},
          clients:         { connected: raw.sessions?.vpn_tunnel_count || raw.live_connections?.active || 0, peak: 0 },
          performance:     raw.performance || { speed_total: 0, speed_in: 0, speed_out: 0, idle: true },
          firewall:        raw.firewall || { status: 'unknown', rules: 0, blocked: 0, rule_details: [], ufw_rules: [] },
          systemHealth:    raw.systemHealth || { overall: 'ok', subsystems: [] },
          live_connections: raw.live_connections || { active: 0, peers: [], svc_connections: 0 },
          logs:            raw.logs || [],
          nodeConnected:   raw.status === 'online',
          fleet:           null,  // hide fleet bar when viewing a specific node
          _fleet_node:     true,  // marker so UI knows we're in single-node view
          _node_label:     raw.label || nodeId,
          _node_id:        nodeId,
          _node_toolkit_url: raw.toolkit_url || null,  // remote toolkit URL for fix requests
        } : raw;

        setMetrics(prev => ({
          nodeStatus: data.nodeStatus || prev.nodeStatus,
          earnings: data.earnings || prev.earnings,
          bandwidth: data.bandwidth || prev.bandwidth,
          services: data.services || prev.services,
          sessions: data.sessions || prev.sessions,
          live_connections: data.live_connections || prev.live_connections,
          clients: data.clients || prev.clients,
          performance: data.performance || prev.performance,
          resources: data.resources || prev.resources,
          firewall: data.firewall || prev.firewall,
          systemHealth: data.systemHealth || prev.systemHealth,
          nodeQuality: data.nodeQuality || prev.nodeQuality,
          logs: data.logs || prev.logs,
          traffic_history: data.traffic_history || prev.traffic_history,
          nodeConnected: data.nodeConnected ?? false,
          fleet: data.fleet !== undefined ? data.fleet : prev.fleet,
          _fleet_node: data._fleet_node || false,
          _node_label: data._node_label || '',
          _node_id: data._node_id || '',
          _node_toolkit_url: data._node_toolkit_url || null,
        }));
        setLastUpdate(new Date());
        // Degraded-state toast: auto-show on warning/critical, auto-dismiss on ok
        if (data.systemHealth && data.systemHealth.overall) {
          if (data.systemHealth.overall !== 'ok') {
            const issues = (data.systemHealth.subsystems || []).filter(s => s.status !== 'ok').length;
            setHealthToast({ msg: `${issues} health issue${issues !== 1 ? 's' : ''} detected`, level: data.systemHealth.overall });
            // Auto-dismiss after 30s
            setTimeout(() => setHealthToast(null), 30000);
          } else {
            setHealthToast(null);
          }
        }
      } else if (response.status === 401) {
        // Auth failed — clear stale credentials and show fresh login
        try { localStorage.removeItem('myst-auth'); localStorage.removeItem('myst-backend-url'); } catch {}
        setIsConnected(false);
        backendUrlRef.current = '';
        authHeaderRef.current = {};
        setSetupMode('apikey_input');
        setConnectionError('');
      }
    } catch (err) {
      console.error('Fetch error:', err);
    }
  }, [isConnected]);

  // Keep ref in sync with state (ref is readable inside fetchMetrics callback)
  useEffect(() => { selectedNodeRef.current = selectedNodeId; }, [selectedNodeId]);

  // Fetch archive sessions from SessionDB when History tab is opened
  const fetchArchive = React.useCallback((offset = 0, replace = true) => {
    if (!backendUrlRef.current) return;
    setArchiveLoading(true);
    const hdrs = authHeaderRef.current || {};
    fetch(`${getNodeAwareUrl()}/sessions/archive?limit=${ARCHIVE_PAGE}&offset=${offset}`, { headers: hdrs })
      .then(r => r.json())
      .then(data => {
        const items = data.items || [];
        // Get IDs already in live store to avoid duplicates
        setArchiveSessions(prev => replace ? items : [...prev, ...items]);
        setArchiveTotal(data.total || 0);
        setArchiveLoading(false);
      })
      .catch(() => setArchiveLoading(false));
  }, []);

  useEffect(() => {
    if (sessionTab === 'history') fetchArchive(0, true);
  }, [sessionTab, fetchArchive]);

  // Auto-refresh every 5s
  useEffect(() => {
    const onDeleted = (e) => {
      // Force immediate refresh + second pass 3s later so backend slow-cache also clears
      setTimeout(fetchMetrics, 300);
      setTimeout(fetchMetrics, 3500);
    };
    window.addEventListener('myst-data-deleted', onDeleted);
    return () => window.removeEventListener('myst-data-deleted', onDeleted);
  }, []);

  useEffect(() => {
    if (!isConnected) return;
    fetchMetrics();
    const interval = setInterval(fetchMetrics, updateInterval);
    return () => clearInterval(interval);
  }, [isConnected, fetchMetrics, updateInterval]);

  // 1-second ticker for live "Xs ago" countdown
  useEffect(() => {
    if (!isConnected) return;
    const tick = setInterval(() => setTickCount(c => c + 1), 1000);
    return () => clearInterval(tick);
  }, [isConnected]);

  // ============ DISCONNECT ============
  const handleDisconnect = () => {
    backendUrlRef.current = '';
    authHeaderRef.current = {};
    try { localStorage.removeItem('myst-auth'); localStorage.removeItem('myst-backend-url'); } catch {}
    setIsConnected(false);
    setSetupMode('loading');
    loadConfig();
  };

  // ============ UI: LOADING ============
  if (setupMode === 'loading') {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-950 via-slate-900 to-slate-800 flex items-center justify-center">
        <div className="text-center">
          <div className="inline-block p-4 rounded-lg bg-emerald-500/10 border border-emerald-500/30 mb-6 animate-pulse">
            <Zap className="w-8 h-8 text-emerald-400" />
          </div>
          <h1 className="text-2xl font-bold text-white mb-2">Mysterium Dashboard</h1>
          <p className="text-slate-400">Initializing...</p>
        </div>
      </div>
    );
  }

  // ============ UI: NO CONFIGURATION ============
  if (setupMode === 'no_config') {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-950 via-slate-900 to-slate-800 text-white font-['SF_Mono',monospace] flex items-center justify-center p-6">
        <div className="max-w-md text-center">
          <div className="inline-block p-4 rounded-lg bg-red-500/10 border border-red-500/30 mb-6">
            <AlertCircle className="w-8 h-8 text-red-400" />
          </div>
          <h1 className="text-2xl font-bold mb-4">
            {connectionError ? 'Cannot Connect to Backend' : 'Setup Required'}
          </h1>
          {connectionError ? (
            <>
              <div className="bg-slate-900/60 border border-red-500/20 rounded p-3 mb-5 text-left">
                <p className="text-sm text-red-300">{connectionError}</p>
              </div>
              <p className="text-sm text-slate-400 mb-5">Make sure the toolkit backend is running:</p>
              <code className="block bg-slate-800 p-3 rounded border border-slate-700 text-sm mb-5 text-left">
                ./start.sh
              </code>
              <div className="flex gap-3 justify-center">
                <button
                  onClick={() => { setSetupMode('loading'); setConnectionError(null); loadConfig(); }}
                  className="px-5 py-2 bg-emerald-500 hover:bg-emerald-600 text-white rounded font-semibold transition text-sm"
                >
                  Retry
                </button>
              </div>
            </>
          ) : (
            <>
              <p className="text-slate-400 mb-6">The dashboard hasn't been configured yet.</p>
              <p className="text-sm text-slate-500 mb-4">Run the setup wizard:</p>
              <code className="block bg-slate-800 p-4 rounded border border-slate-700 text-sm mb-4">
                ./bin/setup.sh
              </code>
              <p className="text-xs text-slate-500 mb-4">Then start the toolkit and refresh this page:</p>
              <code className="block bg-slate-800 p-3 rounded border border-slate-700 text-sm mb-5">
                ./start.sh
              </code>
              <button
                onClick={() => { setSetupMode('loading'); loadConfig(); }}
                className="px-5 py-2 bg-emerald-500 hover:bg-emerald-600 text-white rounded font-semibold transition text-sm"
              >
                Retry
              </button>
            </>
          )}
        </div>
      </div>
    );

  }

  // ============ UI: API KEY INPUT ============
  if (setupMode === 'apikey_input') {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-950 via-slate-900 to-slate-800 text-white font-['SF_Mono',monospace] flex items-center justify-center p-6">
        <div className="max-w-md">
          <div className="text-center mb-8">
            <div className="inline-block p-4 rounded-lg bg-emerald-500/10 border border-emerald-500/30 mb-6">
              <Zap className="w-8 h-8 text-emerald-400" />
            </div>
            <h1 className="text-2xl font-bold">Mysterium Dashboard</h1>
            <p className="text-slate-400 text-sm mt-2">Enter your API Key</p>
          </div>

          <div className="bg-slate-800/40 border border-slate-700 rounded-lg p-6 backdrop-blur">
            <label className="block text-xs font-semibold text-slate-300 mb-1 tracking-widest">API KEY</label>
            <p className="text-xs text-amber-400/80 mb-3">⚠ Copy &amp; paste your key — do not type it manually.</p>
            <input
              type="password"
              placeholder="Paste your API key here"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && apiKey && connectWithApiKey(apiKey)}
              className="w-full px-4 py-2 bg-slate-900 border border-slate-600 rounded text-white mb-4 focus:border-emerald-400 focus:outline-none"
            />
            <button
              onClick={() => connectWithApiKey(apiKey)}
              disabled={!apiKey}
              className="w-full px-4 py-2 bg-emerald-500 hover:bg-emerald-600 text-white rounded font-semibold transition disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Login
            </button>
            <p className="text-xs text-slate-500 mt-3 text-center">Key set during setup.sh — find it in <code className="bg-slate-800 px-1 rounded">.env</code> or <code className="bg-slate-800 px-1 rounded">config/setup.json</code></p>
          </div>

          {connectionError && (
            <div className="mt-6 p-4 bg-red-500/10 border border-red-500/30 rounded flex gap-3 items-start">
              <AlertCircle className="w-4 h-4 text-red-400 flex-shrink-0 mt-0.5" />
              <div>
                <div className="text-sm text-red-200">{connectionError}</div>
                {connectionError.includes('connect') && (
                  <div className="mt-2 text-xs text-slate-400 space-y-1">
                    <div>Is the toolkit backend running? Start it with <code className="bg-slate-800 px-1 rounded">./start.sh</code></div>
                    <div>Is the Mysterium node running? Check: <code className="bg-slate-800 px-1 rounded">sudo systemctl status mysterium-node</code></div>
                    <div>Node UI: <a href="http://localhost:4449/ui" target="_blank" rel="noopener noreferrer" className="text-slate-300 underline">http://localhost:4449/ui</a></div>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    );
  }

  if (setupMode === 'userpass_input') {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-950 via-slate-900 to-slate-800 text-white font-['SF_Mono',monospace] flex items-center justify-center p-6">
        <div className="max-w-md">
          <div className="text-center mb-8">
            <div className="inline-block p-4 rounded-lg bg-emerald-500/10 border border-emerald-500/30 mb-6">
              <Zap className="w-8 h-8 text-emerald-400" />
            </div>
            <h1 className="text-2xl font-bold">Mysterium Dashboard</h1>
            <p className="text-slate-400 text-sm mt-2">Enter your credentials</p>
          </div>

          <div className="bg-slate-800/40 border border-slate-700 rounded-lg p-6 backdrop-blur">
            <label className="block text-xs font-semibold text-slate-300 mb-1 tracking-widest">USERNAME</label>
            <p className="text-xs text-slate-500 mb-2">Default username: <span className="text-slate-300 font-mono">admin</span></p>
            <input
              type="text"
              placeholder="admin"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full px-4 py-2 bg-slate-900 border border-slate-600 rounded text-white mb-4 focus:border-emerald-400 focus:outline-none"
            />

            <label className="block text-xs font-semibold text-slate-300 mb-2 tracking-widest">PASSWORD</label>
            <input
              type="password"
              placeholder="Password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && username && password && connectWithCredentials(username, password)}
              className="w-full px-4 py-2 bg-slate-900 border border-slate-600 rounded text-white mb-4 focus:border-emerald-400 focus:outline-none"
            />

            <button
              onClick={() => connectWithCredentials(username, password)}
              disabled={!username || !password}
              className="w-full px-4 py-2 bg-emerald-500 hover:bg-emerald-600 text-white rounded font-semibold transition disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Login
            </button>
            <p className="text-xs text-slate-500 mt-3 text-center">Credentials set during setup.sh — find them in <code className="bg-slate-800 px-1 rounded">.env</code> or <code className="bg-slate-800 px-1 rounded">config/setup.json</code></p>
          </div>

          {connectionError && (
            <div className="mt-6 p-4 bg-red-500/10 border border-red-500/30 rounded flex gap-3 items-start">
              <AlertCircle className="w-4 h-4 text-red-400 flex-shrink-0 mt-0.5" />
              <div>
                <div className="text-sm text-red-200">{connectionError}</div>
                {connectionError.includes('connect') && (
                  <div className="mt-2 text-xs text-slate-400 space-y-1">
                    <div>Is the toolkit backend running? Start it with <code className="bg-slate-800 px-1 rounded">./start.sh</code></div>
                    <div>Is the Mysterium node running? Check: <code className="bg-slate-800 px-1 rounded">sudo systemctl status mysterium-node</code></div>
                    <div>Node UI: <a href="http://localhost:4449/ui" target="_blank" rel="noopener noreferrer" className="text-slate-300 underline">http://localhost:4449/ui</a></div>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    );
  }

  if (setupMode === 'connected' && isConnected) {
    // ── FLEET LANDING PAGE ─────────────────────────────────────────────────
    // When fleet mode is active and no node is selected yet, show the fleet
    // overview as a dedicated landing page — not embedded in the dashboard.
    if (metrics.fleet?.fleet_mode && !selectedNodeId) {
      const fleetNodes = metrics.fleet.nodes || [];

      // ── Fleet Node Manager — uses top-level state to survive re-renders ───
      const openFleetAdd = () => {
        setFleetEditNode(null);
        setFleetForm({ label: '', toolkit_url: '', toolkit_api_key: '' });
        setFleetProbeResult(null);
        setFleetSaveError('');
        setFleetModalOpen(true);
        fetch(`${backendUrlRef.current}/fleet/config`, { headers: authHeaderRef.current })
          .then(r => r.json()).then(d => setFleetConfigNodes(d.nodes || [])).catch(() => {});
      };

      const openFleetEdit = (node) => {
        setFleetEditNode(node);
        setFleetForm({ label: node.label || '', toolkit_url: node.toolkit_url || '', toolkit_api_key: node.toolkit_api_key || '' });
        setFleetProbeResult(null);
        setFleetSaveError('');
        setFleetModalOpen(true);
        fetch(`${backendUrlRef.current}/fleet/config`, { headers: authHeaderRef.current })
          .then(r => r.json()).then(d => setFleetConfigNodes(d.nodes || [])).catch(() => {});
      };

      const handleFleetProbe = async () => {
        if (!fleetForm.toolkit_url) return;
        setFleetProbing(true);
        setFleetProbeResult(null);
        try {
          const r = await fetch(`${backendUrlRef.current}/fleet/probe`, {
            method: 'POST',
            headers: { ...authHeaderRef.current, 'Content-Type': 'application/json' },
            body: JSON.stringify({ toolkit_url: fleetForm.toolkit_url, toolkit_api_key: fleetForm.toolkit_api_key }),
          });
          const d = await r.json();
          setFleetProbeResult(d);
          if (d.success && !fleetForm.label) {
            setFleetForm(f => ({ ...f, label: d.suggested_label || '' }));
          }
        } catch (e) {
          setFleetProbeResult({ success: false, error: e.message });
        }
        setFleetProbing(false);
      };

      const handleFleetSave = async () => {
        if (!fleetForm.toolkit_url || !fleetForm.toolkit_api_key) {
          setFleetSaveError('Toolkit URL and API key are required.');
          return;
        }
        setFleetSaving(true);
        setFleetSaveError('');
        try {
          let updated;
          if (fleetEditNode) {
            updated = fleetConfigNodes.map(n =>
              (n.toolkit_url === fleetEditNode.toolkit_url)
                ? { ...n, label: fleetForm.label, toolkit_url: fleetForm.toolkit_url, toolkit_api_key: fleetForm.toolkit_api_key }
                : n
            );
          } else {
            const newNode = {
              id: fleetForm.label.toLowerCase().replace(/[^a-z0-9]/g, '-').replace(/-+/g, '-').replace(/^-|-$/g, '') || `node${fleetConfigNodes.length}`,
              label: fleetForm.label || fleetForm.toolkit_url,
              toolkit_url: fleetForm.toolkit_url,
              toolkit_api_key: fleetForm.toolkit_api_key,
            };
            updated = [...fleetConfigNodes, newNode];
          }
          const r = await fetch(`${backendUrlRef.current}/fleet/config`, {
            method: 'POST',
            headers: { ...authHeaderRef.current, 'Content-Type': 'application/json' },
            body: JSON.stringify({ nodes: updated }),
          });
          const d = await r.json();
          if (d.success) {
            setFleetModalOpen(false);
            setTimeout(fetchMetrics, 500);
          } else {
            setFleetSaveError(d.error || 'Save failed');
          }
        } catch (e) {
          setFleetSaveError(e.message);
        }
        setFleetSaving(false);
      };

      const handleFleetRemove = async (node) => {
        if (!window.confirm(`Remove "${node.label || node.toolkit_url}" from fleet?`)) return;
        try {
          const cfgR = await fetch(`${backendUrlRef.current}/fleet/config`, { headers: authHeaderRef.current });
          const cfg = await cfgR.json();
          const updated = (cfg.nodes || []).filter(n => n.toolkit_url !== node.toolkit_url);
          await fetch(`${backendUrlRef.current}/fleet/config`, {
            method: 'POST',
            headers: { ...authHeaderRef.current, 'Content-Type': 'application/json' },
            body: JSON.stringify({ nodes: updated }),
          });
          setTimeout(fetchMetrics, 500);
        } catch (e) {
          console.error('Remove failed:', e);
        }
      };

      const FleetNodeManager = () => {
        return (
          <>
            {/* Add Node button */}
            <button onClick={openFleetAdd}
              className="px-3 py-1.5 text-xs font-semibold rounded border border-violet-500/40 bg-violet-500/10 text-violet-300 hover:bg-violet-500/20 hover:border-violet-400 transition flex items-center gap-1.5">
              <span>⊕</span> Add Node
            </button>

            {/* Edit buttons on node cards — injected via data attribute */}
            {fleetNodes.map(n => (
              <button key={`edit-${n.id}`} data-edit-node={n.id}
                onClick={() => openFleetEdit(n)}
                className="hidden" />
            ))}

            {/* Modal */}
            {fleetModalOpen && (
              <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm px-4">
                <div className="w-full max-w-md bg-slate-900 border border-violet-500/20 rounded-xl shadow-2xl">
                  {/* Modal header */}
                  <div className="flex items-center justify-between px-5 py-4 border-b border-slate-800">
                    <div className="flex items-center gap-2">
                      <span className="text-violet-400">⬡</span>
                      <h3 className="text-sm font-semibold text-slate-200">
                        {fleetEditNode ? 'Edit Node' : 'Add Node to Fleet'}
                      </h3>
                    </div>
                    <button onClick={() => setFleetModalOpen(false)} className="text-slate-500 hover:text-white transition">✕</button>
                  </div>

                  {/* Modal body */}
                  <div className="px-5 py-4 space-y-4">
                    {/* Toolkit URL */}
                    <div>
                      <label className="block text-xs text-slate-400 mb-1">Toolkit URL <span className="text-red-400">*</span></label>
                      <input
                        value={fleetForm.toolkit_url}
                        onChange={e => { setFleetForm(f => ({ ...f, toolkit_url: e.target.value })); setFleetProbeResult(null); }}
                        placeholder="http://NODE_IP:5000"
                        className="w-full bg-slate-800 border border-slate-600 focus:border-violet-400 rounded px-3 py-2 text-xs text-slate-200 outline-none transition font-mono"
                      />
                      <p className="text-xs text-slate-600 mt-1">IP address and port of the remote toolkit backend</p>
                    </div>

                    {/* API Key */}
                    <div>
                      <label className="block text-xs text-slate-400 mb-1">API Key <span className="text-red-400">*</span></label>
                      <input
                        type="password"
                        value={fleetForm.toolkit_api_key}
                        onChange={e => { setFleetForm(f => ({ ...f, toolkit_api_key: e.target.value })); setFleetProbeResult(null); }}
                        placeholder="Paste API key from remote node's config/setup.json"
                        className="w-full bg-slate-800 border border-slate-600 focus:border-violet-400 rounded px-3 py-2 text-xs text-slate-200 outline-none transition font-mono"
                      />
                    </div>

                    {/* Test Connection */}
                    <button onClick={handleFleetProbe} disabled={fleetProbing || !fleetForm.toolkit_url}
                      className="w-full py-2 text-xs font-semibold rounded border border-violet-500/40 bg-violet-500/10 text-violet-300 hover:bg-violet-500/20 transition disabled:opacity-40">
                      {fleetProbing ? '⟳ Testing connection…' : '⚡ Test Connection & Auto-discover'}
                    </button>

                    {/* Probe result */}
                    {fleetProbeResult && (
                      <div className={`p-3 rounded text-xs border ${fleetProbeResult.success ? 'bg-emerald-500/10 border-emerald-500/30' : 'bg-red-500/10 border-red-500/30'}`}>
                        {fleetProbeResult.success ? (
                          <div className="space-y-1">
                            <div className="text-emerald-300 font-semibold">✓ Connection successful</div>
                            {fleetProbeResult.identity && <div className="text-slate-400 font-mono">{fleetProbeResult.identity.slice(0,10)}…{fleetProbeResult.identity.slice(-6)}</div>}
                            <div className="flex gap-3 text-slate-400">
                              {fleetProbeResult.version && <span>v{fleetProbeResult.version}</span>}
                              {fleetProbeResult.ip && <span>{fleetProbeResult.ip}</span>}
                              {fleetProbeResult.nat && <span>NAT: {fleetProbeResult.nat}</span>}
                            </div>
                          </div>
                        ) : (
                          <div className="text-red-300">✗ {fleetProbeResult.error}</div>
                        )}
                      </div>
                    )}

                    {/* Label */}
                    <div>
                      <label className="block text-xs text-slate-400 mb-1">Label</label>
                      <input
                        value={fleetForm.label}
                        onChange={e => setFleetForm(f => ({ ...f, label: e.target.value }))}
                        placeholder="My VPS Node"
                        className="w-full bg-slate-800 border border-slate-600 focus:border-violet-400 rounded px-3 py-2 text-xs text-slate-200 outline-none transition"
                      />
                      <p className="text-xs text-slate-600 mt-1">Display name in the fleet overview (auto-filled after test)</p>
                    </div>

                    {fleetSaveError && <div className="text-xs text-red-400">✗ {fleetSaveError}</div>}
                  </div>

                  {/* Modal footer */}
                  <div className="flex items-center justify-between px-5 py-4 border-t border-slate-800">
                    <div className="flex items-center gap-2">
                      <button onClick={() => setFleetModalOpen(false)}
                        className="px-4 py-2 text-xs rounded border border-slate-700 text-slate-400 hover:text-white hover:border-slate-500 transition">
                        Cancel
                      </button>
                      {fleetEditNode && (
                        <button onClick={() => { setFleetModalOpen(false); handleFleetRemove(fleetEditNode); }}
                          className="px-4 py-2 text-xs rounded border border-red-500/40 bg-red-500/10 text-red-400 hover:bg-red-500/20 transition"
                          title="Remove this node from fleet">
                          ✕ Delete Node
                        </button>
                      )}
                    </div>
                    <button onClick={handleFleetSave} disabled={fleetSaving || !fleetForm.toolkit_url || !fleetForm.toolkit_api_key}
                      className="px-4 py-2 text-xs font-semibold rounded border border-violet-500/40 bg-violet-500/20 text-violet-200 hover:bg-violet-500/30 transition disabled:opacity-40">
                      {fleetSaving ? '⟳ Saving…' : fleetEditNode ? '✓ Save Changes' : '⊕ Add to Fleet'}
                    </button>
                  </div>
                </div>
              </div>
            )}
          </>
        );
      };

      return (
        <div data-theme={theme} className="min-h-screen bg-gradient-to-br from-slate-950 via-slate-900 to-slate-800 text-white font-['SF_Mono',monospace]">
          {theme !== 'emerald' && <style>{generateThemeCSS(theme)}</style>}
          <div className="max-w-4xl mx-auto px-4 py-10">
            {/* Header */}
            <div className="flex items-center justify-between mb-8">
              <div className="flex items-center gap-3">
                <div className="p-2 bg-violet-500/10 rounded-lg border border-violet-500/20">
                  <span className="text-violet-400 text-lg">⬡</span>
                </div>
                <div>
                  <h1 className="text-lg font-bold tracking-tight">Mysterium Fleet</h1>
                  <p className="text-xs text-slate-500">
                    v{toolkitVersion} — select a node to view its dashboard
                    {updateInfo?.update_available && (
                      <span className="ml-2 text-amber-400 border border-amber-500/40 bg-amber-500/10 rounded px-1.5 py-0.5" title={`v${updateInfo.latest} available — run: sudo ./update.sh`}>
                        ↑ v{updateInfo.latest} available
                      </span>
                    )}
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-3">
                <span className={`text-xs px-2 py-1 rounded-full font-medium ${
                  metrics.fleet.fleet_online === metrics.fleet.fleet_nodes
                    ? 'bg-emerald-500/20 text-emerald-300'
                    : 'bg-amber-500/20 text-amber-300'
                }`}>{metrics.fleet.fleet_online}/{metrics.fleet.fleet_nodes} online</span>
                <FleetNodeManager />
                <button onClick={() => {
                    try { localStorage.removeItem('myst-auth'); localStorage.removeItem('myst-backend-url'); } catch {}
                    setIsConnected(false);
                    setSetupMode('apikey_input');
                  }}
                  className="text-xs px-3 py-1.5 rounded border border-slate-700 bg-slate-800/60 text-slate-400 hover:text-white hover:border-slate-500 transition">
                  Logout
                </button>
              </div>
            </div>

            {/* Fleet aggregate bar */}
            <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-slate-500 mb-8 pb-4 border-b border-slate-800">
              <span>Unsettled: <span className="text-emerald-400 font-semibold">{(Number(metrics.fleet.fleet_earnings?.unsettled)||0).toFixed(4)} MYST</span></span>
              <span>Lifetime: <span className="text-slate-300">{(Number(metrics.fleet.fleet_earnings?.lifetime)||0).toFixed(4)} MYST</span></span>
              <span>Active sessions: <span className="text-slate-300">{Number(metrics.fleet.fleet_sessions?.active)||0}</span></span>
              <span>Nodes: <span className="text-slate-300">{metrics.fleet.fleet_nodes}</span></span>
            </div>

            {/* Node cards grid */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              {fleetNodes.map(n => {
                const isOn = n.status === 'online';
                const shortW = n.wallet ? `${n.wallet.slice(0,6)}…${n.wallet.slice(-4)}` : '';
                return (
                  <button key={n.id}
                    onClick={() => {
                      setSelectedNodeId(n.id);
                      selectedNodeRef.current = n.id;
                      setTimeout(fetchMetrics, 50);
                    }}
                    className={`text-left p-4 rounded-xl border transition-all duration-200 hover:scale-[1.01] ${
                      isOn
                        ? 'bg-slate-800/50 border-slate-700 hover:border-violet-500/50 hover:bg-violet-500/5'
                        : 'bg-slate-900/50 border-red-500/20 hover:border-red-400/30 opacity-80'
                    }`}
                  >
                    <div className="flex items-center justify-between mb-3">
                      <div className="flex items-center gap-2">
                        <span className={`text-sm ${isOn ? 'text-emerald-400' : 'text-red-400'}`}>{isOn ? '●' : '○'}</span>
                        <span className="font-semibold text-sm text-white">{n.label || n.id}</span>
                      </div>
                      <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium ${
                        isOn ? 'bg-emerald-500/20 text-emerald-300' : 'bg-red-500/20 text-red-300'
                      }`}>{isOn ? 'Online' : 'Offline'}</span>
                    </div>
                    <div className="space-y-1.5 text-xs">
                      {shortW && <div className="font-mono text-cyan-400/80">{shortW}</div>}
                      <div className="flex gap-3 text-slate-500">
                        {n.version && <span>v{n.version}</span>}
                        {nodeUpdateInfo?.update_available && n.version === nodeUpdateInfo.current && <div className="mt-0.5"><span className="text-amber-400 border border-amber-500/40 bg-amber-500/10 rounded px-1 text-[9px]" title={`Node v${nodeUpdateInfo.latest} available`}>↑ {nodeUpdateInfo.latest}</span></div>}
                        {n.uptime && <span>up {formatUptime(n.uptime)}</span>}
                        {n.nat && <span>NAT: {n.nat}</span>}
                      </div>
                      <div className="flex gap-3">
                        <span className="text-emerald-300 font-semibold">{(Number(n.earnings?.unsettled)||0).toFixed(4)} MYST</span>
                        {n.sessions?.active > 0 && <span className="text-slate-400">{n.sessions.active} sessions</span>}
                      </div>
                      {n.error && <div className="text-red-400/80 text-[10px]">⚠ {n.error}</div>}
                    </div>
                    <div className="mt-3 pt-2 border-t border-slate-700/50 text-[10px] text-slate-600 flex items-center justify-between">
                      <span>{n.peer_mode ? 'Peer mode (full data)' : 'TequilAPI mode (live only)'}</span>
                      <div className="flex items-center gap-2">
                        <button onClick={(e) => { e.stopPropagation(); document.querySelector(`[data-edit-node="${n.id}"]`)?.click(); }}
                          className="text-slate-600 hover:text-violet-400 transition px-1" title="Edit node">✎</button>
                        <button onClick={(e) => { e.stopPropagation(); handleFleetRemove(n); }}
                          className="text-slate-600 hover:text-red-400 transition px-1" title="Remove node from fleet">⊗</button>
                        <span className="text-violet-400">View dashboard →</span>
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>

            {/* Footer */}
            <div className="mt-12 mb-6 text-center">
              <div className="inline-flex flex-col items-center gap-2 px-8 py-4 rounded-xl bg-slate-900/20 border border-slate-800/50 backdrop-blur">
                <div className="flex items-center gap-2 text-xs text-slate-500">
                  <span className="text-slate-600">⟨</span>
                  <span>Crafted with</span>
                  <span className="text-rose-400 animate-pulse text-sm">♥</span>
                  <span>by</span>
                  <span className="font-semibold text-emerald-400/80">Ian Johnsons</span>
                  <span className="text-slate-600">⟩</span>
                </div>
                <div className="text-xs text-slate-600 tracking-wider">
                  Mysterium Node Toolkit v{toolkitVersion} — Free &amp; Open Source (CC BY-NC-SA 4.0)
                </div>
              </div>
            </div>
          </div>
        </div>
      );
    }

    return (
      <div data-theme={theme} className="min-h-screen bg-gradient-to-br from-slate-950 via-slate-900 to-slate-800 text-white font-['SF_Mono',monospace] overflow-x-hidden">
        {/* ── Degraded-state health toast ── */}
        {healthToast && (
          <div className={`fixed top-3 left-1/2 -translate-x-1/2 z-[100] flex items-center gap-3 px-4 py-2.5 rounded-lg border shadow-xl text-xs font-semibold backdrop-blur cursor-pointer transition-all
            ${healthToast.level === 'critical' ? 'bg-red-950/90 border-red-500/50 text-red-200' : 'bg-amber-950/90 border-amber-500/50 text-amber-200'}`}
            onClick={() => { setActivePanel('health'); setHealthToast(null); }}
          >
            <span>{healthToast.level === 'critical' ? '✗' : '▲'}</span>
            <span>{healthToast.msg}</span>
            <span className="text-slate-400 ml-1">→ click to open</span>
            <button onClick={(e) => { e.stopPropagation(); setHealthToast(null); }}
              className="ml-2 text-slate-400 hover:text-white">✕</button>
          </div>
        )}
        {theme !== 'emerald' && <style>{generateThemeCSS(theme)}</style>}
        <div className="fixed inset-0 opacity-5 pointer-events-none">
          <div style={{
            backgroundImage: 'linear-gradient(90deg, #fff 1px, transparent 1px), linear-gradient(#fff 1px, transparent 1px)',
            backgroundSize: '50px 50px'
          }}></div>
        </div>

        <div className="sticky top-0 z-20 backdrop-blur bg-black/40 border-b border-slate-700/50 px-3 sm:px-6 py-3 sm:py-4">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
            <div className="flex items-center gap-3">
              <div className="p-2 bg-emerald-500/10 rounded">
                <Zap className="w-5 h-5 text-emerald-400" />
              </div>
              <div>
                <h1 className="text-lg font-bold tracking-tight">Mysterium Node <span className="text-xs font-normal text-slate-500">v{toolkitVersion}</span>
                  {updateInfo?.update_available && (
                    <span className="ml-2 text-xs font-normal text-amber-400 border border-amber-500/40 bg-amber-500/10 rounded px-1.5 py-0.5" title={`v${updateInfo.latest} available — run: sudo ./update.sh`}>
                      ↑ v{updateInfo.latest}
                    </span>
                  )}
                </h1>
                <div className="flex gap-2 items-center text-xs">
                  <p className="text-slate-400">Status:</p>
                  <div className={`w-2 h-2 rounded-full ${metrics.nodeConnected ? 'bg-emerald-400 animate-pulse' : 'bg-red-400'}`}></div>
                  <p className={metrics.nodeConnected ? 'text-emerald-400' : 'text-red-400'}>
                    {metrics.nodeConnected ? 'Connected' : 'Offline'}
                  </p>
                </div>
              </div>
            </div>

            <div className="flex items-center gap-3 ml-auto sm:ml-0">
              <div className="text-right text-xs">
                <div className="text-slate-400">Last Update</div>
                <div className="text-sm font-semibold">{lastUpdate?.toLocaleTimeString() || '—'}</div>
              </div>
              <button
                onClick={handleDisconnect}
                className="px-3 py-1.5 text-xs border border-slate-600 rounded hover:bg-slate-800 transition"
              >
                Logout Dashboard
              </button>
            </div>
          </div>
        </div>

        <div className="relative z-10 p-3 sm:p-6 max-w-7xl mx-auto">

          {/* ======= BACK BUTTON — always shown when viewing a fleet node ======= */}
          {metrics._fleet_node && (
            <div className="mb-3 flex items-center gap-3">
              <button
                onClick={() => { setSelectedNodeId(null); selectedNodeRef.current = null; setTimeout(fetchMetrics, 50); }}
                className="text-xs px-3 py-1.5 rounded border border-violet-500/40 bg-violet-500/10 text-violet-300 hover:text-violet-100 hover:border-violet-400 transition font-medium"
              >← Fleet Overview</button>
              <span className="text-xs text-violet-400">Viewing: <span className="text-violet-200 font-semibold">{metrics._node_label}</span></span>
            </div>
          )}

          {/* ======= NODE SELECTOR (fleet mode) ======= */}
          {metrics.fleet?.fleet_mode && (
            <div className="mb-5">
              <div className="flex items-center justify-between mb-2.5">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-semibold text-violet-300 tracking-wide">⬡ Fleet</span>
                  <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                    metrics.fleet.fleet_online === metrics.fleet.fleet_nodes
                      ? 'bg-emerald-500/20 text-emerald-300'
                      : 'bg-amber-500/20 text-amber-300'
                  }`}>{metrics.fleet.fleet_online}/{metrics.fleet.fleet_nodes} online</span>
                </div>
                {metrics._fleet_node && (
                  <button
                    onClick={() => { setSelectedNodeId(null); selectedNodeRef.current = null; setTimeout(fetchMetrics, 50); }}
                    className="text-xs px-3 py-1 rounded border border-slate-600 bg-slate-800/60 text-slate-400 hover:text-slate-200 hover:border-slate-500 transition"
                  >← Overview</button>
                )}
              </div>

              {/* Node cards — click to view that node's full dashboard */}
              <div className="flex gap-2 flex-wrap">
                {metrics.fleet.nodes?.map((n) => {
                  const isOn  = n.status === 'online';
                  const isSel = selectedNodeId === n.id;
                  const shortW = n.wallet ? `${n.wallet.slice(0,6)}…${n.wallet.slice(-4)}` : '';
                  return (
                    <button key={n.id}
                      onClick={() => {
                        const next = isSel ? null : n.id;
                        setSelectedNodeId(next);
                        selectedNodeRef.current = next;
                        setTimeout(fetchMetrics, 50);
                      }}
                      className={`text-left px-3 py-2.5 rounded-lg border transition flex-1 min-w-[150px] max-w-[240px] ${
                        isSel
                          ? 'bg-violet-500/20 border-violet-500/50 ring-1 ring-violet-500/30'
                          : isOn
                          ? 'bg-slate-800/40 border-slate-700 hover:border-violet-500/40 hover:bg-violet-500/5'
                          : 'bg-slate-900/40 border-red-500/20 hover:border-red-400/30 opacity-75'
                      }`}
                    >
                      <div className="flex items-center gap-1.5 mb-1.5">
                        <span className={`text-[10px] font-bold ${isOn ? 'text-emerald-400' : 'text-red-400'}`}>
                          {isOn ? '●' : '○'}
                        </span>
                        <span className="text-xs font-semibold text-violet-100 truncate">{n.label || n.id}</span>
                        {isSel && <span className="text-[9px] text-violet-400 ml-auto shrink-0">viewing</span>}
                      </div>
                      <div className="text-[10px] space-y-0.5">
                        {shortW && <div className="font-mono text-cyan-400/80">{shortW}</div>}
                        <div className="flex gap-2 text-slate-500">
                          {n.version && <span>v{n.version}</span>}
                          {nodeUpdateInfo?.update_available && n.version === nodeUpdateInfo.current && <div className="mt-0.5"><span className="text-amber-400 border border-amber-500/40 bg-amber-500/10 rounded px-1 text-[9px]" title={`Node v${nodeUpdateInfo.latest} available`}>↑ {nodeUpdateInfo.latest}</span></div>}
                          {n.uptime  && <span>{formatUptime(n.uptime)}</span>}
                        </div>
                        <div className="flex gap-2 flex-wrap">
                          <span className="text-emerald-300/80 font-medium">{(Number(n.earnings?.unsettled) || 0).toFixed(4)} MYST</span>
                          {(n.sessions?.active > 0) && <span className="text-slate-400">{n.sessions.active}s</span>}
                        </div>
                        {n.error && <div className="text-red-400/80 truncate">⚠ {n.error}</div>}
                      </div>
                    </button>
                  );
                })}
              </div>

              {/* Fleet aggregate — only when no node selected */}
              {!metrics._fleet_node && (
                <div className="mt-2 flex flex-wrap gap-x-4 gap-y-0.5 text-xs text-slate-600">
                  <span>Fleet unsettled: <span className="text-emerald-400/80">{(Number(metrics.fleet.fleet_earnings?.unsettled)||0).toFixed(4)} MYST</span></span>
                  <span>Lifetime: <span className="text-slate-500">{(Number(metrics.fleet.fleet_earnings?.lifetime)||0).toFixed(4)} MYST</span></span>
                  <span>Active sessions: <span className="text-slate-500">{Number(metrics.fleet.fleet_sessions?.active)||0}</span></span>
                  <span className="text-slate-600 italic">Click a node to view its full dashboard</span>
                </div>
              )}

              {/* Viewing banner */}
              {metrics._fleet_node && (
                <div className="mt-2 flex items-center gap-2 text-xs">
                  <span className="text-violet-400">Viewing:</span>
                  <span className="text-violet-200 font-semibold">{metrics._node_label}</span>
                  <span className="text-slate-600">— full dashboard</span>
                </div>
              )}
            </div>
          )}

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
            <StatusCard nodeStatus={metrics.nodeStatus} resources={metrics.resources} earnings={metrics.earnings} clients={metrics.clients} activeSessions={metrics.sessions?.active_unique_consumers ?? metrics.sessions?.active ?? 0} backendUrl={getNodeAwareUrl()} authHeaders={authHeaderRef.current} fleetNode={metrics._fleet_node} nodeUpdateInfo={nodeUpdateInfo} />
            <EarningsCard earnings={metrics.earnings} backendUrl={getNodeAwareUrl()} authHeaders={authHeaderRef.current} />
          </div>

          {/* Settlement History — on-chain wallet balance + Polygonscan transactions */}
          <SettlementHistoryCard backendUrl={getNodeAwareUrl()} authHeaders={authHeaderRef.current} />

          {/* Node Quality — sourced from Mysterium Discovery API */}
          <NodeQualityCard nodeQuality={metrics.nodeQuality} nodeStatus={metrics.nodeStatus} backendUrl={getNodeAwareUrl()} authHeaders={authHeaderRef.current} nodeUrl={metrics._fleet_node && metrics._node_id ? null : (metrics._node_toolkit_url || null)} />

          {/* Earnings History — daily/weekly/monthly/all bar chart */}
          <EarningsHistoryCard backendUrl={getNodeAwareUrl()} authHeaders={authHeaderRef.current} />

          {/* Data Traffic — VPN, NIC total, overhead, per tunnel */}
          <DataTrafficCard bandwidth={metrics.bandwidth} backendUrl={getNodeAwareUrl()} authHeaders={authHeaderRef.current} />

          {/* Analytics — lifetime totals, service breakdown, consumer origin */}
          <AnalyticsCard sessions={metrics.sessions} backendUrl={getNodeAwareUrl()} authHeaders={authHeaderRef.current} />

          {/* Bandwidth — VPN tunnel traffic */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
            {/* Card 1: VPN Traffic Today */}
            <div className="p-5 bg-slate-800/30 border border-slate-700 rounded-lg backdrop-blur">
              <div className="flex items-center gap-2 mb-3">
                <div className="p-2 rounded bg-emerald-500/10 text-emerald-400"><Wifi className="w-4 h-4" /></div>
                <h3 className="text-xs font-semibold text-slate-300 tracking-wide">VPN Traffic Today</h3>
                <span className="ml-auto text-xs px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
                  {(metrics.bandwidth.data_source || 'vnstat').toUpperCase()}
                </span>
              </div>
              <div className="text-3xl font-bold text-emerald-400 mb-1">{formatDataSize(safeNum(metrics.bandwidth.vpn_today_total))}</div>
              <div className="flex gap-4 text-xs text-slate-400">
                <span>↑ Out to consumers: <span className="text-emerald-300 font-semibold">{formatDataSize(safeNum(metrics.bandwidth.vpn_today_out))}</span></span>
                <span>↓ In from consumers: <span className="text-emerald-300 font-semibold">{formatDataSize(safeNum(metrics.bandwidth.vpn_today_in))}</span></span>
              </div>
              {/* Per-interface breakdown — both directions */}
              {metrics.bandwidth.vpn_interfaces && Object.keys(metrics.bandwidth.vpn_interfaces).length > 0 && (
                <div className="mt-2 pt-2 border-t border-slate-700/50 flex flex-wrap gap-3 text-xs text-slate-500 max-h-24 overflow-y-auto">
                  {Object.entries(metrics.bandwidth.vpn_interfaces).map(([name, data]) => (
                    <span key={name} className="text-emerald-400/60">
                      {name}: {formatDataSize(safeNum(data.rx_mb) + safeNum(data.tx_mb))} (↑{formatDataSize(safeNum(data.tx_mb))} out · ↓{formatDataSize(safeNum(data.rx_mb))} in)
                    </span>
                  ))}
                </div>
              )}
              {/* Network total from vnstat as reference */}
              {metrics.bandwidth.vnstat_available && (
                <div className="mt-2 pt-2 border-t border-slate-700/50 text-xs text-slate-500">
                  Network ({metrics.bandwidth.vnstat_nic_name || 'NIC'}): {formatDataSize(safeNum(metrics.bandwidth.vnstat_today_total))}
                  <span className="ml-1 text-slate-600">(includes tunnel overhead — each VPN byte crosses NIC twice)</span>
                </div>
              )}
            </div>

            {/* Card 2: VPN Traffic This Month */}
            <div className="p-5 bg-slate-800/30 border border-slate-700 rounded-lg backdrop-blur">
              <div className="flex items-center gap-2 mb-3">
                <div className="p-2 rounded bg-sky-500/10 text-sky-400"><Wifi className="w-4 h-4" /></div>
                <h3 className="text-xs font-semibold text-slate-300 tracking-wide">VPN Traffic This Month</h3>
                <span className="ml-auto text-xs px-2 py-0.5 rounded bg-sky-500/20 text-sky-300 border border-sky-500/30">
                  {(metrics.bandwidth.data_source || 'vnstat').toUpperCase()}
                </span>
              </div>
              <div className="text-3xl font-bold text-sky-400 mb-1">
                {formatDataSize(safeNum(metrics.bandwidth.vpn_month_total))}
              </div>
              <div className="flex gap-4 text-xs text-slate-400">
                <span>↑ Out to consumers: <span className="text-sky-300 font-semibold">{formatDataSize(safeNum(metrics.bandwidth.vpn_month_out))}</span></span>
                <span>↓ In from consumers: <span className="text-slate-300 font-semibold">{formatDataSize(safeNum(metrics.bandwidth.vpn_month_in))}</span></span>
              </div>
              {/* Network total from vnstat as reference */}
              {metrics.bandwidth.vnstat_available && (
                <div className="mt-2 pt-2 border-t border-slate-700/50 text-xs text-slate-500">
                  Network ({metrics.bandwidth.vnstat_nic_name || 'NIC'}): {formatDataSize(safeNum(metrics.bandwidth.vnstat_month_total))}
                  <span className="ml-1 text-slate-600">(includes tunnel overhead)</span>
                </div>
              )}
            </div>
          </div>

          {/* Metric cards row */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
            {/* Clickable Services card */}
            <button
              onClick={() => setActivePanel(activePanel === 'services' ? null : 'services')}
              className={`text-left p-4 bg-slate-800/30 border rounded-lg backdrop-blur transition hover:border-emerald-500/50 ${
                activePanel === 'services' ? 'border-emerald-500/50 ring-1 ring-emerald-500/20' : 'border-slate-700'
              }`}
            >
              <div className="inline-block p-2 rounded mb-3 text-emerald-400 bg-emerald-500/10 border border-emerald-500/30">
                <Shield className="w-4 h-4" />
              </div>
              <h3 className="text-xs font-semibold text-slate-300 tracking-wide mb-2">Running Services</h3>
              <div className="text-2xl font-bold mb-1">{safeNum(metrics.services.active)}</div>
              <div className="text-xs text-slate-400">Click to view</div>
            </button>

            {/* Clickable Sessions card */}
            <button
              onClick={() => setActivePanel(activePanel === 'sessions' ? null : 'sessions')}
              className={`text-left p-4 bg-slate-800/30 border rounded-lg backdrop-blur transition hover:border-emerald-500/50 ${
                activePanel === 'sessions' ? 'border-emerald-500/50 ring-1 ring-emerald-500/20' : 'border-slate-700'
              }`}
            >
              <div className="inline-block p-2 rounded mb-3 text-emerald-400 bg-emerald-500/10 border border-emerald-500/30">
                <Activity className="w-4 h-4" />
              </div>
              <h3 className="text-xs font-semibold text-slate-300 tracking-wide mb-2">Tunnels & Sessions</h3>
              <div className="flex items-center gap-2">
                <div className="text-2xl font-bold mb-1">{safeNum(metrics.sessions?.vpn_tunnel_count || 0)}</div>
                {safeNum(metrics.sessions?.vpn_tunnel_count || 0) > 0 && (
                  <div className="w-2.5 h-2.5 rounded-full bg-emerald-400 animate-pulse mb-1" />
                )}
              </div>
              <div className="text-xs text-slate-400">
                {(() => {
                  const tunnels  = safeNum(metrics.sessions?.vpn_tunnel_count || 0);
                  const sessions = safeNum(metrics.sessions?.active || 0);
                  const clients  = safeNum(metrics.sessions?.active_unique_consumers || 0);
                  const parts = [`${tunnels} tunnel${tunnels !== 1 ? 's' : ''}`];
                  if (sessions > 0) parts.push(`${sessions} session${sessions !== 1 ? 's' : ''}`);
                  if (clients > 0) parts.push(`${clients} client${clients !== 1 ? 's' : ''}`);
                  return parts.join(' · ') + ' · Click to view';
                })()}
              </div>
            </button>

            <MetricCard
              icon={<Activity className="w-4 h-4" />}
              title="Node Speed"
              value={formatSpeed(metrics.performance.speed_total)}
              subtitle={metrics.performance.idle
                ? `Idle · ${Math.max(safeNum(metrics.live_connections?.active || 0), Object.keys(metrics.bandwidth.vpn_interfaces || {}).length)} tunnels`
                : `↑ Out ${formatSpeedShort(metrics.performance.speed_out)} · ↓ In ${formatSpeedShort(metrics.performance.speed_in)}`}
              color="emerald"
            />
            {/* System NIC speed card — custom two-line layout */}
            <div className="p-4 bg-slate-800/30 border border-emerald-500/10 rounded-lg backdrop-blur">
              <div className="inline-block p-2 rounded mb-3 text-emerald-400 bg-emerald-500/10 border-emerald-500/30">
                <Zap className="w-4 h-4" />
              </div>
              <h3 className="text-xs font-semibold text-slate-300 tracking-wide mb-2">
                System ({metrics.performance.sys_nic || 'NIC'})
              </h3>
              <div className="text-2xl font-bold mb-1">
                {formatSpeed(metrics.performance.sys_speed_total)}
              </div>
              <div className="text-xs text-slate-400 mb-1">
                ↑ {formatSpeedShort(metrics.performance.sys_speed_out)} · ↓ {formatSpeedShort(metrics.performance.sys_speed_in)}
              </div>
              <div className="text-xs text-slate-400 flex items-center gap-3">
                <span>{safeNum(metrics.performance.latency)}ms</span>
                {metrics.performance.packet_loss > 0 && (
                  <span className="text-amber-400">Loss {safeNum(metrics.performance.packet_loss)}%</span>
                )}
              </div>
              {metrics.performance.packet_loss === 0 && (
                <div className="text-xs text-emerald-500/60">Loss 0%</div>
              )}
            </div>
          </div>

          {/* Expandable Services Panel */}
          {activePanel === 'services' && (
            <>
            <div className="fixed inset-0 z-40 bg-black/60 sm:hidden" onClick={() => setActivePanel(null)} />
            <div style={{ backgroundColor: panelBg }} className="fixed inset-0 z-50 overflow-y-auto p-4 pt-6
                            sm:static sm:bg-slate-800/30 sm:p-5 sm:mb-6 sm:rounded-lg sm:border sm:border-cyan-500/30 sm:backdrop-blur sm:max-h-[85vh] sm:overflow-y-auto">
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-2">
                  <Shield className="w-4 h-4 text-emerald-400" />
                  <h3 className="text-sm font-semibold tracking-wide">Running Services</h3>
                  <span className="text-xs text-slate-400 ml-2">{safeNum(metrics.services.active)} active</span>
                </div>
                <button onClick={() => setActivePanel(null)} className="p-2 bg-slate-800 hover:bg-slate-700 rounded transition text-slate-300 text-sm font-semibold">✕ Close</button>
              </div>

              {(() => {
                // Static list of user-controllable service types — always shown
                const TOGGLEABLE_TYPES = [
                  { type: 'dvpn',          label: 'VPN' },
                  { type: 'wireguard',     label: 'Public' },
                  { type: 'scraping',      label: 'B2B Data Scraping' },
                  { type: 'data_transfer', label: 'B2B VPN and data transfer' },
                  { type: 'quic_scraping', label: 'QUIC Scraping' },
                ];
                // Internal node-managed services — shown read-only below
                const INTERNAL_TYPES = ['noop', 'monitoring'];
                const INTERNAL_LABELS = {
                  noop:       'Noop',
                  monitoring: 'Monitoring',
                };

                const liveItems = metrics.services.items || [];
                // Build a map of type → live service entry for status lookup
                const liveByType = {};
                liveItems.forEach(s => {
                  if (!liveByType[s.type]) liveByType[s.type] = s;
                });

                // For each toggleable type, build a merged entry:
                // - if API returned it: use that (has id, status, is_active)
                // - if not: synthesise a stopped entry so it stays visible
                const toggleRows = TOGGLEABLE_TYPES.map(({ type, label }) => {
                  const live = liveByType[type];
                  return live
                    ? { ...live, type, label }
                    : { id: null, type, label, status: 'stopped', is_active: false };
                });

                // Internal services: only show those the API reported
                const internalRows = liveItems.filter(s => INTERNAL_TYPES.includes(s.type));

                return (
                  <div className="space-y-2">
                    {/* User-controllable services — static list */}
                    {toggleRows.map((svc, i) => (
                      <ServiceToggleRow key={svc.id || svc.type} svc={svc}
                        backendUrl={backendUrlRef.current} authHeaders={authHeaderRef.current} />
                    ))}
                    {/* Divider */}
                    {internalRows.length > 0 && (
                      <div className="pt-2 mt-2 border-t border-slate-700/30">
                        <div className="text-[10px] text-slate-600 uppercase tracking-wide mb-2 px-1">Node-managed (internal)</div>
                        {internalRows.map((svc, i) => (
                          <div key={svc.id || i} className="flex items-center gap-3 text-xs px-4 py-2 rounded border bg-slate-900/20 border-slate-700/20 mb-1">
                            <div className="w-2 h-2 rounded-full bg-slate-600" />
                            <span className="flex-1 text-slate-500">{INTERNAL_LABELS[svc.type] || svc.type}</span>
                            <span className="text-slate-600 text-[10px]">{svc.status}</span>
                          </div>
                        ))}
                      </div>
                    )}
                    {toggleRows.length === 0 && internalRows.length === 0 && (
                      <div className="text-xs text-slate-500 py-8 text-center">No services detected</div>
                    )}
                  </div>
                );
              })()}
            </div>
            </>
          )}

          {/* Expandable Sessions Panel — Tunnels / Active Sessions / History tabs */}
          {activePanel === 'sessions' && (
            <>
            <div className="fixed inset-0 z-40 bg-black/60 sm:hidden" onClick={() => setActivePanel(null)} />
            <div style={{ backgroundColor: panelBg }} className="fixed inset-0 z-50 overflow-y-auto p-4 pt-6
                            sm:static sm:bg-slate-800/30 sm:p-5 sm:mb-6 sm:rounded-lg sm:border sm:border-emerald-500/30 sm:backdrop-blur sm:max-h-[85vh] sm:overflow-y-auto">
              <div className="flex flex-col gap-3 mb-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Activity className="w-4 h-4 text-emerald-400" />
                    <h3 className="text-sm font-semibold tracking-wide">Connections</h3>
                  </div>
                  <button onClick={() => setActivePanel(null)} className="p-2 bg-slate-800 hover:bg-slate-700 rounded transition text-slate-300 text-sm font-semibold">✕ Close</button>
                </div>
                {/* Tab switcher — wraps on mobile */}
                <div className="flex flex-wrap gap-1.5">
                  <button
                    onClick={() => setSessionTab('live')}
                    className={`px-3 py-1.5 text-xs rounded-md transition font-medium ${
                      sessionTab === 'live'
                        ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                        : 'bg-slate-800/60 text-slate-400 border border-slate-700 hover:text-slate-200'
                    }`}
                  >
                    ● Tunnels ({safeNum(metrics.live_connections?.active || 0)})
                  </button>
                  <button
                    onClick={() => setSessionTab('active_sessions')}
                    className={`px-3 py-1.5 text-xs rounded-md transition font-medium ${
                      sessionTab === 'active_sessions'
                        ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                        : 'bg-slate-800/60 text-slate-400 border border-slate-700 hover:text-slate-200'
                    }`}
                  >
                    ◉ Active ({Math.max(safeNum(metrics.sessions?.items?.filter(s => s.is_active)?.length || 0), safeNum(metrics.sessions?.vpn_tunnel_count || 0))})
                  </button>
                  <button
                    onClick={() => setSessionTab('history')}
                    className={`px-3 py-1.5 text-xs rounded-md transition font-medium ${
                      sessionTab === 'history'
                        ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                        : 'bg-slate-800/60 text-slate-400 border border-slate-700 hover:text-slate-200'
                    }`}
                  >
                    History ({safeNum(metrics.sessions?.total || 0)}{metrics.sessions?.history_loaded === false ? ' ⟳' : ''})
                  </button>
                  <button
                    onClick={() => setSessionTab('consumers')}
                    className={`px-3 py-1.5 text-xs rounded-md transition font-medium ${
                      sessionTab === 'consumers'
                        ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                        : 'bg-slate-800/60 text-slate-400 border border-slate-700 hover:text-slate-200'
                    }`}
                  >
                    Consumers ({safeNum(metrics.sessions?.unique_consumers || 0)})
                  </button>
                </div>
              </div>

              {/* ======= TUNNELS TAB (myst* interfaces) ======= */}
              {sessionTab === 'live' && (
                <>
                  {(() => {
                    let peers = metrics.live_connections?.peers || [];
                    if (peers.length === 0 && metrics.bandwidth.vpn_interfaces && Object.keys(metrics.bandwidth.vpn_interfaces).length > 0) {
                      peers = Object.entries(metrics.bandwidth.vpn_interfaces).map(([name, data]) => ({
                        interface: name,
                        is_active: (safeNum(data.rx_mb) + safeNum(data.tx_mb)) > 0,
                        has_speed: false,
                        download_mb: safeNum(data.tx_mb),
                        upload_mb: safeNum(data.rx_mb),
                        total_mb: safeNum(data.rx_mb) + safeNum(data.tx_mb),
                        speed_down: 0, speed_up: 0, speed_total: 0,
                        duration: '—',
                      }));
                    }
                    const dotColor = (p) => p.has_speed ? 'bg-emerald-400 animate-pulse' : p.is_active ? 'bg-cyan-400' : 'bg-slate-600';
                    const rowBg = (p) => p.has_speed ? 'bg-emerald-500/5 border-emerald-500/20' : p.is_active ? 'bg-emerald-500/5 border-emerald-500/20' : 'bg-slate-900/30 border-slate-700/30 opacity-50';
                    return peers.length > 0 ? (
                      <>
                        {/* Mobile stacked view */}
                        <div className="sm:hidden space-y-2">
                          <MobileSortBar state={tunnelSort} setState={setTunnelSort} keys={[
                            { key: 'total_mb',    label: 'Total' },
                            { key: 'download_mb', label: '↑Out' },
                            { key: 'upload_mb',   label: '↓In' },
                            { key: 'speed_total', label: 'Speed' },
                            { key: 'duration',    label: 'Uptime' },
                          ]} />
                          {sortRows(peers, tunnelSort).map((peer, i) => (
                            <div key={peer.interface || i} className={`p-3 rounded border ${rowBg(peer)}`}>
                              <div className="flex items-center justify-between mb-1">
                                <div className="flex items-center gap-2">
                                  <div className={`w-2.5 h-2.5 rounded-full flex-shrink-0 ${dotColor(peer)}`} />
                                  <span className="text-cyan-400 font-mono text-sm font-semibold">{peer.interface}</span>
                                </div>
                                <span className="text-slate-300 text-xs">{peer.duration}</span>
                              </div>
                              <div className="flex flex-wrap items-center gap-x-4 gap-y-0.5 text-xs text-slate-400 mt-1">
                                <span>↑ <span className="text-emerald-300">{formatDataSize(peer.download_mb)}</span></span>
                                <span>↓ <span className="text-slate-300">{formatDataSize(peer.upload_mb)}</span></span>
                                <span>Total <span className="text-emerald-400 font-semibold">{formatDataSize(peer.total_mb)}</span></span>
                                {peer.speed_total > 0.0001 && <span className="text-slate-200">{formatSpeedShort(peer.speed_total)}</span>}
                              </div>
                            </div>
                          ))}
                        </div>
                        {/* Desktop table view */}
                        <div className="hidden sm:block space-y-1.5">
                          <div className="grid grid-cols-12 gap-2 text-xs text-slate-500 font-semibold uppercase tracking-widest px-3 py-1">
                            <div className="col-span-1">Status</div>
                            <div className={`col-span-2 ${hdrCls(tunnelSort,'interface')}`} onClick={() => mkSort(setTunnelSort)('interface')}>Tunnel <span className="text-[10px]">{sortIcon(tunnelSort,'interface')}</span></div>
                            <div className={`col-span-2 ${hdrCls(tunnelSort,'duration')}`} onClick={() => mkSort(setTunnelSort)('duration')}>Uptime <span className="text-[10px]">{sortIcon(tunnelSort,'duration')}</span></div>
                            <div className={`col-span-2 ${hdrCls(tunnelSort,'download_mb')}`} onClick={() => mkSort(setTunnelSort)('download_mb')}>↑ Out <span className="text-[10px]">{sortIcon(tunnelSort,'download_mb')}</span></div>
                            <div className={`col-span-2 ${hdrCls(tunnelSort,'upload_mb')}`} onClick={() => mkSort(setTunnelSort)('upload_mb')}>↓ In <span className="text-[10px]">{sortIcon(tunnelSort,'upload_mb')}</span></div>
                            <div className={`col-span-2 ${hdrCls(tunnelSort,'total_mb')}`} onClick={() => mkSort(setTunnelSort)('total_mb')}>Total <span className="text-[10px]">{sortIcon(tunnelSort,'total_mb')}</span></div>
                            <div className={`col-span-1 ${hdrCls(tunnelSort,'speed_total')}`} onClick={() => mkSort(setTunnelSort)('speed_total')}>Speed <span className="text-[10px]">{sortIcon(tunnelSort,'speed_total')}</span></div>
                          </div>
                          {sortRows(peers, tunnelSort).map((peer, i) => (
                            <div key={peer.interface || i} className={`grid grid-cols-12 gap-2 text-xs px-3 py-2.5 rounded border transition ${rowBg(peer)}`}>
                              <div className="col-span-1 flex items-center">
                                <div className={`w-2.5 h-2.5 rounded-full ${dotColor(peer)}`} />
                              </div>
                              <div className="col-span-2 text-cyan-400 font-mono text-xs font-semibold">{peer.interface}</div>
                              <div className="col-span-2 text-slate-400">{peer.duration}</div>
                              <div className="col-span-2 text-emerald-300">{formatDataSize(peer.download_mb)}</div>
                              <div className="col-span-2 text-slate-300">{formatDataSize(peer.upload_mb)}</div>
                              <div className="col-span-2 font-semibold text-emerald-400">{formatDataSize(peer.total_mb)}</div>
                              <div className="col-span-1 text-slate-300">{peer.speed_total > 0.0001 ? formatSpeedShort(peer.speed_total) : '—'}</div>
                            </div>
                          ))}
                        </div>
                      </>
                    ) : (
                      <div className="text-xs text-slate-500 py-8 text-center">
                        {safeNum(metrics.clients?.connected || 0) > 0
                          ? `${safeNum(metrics.clients.connected)} service connections active but no VPN tunnel interfaces detected`
                          : 'No active tunnels — waiting for consumers to connect'}
                      </div>
                    );
                  })()}
                  {(metrics.live_connections?.peers?.length > 0 || (metrics.bandwidth.vpn_interfaces && Object.keys(metrics.bandwidth.vpn_interfaces).length > 0)) && (
                    <div className="mt-3 pt-3 border-t border-slate-700/30 flex items-center justify-between text-xs text-slate-500 flex-wrap gap-2">
                      <span>Tunnels: {metrics.live_connections.active} active ({metrics.live_connections.transferring || 0} transferring)</span>
                      <span>Service connections: {metrics.live_connections.svc_connections}</span>
                    </div>
                  )}
                </>
              )}

              {/* ======= ACTIVE SESSIONS TAB ======= */}
              {sessionTab === 'active_sessions' && (
                <>
                  {/* Live VPN traffic banner — bytes come from psutil on WireGuard interfaces,
                      NOT from TequilAPI (which only reports bytes at session close) */}
                  {(safeNum(metrics.sessions?.live_vpn_rx_mb || 0) + safeNum(metrics.sessions?.live_vpn_tx_mb || 0)) > 0 && (
                    <div className="mb-3 px-3 py-2 bg-cyan-500/5 border border-cyan-500/20 rounded text-xs text-slate-400 flex flex-wrap items-center gap-x-4 gap-y-1">
                      <span className="text-cyan-400 font-semibold">Live VPN traffic (since boot)</span>
                      <span>↑ Out: <span className="text-emerald-300 font-semibold">{formatDataSize(safeNum(metrics.sessions?.live_vpn_tx_mb || 0))}</span></span>
                      <span>↓ In: <span className="text-slate-300 font-semibold">{formatDataSize(safeNum(metrics.sessions?.live_vpn_rx_mb || 0))}</span></span>
                      <span className="text-slate-600 italic">Session bytes shown at close</span>
                    </div>
                  )}
                  {(() => {
                    const activeSessions = (metrics.sessions?.items || []).filter(s => s.is_active);
                    return activeSessions.length > 0 ? (
                      <>
                        {/* Mobile stacked view */}
                        <div className="sm:hidden space-y-2">
                          <MobileSortBar state={activeSort} setState={setActiveSort} keys={[
                            { key: 'earnings_myst',    label: 'Earned' },
                            { key: 'data_out',         label: '↑Out' },
                            { key: 'data_in',          label: '↓In' },
                            { key: 'duration',         label: 'Duration' },
                            { key: 'service_type',     label: 'Type' },
                            { key: 'consumer_country', label: 'Country' },
                          ]} />
                          {sortRows((metrics.sessions?.items || []).filter(s => s.is_active), activeSort).map((s, i) => (
                            <div key={s.id || i} className="p-3 bg-emerald-500/5 border border-emerald-500/20 rounded">
                              <div className="flex items-center justify-between mb-1">
                                <CopyableId id={s.consumer_id} />
                                <span className={`text-xs font-semibold ${s.earnings_myst > 0 ? 'text-emerald-400' : 'text-slate-500'}`}>
                                  {s.earnings_myst > 0 ? `${s.earnings_myst.toFixed(4)} MYST` : '—'}
                                </span>
                              </div>
                              <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-slate-400">
                                <span>{countryFlag(s.consumer_country) || '—'}</span>
                                <span className="text-slate-300">{s.service_type || '—'}</span>
                                <span>{s.duration}</span>
                                <span>↑{s.bytes_pending ? <span className="text-slate-600 italic">—</span> : formatDataSize(s.data_out)}</span>
                                <span>↓{s.bytes_pending ? <span className="text-slate-600 italic">—</span> : formatDataSize(s.data_in)}</span>
                              </div>
                            </div>
                          ))}
                        </div>
                        {/* Desktop table view */}
                        <div className="hidden sm:block space-y-2">
                          <div className="grid grid-cols-12 gap-2 text-xs text-slate-500 font-semibold uppercase tracking-widest px-3 py-1">
                            <div className="col-span-1">●</div>
                            <div className={`col-span-3 ${hdrCls(activeSort,'consumer_id')}`} onClick={() => mkSort(setActiveSort)('consumer_id')}>Consumer <span className="text-[10px]">{sortIcon(activeSort,'consumer_id')}</span></div>
                            <div className={`col-span-1 ${hdrCls(activeSort,'consumer_country')}`} onClick={() => mkSort(setActiveSort)('consumer_country')}>🌍 <span className="text-[10px]">{sortIcon(activeSort,'consumer_country')}</span></div>
                            <div className={`col-span-1 ${hdrCls(activeSort,'service_type')}`} onClick={() => mkSort(setActiveSort)('service_type')}>Type <span className="text-[10px]">{sortIcon(activeSort,'service_type')}</span></div>
                            <div className={`col-span-1 ${hdrCls(activeSort,'duration')}`} onClick={() => mkSort(setActiveSort)('duration')}>Dur <span className="text-[10px]">{sortIcon(activeSort,'duration')}</span></div>
                            <div className={`col-span-2 ${hdrCls(activeSort,'data_out')}`} onClick={() => mkSort(setActiveSort)('data_out')}>↑ Out <span className="text-[10px]">{sortIcon(activeSort,'data_out')}</span></div>
                            <div className={`col-span-1 ${hdrCls(activeSort,'data_in')}`} onClick={() => mkSort(setActiveSort)('data_in')}>↓ In <span className="text-[10px]">{sortIcon(activeSort,'data_in')}</span></div>
                            <div className={`col-span-2 ${hdrCls(activeSort,'earnings_myst')}`} onClick={() => mkSort(setActiveSort)('earnings_myst')}>Earned <span className="text-[10px]">{sortIcon(activeSort,'earnings_myst')}</span></div>
                          </div>
                          {sortRows((metrics.sessions?.items || []).filter(s => s.is_active), activeSort).map((s, i) => (
                            <div key={s.id || i} className="grid grid-cols-12 gap-2 text-xs px-3 py-2.5 rounded border bg-emerald-500/5 border-emerald-500/20">
                              <div className="col-span-1"><div className="w-2.5 h-2.5 rounded-full bg-cyan-400 animate-pulse mt-0.5" /></div>
                              <div className="col-span-3 min-w-0"><CopyableId id={s.consumer_id} /></div>
                              <div className="col-span-1 text-sm">{countryFlag(s.consumer_country) || '—'}</div>
                              <div className="col-span-1 text-slate-300 text-xs truncate">{fmtType(s.service_type) || '—'}</div>
                              <div className="col-span-1 text-slate-300">{s.duration}</div>
                              <div className="col-span-2 text-emerald-300">
                                {s.bytes_pending
                                  ? <span className="text-slate-600 italic" title="Bytes reported at session close by Mysterium">—</span>
                                  : formatDataSize(s.data_out)}
                              </div>
                              <div className="col-span-1 text-slate-300">
                                {s.bytes_pending
                                  ? <span className="text-slate-600 italic" title="Bytes reported at session close by Mysterium">—</span>
                                  : formatDataSize(s.data_in)}
                              </div>
                              <div className="col-span-2 text-emerald-400">{s.earnings_myst > 0
                                ? s.earnings_myst < 0.00001 ? '< 0.00001 MYST' : `${s.earnings_myst.toFixed(6)} MYST`
                                : '—'}</div>
                            </div>
                          ))}
                        </div>
                      </>
                    ) : (
                      <div className="text-xs text-slate-500 py-8 text-center">
                        No active sessions — no VPN tunnels are currently connected.
                      </div>
                    );
                  })()}
                </>
              )}

              {/* ======= HISTORY TAB ======= */}
              {sessionTab === 'history' && (
                <>
                  {metrics.sessions.items && metrics.sessions.items.length > 0 ? (
                    <>
                      {/* Mobile stacked view */}
                      <div className="sm:hidden space-y-2">
                        <MobileSortBar state={historySort} setState={setHistorySort} keys={[
                          { key: 'earnings_myst',    label: 'Earned' },
                          { key: 'data_total',       label: 'Data' },
                          { key: 'duration_secs',    label: 'Duration' },
                          { key: 'started',          label: 'Started' },
                          { key: 'service_type',     label: 'Type' },
                          { key: 'consumer_country', label: 'Country' },
                        ]} />
                        {sortRows(metrics.sessions.items, historySort).map((s, i) => (
                          <div key={s.id || i} className={`p-3 rounded border ${
                            s.is_active
                              ? s.is_paid ? 'bg-emerald-500/5 border-emerald-500/20' : 'bg-emerald-500/5 border-emerald-500/20'
                              : 'bg-slate-900/30 border-slate-700/30'
                          }`}>
                            <div className="flex items-center justify-between mb-1">
                              <CopyableId id={s.consumer_id} />
                              <span className={`text-xs font-semibold ${s.is_paid ? 'text-emerald-400' : 'text-slate-500'}`}>
                                {s.is_paid
                                  ? s.earnings_myst < 0.00001 ? '< 0.00001 MYST' : `${s.earnings_myst.toFixed(6)} MYST`
                                  : '—'}
                              </span>
                            </div>
                            <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-slate-400">
                              <span>{countryFlag(s.consumer_country) || '—'}</span>
                              <span className="text-slate-300">{s.service_type}</span>
                              <span className="font-mono">{s.duration}</span>
                              <span>{formatDataSize(s.data_total)}</span>
                              {s.started_fmt && <span className="text-slate-500">{s.started_fmt}</span>}
                              {s.is_active && <span className="text-emerald-400 text-[10px]">● live</span>}
                            </div>
                            {s.id && <div className="mt-1 text-slate-600 font-mono text-[10px]">{s.id.slice(0, 8)}…</div>}
                          </div>
                        ))}
                      </div>
                      {/* Desktop table view */}
                      <div className="hidden sm:block space-y-1.5">
                        <div className="grid grid-cols-12 gap-2 text-xs text-slate-500 font-semibold uppercase tracking-widest px-3 py-1">
                          <div className="col-span-1">●</div>
                          <div className={`col-span-2 ${hdrCls(historySort,'consumer_id')}`} onClick={() => mkSort(setHistorySort)('consumer_id')}>Consumer <span className="text-[10px]">{sortIcon(historySort,'consumer_id')}</span></div>
                          <div className={`col-span-1 ${hdrCls(historySort,'consumer_country')}`} onClick={() => mkSort(setHistorySort)('consumer_country')}>🌍 <span className="text-[10px]">{sortIcon(historySort,'consumer_country')}</span></div>
                          <div className={`col-span-2 ${hdrCls(historySort,'service_type')}`} onClick={() => mkSort(setHistorySort)('service_type')}>Type <span className="text-[10px]">{sortIcon(historySort,'service_type')}</span></div>
                          <div className={`col-span-1 ${hdrCls(historySort,'duration_secs')}`} onClick={() => mkSort(setHistorySort)('duration_secs')}>Duration <span className="text-[10px]">{sortIcon(historySort,'duration_secs')}</span></div>
                          <div className={`col-span-2 ${hdrCls(historySort,'started')}`} onClick={() => mkSort(setHistorySort)('started')}>Started <span className="text-[10px]">{sortIcon(historySort,'started')}</span></div>
                          <div className={`col-span-1 ${hdrCls(historySort,'data_total')}`} onClick={() => mkSort(setHistorySort)('data_total')}>Data <span className="text-[10px]">{sortIcon(historySort,'data_total')}</span></div>
                          <div className={`col-span-1 ${hdrCls(historySort,'earnings_myst')}`} onClick={() => mkSort(setHistorySort)('earnings_myst')}>Earned <span className="text-[10px]">{sortIcon(historySort,'earnings_myst')}</span></div>
                          <div className="col-span-1 text-slate-500">Session ID</div>
                        </div>
                        {sortRows(metrics.sessions.items, historySort).map((session, i) => (
                          <div key={session.id || i} className={`grid grid-cols-12 gap-2 text-xs px-3 py-2 rounded border transition ${
                            session.is_active
                              ? session.is_paid ? 'bg-emerald-500/5 border-emerald-500/20' : 'bg-emerald-500/5 border-emerald-500/20'
                              : 'bg-slate-900/30 border-slate-700/30'
                          }`}>
                            <div className="col-span-1 flex items-center">
                              <div className={`w-2 h-2 rounded-full ${session.is_active ? 'bg-emerald-400 animate-pulse' : 'bg-slate-500'}`} />
                            </div>
                            <div className="col-span-2 min-w-0"><CopyableId id={session.consumer_id} /></div>
                            <div className="col-span-1 text-sm">{countryFlag(session.consumer_country) || '—'}</div>
                            <div className="col-span-2 text-slate-300 text-xs truncate">{fmtType(session.service_type)}</div>
                            <div className="col-span-1 text-slate-400 font-mono">{session.duration}</div>
                            <div className="col-span-2 text-slate-400 text-xs">{session.started_fmt || '—'}</div>
                            <div className="col-span-1 text-slate-300">{formatDataSize(session.data_total)}</div>
                            <div className={`col-span-1 font-semibold text-xs truncate ${session.is_paid ? 'text-emerald-400' : 'text-slate-500'}`}>
                              {session.is_paid
                                ? session.earnings_myst < 0.00001
                                  ? '<0.00001'
                                  : session.earnings_myst.toFixed(6)
                                : '—'}
                            </div>
                            <div className="col-span-1 text-slate-500 font-mono text-xs truncate" title={session.id}>
                              {session.id ? session.id.slice(0, 8) + '…' : '—'}
                            </div>
                          </div>
                        ))}
                      </div>
                    </>
                  ) : (
                    <div className="text-xs text-slate-500 py-8 text-center">No completed sessions yet</div>
                  )}

                  {/* ======= ARCHIVE SECTION — SessionDB history (survives node restarts) ======= */}
                  {(() => {
                    // Only show archive sessions not already in the live TequilAPI store
                    const liveIds = new Set((metrics.sessions?.items || []).map(s => s.id));
                    const archiveOnly = archiveSessions.filter(s => !liveIds.has(s.id));

                    // Still loading — show spinner
                    if (archiveLoading && archiveOnly.length === 0) return (
                      <div className="mt-4 pt-4 border-t border-slate-700/40">
                        <span className="text-xs text-slate-500 animate-pulse">Loading archive…</span>
                      </div>
                    );

                    // Archive fetched but all sessions overlap with live store
                    if (!archiveLoading && archiveSessions.length > 0 && archiveOnly.length === 0) return (
                      <div className="mt-4 pt-4 border-t border-slate-700/40">
                        <span className="text-xs text-slate-600">
                          Archive ({archiveTotal} sessions) — all visible in live sessions above.
                        </span>
                      </div>
                    );

                    // Nothing in archive at all
                    if (!archiveLoading && archiveSessions.length === 0) return (
                      <div className="mt-4 pt-4 border-t border-slate-700/40">
                        <div className="text-xs text-slate-600">
                          Archive is empty — sessions older than 30 days will appear here automatically as your node keeps running.
                        </div>
                      </div>
                    );

                    return (
                      <div className="mt-4 pt-4 border-t border-slate-700/40">
                        <div className="flex items-center justify-between mb-2">
                          <div className="flex items-center gap-2">
                            <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Archive</span>
                            <span className="text-xs text-slate-600">— from database, pre-restart sessions</span>
                            <span className="text-xs text-slate-600">({archiveTotal} total)</span>
                          </div>
                          {archiveLoading && <span className="text-xs text-slate-500 animate-pulse">Loading…</span>}
                        </div>
                        {archiveOnly.length > 0 && (
                          <>
                            {/* Mobile stacked */}
                            <div className="sm:hidden space-y-2">
                              {archiveOnly.map((s, i) => (
                                <div key={s.id || i} className="p-3 rounded border bg-slate-900/40 border-slate-700/30 opacity-80">
                                  <div className="flex items-center justify-between mb-1">
                                    <CopyableId id={s.consumer_id} />
                                    <span className={`text-xs font-semibold ${s.is_paid ? 'text-emerald-400' : 'text-slate-500'}`}>
                                      {s.is_paid ? `${s.earnings_myst.toFixed(6)} MYST` : '—'}
                                    </span>
                                  </div>
                                  <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-slate-400">
                                    <span>{countryFlag(s.consumer_country) || '—'}</span>
                                    <span className="text-slate-300">{s.service_type}</span>
                                    <span className="font-mono">{s.duration}</span>
                                    <span>{formatDataSize(s.data_total)}</span>
                                    {s.started_fmt && <span className="text-slate-500">{s.started_fmt}</span>}
                                  </div>
                                </div>
                              ))}
                            </div>
                            {/* Desktop table */}
                            <div className="hidden sm:block space-y-1">
                              {sortRows(archiveOnly, historySort).map((s, i) => (
                                <div key={s.id || i} className="grid grid-cols-12 gap-2 text-xs px-3 py-1.5 rounded border bg-slate-900/30 border-slate-700/20 opacity-80 hover:opacity-100 transition">
                                  <div className="col-span-1 flex items-center"><div className="w-2 h-2 rounded-full bg-slate-600" /></div>
                                  <div className="col-span-2 min-w-0"><CopyableId id={s.consumer_id} /></div>
                                  <div className="col-span-1 text-sm">{countryFlag(s.consumer_country) || '—'}</div>
                                  <div className="col-span-2 text-slate-400 text-xs truncate">{fmtType(s.service_type)}</div>
                                  <div className="col-span-1 text-slate-500 font-mono">{s.duration}</div>
                                  <div className="col-span-2 text-slate-500 text-xs">{s.started_fmt || '—'}</div>
                                  <div className="col-span-1 text-slate-400">{formatDataSize(s.data_total)}</div>
                                  <div className={`col-span-1 font-semibold text-xs ${s.is_paid ? 'text-emerald-400/80' : 'text-slate-600'}`}>
                                    {s.is_paid ? s.earnings_myst.toFixed(6) : '—'}
                                  </div>
                                  <div className="col-span-1 text-slate-600 font-mono text-xs truncate">{s.id ? s.id.slice(0,8)+'…' : '—'}</div>
                                </div>
                              ))}
                            </div>
                            {/* Load more */}
                            {(archiveOffset + ARCHIVE_PAGE) < archiveTotal && (
                              <button
                                onClick={() => { const next = archiveOffset + ARCHIVE_PAGE; setArchiveOffset(next); fetchArchive(next, false); }}
                                className="mt-2 text-xs text-slate-500 hover:text-slate-300 transition px-3 py-1 border border-slate-700 rounded"
                              >Load more ({archiveTotal - archiveSessions.length} remaining)</button>
                            )}
                          </>
                        )}
                      </div>
                    );
                  })()}
                </>
              )}

              {/* ======= CONSUMERS TAB ======= */}
              {sessionTab === 'consumers' && (
                <>
                  <div className="mb-3 flex gap-4 text-xs text-slate-400">
                    <span>Unique: <span className="text-slate-200 font-semibold">{safeNum(metrics.sessions?.unique_consumers || 0)}</span></span>
                    <span>Paying: <span className="text-emerald-300 font-semibold">{safeNum(metrics.sessions?.paying_consumers || 0)}</span></span>
                    <span>Sessions: <span className="text-slate-200">{safeNum(metrics.sessions?.total || 0)}</span></span>
                  </div>
                  {(metrics.sessions?.top_consumers || []).length > 0 ? (
                    <>
                      {/* Mobile stacked view */}
                      <div className="sm:hidden space-y-2">
                        <MobileSortBar state={consumerSort} setState={setConsumerSort} keys={[
                          { key: 'total_earnings', label: 'Earned' },
                          { key: 'total_data_mb',  label: 'Data' },
                          { key: 'sessions',       label: 'Sessions' },
                        ]} />
                        {sortRows(metrics.sessions.top_consumers || [], consumerSort).map((c, i) => (
                          <div key={c.consumer_id || i} className={`p-3 rounded border ${
                            c.active_sessions > 0 ? 'bg-emerald-500/5 border-emerald-500/20' : 'bg-slate-900/30 border-slate-700/30'
                          }`}>
                            <div className="flex items-center justify-between mb-1">
                              <CopyableId id={c.consumer_id} />
                              <span className={`text-xs font-semibold ${c.total_earnings > 0 ? 'text-emerald-400' : 'text-slate-500'}`}>
                                {c.total_earnings > 0 ? `${c.total_earnings.toFixed(4)} MYST` : '—'}
                              </span>
                            </div>
                            <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-slate-400">
                              <span>{countryFlag(c.consumer_country) || '—'}</span>
                              {(c.service_types || []).map(st => (
                                <span key={st} className="text-slate-300">{st}</span>
                              ))}
                              <span>{c.sessions}{c.active_sessions > 0 ? ` (${c.active_sessions} live)` : ''}</span>
                              <span>{formatDataSize(c.total_data_mb)}</span>
                              {c.active_sessions > 0
                                ? <span className="text-emerald-400">● connected</span>
                                : <span className="text-slate-500">○ offline</span>}
                            </div>
                          </div>
                        ))}
                      </div>
                      {/* Desktop sortable table */}
                      <div className="hidden sm:block space-y-1.5">
                        <div className="grid grid-cols-12 gap-2 text-xs text-slate-500 font-semibold uppercase tracking-widest px-3 py-1">
                          <div className="col-span-3">Consumer</div>
                          <div className="col-span-1">🌍</div>
                          <div className="col-span-2">Service</div>
                          <div
                            className={`col-span-1 cursor-pointer select-none flex items-center gap-1 hover:text-slate-200 transition ${consumerSort.key === 'sessions' ? 'text-slate-200' : ''}`}
                            onClick={() => setConsumerSort(prev => ({ key: 'sessions', dir: prev.key === 'sessions' && prev.dir === 'desc' ? 'asc' : 'desc' }))}
                          >Sessions <span className="text-[10px]">{consumerSort.key === 'sessions' ? (consumerSort.dir === 'desc' ? '▼' : '▲') : '⇅'}</span></div>
                          <div
                            className={`col-span-2 cursor-pointer select-none flex items-center gap-1 hover:text-slate-200 transition ${consumerSort.key === 'total_data_mb' ? 'text-slate-200' : ''}`}
                            onClick={() => setConsumerSort(prev => ({ key: 'total_data_mb', dir: prev.key === 'total_data_mb' && prev.dir === 'desc' ? 'asc' : 'desc' }))}
                          >Data <span className="text-[10px]">{consumerSort.key === 'total_data_mb' ? (consumerSort.dir === 'desc' ? '▼' : '▲') : '⇅'}</span></div>
                          <div
                            className={`col-span-2 cursor-pointer select-none flex items-center gap-1 hover:text-slate-200 transition ${consumerSort.key === 'total_earnings' ? 'text-slate-200' : ''}`}
                            onClick={() => setConsumerSort(prev => ({ key: 'total_earnings', dir: prev.key === 'total_earnings' && prev.dir === 'desc' ? 'asc' : 'desc' }))}
                          >Earned <span className="text-[10px]">{consumerSort.key === 'total_earnings' ? (consumerSort.dir === 'desc' ? '▼' : '▲') : '⇅'}</span></div>
                          <div className="col-span-1">Status</div>
                        </div>
                        {[...(metrics.sessions.top_consumers || [])]
                          .sort((a, b) => {
                            const mul = consumerSort.dir === 'desc' ? -1 : 1;
                            const av = a[consumerSort.key] ?? 0;
                            const bv = b[consumerSort.key] ?? 0;
                            return av > bv ? -mul : av < bv ? mul : 0;
                          })
                          .map((c, i) => (
                          <div key={c.consumer_id || i} className={`grid grid-cols-12 gap-2 text-xs px-3 py-2 rounded border transition ${
                            c.active_sessions > 0 ? 'bg-emerald-500/5 border-emerald-500/20' : 'bg-slate-900/30 border-slate-700/30'
                          }`}>
                            <div className="col-span-3 min-w-0"><CopyableId id={c.consumer_id} /></div>
                            <div className="col-span-1 text-sm">{countryFlag(c.consumer_country) || '—'}</div>
                            <div className="col-span-2 text-slate-300 text-xs truncate">{(c.service_types || []).map(t => fmtType(t)).join(', ') || '—'}</div>
                            <div className="col-span-1 text-slate-300">{c.sessions}{c.active_sessions > 0 ? ` (${c.active_sessions} live)` : ''}</div>
                            <div className="col-span-2 text-slate-300">{formatDataSize(c.total_data_mb)}</div>
                            <div className={`col-span-2 font-semibold ${c.total_earnings > 0 ? 'text-emerald-400' : 'text-slate-500'}`}>
                              {c.total_earnings > 0 ? `${c.total_earnings.toFixed(4)} MYST` : '—'}
                            </div>
                            <div className="col-span-1">
                              {c.active_sessions > 0
                                ? <span className="text-emerald-400 text-xs">● live</span>
                                : <span className="text-slate-500 text-xs">○</span>}
                            </div>
                          </div>
                        ))}
                      </div>
                    </>
                  ) : (
                    <div className="text-xs text-slate-500 py-8 text-center">No consumer data available</div>
                  )}
                </>
              )}

            </div>
            </>
          )}

          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
            {/* System CPU card — Ambient first, then CPU paired, then RAM paired */}
            <div className="min-w-[140px] flex-1 p-4 bg-slate-800/30 border border-slate-700 rounded-lg backdrop-blur flex items-start gap-3">
              <div className="flex-shrink-0 mt-1"><Database className="w-4 h-4 text-emerald-400" /></div>
              <div className="flex-1 min-w-0">
                <h3 className="text-xs font-semibold text-slate-300 tracking-wide mb-1">System CPU</h3>
                {(() => {
                  const at = metrics.resources.all_temps || [];
                  const cpuPct = safeNum(metrics.resources.cpu).toFixed(1);
                  const ramPct = safeNum(metrics.resources.ram).toFixed(1);
                  const cpuTempColor = (v) => v < 60 ? 'text-green-400' : v < 80 ? 'text-yellow-400' : 'text-red-400';
                  const cpuPctColor = (v) => v < 70 ? 'text-green-400' : v < 90 ? 'text-yellow-400' : 'text-red-400';

                  if (at.length > 0) {
                    // Sort: Ambient/other first, CPU second, RAM last
                    const sortOrder = (lbl) => {
                      const l = (lbl || '').toLowerCase();
                      if (l === 'cpu') return 1;
                      if (['ram', 'sodimm', 'mem'].includes(l)) return 2;
                      return 0;
                    };
                    const sorted = [...at].sort((a, b) => sortOrder(a.label) - sortOrder(b.label));
                    return sorted.map((t, i) => {
                      const lbl = t.label || '';
                      const lblLower = lbl.toLowerCase();
                      const tc = cpuTempColor(t.value);
                      const isCpu = lblLower === 'cpu';
                      const isRam = ['ram', 'sodimm', 'mem'].includes(lblLower);
                      if (isCpu) {
                        return (
                          <div key={i} className="flex items-center justify-between gap-3 mt-1">
                            <span className={`text-xs font-medium ${tc}`}>CPU: {t.value.toFixed(0)}°C</span>
                            <span className={`text-xs font-medium ${cpuPctColor(safeNum(metrics.resources.cpu))}`}>CPU: {cpuPct}%</span>
                          </div>
                        );
                      } else if (isRam) {
                        return (
                          <div key={i} className="flex items-center justify-between gap-3 mt-1">
                            <span className={`text-xs font-medium ${tc}`}>RAM: {t.value.toFixed(0)}°C</span>
                            <span className={`text-xs font-medium ${cpuPctColor(safeNum(metrics.resources.ram))}`}>RAM: {ramPct}%</span>
                          </div>
                        );
                      } else {
                        // Ambient or other — full-width, temp only
                        return (
                          <div key={i} className={`text-xs font-medium mt-1 ${tc}`}>{lbl}: {t.value.toFixed(0)}°C</div>
                        );
                      }
                    });
                  }

                  // Fallback: no all_temps — show cpu% and ram% stacked, plus single cpu_temp if available
                  return (
                    <>
                      {metrics.resources.cpu_temp != null && (
                        <div className={`flex items-center justify-between gap-3 mt-1`}>
                          <span className={`text-xs font-medium ${cpuTempColor(metrics.resources.cpu_temp)}`}>CPU: {metrics.resources.cpu_temp.toFixed(0)}°C</span>
                          <span className={`text-xs font-medium ${cpuPctColor(safeNum(metrics.resources.cpu))}`}>CPU: {cpuPct}%</span>
                        </div>
                      )}
                      {metrics.resources.cpu_temp == null && (
                        <div className={`text-xl font-bold mt-1 ${cpuPctColor(safeNum(metrics.resources.cpu))}`}>{cpuPct}%</div>
                      )}
                      <div className={`text-xs font-medium mt-1 ${cpuPctColor(safeNum(metrics.resources.ram))}`}>RAM: {ramPct}%</div>
                    </>
                  );
                })()}
              </div>
            </div>
            <DetailCard title="Disk Usage" value={`${safeNum(metrics.resources.disk).toFixed(1)}%`} icon={<Database className="w-4 h-4 text-emerald-400" />} />

            {/* Clickable Firewall card */}
            <button
              onClick={() => setActivePanel(activePanel === 'firewall' ? null : 'firewall')}
              className={`min-w-[140px] flex-1 text-left p-4 bg-slate-800/30 border rounded-lg backdrop-blur flex items-start gap-3 transition hover:border-emerald-500/50 ${
                activePanel === 'firewall' ? 'border-emerald-500/50 ring-1 ring-emerald-500/20' : 'border-slate-700'
              }`}
            >
              <div className="flex-shrink-0 mt-1"><Shield className="w-4 h-4 text-emerald-400" /></div>
              <div className="flex-1">
                <h3 className="text-xs font-semibold text-slate-300 tracking-wide mb-1">Firewall Rules</h3>
                <div className="text-xl font-bold">{safeNum(metrics.firewall.rules)} active</div>
                <div className="text-xs text-slate-400 mt-1">{safeNum(metrics.firewall.blocked)} blocked · Click to view</div>
              </div>
            </button>

            <DetailCard
              title="Network Quality"
              value={`${safeNum(metrics.performance.latency)}ms`}
              subtitle={`Loss: ${safeNum(metrics.performance.packet_loss)}% · ${safeNum(metrics.clients?.connected || 0)} clients · Peak: ${safeNum(metrics.clients?.peak || 0)}`}
              icon={<Wifi className="w-4 h-4 text-emerald-400" />}
            />
          </div>

          {/* System Metrics History Card */}
          <SystemMetricsHistoryCard backendUrl={getNodeAwareUrl()} authHeaders={authHeaderRef.current} />

          {/* System Health Card — full width */}
          <div className="mb-6">
            <button
              onClick={() => setActivePanel(activePanel === 'health' ? null : 'health')}
              className={`w-full text-left p-4 bg-slate-800/30 border rounded-lg backdrop-blur transition hover:border-rose-500/50 ${
                activePanel === 'health' ? 'border-rose-500/50 ring-1 ring-rose-500/20' : 'border-slate-700'
              }`}
            >
              <div className="flex items-center gap-3">
                <Heart className={`w-5 h-5 ${
                  metrics.systemHealth.overall === 'ok' ? 'text-emerald-400' :
                  metrics.systemHealth.overall === 'warning' ? 'text-amber-400' : 'text-red-400'
                }`} />
                <div className="flex-1">
                  <div className="flex items-center gap-2 mb-1">
                    <h3 className="text-xs font-semibold text-slate-300 tracking-wide">System Health</h3>
                    {(() => {
                      const issues = (metrics.systemHealth.subsystems || []).filter(s => s.status !== 'ok').length;
                      const cls = issues === 0 ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                        : issues <= 2 ? 'bg-yellow-500/20 text-yellow-300 border border-yellow-500/30'
                        : issues <= 4 ? 'bg-amber-500/20 text-amber-300 border border-amber-500/30'
                        : 'bg-red-500/20 text-red-300 border border-red-500/30';
                      const label = issues === 0 ? 'OK' : issues <= 2 ? 'ATTENTION' : issues <= 4 ? 'WARNING' : 'CRITICAL';
                      return <span className={`text-xs px-2 py-0.5 rounded font-semibold ${cls}`}>{label}</span>;
                    })()}
                  </div>
                  <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs">
                    {(metrics.systemHealth.subsystems || []).map((sub) => {
                      const icon = sub.status === 'ok' ? '●' : sub.status === 'warning' ? '▲' : '✗';
                      const color = sub.status === 'ok' ? 'text-emerald-400' : sub.status === 'warning' ? 'text-amber-400' : 'text-red-400';
                      return <span key={sub.name} className={color}>{icon} {sub.title || sub.name}</span>;
                    })}
                  </div>
                </div>
                <span className="text-xs text-slate-500">Click to view</span>
              </div>
            </button>
          </div>

          {/* Data Management Card — full width */}
          <div className="mb-6">
            <button
              onClick={() => setActivePanel(activePanel === 'data' ? null : 'data')}
              className={`w-full text-left p-4 bg-slate-800/30 border rounded-lg backdrop-blur transition hover:border-emerald-500/50 ${
                activePanel === 'data' ? 'border-emerald-500/50 ring-1 ring-emerald-500/20' : 'border-slate-700'
              }`}
            >
              <div className="flex items-center gap-3">
                <Database className="w-5 h-5 text-emerald-400" />
                <div className="flex-1">
                  <div className="flex items-center gap-2 mb-1">
                    <h3 className="text-xs font-semibold text-slate-300 tracking-wide">Data Management</h3>
                    <span className="text-xs px-2 py-0.5 rounded font-semibold bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">STORAGE</span>
                  </div>
                  <p className="text-xs text-slate-500">View database sizes · clear old records · manage retention across earnings, quality, system metrics, sessions and more.</p>
                </div>
                <span className="text-xs text-slate-500">Click to manage</span>
              </div>
            </button>
          </div>

          {/* Expandable Firewall Panel */}
          {activePanel === 'firewall' && (
            <>
            <div className="fixed inset-0 z-40 bg-black/60 sm:hidden" onClick={() => setActivePanel(null)} />
            <div style={{ backgroundColor: panelBg }} className="fixed inset-0 z-50 overflow-y-auto p-4 pt-6
                            sm:static sm:bg-slate-800/30 sm:p-5 sm:mb-6 sm:rounded-lg sm:border sm:border-amber-500/30 sm:backdrop-blur sm:max-h-[80vh] sm:overflow-y-auto">
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-2">
                  <Shield className="w-4 h-4 text-emerald-400" />
                  <h3 className="text-sm font-semibold tracking-wide">Firewall Details</h3>
                  <span className={`text-xs ml-2 px-2 py-0.5 rounded ${
                    metrics.firewall.status === 'active'
                      ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                      : 'bg-red-500/20 text-red-300 border border-red-500/30'
                  }`}>{metrics.firewall.status}</span>
                  {metrics.firewall.fw_type && metrics.firewall.fw_type !== 'unknown' && (
                    <span className="text-xs px-2 py-0.5 rounded bg-slate-700/50 text-slate-400 border border-slate-600/30">
                      {metrics.firewall.fw_type}
                    </span>
                  )}
                </div>
                <button onClick={() => setActivePanel(null)} className="p-2 bg-slate-800 hover:bg-slate-700 rounded transition text-slate-300 text-sm font-semibold">✕ Close</button>
              </div>

              {/* iptables rules */}
              {metrics.firewall.rule_details && metrics.firewall.rule_details.length > 0 ? (() => {
                // Deduplicate rules for display — same chain+action+proto+source+dest+extra = one row
                const seen = new Map();
                const deduped = [];
                metrics.firewall.rule_details.forEach(rule => {
                  const key = `${rule.chain}|${rule.action}|${rule.protocol}|${rule.source}|${rule.destination}|${rule.extra}`;
                  if (seen.has(key)) {
                    seen.get(key).count++;
                  } else {
                    const r = { ...rule, count: 1 };
                    seen.set(key, r);
                    deduped.push(r);
                  }
                });
                const dupCount = metrics.firewall.rule_details.length - deduped.length;
                return (
                  <div className="mb-4">
                    {dupCount > 0 && (
                      <div className="flex items-center justify-between mb-2 px-1">
                        <div className="text-[10px] text-amber-400">
                          {dupCount} duplicate rule(s) hidden — likely leftover Mysterium WireGuard FORWARD rules
                        </div>
                        <button
                          onClick={() => {
                            fetch(`${getNodeAwareUrl()}/firewall/cleanup`, {
                              method: 'POST',
                              headers: authHeaderRef.current || {}
                            })
                            .then(r => r.json())
                            .then(d => alert(d.message || (d.error ? `Error: ${d.error}` : 'Done')))
                            .catch(() => alert('Cleanup request failed'));
                          }}
                          className="text-[10px] px-2 py-1 rounded bg-amber-500/10 border border-amber-500/30 text-amber-400 hover:bg-amber-500/20 transition"
                        >
                          Clean up
                        </button>
                      </div>
                    )}
                    <div className="space-y-1 max-h-72 overflow-y-auto overflow-x-auto">
                      <div className="text-xs text-slate-500 font-semibold uppercase tracking-widest px-3 py-1 flex gap-3">
                        <span className="w-16">Chain</span>
                        <span className="w-16">Action</span>
                        <span className="w-12">Proto</span>
                        <span className="w-28">Source</span>
                        <span className="w-28">Dest</span>
                        <span className="flex-1">Details</span>
                      </div>
                      {deduped.map((rule, i) => (
                        <div
                          key={i}
                          className={`text-xs font-mono px-3 py-1.5 rounded flex gap-3 ${
                            rule.blocked
                              ? 'bg-red-500/5 border border-red-500/20 text-red-300'
                              : 'bg-slate-900/30 border border-slate-700/30 text-slate-400'
                          }`}
                        >
                          <span className="w-16 text-slate-500">{rule.chain}</span>
                          <span className={`w-16 font-semibold ${
                            rule.action === 'ACCEPT' ? 'text-emerald-400' :
                            rule.action === 'DROP' ? 'text-red-400' :
                            rule.action === 'REJECT' ? 'text-amber-400' : 'text-slate-300'
                          }`}>{rule.action}</span>
                          <span className="w-12">{rule.protocol}</span>
                          <span className="w-28">{rule.source}</span>
                          <span className="w-28">{rule.destination}</span>
                          <span className="flex-1 text-slate-500 truncate">
                            {rule.extra}
                            {rule.count > 1 && <span className="ml-2 text-amber-400/70">×{rule.count}</span>}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                );
              })() : (
                <div className="text-xs text-slate-500 py-4 text-center mb-4 space-y-1">
                  {metrics.firewall.status === 'active' ? (
                    <>
                      <div className="text-amber-400">No firewall rules visible</div>
                      <div className="text-slate-500">The backend needs passwordless sudo to read firewall rules.</div>
                      {(() => {
                        const ft = metrics.firewall.fw_type || 'iptables';
                        const cmds = {
                          'ufw': 'NOPASSWD: /usr/sbin/ufw',
                          'firewalld': 'NOPASSWD: /usr/bin/firewall-cmd',
                          'nftables': 'NOPASSWD: /usr/sbin/nft',
                        };
                        const cmd = cmds[ft] || 'NOPASSWD: /sbin/iptables, /usr/sbin/iptables-legacy';
                        return (
                          <div className="font-mono bg-slate-900/60 px-3 py-1.5 rounded inline-block mt-1 text-left">
                            <div className="text-slate-500 mb-0.5">sudo visudo → add:</div>
                            <div className="text-cyan-400">{'{user}'} ALL=(ALL) {cmd}</div>
                          </div>
                        );
                      })()}
                    </>
                  ) : (
                    <div>Firewall not detected or inactive</div>
                  )}
                </div>
              )}

              {/* UFW rules if present */}
              {metrics.firewall.ufw_rules && metrics.firewall.ufw_rules.length > 0 && (
                <div>
                  <h4 className="text-xs font-semibold text-slate-400 mb-2">UFW Rules</h4>
                  <div className="space-y-1 max-h-48 overflow-y-auto">
                    {metrics.firewall.ufw_rules.map((rule, i) => (
                      <div key={i} className="text-xs font-mono px-3 py-1.5 bg-slate-900/30 border border-slate-700/30 rounded text-slate-400">
                        {rule}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
            </>
          )}

          {/* Expandable System Health Panel */}
          {/* ======= HEALTH PANEL — centred modal, scrollable, same on all screen sizes ======= */}
          {activePanel === 'health' && (
            <>
              {/* Backdrop */}
              <div className="fixed inset-0 z-40 bg-black/70 backdrop-blur-sm" onClick={() => setActivePanel(null)} />
              {/* Modal */}
              <div className="fixed inset-x-3 top-4 bottom-4 z-50 flex flex-col max-w-2xl mx-auto
                              border border-rose-500/30 rounded-xl shadow-2xl overflow-hidden"
                   style={{ backgroundColor: panelBg }}>
                {/* Header — sticky */}
                <div className="flex-shrink-0 px-5 py-4 border-b border-slate-700/50 flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <Heart className="w-4 h-4 text-rose-400" />
                    <h3 className="text-sm font-semibold tracking-wide">System Health</h3>
                    <span className={`text-xs px-2 py-0.5 rounded font-semibold ${
                      metrics.systemHealth.overall === 'ok' ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30' :
                      metrics.systemHealth.overall === 'warning' ? 'bg-amber-500/20 text-amber-300 border border-amber-500/30' :
                      'bg-red-500/20 text-red-300 border border-red-500/30'
                    }`}>{(metrics.systemHealth.overall || 'unknown').toUpperCase()}</span>
                  </div>
                  <div className="flex items-center gap-2 flex-wrap">
                    {/* Scan */}
                    <button
                      onClick={async () => {
                        try {
                          setHealthBusy(true);
                          const r = await fetch(`${healthFixUrl('system-health/scan')}`, {
                            method: 'POST', headers: { ...authHeaderRef.current, 'Content-Type': 'application/json' },
                          });
                          if (r.ok) fetchMetrics();
                        } catch (e) { console.error(e); } finally { setHealthBusy(false); }
                      }}
                      className="px-3 py-1 text-xs bg-slate-600/30 text-slate-300 border border-slate-500/30 rounded hover:bg-slate-600/50 transition"
                    >{healthBusy ? '⟳ Scanning…' : '⟳ Scan Now'}</button>
                    {/* Optimize & Lock All — fix + persist in one shot */}
                    <button
                      onClick={async () => {
                        try {
                          setHealthBusy(true);
                          const [fixR, persistR] = await Promise.all([
                            fetch(`${healthFixUrl('system-health/fix')}`, {
                              method: 'POST',
                              headers: { ...authHeaderRef.current, 'Content-Type': 'application/json' },
                              body: JSON.stringify({ subsystem: 'all' }),
                            }),
                            fetch(`${healthFixUrl('system-health/persist')}`, {
                              method: 'POST',
                              headers: { ...authHeaderRef.current, 'Content-Type': 'application/json' },
                            }),
                          ]);
                          if (fixR.ok) {
                            const data = await fixR.json();
                            const merged = {};
                            (data.subsystems || []).forEach(s => { merged[s.name] = s.actions || []; });
                            setFixResults(prev => ({ ...prev, ...merged }));
                          }
                          fetchMetrics();
                        } catch (e) { console.error(e); } finally { setHealthBusy(false); }
                      }}
                      className="px-3 py-1 text-xs bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 rounded hover:bg-emerald-500/30 transition font-semibold"
                      title="Apply all fixes and lock them in permanently"
                    >⚡ Optimize &amp; Lock All</button>
                    {/* Unpersist All */}
                    <button
                      onClick={async () => {
                        try {
                          await fetch(`${healthFixUrl('system-health/unpersist')}`, {
                            method: 'POST', headers: { ...authHeaderRef.current, 'Content-Type': 'application/json' },
                          });
                          setFixResults({});
                          fetchMetrics();
                        } catch (e) { console.error(e); }
                      }}
                      className="px-3 py-1 text-xs bg-amber-500/10 text-amber-400 border border-amber-500/20 rounded hover:bg-amber-500/20 transition"
                      title="Remove all persisted settings — revert to defaults on next reboot"
                    >Unpersist All</button>
                    <button
                      onClick={() => setActivePanel(null)}
                      className="px-3 py-1 text-xs bg-slate-700/50 text-slate-300 border border-slate-600/30 rounded hover:bg-slate-600/50 transition font-semibold"
                    >✕ Close</button>
                  </div>
                </div>

                {/* Scrollable content */}
                <div className="flex-1 overflow-y-auto px-5 py-4 space-y-3">
                  {(metrics.systemHealth.subsystems || []).map((sub) => (
                    <div key={sub.name} className={`p-3 rounded-lg border ${
                      sub.status === 'ok'      ? 'bg-emerald-500/5 border-emerald-500/20' :
                      sub.status === 'warning' ? 'bg-amber-500/5  border-amber-500/20'   :
                                                 'bg-red-500/5    border-red-500/20'
                    }`}>
                      {/* Title row */}
                      <div className="flex items-center gap-2 mb-2">
                        <span className={`text-sm font-semibold flex-shrink-0 ${
                          sub.status === 'ok' ? 'text-emerald-400' : sub.status === 'warning' ? 'text-amber-400' : 'text-red-400'
                        }`}>{sub.status === 'ok' ? '●' : sub.status === 'warning' ? '▲' : '✗'}</span>
                        <h4 className="text-xs font-semibold text-slate-200 flex-1 min-w-0 truncate">{sub.title || sub.name}</h4>
                        <span className={`text-xs px-1.5 py-0.5 rounded flex-shrink-0 ${
                          sub.status === 'ok' ? 'bg-emerald-500/10 text-emerald-400' :
                          sub.status === 'warning' ? 'bg-amber-500/10 text-amber-400' : 'bg-red-500/10 text-red-400'
                        }`}>{sub.status}</span>
                      </div>

                      {/* Action buttons — Fix & Lock is primary; Unpersist + Fix-only are secondary */}
                      <div className="flex flex-wrap items-center gap-1.5 mb-2">
                        {/* PRIMARY: Fix & Lock */}
                        <button
                          onClick={async () => {
                            try {
                              const fixR = await fetch(`${healthFixUrl('system-health/fix')}`, {
                                method: 'POST',
                                headers: { ...authHeaderRef.current, 'Content-Type': 'application/json' },
                                body: JSON.stringify({ subsystem: sub.name }),
                              });
                              if (fixR.ok) {
                                const data = await fixR.json();
                                setFixResults(prev => ({ ...prev, [sub.name]: data.actions || [] }));
                              }
                              await fetch(`${healthFixUrl('system-health/persist')}`, {
                                method: 'POST',
                                headers: { ...authHeaderRef.current, 'Content-Type': 'application/json' },
                                body: JSON.stringify({ subsystem: sub.name }),
                              });
                              fetchMetrics();
                            } catch (e) { console.error(e); }
                          }}
                          className="px-2.5 py-1 text-xs bg-emerald-500/15 text-emerald-300 rounded hover:bg-emerald-500/25 active:bg-emerald-500/35 transition border border-emerald-500/30 font-semibold"
                          title="Fix now and persist — survives reboots"
                        >⚡ Fix &amp; Lock</button>
                        {/* SECONDARY: Unpersist */}
                        <button
                          onClick={async () => {
                            try {
                              await fetch(`${healthFixUrl('system-health/unpersist')}`, {
                                method: 'POST',
                                headers: { ...authHeaderRef.current, 'Content-Type': 'application/json' },
                                body: JSON.stringify({ subsystem: sub.name }),
                              });
                              setFixResults(prev => { const n = {...prev}; delete n[sub.name]; return n; });
                              fetchMetrics();
                            } catch (e) { console.error(e); }
                          }}
                          className="px-2.5 py-1 text-xs bg-amber-500/10 text-amber-400 rounded hover:bg-amber-500/20 active:bg-amber-500/30 transition border border-amber-500/20"
                          title="Remove persisted settings for this subsystem"
                        >Unpersist</button>
                        {/* TERTIARY: Fix in-memory only (advanced) */}
                        <button
                          onClick={async () => {
                            try {
                              const r = await fetch(`${healthFixUrl('system-health/fix')}`, {
                                method: 'POST',
                                headers: { ...authHeaderRef.current, 'Content-Type': 'application/json' },
                                body: JSON.stringify({ subsystem: sub.name }),
                              });
                              if (r.ok) {
                                const data = await r.json();
                                setFixResults(prev => ({ ...prev, [sub.name]: data.actions || [] }));
                              }
                              fetchMetrics();
                            } catch (e) { console.error(e); }
                          }}
                          className="px-2.5 py-1 text-xs bg-slate-600/15 text-slate-400 rounded hover:bg-slate-600/30 transition border border-slate-600/20"
                          title="Apply fix in memory only — reverts on reboot"
                        >Fix only</button>
                      </div>

                      {/* Check details */}
                      <div className="space-y-1">
                        {(sub.checks || []).map((check, ci) => (
                          <div key={ci} className="flex items-start gap-2 text-xs">
                            <span className={`w-2 h-2 rounded-full flex-shrink-0 mt-1 ${
                              check.status === 'ok' ? 'bg-emerald-400' : check.status === 'warning' ? 'bg-amber-400' : 'bg-red-400'
                            }`} />
                            <span className="text-slate-400 w-36 flex-shrink-0 leading-relaxed">{check.name}</span>
                            <span className="text-slate-500 flex-1 leading-relaxed break-words">{check.detail}</span>
                          </div>
                        ))}
                      </div>

                      {/* Recommendations */}
                      {sub.recommendations && sub.recommendations.length > 0 && (
                        <div className="mt-2 pt-2 border-t border-slate-700/30 space-y-1">
                          {sub.recommendations.map((rec, ri) => (
                            <div key={ri} className="text-xs text-amber-400/80 flex items-start gap-1">
                              <span className="flex-shrink-0">→</span>
                              <span className="break-words">{rec}</span>
                            </div>
                          ))}
                        </div>
                      )}

                      {/* Fix results — shown after any fix action */}
                      {fixResults[sub.name] && fixResults[sub.name].length > 0 && (
                        <div className="mt-2 pt-2 border-t border-slate-700/40">
                          <div className="flex items-center justify-between mb-1">
                            <span className="text-xs text-slate-500 font-medium">Last fix result</span>
                            <button
                              onClick={() => setFixResults(prev => { const n = {...prev}; delete n[sub.name]; return n; })}
                              className="text-xs text-slate-600 hover:text-slate-400 transition"
                            >✕</button>
                          </div>
                          <div className="space-y-0.5">
                            {fixResults[sub.name].map((action, ai) => (
                              <div key={ai} className="flex items-start gap-2 text-xs">
                                <span className={`flex-shrink-0 font-bold ${action.success ? 'text-emerald-400' : 'text-red-400'}`}>
                                  {action.success ? '✓' : '✗'}
                                </span>
                                <span className={`break-words flex-1 ${action.success ? 'text-slate-400' : 'text-red-400/80'}`}>
                                  {action.action}
                                  {action.error && <span className="text-red-500/70 ml-1">({action.error})</span>}
                                </span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  ))}
                  {(!metrics.systemHealth.subsystems || metrics.systemHealth.subsystems.length === 0) && (
                    <div className="text-xs text-slate-500 py-8 text-center">No health data — click Scan Now</div>
                  )}
                </div>
              </div>
            </>
          )}

          {/* Expandable Data Management Panel */}
          {activePanel === 'data' && (
            <>
            <div className="fixed inset-0 z-40 bg-black/60 sm:hidden" onClick={() => setActivePanel(null)} />
            <div style={{ backgroundColor: panelBg }} className="fixed inset-0 z-50 overflow-y-auto p-4 pt-6
                            sm:static sm:bg-slate-800/30 sm:p-5 sm:mb-6 sm:rounded-lg sm:border sm:border-emerald-500/30 sm:backdrop-blur sm:max-h-[80vh] sm:overflow-y-auto">
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-2">
                  <Database className="w-4 h-4 text-emerald-400" />
                  <h3 className="text-sm font-semibold tracking-wide">Data Management</h3>
                </div>
                <button onClick={() => setActivePanel(null)} className="p-2 bg-slate-800 hover:bg-slate-700 rounded transition text-slate-300 text-sm font-semibold">✕ Close</button>
              </div>
              <DataManager
                nodeId={selectedNodeId || ''}
                isFleetMode={!!(metrics.fleet?.fleet_mode && selectedNodeId)}
                authHeaders={authHeaderRef.current || {}}
              />
            </div>
            </>
          )}

          {showLogs && (
          <div className="p-6 bg-slate-800/30 border border-slate-700 rounded-lg backdrop-blur">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <Terminal className="w-4 h-4 text-slate-400" />
                <h3 className="text-sm font-semibold tracking-wide">Recent Logs</h3>
              </div>
              <button onClick={fetchMetrics} className="p-1 hover:bg-slate-700 rounded transition">
                <RefreshCw className="w-4 h-4 text-slate-400" />
              </button>
            </div>
            <div className="space-y-2 max-h-64 overflow-y-auto overflow-x-auto">
              {metrics.logs && metrics.logs.length > 0 ? (
                metrics.logs.map((log, i) => {
                  const level = log.level || 'INFO';
                  const levelColor = level === 'ERROR' || level === 'CRITICAL' ? 'text-red-400'
                    : level === 'WARNING' ? 'text-amber-400'
                    : 'text-slate-500';
                  return (
                    <div key={i} className="text-xs text-slate-400 font-mono py-1 px-2 bg-slate-900/50 rounded border border-slate-700/50">
                      <span className="text-slate-500">[{log.timestamp || '—'}]</span>
                      {' '}<span className={`font-semibold ${levelColor}`}>{level}</span>
                      {' '}{log.message || log}
                    </div>
                  );
                })
              ) : (
                <div className="text-xs text-slate-500 py-8 text-center">No logs available</div>
              )}
            </div>
          </div>
          )}

          <div className="mt-8 p-4 bg-slate-800/20 border border-slate-700/30 rounded-lg flex items-center justify-between flex-wrap gap-3">
            <div className="text-xs text-slate-400">
              Last updated: <span className="text-slate-300 font-semibold">{lastUpdate ? `${Math.round((Date.now() - lastUpdate.getTime()) / 1000)}s ago` : '—'}</span>{tickCount ? '' : ''}
            </div>
            <div className="flex gap-2 items-center flex-wrap">
              <button
                onClick={() => setShowLogs(!showLogs)}
                className={`px-3 py-1 text-xs rounded border transition flex items-center gap-1 ${
                  showLogs
                    ? 'bg-cyan-500/20 border-cyan-400 text-cyan-200'
                    : 'border-slate-600 text-slate-400 hover:border-slate-500'
                }`}
              >
                <Terminal className="w-3 h-3" /> Logs
              </button>
              <button
                onClick={() => setShowHelp(!showHelp)}
                className={`px-3 py-1 text-xs rounded border transition flex items-center gap-1 ${
                  showHelp
                    ? 'bg-amber-500/20 border-amber-400 text-amber-200'
                    : 'border-slate-600 text-slate-400 hover:border-slate-500'
                }`}
              >
                ? Help
              </button>
              <span className="text-slate-600 mx-1">|</span>
              <span className="text-xs text-slate-500 mr-1">{THEMES[theme].name}</span>
              {THEME_KEYS.map(k => (
                <button
                  key={k}
                  onClick={() => setTheme(k)}
                  title={THEMES[k].name}
                  className={`w-5 h-5 rounded-full border-2 transition-all duration-200 ${
                    theme === k
                      ? 'border-white scale-125 shadow-lg'
                      : 'border-slate-600 hover:border-slate-400 opacity-50 hover:opacity-100 hover:scale-110'
                  }`}
                  style={{ backgroundColor: THEMES[k].dot }}
                />
              ))}
            </div>
          </div>

          {/* ═══ Help Section ═══ */}
          {showHelp && (
            <div className="mb-6 p-3 sm:p-5 bg-slate-800/30 border border-amber-500/30 rounded-lg backdrop-blur animate-fadeIn max-h-[70vh] overflow-y-auto">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-sm font-semibold text-emerald-400">Help — Mysterium Node Toolkit v{toolkitVersion}</h3>
                <button onClick={() => setShowHelp(false)} className="p-1 hover:bg-slate-700 rounded text-slate-400 text-xs">✕</button>
              </div>
              <div className="space-y-4 text-xs text-slate-300">

                {/* Colour Scheme */}
                <div>
                  <h4 className="text-slate-300 font-semibold mb-2 flex items-center gap-2">
                    Colour Scheme
                    <span className="text-xs font-normal text-slate-500">currently: <span className="text-slate-300">{THEMES[theme].name}</span></span>
                  </h4>
                  <div className="flex flex-wrap gap-2">
                    {THEME_KEYS.map(k => (
                      <button key={k} onClick={() => setTheme(k)}
                        className={`flex items-center gap-2 px-3 py-1.5 rounded border text-xs transition-all duration-200 ${theme === k ? 'border-white/60 bg-slate-700/60 text-slate-100 font-semibold' : 'border-slate-600 text-slate-400 hover:border-slate-400 hover:text-slate-200'}`}>
                        <span className={`w-3 h-3 rounded-full flex-shrink-0 border ${theme === k ? 'border-white/60 scale-125' : 'border-slate-500'}`} style={{ backgroundColor: THEMES[k].dot }} />
                        {THEMES[k].name}
                      </button>
                    ))}
                  </div>
                </div>

                <div>
                  <h4 className="text-emerald-400 font-semibold mb-1">Traffic Explained</h4>
                  <p className="text-slate-400"><strong className="text-slate-300">↑ Out to consumers</strong> = content forwarded (earns MYST). <strong className="text-slate-300">↓ In from consumers</strong> = their requests (small). <strong className="text-slate-300">NIC total</strong> = physical interface including tunnel overhead (~2× VPN). <strong className="text-slate-300">Overhead</strong> = NIC − VPN. <strong className="text-slate-300">VNSTAT</strong> = persistent counters (survive reboot). <strong className="text-slate-300">PSUTIL</strong> = since-boot fallback.</p>
                </div>

                <div>
                  <h4 className="text-emerald-400 font-semibold mb-1">Sessions &amp; Consumers</h4>
                  <p className="text-slate-400"><strong className="text-slate-300">Tunnels</strong> — Live WireGuard interfaces with real-time speed. <strong className="text-slate-300">Active</strong> — matched to live tunnels (psutil ground truth). <strong className="text-slate-300">History</strong> — all pages loaded at startup. <strong className="text-slate-300">Consumers</strong> — grouped by wallet, sortable. Multiple sessions per consumer is normal — Mysterium reconnects frequently. All tabs are sortable.</p>
                </div>

                <div>
                  <h4 className="text-emerald-400 font-semibold mb-1">Earnings &amp; Settle</h4>
                  <p className="text-slate-400"><strong className="text-slate-300">Unsettled</strong> = earned but not yet settled on-chain. Auto-settles at 5 MYST. <strong className="text-slate-300">Lifetime Gross (pre-fee)</strong> = all-time cumulative earnings before 20% Hermes fee — never decreases. <strong className="text-slate-300">Hermes Channel</strong> = MYST sitting in the Hermes payment channel ready to withdraw to your wallet. Shows 0.0000 (withdrawn to wallet) when you have already moved funds to an external wallet — this is correct. <strong className="text-slate-300">Daily/Weekly/Monthly</strong> = delta between snapshots stored in earnings_history.db (SQLite), recorded every 10 minutes. Daily needs 24h of history, weekly 7d, monthly 30d. <strong className="text-slate-300">RATE LIMITED</strong> = identity API blocked — history paused, no snapshot saved. Settle auto-fetches hermes_id from the node.</p>
                </div>

                <div>
                  <h4 className="text-emerald-400 font-semibold mb-1">MYST Token Price</h4>
                  <p className="text-slate-400">Live MYST/EUR and MYST/USD shown next to your unsettled balance. Fetched every 5 minutes from <strong className="text-slate-300">CoinPaprika</strong> (USD price) and <strong className="text-slate-300">Frankfurter ECB</strong> (EUR rate) — both completely free, no account, no API key. If unavailable the last known price is shown as <strong className="text-slate-300">(stale)</strong>. Also shown per day/week/month when history is tracked.</p>
                </div>

                <div>
                  <h4 className="text-emerald-400 font-semibold mb-1">Earnings History Chart</h4>
                  <p className="text-slate-400">Bar chart built from snapshots recorded every 10 minutes. <strong className="text-slate-300">Daily</strong> = last 30 daily bars. <strong className="text-slate-300">Weekly/Monthly/All</strong> = aggregated from all stored snapshots. Today highlighted in cyan. Corrupt snapshots (from rate-limited sessions) are auto-detected and removed. Use the <strong className="text-slate-300">⚙ Data</strong> button to selectively delete corrupted periods (first week, first month, etc.) — requires two-click confirmation.</p>
                </div>

                <div>
                  <h4 className="text-emerald-400 font-semibold mb-1">Data Management &amp; Retention</h4>
                  <p className="text-slate-400">The <strong className="text-slate-300">Data Management</strong> panel (below System Health) shows all 7 databases with record counts and date ranges. Use it to manually delete data older than N days or wipe a type entirely — two-click confirmation required.</p>
                  <p className="text-slate-400 mt-1"><strong className="text-slate-300">Auto-retention</strong> — databases are pruned automatically once per calendar day during the slow-tier cycle. Default windows: earnings 365d · sessions 90d · traffic 730d · quality 90d · system 30d · services 30d · uptime 90d. The panel shows the active limits and the date of the last prune.</p>
                  <p className="text-slate-400 mt-1"><strong className="text-slate-300">Override retention</strong> — add a <code className="bg-slate-800 px-1 rounded">data_retention</code> object to <code className="bg-slate-800 px-1 rounded">config/setup.json</code> to change any window (in days):<br/>
                  <code className="bg-slate-800 px-1 rounded text-cyan-300">{`"data_retention": {"earnings": 730, "sessions": 180, "quality": 60}`}</code><br/>
                  Only the keys you specify are overridden — the rest keep their defaults. Restart the backend after editing.</p>
                </div>

                <div>
                  <h4 className="text-emerald-400 font-semibold mb-1">Node Analytics</h4>
                  <p className="text-slate-400"><strong className="text-slate-300">API cache row</strong> (grey) — live session data. Earnings are low because Mysterium zeroes token values after settlement. <strong className="text-slate-300">Archive row</strong> (green) — from sessions_history.db. Token values are frozen at fetch time before zeroing, giving accurate historical earnings. Includes service type breakdown and consumer origin.</p>
                  <p className="text-slate-400 mt-1"><strong className="text-slate-300">Service types</strong> — reported directly by the Mysterium TequilAPI. <strong className="text-slate-300">B2B VPN and data transfer</strong> = B2B streaming/data traffic (access policy: mysterium). <strong className="text-slate-300">B2B Data Scraping</strong> = B2B scraping traffic (access policy: mysterium). <strong className="text-slate-300">VPN</strong> = Mysterium VPN app users (access policy: mysterium). <strong className="text-slate-300">Public</strong> = open network, no access policy — includes Mysterium Dark and 3rd party consumers (service type: wireguard in TequilAPI). <strong className="text-slate-300">QUIC Scraping</strong> = QUIC protocol variant for scraping. <strong className="text-slate-300">Monitoring</strong> = Mysterium network probe sessions, excluded from analytics.</p>
                </div>

                <div>
                  <h4 className="text-emerald-400 font-semibold mb-1">Node Quality &amp; Online Time</h4>
                  <p className="text-slate-400"><strong className="text-slate-300">Quality Score</strong> — Discovery composite 0–3 (uptime × latency × bandwidth × packet loss). <strong className="text-slate-300">24h net</strong> = % time Discovery monitoring agent reached your node (matches mystnodes.com). <strong className="text-slate-300">Net Loss</strong> = % of monitoring probe packets dropped by Mysterium's Discovery agent — a network quality measurement, not an API error. <strong className="text-slate-300">Connected %</strong> = 100 − pkt loss (matches mystnodes.com connected bar). <strong className="text-slate-300">24h/30d local</strong> = toolkit-observed poll cycles. <strong className="text-slate-300">(Xd of 30)</strong> shows how many days of local data have built up. <strong className="text-slate-300">⚡ Test Node</strong> = live fresh probe, bypasses 10-minute cache.</p>
                </div>

                <div>
                  <h4 className="text-slate-300 font-semibold mb-1">Data Traffic Card</h4>
                  <p className="text-slate-400"><strong className="text-slate-300">Today / Month</strong> = live from vnstat. <strong className="text-slate-300">3 Months / Year / All Time</strong> = from traffic_history.db (SQLite). At first start, all historical vnstat monthly data is auto-imported — history goes back to when vnstat was installed. The database grows ~1 KB/day and is migrated automatically between versions.</p>
                </div>

                <div>
                  <h4 className="text-emerald-400 font-semibold mb-1">Fleet Monitor (Multi-Node) <span className="text-amber-400 font-normal text-[10px] ml-1">BETA</span></h4>
                  <p className="text-slate-400">
                    Monitor multiple Mysterium nodes from one central dashboard. Each node keeps its own data — nothing is ever mixed between nodes.<br/><br/>

                    <strong className="text-slate-300">Installation types:</strong><br/>
                    <strong className="text-emerald-400">Type 1 — Full install</strong> — node on this machine, full dashboard. Default for your main node machine.<br/>
                    <strong className="text-emerald-400">Type 2 — Fleet master</strong> — central dashboard. Guides you through nodes.json setup after the wizard.<br/>
                    <strong className="text-emerald-400">Type 3 — Lightweight backend</strong> — backend only, no browser UI, no Node.js needed. For remote nodes monitored by a fleet master.<br/><br/>

                    <strong className="text-slate-300">Step 1</strong> — Install toolkit on each node (Type 1 or Type 3)<br/>
                    <strong className="text-slate-300">Step 2</strong> — Find each node's API key: <code className="bg-slate-800 px-1 rounded">config/setup.json</code> → <code className="bg-slate-800 px-1 rounded">dashboard_api_key</code><br/>
                    <strong className="text-slate-300">Step 3</strong> — Ensure port 5000 is reachable (router port forwarding if behind NAT)<br/>
                    <strong className="text-slate-300">Step 4</strong> — Create <code className="bg-slate-800 px-1 rounded">config/nodes.json</code> on the central machine (template: <code className="bg-slate-800 px-1 rounded">config/nodes.json.example</code>)<br/>
                    <strong className="text-slate-300">Step 5</strong> — Restart toolkit. Fleet overview appears automatically.<br/><br/>
                  </p>
                  <pre className="bg-slate-900/60 rounded p-2 text-[10px] text-cyan-300 overflow-x-auto mt-1 mb-2">{`{
  "nodes": [
    {
      "id": "vps",
      "label": "My VPS Node",
      "url": "http://localhost:4449",
      "toolkit_url": "http://localhost:5000",
      "toolkit_api_key": "YOUR_VPS_API_KEY"
    },
    {
      "id": "home",
      "label": "Home Node",
      "url": "http://YOUR_HOME_IP:4449",
      "toolkit_url": "http://YOUR_HOME_IP:5000",
      "toolkit_api_key": "YOUR_HOME_API_KEY"
    }
  ]
}`}</pre>
                  <p className="text-slate-400">
                    <strong className="text-slate-300">Hot-reload:</strong> edit nodes.json while running — changes apply within 30s.<br/>
                    <span className="text-amber-400">Fleet mode is in beta — verify port reachability before relying on it in production.</span>
                  </p>
                </div>

                <div>
                  <h4 className="text-emerald-400 font-semibold mb-1">Node Control &amp; Config</h4>
                  <p className="text-slate-400"><strong className="text-slate-300">Restart</strong> — tries systemd → service → Docker → docker-compose → TequilAPI stop. <strong className="text-slate-300">Settle</strong> — fetches hermes_id from identity endpoint, calls /transactor/settle/sync. 20% Hermes fee deducted automatically. <strong className="text-slate-300">⚙ Config</strong> — payment interval tuning. <span className="text-amber-400">Only works when the toolkit runs on the same machine as the node</span> — requires <code className="bg-slate-800 px-1 rounded">myst</code> binary in PATH and passwordless sudo. High Load preset for 50+ sessions. Node restart required after applying.</p>
                </div>

                <div>
                  <h4 className="text-emerald-400 font-semibold mb-1">Setup &amp; Kernel Tuning</h4>
                  <p className="text-slate-400">Setup (setup.sh) runs kernel optimisations automatically at step 9 — no manual commands needed. Creates: <code className="bg-slate-800 px-1 rounded">/etc/sysctl.d/99-mysterium-node.conf</code> (kernel network params), <code className="bg-slate-800 px-1 rounded">mysterium-cpu-governor.service</code> (CPU performance on boot), <code className="bg-slate-800 px-1 rounded">tcp_bbr.conf</code> (BBR on boot), <code className="bg-slate-800 px-1 rounded">mysterium-rps-tuning.service</code> (NIC/RPS on boot). All survive reboot. If you skipped setup or upgraded from an older version, use the System Health panel to apply and persist missing fixes.</p>
                  <p className="text-slate-400 mt-1"><strong className="text-slate-300">Existing config detection</strong> — if <code className="bg-slate-800 px-1 rounded">config/setup.json</code> already exists when you run setup.sh, you will be asked whether to keep it. Choosing yes skips the entire setup wizard and reconstructs <code className="bg-slate-800 px-1 rounded">.env</code> from the existing config automatically. Your node password, API key, port and all other settings are preserved.</p>
                  <p className="text-slate-400 mt-1"><strong className="text-slate-300">nodes.json migration</strong> — when setup.sh detects a previous toolkit installation, it automatically copies <code className="bg-slate-800 px-1 rounded">config/nodes.json</code> (fleet node list) alongside earnings, sessions and traffic databases. On update via update.sh, nodes.json is backed up before git pull and restored if the pull would overwrite it.</p>
                  <p className="text-slate-400 mt-1"><strong className="text-slate-300">Autostart (option 9)</strong> — installs a systemd service <code className="bg-slate-800 px-1 rounded">mysterium-toolkit</code> that starts the backend automatically at every boot. The service starts <strong className="text-slate-300">after</strong> the Mysterium node service so snapshots are never missed at boot. Restarts automatically after crashes (15 second delay, up to 5 retries). Works on laptops and VPS — no login required.</p>
                  <p className="text-slate-400 mt-1"><span className="text-amber-400 font-semibold">Type 3 (lightweight) autostart order:</span> start the backend manually first via option 1 or <code className="bg-slate-800 px-1 rounded">./start.sh</code>, <strong className="text-slate-300">then</strong> activate autostart via option 9. Activating autostart before the backend is running will fail on this node type.</p>
                  <p className="text-slate-400 mt-1"><span className="text-amber-400 font-semibold">First-enable tip:</span> on the first enable, the service may show a warning and fail within the 25s window — this is normal. Systemd auto-retries after 15s. If still failed: <strong className="text-slate-300">disable → wait 10s → enable again</strong>. The second attempt always succeeds because the port is fully free by then.</p>
                </div>

                <div>
                  <h4 className="text-emerald-400 font-semibold mb-1">Health &amp; System (13 subsystems)</h4>
                  <p className="text-slate-400"><strong className="text-slate-300">⚡ Fix &amp; Lock</strong> = apply + persist (survives reboot). <strong className="text-slate-300">Fix only</strong> = live fix, resets on reboot. <strong className="text-slate-300">NIC Checksum</strong> — smart: if fix already applied (rx off), historical error counter is silently ignored — no false alarm after fixing. <strong className="text-slate-300">BBR</strong> — TCP congestion control for better VPN throughput. Temps: green &lt;60°C, amber &lt;80°C, red ≥80°C.</p>
                  <p className="text-slate-400 mt-1"><strong className="text-slate-300">CPU Governor (adaptive)</strong> — adjusts automatically every 10 minutes based on active session count: 0 sessions → powersave · 1–5 → schedutil (kernel-managed) · 6+ → performance. No manual action needed. Keeps CPU cool at idle, fast under load.</p>
                  <p className="text-slate-400 mt-1"><strong className="text-slate-300">Connection Tracking (adaptive)</strong> — conntrack table auto-scales with VPN tunnel count: 0–4 tunnels → 128K · 5–19 → 256K · 20+ → 512K. Applied automatically every 10 minutes alongside the governor.</p>
                  <p className="text-slate-400 mt-1"><strong className="text-slate-300">Sudoers</strong> — setup.sh writes <code className="bg-slate-800 px-1 rounded">/etc/sudoers.d/mysterium-toolkit</code> with narrow passwordless rules for specific commands only (sysctl, ethtool, modprobe, systemctl restart mysterium-node, cpupower, etc.). These rules never expire — health fixes work permanently without a timeout.</p>
                </div>

                <div>
                  <h4 className="text-slate-400 font-semibold mb-1">CLI, Mobile &amp; Phone Access</h4>
                  <p className="text-slate-400">CLI has 2 pages: <strong className="text-slate-300">1 Status</strong> (node info, resources, quality, uptime) and <strong className="text-slate-300">2 Earnings</strong> (balance, daily/weekly/monthly, history chart). Auto-adapts to screen size: full mode (≥90×27), compact mode (&lt;90 cols or &lt;27 rows). Keys: <strong className="text-slate-300">?</strong>=help, <strong className="text-slate-300">w</strong>=restart, <strong className="text-slate-300">$</strong>=settle, <strong className="text-slate-300">T</strong>=test node, <strong className="text-slate-300">t</strong>=theme, <strong className="text-slate-300">r</strong>=refresh, <strong className="text-slate-300">+/-</strong>=interval, <strong className="text-slate-300">Tab</strong>=next page. <strong className="text-slate-300">Phone/LAN:</strong> open <code className="bg-slate-800 px-1 rounded">http://&lt;your-ip&gt;:5000</code>. Ensure ufw allows port 5000.</p>
                </div>

                <div>
                  <h4 className="text-emerald-400 font-semibold mb-1">Dashboard Authentication</h4>
                  <p className="text-slate-400">
                    Two auth modes — set during <code className="bg-slate-800 px-1 rounded">setup.sh</code>, stored in <code className="bg-slate-800 px-1 rounded">.env</code> and <code className="bg-slate-800 px-1 rounded">config/setup.json</code>.<br/>
                    <strong className="text-slate-300">API Key mode</strong> — paste a Bearer token in the login screen. <span className="text-amber-400">Always copy/paste — never type the key manually</span> (one wrong character = locked out). Key is in <code className="bg-slate-800 px-1 rounded">.env</code> as <code className="bg-slate-800 px-1 rounded">DASHBOARD_API_KEY</code>.<br/>
                    <strong className="text-slate-300">Admin + Password mode</strong> — username is always <code className="bg-slate-800 px-1 rounded">admin</code>, password set during setup. Find it in <code className="bg-slate-800 px-1 rounded">.env</code> as <code className="bg-slate-800 px-1 rounded">DASHBOARD_PASSWORD</code>.<br/>
                    <strong className="text-slate-300">Localhost bypass</strong> — 127.0.0.1 always bypasses auth (no login needed locally).<br/>
                    <strong className="text-slate-300">Session</strong> — auth is stored in localStorage; closing the tab does not log you out.
                  </p>
                </div>

                <div>
                  <h4 className="text-emerald-400 font-semibold mb-1">On-Chain Wallet</h4>
                  <p className="text-slate-400"><strong className="text-slate-300">MYST balance on Polygon</strong> — fetched live from Polygonscan API. Shows your actual on-chain wallet balance. <strong className="text-slate-300">Beneficiary</strong> = the Polygon wallet address where your settled MYST lands — set during setup or via the node's own UI. <strong className="text-slate-300">Settlement history</strong> = every on-chain settlement with date, amount, and a direct Polygonscan link. <strong className="text-slate-300">Polygonscan API key</strong> — free at etherscan.io → My Account → API Keys. Without it: balance refreshes once per hour. With it: refreshes on demand after each settlement. Add it to <code className="bg-slate-800 px-1 rounded">config/setup.json</code> as <code className="bg-slate-800 px-1 rounded">polygonscan_api_key</code> or re-run the setup wizard. <strong className="text-slate-300">Note:</strong> Polygon and Ethereum are separate chains — the balance shown is MYST on Polygon only.</p>
                </div>

                <div>
                  <h4 className="text-slate-400 font-semibold mb-1">npm &amp; node_modules</h4>
                  <p className="text-slate-400"><strong className="text-slate-300">npm</strong> is a system package — the toolkit never installs or removes it. <strong className="text-slate-300">node_modules/</strong> is built during setup and not stored in the repository. On a fresh clone, <code className="bg-slate-800 px-1 rounded">setup.sh</code> installs and builds everything automatically. On update via <code className="bg-slate-800 px-1 rounded">update.sh</code>, the frontend is rebuilt from source.</p>
                </div>

                <div>
                  <h4 className="text-slate-400 font-semibold mb-1">Compatibility</h4>
                  <p className="text-slate-400">Python 3.8+. CLI needs: python3, psutil, requests. Web needs: Node.js 18+ + npm (auto-installed). Optional: vnstat, ethtool, ufw, docker. Works on: Debian, Ubuntu, Parrot, Fedora, Arch, Alpine. Environments: bare metal, Docker, LXC, Proxmox.</p>
                </div>

              </div>
            </div>
          )}

          
          {/* ═══ Credit Footer ═══ */}
          <div className="mt-12 mb-6 text-center">
            <div className="inline-flex flex-col items-center gap-2 px-8 py-4 rounded-xl bg-slate-900/20 border border-slate-800/50 backdrop-blur">
              <div className="flex items-center gap-2 text-xs text-slate-500">
                <span className="text-slate-600">⟨</span>
                <span>Crafted with</span>
                <span className="text-rose-400 animate-pulse text-sm">♥</span>
                <span>by</span>
                <span className="font-semibold text-emerald-400/80">Ian Johnsons</span>
                <span className="text-slate-600">⟩</span>
              </div>
              <div className="text-xs text-slate-600 tracking-wider">
                Mysterium Node Toolkit v{toolkitVersion} — Free &amp; Open Source (CC BY-NC-SA 4.0)
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // ============ FALLBACK: Error State ============
  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-950 via-slate-900 to-slate-800 text-white flex items-center justify-center p-6">
      <div className="max-w-md text-center">
        <div className="inline-block p-4 rounded-lg bg-amber-500/10 border border-amber-500/30 mb-6">
          <AlertCircle className="w-8 h-8 text-amber-400" />
        </div>
        <h1 className="text-2xl font-bold mb-4">Unexpected State</h1>
        <p className="text-slate-400 mb-6">Something went wrong during initialization.</p>
        <button
          onClick={() => { setSetupMode('loading'); loadConfig(); }}
          className="px-6 py-2 bg-emerald-500 hover:bg-emerald-600 text-white rounded font-semibold transition"
        >
          Retry
        </button>
      </div>
    </div>
  );
};

// ============ COMPONENTS ============

// ---- Analytics Card ----
const EarningsHistoryCard = ({ backendUrl, authHeaders }) => {
  const [data, setData] = React.useState(null);
  const [view, setView] = React.useState('daily');
  const [loading, setLoading] = React.useState(false);


  const loadChart = React.useCallback(() => {
    if (!backendUrl) return;
    setLoading(true);
    fetch(`${backendUrl}/earnings/chart`, { headers: authHeaders || {} })
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, [backendUrl]);

  React.useEffect(() => { loadChart(); }, [loadChart]);

  if (loading) return (
    <div className="mb-6 p-4 bg-slate-800/30 border border-slate-700 rounded-lg backdrop-blur">
      <div className="text-xs text-slate-500">Loading earnings history…</div>
    </div>
  );

  if (!data || !data.daily || data.daily.length === 0) return (
    <div className="mb-6 p-4 bg-slate-800/30 border border-slate-700 rounded-lg backdrop-blur">
      <div className="flex items-center justify-between mb-1">
        <h3 className="text-sm font-semibold text-slate-300 tracking-wide">Earnings History</h3>
        </div>
      <div className="text-xs text-slate-600 py-3 text-center">
        No snapshots yet — the toolkit records one every 10 minutes.<br/>Check back after 24h for the first daily bar.
      </div>
    </div>
  );

  const allDaily = data.daily || [];
  const totalCalendarDays = data.days || allDaily.length;

  // Auto-aggregation thresholds for the All tab
  // < 60 days  → daily bars (as-is)
  // 60–180 days → weekly bars
  // > 180 days  → monthly bars
  const allAutoGranularity = totalCalendarDays < 60 ? 'day'
                           : totalCalendarDays < 180 ? 'week'
                           : 'month';

  const _aggregateWeekly = (days) => {
    const wkMap = {};
    days.forEach(d => {
      const dt = new Date(d.date);
      const jan1 = new Date(dt.getFullYear(), 0, 1);
      const wkNum = Math.ceil(((dt - jan1) / 86400000 + jan1.getDay() + 1) / 7);
      const wk = `${dt.getFullYear()}-W${String(wkNum).padStart(2, '0')}`;
      wkMap[wk] = (wkMap[wk] || 0) + d.earned;
    });
    return Object.entries(wkMap).map(([date, earned]) => ({ date, earned: Math.round(earned * 10000) / 10000 }));
  };

  const _aggregateMonthly = (days) => {
    const mMap = {};
    days.forEach(d => {
      const mo = d.date.slice(0, 7);
      mMap[mo] = (mMap[mo] || 0) + d.earned;
    });
    return Object.entries(mMap).map(([date, earned]) => ({ date, earned: Math.round(earned * 10000) / 10000 }));
  };

  // Build view-specific chart data
  let chartDays;
  if (view === 'daily') {
    // Last 30 calendar days — based on actual date, not array slice
    const cutoff = new Date();
    cutoff.setDate(cutoff.getDate() - 29);
    const cutoffStr = cutoff.toISOString().slice(0, 10);
    chartDays = allDaily.filter(d => d.date >= cutoffStr);
  } else if (view === 'weekly') {
    chartDays = _aggregateWeekly(allDaily);
  } else if (view === 'monthly') {
    chartDays = _aggregateMonthly(allDaily);
  } else {
    // All tab — auto granularity based on history length
    if (allAutoGranularity === 'week') {
      chartDays = _aggregateWeekly(allDaily);
    } else if (allAutoGranularity === 'month') {
      chartDays = _aggregateMonthly(allDaily);
    } else {
      chartDays = allDaily;
    }
  }

  // Subtitle: show the actual range visible in the current view
  const visibleOldest = chartDays.length > 0 ? chartDays[0].date : data.oldest;
  const visibleNewest = chartDays.length > 0 ? chartDays[chartDays.length - 1].date : data.newest;
  const allGranularityLabel = allAutoGranularity === 'week' ? 'weekly bars'
                            : allAutoGranularity === 'month' ? 'monthly bars'
                            : 'daily bars';
  const visibleDays = view === 'daily' ? 'last 30 days'
                    : view === 'all'   ? `${data.days} calendar days · ${allGranularityLabel}`
                    : `${data.days} calendar days`;

  const maxEarned = Math.max(...chartDays.map(d => d.earned), 0.0001);
  const totalShown = chartDays.reduce((s, d) => s + d.earned, 0);
  const today = new Date().toISOString().slice(0, 10);

  // Fix 5: always use days-with-data as divisor (non-gap days), all views
  const daysWithData = chartDays.filter(d => !d.gap && d.earned > 0).length;

  // Fix 6: tracked label per view
  const allDaysWithData = allDaily.filter(d => !d.gap).length;
  const trackedLabel = view === 'daily'
    ? `${chartDays.filter(d => !d.gap).length} / 30`
    : view === 'all'
    ? `${allDaysWithData} / ${data.days}`
    : null;
  // Fix 4: older data exists beyond daily 30-day window
  const hasOlderData = view === 'daily' && allDaily.length > chartDays.length;

  const tabs = [
    { key: 'daily',   label: 'Daily',   title: 'One bar per day — last 30 days' },
    { key: 'weekly',  label: 'Weekly',  title: 'One bar per week — full history' },
    { key: 'monthly', label: 'Monthly', title: 'One bar per month — full history' },
    { key: 'all',     label: 'All',     title: `Full history — auto scale (${allGranularityLabel})` },
  ];

  return (
    <div className="mb-6 p-4 bg-slate-800/30 border border-slate-700 rounded-lg backdrop-blur">
      {/* Header */}
      <div className="flex items-start justify-between mb-3 gap-2 flex-wrap">
        <div>
          <h3 className="text-sm font-semibold text-slate-300 tracking-wide">Earnings History</h3>
          <div className="text-[10px] text-slate-600 mt-0.5">
            {visibleOldest} → {visibleNewest} · {visibleDays}
          </div>
        </div>
        <div className="flex gap-1 flex-shrink-0 flex-wrap items-center">
          {tabs.map(tab => (
            <button key={tab.key} onClick={() => setView(tab.key)} title={tab.title}
              className={`px-2 py-1 text-[10px] rounded font-medium transition ${view === tab.key
                ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                : 'bg-slate-800/60 text-slate-500 border border-slate-700 hover:text-slate-300'}`}>
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {/* Bar chart — fixed height, bars flex to fill width */}
      <div className="relative h-28 w-full">
        <div className="flex items-end gap-px h-full w-full">
          {chartDays.map((d, i) => {
            const hPct = maxEarned > 0 ? Math.max(2, (d.earned / maxEarned) * 100) : 2;
            const isToday = d.date === today;
            const isEmpty = d.earned === 0;
            return (
              <div key={i} className="flex-1 flex flex-col justify-end h-full min-w-[2px] group relative">
                <div
                  className={`w-full rounded-t-sm ${isToday ? 'bg-cyan-400' : isEmpty ? 'bg-slate-700/30' : 'bg-emerald-500/70 group-hover:bg-emerald-400'}`}
                  style={{ height: `${hPct}%` }}
                />
                {/* Hover tooltip */}
                <div className="absolute bottom-full mb-1 left-1/2 -translate-x-1/2 hidden group-hover:flex flex-col items-center bg-slate-900 border border-slate-700 rounded px-2 py-1 text-[10px] text-slate-200 whitespace-nowrap z-20 pointer-events-none shadow-lg">
                  <span className="text-slate-400">{d.date}{isToday ? ' (today)' : ''}</span>
                  <span className="text-emerald-300 font-semibold">{d.earned.toFixed(4)} MYST{isToday ? ' so far' : ''}</span>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* X-axis */}
      {chartDays.length > 1 && (
        <div className="flex justify-between text-[9px] text-slate-700 mt-1">
          <span>{chartDays[0]?.date}</span>
          {chartDays.length > 6 && <span>{chartDays[Math.floor(chartDays.length / 2)]?.date}</span>}
          <span>{chartDays[chartDays.length - 1]?.date}</span>
        </div>
      )}

      {/* Fix 4: note when daily view hides older data */}
      {hasOlderData && (
        <div className="text-[10px] text-slate-600 mt-1">
          Showing last 30 days. Switch to <button onClick={() => setView('all')} className="text-emerald-500 hover:text-emerald-400 underline">All</button> for full history ({data.days} days, {totalShown < allDaily.reduce((s,d) => s+d.earned,0) ? allDaily.reduce((s,d) => s+d.earned,0).toFixed(4) : totalShown.toFixed(4)} MYST).
        </div>
      )}

      {/* Summary */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mt-3 pt-3 border-t border-slate-700/40 text-xs">
        <div>
          <div className="text-slate-500">Period total</div>
          <div className="text-emerald-300 font-semibold">{totalShown.toFixed(4)} MYST</div>
        </div>
        <div>
          <div className="text-slate-500">Peak {view === 'daily' ? 'day' : view === 'weekly' ? 'week' : view === 'monthly' ? 'month' : 'day'}</div>
          <div className="text-slate-300 font-medium">{maxEarned.toFixed(4)} MYST</div>
        </div>
        <div>
          <div className="text-slate-500">Avg {view === 'daily' ? 'day' : view === 'weekly' ? 'week' : view === 'monthly' ? 'month' : 'day'}</div>
          {/* Fix 5: always divide by days with actual data */}
          <div className="text-slate-300 font-medium">{daysWithData > 0 ? (totalShown / daysWithData).toFixed(4) : '—'} MYST</div>
        </div>
        <div>
          <div className="text-slate-500">
            {view === 'weekly' ? 'Weeks'
           : view === 'monthly' ? 'Months'
           : view === 'all' && allAutoGranularity === 'week' ? 'Weeks'
           : view === 'all' && allAutoGranularity === 'month' ? 'Months'
           : <span title="Days in the last 30 days where an earnings snapshot was recorded. Grows by 1 each day the toolkit runs.">Tracked</span>}
          </div>
          {/* Fix 6: show "X days with data / Y calendar days" for daily/all-daily */}
          <div className="text-slate-300 font-medium" title={
            (view === 'daily' || (view === 'all' && allAutoGranularity === 'day'))
              ? `${chartDays.filter(d => !d.gap).length} days with earnings snapshots out of the last 30 days. Increases by 1 each day the toolkit is running.`
              : undefined
          }>
            {trackedLabel !== null && (view === 'daily' || (view === 'all' && allAutoGranularity === 'day'))
              ? trackedLabel
              : chartDays.length}
          </div>
        </div>
      </div>
    </div>
  );
};

const DataTrafficCard = ({ bandwidth, backendUrl, authHeaders }) => {
  const bw  = bandwidth || {};
  const nic = bw.vnstat_nic_name || 'NIC';
  const src = (bw.data_source || 'vnstat').toUpperCase();

  const [view, setView]       = React.useState('today');
  const [histData, setHistData] = React.useState(null);
  const [loading, setLoading] = React.useState(false);


  // Fetch history when view changes to anything other than today/month
  React.useEffect(() => {
    if (view === 'today' || view === 'month') { setHistData(null); return; }
    if (!backendUrl) return;
    const rangeMap = { '3month': '3month', 'year': 'year', 'all': 'all' };
    const r = rangeMap[view] || 'all';
    setLoading(true);
    fetch(`${backendUrl}/traffic/history?range=${r}`, { headers: authHeaders || {} })
      .then(res => res.json())
      .then(d => { setHistData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, [view, backendUrl]);

  const MB  = 1;            // already in MB from backend
  const fmtGB = (mb) => {
    if (!mb || mb === 0) return '0 MB';
    if (mb >= 1024 * 1024) return `${(mb / 1024 / 1024).toFixed(2)} TiB`;
    if (mb >= 1024)        return `${(mb / 1024).toFixed(2)} GiB`;
    if (mb >= 1)           return `${mb.toFixed(1)} MB`;
    return `${(mb * 1024).toFixed(0)} KB`;
  };

  // Current period data from live bandwidth metrics
  const live = {
    today: {
      vpn_rx: bw.vpn_today_in    || 0,
      vpn_tx: bw.vpn_today_out   || 0,
      vpn_tot: bw.vpn_today_total|| 0,
      nic_rx: bw.vnstat_today_rx || 0,
      nic_tx: bw.vnstat_today_tx || 0,
      nic_tot: bw.vnstat_today_total || 0,
    },
    month: {
      vpn_rx: bw.vpn_month_in    || 0,
      vpn_tx: bw.vpn_month_out   || 0,
      vpn_tot: bw.vpn_month_total|| 0,
      nic_rx: bw.vnstat_month_rx || 0,
      nic_tx: bw.vnstat_month_tx || 0,
      nic_tot: bw.vnstat_month_total || 0,
    },
  };

  // For history views, sum from SQLite rows
  const hist = histData ? {
    vpn_rx:  histData.period_vpn_rx  || 0,
    vpn_tx:  histData.period_vpn_tx  || 0,
    vpn_tot: histData.period_vpn_total || 0,
    nic_rx:  histData.period_nic_rx  || 0,
    nic_tx:  histData.period_nic_tx  || 0,
    nic_tot: histData.period_nic_total || 0,
  } : null;

  const alltime = histData?.alltime;

  const d = view === 'today' ? live.today
          : view === 'month' ? live.month
          : hist;

  const tabs = [
    { key: 'today',  label: 'Today' },
    { key: 'month',  label: 'Month' },
    { key: '3month', label: '3 Months' },
    { key: 'year',   label: 'Year' },
    { key: 'all',    label: 'All Time' },
  ];

  // Today and Month come from live vnstat (bandwidth prop).
  // 3 Months / Year / All Time come from SQLite history endpoint.
  // The history endpoint now supplements the current month with live vnstat data
  // so "3 Months" >= "Month" always holds.

  const StatRow = ({ label, tx, rx, total, color }) => (
    <div className="grid grid-cols-4 gap-1 py-1.5 border-b border-slate-700/30 text-xs last:border-0 items-center">
      <div className="text-slate-400 truncate">{label}</div>
      <div className={`${color || 'text-emerald-300'} font-semibold text-right tabular-nums`}>{fmtGB(tx)}</div>
      <div className="text-slate-400 text-right tabular-nums">{fmtGB(rx)}</div>
      <div className="text-slate-300 font-semibold text-right tabular-nums">{fmtGB(total)}</div>
    </div>
  );

  return (
    <div className="mb-6 p-4 bg-slate-800/30 border border-slate-700 rounded-lg backdrop-blur">
      {/* Header */}
      <div className="flex items-start justify-between mb-3 gap-2 flex-wrap">
        <div>
          <h3 className="text-sm font-semibold text-slate-300 tracking-wide">Data Traffic</h3>
          <div className="text-[10px] text-slate-600 mt-0.5">{nic} · {src}
            {alltime?.oldest && <span className="ml-1">· history from {alltime.oldest}</span>}
          </div>
        </div>
        <div className="flex gap-1 flex-wrap justify-end items-center">
          {tabs.map(t => (
            <button key={t.key} onClick={() => setView(t.key)}
              className={`px-2 py-1 text-[10px] rounded font-medium transition ${view === t.key
                ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/30'
                : 'bg-slate-800/60 text-slate-500 border border-slate-700 hover:text-slate-300'}`}>
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {/* Column headers */}
      {/* Column headers */}
      <div className="grid grid-cols-4 gap-1 mb-1 text-[10px] text-slate-600 uppercase tracking-wider">
        <div></div>
        <div className="text-right">↑ Out</div>
        <div className="text-right">↓ In</div>
        <div className="text-right">Total</div>
      </div>

      {loading ? (
        <div className="text-xs text-slate-500 py-4 text-center">Loading…</div>
      ) : !d ? (
        <div className="text-xs text-slate-600 py-4 text-center">No data yet for this period</div>
      ) : (
        <>
          <StatRow label="VPN traffic"     tx={d.vpn_tx}  rx={d.vpn_rx}  total={d.vpn_tot}  color="text-emerald-300" />
          <StatRow label={`${nic} total`}   tx={d.nic_tx}  rx={d.nic_rx}  total={d.nic_tot}  color="text-cyan-300" />
          {d.nic_tot > 0 && d.vpn_tot > 0 && (
            <div className="grid grid-cols-4 gap-1 py-1 text-xs">
              <div className="text-slate-600">Overhead</div>
              <div className="col-span-2"></div>
              <div className="text-slate-500 text-right tabular-nums">{fmtGB(Math.max(0, d.nic_tot - d.vpn_tot))}</div>
            </div>
          )}

          {/* All-time summary strip */}
          {alltime && alltime.days > 0 && (
            <div className="mt-3 pt-3 border-t border-slate-700/40 grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
              <div>
                <div className="text-slate-600 text-[10px]">All-time VPN</div>
                <div className="text-emerald-300 font-semibold">{fmtGB(alltime.vpn_rx_mb + alltime.vpn_tx_mb)}</div>
              </div>
              <div>
                <div className="text-slate-600 text-[10px]">All-time NIC</div>
                <div className="text-cyan-300 font-semibold">{fmtGB(alltime.nic_rx_mb + alltime.nic_tx_mb)}</div>
              </div>
              <div>
                <div className="text-slate-600 text-[10px]" title="Number of daily rows recorded in the database — not calendar days">
                  Recorded days
                </div>
                <div className="text-slate-300 font-medium">{alltime.days}</div>
              </div>
              <div>
                <div className="text-slate-600 text-[10px]">Since</div>
                <div className="text-slate-400 font-medium">{alltime.oldest || '—'}</div>
              </div>
            </div>
          )}
          {/* Fix 8: note when all history fits within the selected window */}
          {histData && alltime && (view === '3month' || view === 'year') && (() => {
            const oldestDate = alltime.oldest ? new Date(alltime.oldest) : null;
            if (!oldestDate) return null;
            const windowDays = view === '3month' ? 92 : 366;
            const windowStart = new Date();
            windowStart.setDate(windowStart.getDate() - windowDays);
            if (oldestDate >= windowStart) {
              return (
                <div className="mt-2 text-[10px] text-slate-600 italic">
                  All recorded history fits within this window — totals match All Time.
                </div>
              );
            }
            return null;
          })()}
        </>
      )}

      {/* Per-tunnel breakdown — today only */}
      {view === 'today' && bw.vpn_interfaces && Object.keys(bw.vpn_interfaces).length > 0 && (
        <div className="mt-3 pt-3 border-t border-slate-700/40">
          <div className="text-[10px] text-slate-600 uppercase tracking-wider mb-1">Per tunnel</div>
          <div className="space-y-1">
            {Object.entries(bw.vpn_interfaces).map(([name, iface]) => {
              const rx = iface.rx_mb || 0;
              const tx = iface.tx_mb || 0;
              return (
                <div key={name} className="flex items-center gap-2 text-xs">
                  <span className="text-slate-500 w-10 font-mono text-[10px]">{name}</span>
                  <span className="text-slate-400 text-[10px]">↑{fmtGB(tx)}</span>
                  <span className="text-slate-600 text-[10px]">↓{fmtGB(rx)}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
};


const AnalyticsCard = ({ sessions, backendUrl, authHeaders }) => {
  const sb = sessions?.service_breakdown || [];
  const cb = sessions?.country_breakdown || [];
  const lt = sessions?.lifetime_totals || { sessions: 0, earnings_myst: 0, data_gb: 0 };
  const hasData = sb.length > 0 || cb.length > 0;

  const [dbStats, setDbStats] = React.useState(null);
  const [showAllCountries, setShowAllCountries] = React.useState(false);
  React.useEffect(() => {
    if (!backendUrl) return;
    fetch(`${backendUrl}/sessions/db/stats`, { headers: authHeaders || {} })
      .then(r => r.json()).then(setDbStats).catch(() => {});
  }, [backendUrl]);

  const BarRow = ({ label, pct, value, color }) => (
    <div className="flex items-center gap-2 py-0.5">
      <span className="text-xs text-slate-400 w-32 flex-shrink-0 truncate" title={label}>{label}</span>
      <div className="flex-1 h-1.5 bg-slate-700/60 rounded-full overflow-hidden">
        <div className={`h-full ${color} rounded-full transition-all`} style={{ width: `${Math.min(100, pct || 0)}%` }} />
      </div>
      <span className="text-xs text-slate-300 w-10 text-right font-medium">{(pct || 0).toFixed(1)}%</span>
      <span className="text-xs text-slate-500 w-28 text-right">{value}</span>
    </div>
  );

  return (
    <div className="mb-6 p-4 bg-slate-800/30 border border-slate-700 rounded-lg backdrop-blur">
      <div className="flex items-center gap-2 mb-4">
        <h3 className="text-sm font-semibold text-slate-300 tracking-wide">Node Analytics</h3>
        <span className="text-xs text-slate-600">— node statistics</span>
      </div>



      {hasData ? (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* Service breakdown */}
          {sb.length > 0 && (
            <div>
              <div className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">Service Type — % of Earnings</div>
              {sb.map((s, i) => (
                <BarRow
                  key={i}
                  label={fmtType(s.service_type)}
                  pct={s.pct_earnings}
                  value={`${s.sessions} · ${s.earnings_myst.toFixed(4)} MYST`}
                  color={i === 0 ? 'bg-emerald-500' : i === 1 ? 'bg-cyan-500' : i === 2 ? 'bg-violet-500' : 'bg-slate-500'}
                />
              ))}
              <div className="mt-2 flex flex-wrap gap-x-4 gap-y-0.5 text-[10px] text-slate-600">
                {sb.map((s, i) => (
                  <span key={i}>
                    <span className="text-slate-500">{fmtType(s.service_type)}</span>
                    <span className="text-slate-700"> — </span>
                    <span>{s.pct_data.toFixed(1)}% data</span>
                    <span className="text-slate-700"> · </span>
                    <span>{s.pct_sessions.toFixed(1)}% sessions</span>
                  </span>
                ))}
              </div>
              {sessions?.monitoring_sessions > 0 && (
                <div className="mt-1 text-[10px] text-slate-700">
                  + {sessions.monitoring_sessions} monitoring probe sessions excluded (infrastructure only)
                </div>
              )}
            </div>
          )}

          {/* Country breakdown */}
          {cb.length > 0 && (
            <div>
              <div className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">
                Consumer Origin — % of Sessions
                <span className="font-normal text-slate-700 ml-1">({cb.length} {cb.length === 1 ? 'country' : 'countries'})</span>
              </div>
              <div className={`${showAllCountries ? '' : 'max-h-64'} overflow-y-auto pr-1 space-y-0`}>
                {(showAllCountries ? cb : cb.slice(0, 20)).map((c, i) => (
                  <BarRow
                    key={i}
                    label={c.country === '—' ? 'Unknown' : c.country}
                    pct={c.pct_sessions}
                    value={`${c.sessions} · ${c.earnings_myst.toFixed(4)} MYST`}
                    color={i === 0 ? 'bg-amber-500' : i < 3 ? 'bg-amber-400/70' : 'bg-slate-600'}
                  />
                ))}
              </div>
              {cb.length > 20 && (
                <button
                  onClick={() => setShowAllCountries(v => !v)}
                  className="mt-1 text-[10px] text-slate-500 hover:text-slate-300 transition"
                >
                  {showAllCountries ? '▲ show less' : `+${cb.length - 20} more countries — click to expand`}
                </button>
              )}
            </div>
          )}
        </div>
      ) : (
        <>
          <div className="text-xs text-slate-600 text-center py-2">Analytics populate as session history loads — check back shortly</div>
          <div className="mt-1 text-[10px] text-slate-700 text-center">Data from node memory — reflects all sessions since node was installed</div>
        </>
      )}
    </div>
  );
};

// ---- Node Quality Card ----

// ============ QUALITY HISTORY SPARKLINE ============
const QualityHistorySparkline = ({ backendUrl, authHeaders }) => {
  const [history, setHistory] = React.useState([]);
  const [loading, setLoading] = React.useState(false);
  const [open, setOpen]       = React.useState(false);
  const [days, setDays]       = React.useState(30);

  const load = React.useCallback(() => {
    if (!open) return;
    setLoading(true);
    fetch(`${backendUrl}/data/quality/history?days=${days}`, { headers: authHeaders || {} })
      .then(r => r.json())
      .then(d => { setHistory(d.history || []); setLoading(false); })
      .catch(() => setLoading(false));
  }, [open, days, authHeaders, backendUrl]);

  React.useEffect(() => { load(); }, [load]);

  const Sparkline = ({ data, key1, key2, label1, label2, color1, color2, unit }) => {
    if (!data || data.length < 2) return null;
    const v1 = data.map(d => d[key1]).filter(v => v != null);
    const v2 = key2 ? data.map(d => d[key2]).filter(v => v != null) : [];
    const allV = [...v1, ...v2];
    if (!allV.length) return null;
    const mn = Math.min(...allV) * 0.9;
    const mx = Math.max(...allV) * 1.1 || 1;
    const range = mx - mn || 1;
    const W = 300; const H = 48;
    const px = (i) => (i / (data.length - 1)) * W;
    const py = (v) => H - ((v - mn) / range) * H;
    const pts1 = data.map((d, i) => d[key1] != null ? `${px(i).toFixed(1)},${py(d[key1]).toFixed(1)}` : null)
                      .filter(Boolean).join(' ');
    const pts2 = key2 ? data.map((d, i) => d[key2] != null ? `${px(i).toFixed(1)},${py(d[key2]).toFixed(1)}` : null)
                              .filter(Boolean).join(' ') : '';
    const last1 = v1[v1.length - 1];
    const last2 = v2.length ? v2[v2.length - 1] : null;
    return (
      <div className="mb-3">
        <div className="flex items-center justify-between mb-1">
          <div className="flex items-center gap-3 text-xs">
            <span className={`${color1} font-medium`}>{label1}: {last1 != null ? `${typeof last1 === 'number' ? last1.toFixed(1) : last1}${unit}` : '—'}</span>
            {last2 != null && <span className={`${color2} font-medium`}>{label2}: {last2.toFixed(1)}{unit}</span>}
          </div>
        </div>
        <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-12" preserveAspectRatio="none">
          {pts1 && <polyline points={pts1} fill="none" stroke="currentColor" strokeWidth="1.5"
            className={color1.replace('text-', 'text-')} style={{color: color1.includes('emerald') ? 'rgb(52,211,153)' : color1.includes('amber') ? 'rgb(251,191,36)' : color1.includes('sky') ? 'rgb(56,189,248)' : 'rgb(167,139,250)'}} />}
          {pts2 && <polyline points={pts2} fill="none" stroke="currentColor" strokeWidth="1.5" strokeDasharray="3,2"
            style={{color: color2?.includes('amber') ? 'rgb(251,191,36)' : 'rgb(167,139,250)'}} />}
        </svg>
      </div>
    );
  };

  return (
    <div className="mt-3 pt-3 border-t border-slate-700/50">
      <button onClick={() => setOpen(o => !o)}
        className="flex items-center gap-2 text-xs text-slate-400 hover:text-slate-200 transition-colors w-full">
        <svg className="w-3 h-3 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 12l3-3 3 3 4-4" />
        </svg>
        <span className="font-medium text-slate-300">Quality History</span>
        {history.length > 0 && <span className="text-slate-600">{history.length} snapshots</span>}
        <span className="ml-auto">{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div className="mt-3">
          <div className="flex gap-1 mb-3">
            {[7, 14, 30, 90].map(d => (
              <button key={d} onClick={() => setDays(d)}
                className={`px-2 py-0.5 text-xs rounded border transition ${days === d
                  ? 'border-emerald-500/50 bg-emerald-500/10 text-emerald-300'
                  : 'border-slate-700 text-slate-500 hover:text-slate-300'}`}>
                {d}d
              </button>
            ))}
            {loading && <span className="text-xs text-slate-600 ml-2">loading…</span>}
          </div>

          {history.length === 0 && !loading && (
            <div className="text-xs text-slate-600 py-4 text-center">
              No quality history yet — snapshots recorded every 10 minutes.
            </div>
          )}

          {history.length > 0 && (
            <>
              <Sparkline data={history} key1="quality_score" label1="Quality" color1="text-emerald-400" unit="" />
              <Sparkline data={history} key1="latency_ms" key2={null} label1="Latency" color1="text-amber-400" unit="ms" />
              <Sparkline data={history} key1="bandwidth_mbps" label1="Bandwidth" color1="text-sky-400" unit=" Mbps" />
            </>
          )}
        </div>
      )}
    </div>
  );
};

// ============ SYSTEM METRICS HISTORY CARD ============
const SystemMetricsHistoryCard = ({ backendUrl, authHeaders }) => {
  const [history, setHistory] = React.useState([]);
  const [loading, setLoading] = React.useState(false);
  const [open, setOpen]       = React.useState(false);
  const [days, setDays]       = React.useState(7);

  const load = React.useCallback(() => {
    if (!open) return;
    setLoading(true);
    fetch(`${backendUrl}/data/system/history?days=${days}`, { headers: authHeaders || {} })
      .then(r => r.json())
      .then(d => { setHistory(d.history || []); setLoading(false); })
      .catch(() => setLoading(false));
  }, [open, days, authHeaders, backendUrl]);

  React.useEffect(() => { load(); }, [load]);

  const Spark = ({ data, yKey, label, colorClass, hexColor, unit = '%' }) => {
    const vals = data.map(d => d[yKey]).filter(v => v != null);
    if (!vals.length) return null;
    const mn = 0; const mx = Math.max(...vals, 1) * 1.1;
    const W = 300; const H = 40;
    const pts = data.map((d, i) => {
      if (d[yKey] == null) return null;
      const x = (i / Math.max(data.length - 1, 1)) * W;
      const y = H - ((d[yKey] - mn) / (mx - mn || 1)) * H;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).filter(Boolean).join(' ');
    const avg = vals.reduce((a, b) => a + b, 0) / vals.length;
    const last = vals[vals.length - 1];
    const peak = Math.max(...vals);
    return (
      <div className="flex items-center gap-3">
        <div className={`text-xs w-28 flex-shrink-0 ${colorClass}`}>
          <span className="font-semibold">{label}</span>
          <div className="text-[10px] text-slate-500 font-mono leading-tight">
            avg <span className={colorClass}>{avg.toFixed(1)}{unit}</span>
            <span className="text-slate-700 mx-1">·</span>
            peak {peak.toFixed(1)}{unit}
          </div>
        </div>
        <svg viewBox={`0 0 ${W} ${H}`} className="flex-1 h-8" preserveAspectRatio="none">
          <polyline points={pts} fill="none" strokeWidth="1.5" style={{ stroke: hexColor }} />
        </svg>
        <span className="text-[10px] text-slate-600 w-12 text-right font-mono">{last.toFixed(1)}{unit}</span>
      </div>
    );
  };

  return (
    <div className="mb-6 p-4 bg-slate-800/30 border border-slate-700 rounded-lg backdrop-blur">
      <button onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between">
        <h3 className="text-xs font-semibold text-slate-300 tracking-wide flex items-center gap-2">
          <svg className="w-4 h-4 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
          </svg>
          System Metrics History
          {history.length > 0 && <span className="text-xs font-normal text-slate-500">{history.length} snapshots · 5 min interval</span>}
        </h3>
        <span className="text-xs text-slate-500">{open ? '▲ collapse' : '▼ expand'}</span>
      </button>

      {open && (
        <div className="mt-3">
          <div className="flex gap-1 mb-3">
            {[1, 3, 7, 14, 30].map(d => (
              <button key={d} onClick={() => setDays(d)}
                className={`px-2 py-0.5 text-xs rounded border transition ${days === d
                  ? 'border-emerald-500/50 bg-emerald-500/10 text-emerald-300'
                  : 'border-slate-700 text-slate-500 hover:text-slate-300'}`}>
                {d}d
              </button>
            ))}
            {loading && <span className="text-xs text-slate-600 ml-2">loading…</span>}
          </div>

          {history.length === 0 && !loading && (
            <div className="text-xs text-slate-500 py-4 text-center">
              No snapshots yet — recording every 5 minutes. Check back shortly.
            </div>
          )}

          {history.length > 0 && (
            <div className="space-y-2">
              <Spark data={history} yKey="cpu_pct"  label="CPU"  colorClass="text-emerald-400" hexColor="rgb(52,211,153)" />
              <Spark data={history} yKey="ram_pct"  label="RAM"  colorClass="text-sky-400"     hexColor="rgb(56,189,248)" />
              <Spark data={history} yKey="disk_pct" label="Disk" colorClass="text-amber-400"   hexColor="rgb(251,191,36)" />
              {history.some(d => d.cpu_temp != null) && (
                <Spark data={history} yKey="cpu_temp"     label="CPU Temp" colorClass="text-rose-400"    hexColor="rgb(251,113,133)" unit="°C" />
              )}
              {history.some(d => d.ambient_temp != null) && (
                <Spark data={history} yKey="ambient_temp" label="Ambient"  colorClass="text-amber-400"   hexColor="rgb(251,191,36)"  unit="°C" />
              )}
              {history.some(d => d.ram_temp != null) && (
                <Spark data={history} yKey="ram_temp"     label="RAM Temp" colorClass="text-rose-400"    hexColor="rgb(251,113,133)" unit="°C" />
              )}
              {history.some(d => d.tunnel_count != null) && (
                <Spark data={history} yKey="tunnel_count"    label="Tunnels"   colorClass="text-violet-400" hexColor="rgb(167,139,250)" unit="" />
              )}
              {history.some(d => d.node_speed_mbps != null) && (
                <Spark data={history} yKey="node_speed_mbps" label="VPN Speed" colorClass="text-cyan-400"   hexColor="rgb(34,211,238)"  unit=" MB/s" />
              )}
              {history.some(d => d.sys_speed_mbps != null) && (
                <Spark data={history} yKey="sys_speed_mbps"  label="NIC Speed" colorClass="text-sky-400"    hexColor="rgb(56,189,248)"  unit=" MB/s" />
              )}
              {history.some(d => d.latency_ms != null) && (
                <Spark data={history} yKey="latency_ms"      label="Latency"   colorClass="text-emerald-400" hexColor="rgb(52,211,153)" unit="ms" />
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

const NodeQualityCard = ({ nodeQuality: q, nodeStatus, backendUrl, authHeaders, nodeUrl }) => {
  const nq = q || {};
  const available = nq.available;
  const score = nq.quality_score;
  const latency = nq.latency_ms;
  const bw = nq.bandwidth_mbps;
  const monFail = nq.monitoring_failed;
  const upNet = nq.uptime_24h_net;
  const up24 = nq.uptime_24h_local;
  const up30 = nq.uptime_30d_local;
  const since = nq.tracking_since;
  const trackingDays = nq.tracking_days ?? 0;
  const services = nq.services || [];
  const error = nq.error;

  const plNet = nq.packet_loss_net;  // Discovery monitoring agent packet loss (%)

  const [testResult, setTestResult] = React.useState(null);
  const [testing, setTesting] = React.useState(false);

  const handleTest = async () => {
    if (!backendUrl) return;
    setTesting(true);
    setTestResult(null);
    try {
      const resp = await fetch(`${backendUrl}/node/test`, {
        method: 'POST',
        headers: { ...(authHeaders || {}), 'Content-Type': 'application/json' },
        body: JSON.stringify(nodeUrl ? { toolkit_url: nodeUrl } : {}),
      });
      const data = await resp.json();
      setTestResult(data);
    } catch (e) {
      setTestResult({ visible: false, error: e.message });
    }
    setTesting(false);
  };

  // Quality score color — 0-1: red, 1-1.8: amber, 1.8-3: green
  const scoreColor = score == null ? 'text-slate-500'
    : score >= 1.8 ? 'text-green-400'
    : score >= 1.0 ? 'text-amber-400'
    : 'text-red-400';

  // Score bars (0=none, 1=1bar, 2=2bars, 3=3bars — NodeUI thresholds)
  const scoreBars = score == null ? 0 : score > 2 ? 3 : score > 1 ? 2 : score > 0 ? 1 : 0;
  const Bar = ({ active }) => (
    <div className={`w-3 h-4 rounded-sm ${active ? (scoreBars === 3 ? 'bg-green-400' : scoreBars === 2 ? 'bg-amber-400' : 'bg-red-400') : 'bg-slate-700'}`} />
  );

  const monitoringBadge = monFail === null ? null
    : monFail
      ? <span className="text-xs px-2 py-0.5 rounded font-semibold bg-red-500/20 text-red-300 border border-red-500/30">Monitoring Failed</span>
      : <span className="text-xs px-2 py-0.5 rounded font-semibold bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">Monitoring OK</span>;

  const UptimeBar = ({ pct, label }) => {
    if (pct == null) return null;
    // Grey when 0% — no data yet (new node). Color only when tracking has started.
    const color = pct === 0 ? 'bg-slate-600' : pct >= 90 ? 'bg-green-500' : pct >= 70 ? 'bg-amber-500' : 'bg-red-500';
    const textColor = pct === 0 ? 'text-slate-500' : pct >= 90 ? 'text-green-400' : pct >= 70 ? 'text-amber-400' : 'text-red-400';
    return (
      <div className="flex items-center gap-2 mt-1">
        <span className="text-xs text-slate-400 w-16 flex-shrink-0">{label}</span>
        <div className="flex-1 h-1.5 bg-slate-700 rounded-full overflow-hidden">
          <div className={`h-full ${color} rounded-full`} style={{ width: `${Math.min(100, pct)}%` }} />
        </div>
        <span className={`text-xs font-medium w-10 text-right ${textColor}`}>{pct.toFixed(1)}%</span>
      </div>
    );
  };

  // Always label this metric "30d local" — it IS the 30d local metric.
  // How much data we actually have is shown in the footer "(Xd of 30)".
  const localLabel30d = '30d local';

  return (
    <div className="mb-6 p-4 bg-slate-800/30 border border-slate-700 rounded-lg backdrop-blur">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-slate-300 tracking-wide flex items-center gap-2">
          <svg className="w-4 h-4 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
          </svg>
          Node Quality
          <span className="text-xs font-normal text-slate-500">— Mysterium Discovery Network</span>
        </h3>
        <div className="flex items-center gap-2">
          {monitoringBadge}
          <button
            onClick={handleTest}
            disabled={testing}
            className="px-1.5 py-0.5 text-[11px] font-semibold uppercase tracking-normal bg-cyan-500/20 text-cyan-300 border border-cyan-500/30 rounded hover:bg-cyan-500/30 transition disabled:opacity-50"
            title="Live probe via Mysterium Discovery network — bypasses 10-minute cache"
          >
            {testing ? '⟳ Checking…' : '⚡ Discovery Check'}
          </button>
        </div>
      </div>

      {/* Discovery Check result popup */}
      {testResult && (
        <div className={`mb-3 px-3 py-2 rounded text-xs border ${testResult.visible ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300' : 'bg-red-500/10 border-red-500/30 text-red-300'}`}>
          {testResult.visible ? (
            <div>
              <div className="flex items-center gap-2 flex-wrap mb-1">
                <span className="text-emerald-400 font-semibold">✓ Visible on Discovery</span>
                {testResult.monitoring_ok != null && (
                  <span className={`px-1.5 py-0.5 rounded ${testResult.monitoring_ok ? 'bg-emerald-500/20 text-emerald-300' : 'bg-red-500/20 text-red-300'}`}>
                    Monitoring {testResult.monitoring_ok ? 'OK' : 'FAILED'}
                  </span>
                )}
                <span className="text-slate-500 ml-auto">{testResult.timestamp}</span>
              </div>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mt-2">
                {testResult.quality_score != null && (
                  <div className="bg-slate-800/50 rounded p-1.5">
                    <div className="text-slate-400 text-xs">Score</div>
                    <div className={`font-semibold ${testResult.quality_score >= 1.8 ? 'text-green-400' : testResult.quality_score >= 1.0 ? 'text-amber-400' : 'text-red-400'}`}>
                      {testResult.quality_score.toFixed(2)} / 3.00
                    </div>
                   </div>

                )}
                {testResult.uptime_24h_net != null && (
                  <div className="bg-slate-800/50 rounded p-1.5">
                    <div className="text-slate-400 text-xs">24h Uptime</div>
                    <div className="text-slate-200 font-semibold">{testResult.uptime_24h_net.toFixed(1)}%</div>
                  </div>
                )}
                {testResult.latency_ms != null && (
                  <div className="bg-slate-800/50 rounded p-1.5">
                    <div className="text-slate-400 text-xs">Latency</div>
                    <div className="text-slate-200 font-semibold">{testResult.latency_ms} ms</div>
                  </div>
                )}
                {testResult.bandwidth_mbps != null && (
                  <div className="bg-slate-800/50 rounded p-1.5">
                    <div className="text-slate-400 text-xs">Bandwidth</div>
                    <div className="text-slate-200 font-semibold">{testResult.bandwidth_mbps.toFixed(1)} Mbit/s</div>
                  </div>
                )}
              </div>
              {testResult.services && testResult.services.length > 0 && (
                <div className="mt-2">
                  <div className="text-slate-400 mb-1">Services</div>
                  <div className="flex flex-wrap gap-1">
                    {testResult.services.map((s, i) => (
                      <span key={i} className={`px-1.5 py-0.5 rounded text-xs ${s.monitoring_failed ? 'bg-red-500/20 text-red-300' : 'bg-slate-700 text-slate-300'}`}>
                        {s.service_type} {s.quality_score != null ? `· ${s.quality_score.toFixed(2)}` : ''} {s.monitoring_failed ? '⚠' : ''}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ) : (
            <span>
              {testResult.node_online && <span className="text-emerald-400 mr-1">✓ Node online locally · </span>}
              ✗ {testResult.error || 'Node not found in Discovery network'}
            </span>
          )}
        </div>
      )}

      {!available && (
        <div className="text-xs text-slate-500 italic">{error || 'Quality data not yet available — fetched every 10 minutes'}</div>
      )}

      {available && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">

          {/* Quality Score */}
          <div>
            <div className="text-xs text-slate-500 mb-1">Quality Score</div>
            <div className={`text-2xl font-bold ${scoreColor}`}>{score != null ? score.toFixed(2) : '—'}</div>
            <div className="text-xs text-slate-500">/ 3.00</div>
            <div className="flex gap-1 mt-1.5">
              <Bar active={scoreBars >= 1} />
              <Bar active={scoreBars >= 2} />
              <Bar active={scoreBars >= 3} />
            </div>
          </div>

          {/* Latency */}
          <div>
            <div className="text-xs text-slate-500 mb-1">Network Latency</div>
            <div className={`text-2xl font-bold ${latency == null ? 'text-slate-500' : latency < 100 ? 'text-green-400' : latency < 300 ? 'text-amber-400' : 'text-red-400'}`}>
              {latency != null && latency > 0 ? `${Math.round(latency)}` : '—'}
            </div>
            <div className="text-xs text-slate-500">ms{latency === 0 ? ' (no data yet)' : ''}</div>
          </div>

          {/* Bandwidth */}
          <div>
            <div className="text-xs text-slate-500 mb-1">Monitored Link Speed</div>
            <div className={`text-2xl font-bold ${bw == null ? 'text-slate-500' : bw >= 10 ? 'text-green-400' : bw >= 2 ? 'text-amber-400' : 'text-red-400'}`}>
              {bw != null ? bw.toFixed(1) : '—'}
            </div>
            <div className="text-xs text-slate-500">Mbit/s</div>
            <div className="text-[10px] text-slate-600 mt-0.5 leading-tight">speed test by<br/>Discovery API</div>
          </div>

          {/* Online Time + Packet Loss — combined in one column */}
          <div>
            <div className="text-xs text-slate-500 mb-2">Online Time</div>
            {upNet != null && <UptimeBar pct={upNet} label="24h net" />}
            {up24 != null && <UptimeBar pct={up24} label="24h local" />}
            {up30 != null && <UptimeBar pct={up30} label={localLabel30d} />}
            {/* Packet Loss + Connected % — two rows */}
            {plNet != null && (() => {
              const connPct = Math.max(0, 100 - plNet);
              const plColor = plNet === 0 ? 'bg-green-500' : plNet < 2 ? 'bg-emerald-500' : plNet < 5 ? 'bg-amber-500' : 'bg-red-500';
              const plTextColor = plNet === 0 ? 'text-green-400' : plNet < 2 ? 'text-emerald-400' : plNet < 5 ? 'text-amber-400' : 'text-red-400';
              return (
                <>
                  {/* Packet Loss row */}
                  <div className="flex items-center gap-2 mt-1">
                    <span className="text-[10px] text-slate-500 w-14 flex-shrink-0">net loss</span>
                    <div className="flex-1 h-1.5 bg-slate-700/60 rounded-full overflow-hidden">
                      <div className={`h-full ${plColor} rounded-full`} style={{ width: `${Math.min(100, plNet)}%` }} />
                    </div>
                    <span className={`text-[10px] font-medium w-10 text-right ${plTextColor}`}>{plNet.toFixed(1)}%</span>
                  </div>
                  {/* Connected % row */}
                  <div className="flex items-center gap-2 mt-1">
                    <span className="text-[10px] text-slate-500 w-14 flex-shrink-0">connected</span>
                    <div className="flex-1 h-1.5 bg-slate-700/60 rounded-full overflow-hidden">
                      <div className={`h-full ${plColor} rounded-full`} style={{ width: `${connPct}%` }} />
                    </div>
                    <span className={`text-[10px] font-medium w-10 text-right ${plTextColor}`}>{connPct.toFixed(1)}%</span>
                  </div>
                </>
              );
            })()}
            {since && (
              <div className="text-xs text-slate-600 mt-1.5">
                tracking since {since.split('T')[0]}
                {trackingDays < 30 && <span className="text-slate-700"> ({trackingDays}d of 30)</span>}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Per-service breakdown if multiple services */}
      {available && services.length > 1 && (
        <div className="mt-3 pt-3 border-t border-slate-700/50">
          <div className="text-xs text-slate-500 mb-2">Per service</div>
          <div className="flex flex-wrap gap-2">
            {services.map((s, i) => (
              <div key={i} className="text-xs bg-slate-800 border border-slate-700 rounded px-2 py-1">
                <span className="text-slate-400 mr-1">{fmtType(s.service_type)}</span>
                {s.quality_score != null && <span className={`font-medium mr-1 ${s.quality_score >= 1.8 ? 'text-green-400' : s.quality_score >= 1 ? 'text-amber-400' : 'text-red-400'}`}>{s.quality_score.toFixed(2)}</span>}
                {s.latency_ms != null && s.latency_ms > 0 && <span className="text-slate-500">{Math.round(s.latency_ms)}ms</span>}
                {s.uptime_net_pct != null && <span className="text-slate-500 ml-1">{s.uptime_net_pct.toFixed(0)}%↑</span>}
                {s.monitoring_failed && <span className="text-red-500 ml-1">✗</span>}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Quality History Sparkline */}
      <QualityHistorySparkline backendUrl={backendUrl} authHeaders={authHeaders} />
    </div>
  );
};

// ─── Node Payment Config Modal ─────────────────────────────────────────────
const NODE_CONFIG_KEYS_META = [
  {
    key: 'payments.zero-stake-unsettled-amount',
    label: 'Auto-Settle Threshold',
    unit: 'MYST',
    group: 'settlement',
    desc: 'Unsettled MYST required to trigger automatic settlement. Default: 5. Higher = fewer blockchain transactions, more MYST at risk if daemon crashes.',
  },
  {
    key: 'payments.unsettled-max-amount',
    label: 'Max Unsettled Amount',
    unit: 'MYST',
    group: 'settlement',
    desc: 'Hard ceiling on unsettled balance before forced settlement. Default: ~10. High-load recommended: 25.',
  },
  {
    key: 'payments.settle.min-amount',
    label: 'Manual Settle Min',
    unit: 'MYST',
    group: 'settlement',
    desc: 'Minimum balance for the Settle button to work. Default: 1. Set to 0.01 to allow settling at any balance.',
  },
  {
    key: 'payments.min_promise_amount',
    label: 'Min Promise Amount',
    unit: 'MYST',
    group: 'session',
    desc: 'Minimum MYST in consumer\'s first promise before your node accepts the session. Lower = accepts more short/micro sessions.',
  },
  {
    key: 'payments.provider.invoice-frequency',
    label: 'Invoice Frequency',
    unit: 'seconds',
    group: 'timing',
    desc: 'How often to send payment invoices to the consumer during a session. Default: 60s. Higher = fewer API calls per session. At 300s with 50+ sessions: ~5× less API traffic.',
  },
  {
    key: 'pingpong.balance-check-interval',
    label: 'Balance Check Interval',
    unit: 'seconds',
    group: 'timing',
    desc: 'How often to poll consumer channel balance. PRIMARY rate-limit fix. Default: ~90s. Do not exceed 600s (consumer-side timeout is 10 min). Also writes session.pingpong.balance-check-interval automatically.',
  },
  {
    key: 'pingpong.promise-wait-timeout',
    label: 'Promise Wait Timeout',
    unit: 'seconds',
    group: 'timing',
    desc: 'How long to wait for a consumer promise before abandoning the session. Default: 180s (3m). Higher = more patient with slow consumers. Do not exceed 600s.',
  },
];

const PRESETS = {
  defaults: {
    label: 'Standard · Stable Node',
    color: 'slate',
    values: {
      'payments.zero-stake-unsettled-amount': '5.0',
      'payments.unsettled-max-amount': '10.0',
      'payments.min_promise_amount': '0.05',
      'payments.provider.invoice-frequency': '60',
      'pingpong.balance-check-interval': '90',
      'pingpong.promise-wait-timeout': '180',
      'payments.settle.min-amount': '1.0',
    }
  },
  'high-traffic': {
    label: 'High Load · 50+ Sessions',
    color: 'emerald',
    values: {
      'payments.zero-stake-unsettled-amount': '10',
      'payments.unsettled-max-amount': '25',
      'payments.min_promise_amount': '0.01',
      'payments.provider.invoice-frequency': '300',
      'pingpong.balance-check-interval': '300',
      'pingpong.promise-wait-timeout': '600',
      'payments.settle.min-amount': '0.01',
    }
  },
};

const NodeConfigModal = ({ backendUrl, authHeaders, onClose }) => {
  const theme = (() => { try { return localStorage.getItem('myst-theme') || 'emerald'; } catch { return 'emerald'; } })();
  const modalBg = THEMES[theme]?.bg?.[0] ?? '#0a0a0a';
  const [phase, setPhase] = React.useState(1); // 1=read, 2=edit
  const [acknowledged, setAcknowledged] = React.useState(false);
  const [scrolledToBottom, setScrolledToBottom] = React.useState(false);
  const [currentValues, setCurrentValues] = React.useState({});
  const [pendingValues, setPendingValues] = React.useState({});
  const [loading, setLoading] = React.useState(true);
  const [applying, setApplying] = React.useState({});
  const [results, setResults] = React.useState({});
  const [tomlPath, setTomlPath] = React.useState('/etc/mysterium-node/config-mainnet.toml');
  const scrollRef = React.useRef(null);

  React.useEffect(() => {
    const fetchCurrent = async () => {
      setLoading(true);
      try {
        const resp = await fetch(`${backendUrl}/node/config/current`, { headers: authHeaders || {} });
        const data = await resp.json();
        if (data.success) {
          setCurrentValues(data.current || {});
          setPendingValues({ ...data.current });
          if (data.toml_path) setTomlPath(data.toml_path);
        }
      } catch (e) {
        console.error('Config fetch failed:', e);
      } finally {
        setLoading(false);
      }
    };
    fetchCurrent();
  }, [backendUrl]);

  const handleScroll = (e) => {
    const el = e.target;
    if (el.scrollHeight - el.scrollTop <= el.clientHeight + 40) {
      setScrolledToBottom(true);
    }
  };

  const applyOne = async (key) => {
    const value = pendingValues[key];
    if (!value) return;
    setApplying(p => ({ ...p, [key]: true }));
    try {
      const resp = await fetch(`${backendUrl}/node/config/set`, {
        method: 'POST',
        headers: { ...(authHeaders || {}), 'Content-Type': 'application/json' },
        body: JSON.stringify({ key, value }),
      });
      const data = await resp.json();
      setResults(p => ({ ...p, [key]: data.success ? 'ok' : (data.error || 'failed') }));
      if (data.success) setCurrentValues(p => ({ ...p, [key]: value }));
    } catch (e) {
      setResults(p => ({ ...p, [key]: e.message }));
    } finally {
      setApplying(p => ({ ...p, [key]: false }));
      setTimeout(() => setResults(p => { const n = { ...p }; delete n[key]; return n; }), 6000);
    }
  };

  const applyAll = async () => {
    for (const meta of NODE_CONFIG_KEYS_META) {
      await applyOne(meta.key);
    }
  };

  const loadPreset = (presetKey) => {
    setPendingValues({ ...PRESETS[presetKey].values });
    setResults({});
  };

  const resetOne = async (key) => {
    setApplying(p => ({ ...p, [key]: true }));
    try {
      const resp = await fetch(`${backendUrl}/node/config/reset`, {
        method: 'POST',
        headers: { ...(authHeaders || {}), 'Content-Type': 'application/json' },
        body: JSON.stringify({ key }),
      });
      const data = await resp.json();
      if (data.success) {
        const defVal = PRESETS.defaults.values[key];
        setPendingValues(p => ({ ...p, [key]: defVal }));
        setCurrentValues(p => ({ ...p, [key]: defVal }));
        setResults(p => ({ ...p, [key]: 'reset to default' }));
      } else {
        setResults(p => ({ ...p, [key]: data.error || 'reset failed' }));
      }
    } catch (e) {
      setResults(p => ({ ...p, [key]: e.message }));
    } finally {
      setApplying(p => ({ ...p, [key]: false }));
      setTimeout(() => setResults(p => { const n = { ...p }; delete n[key]; return n; }), 6000);
    }
  };

  const groups = {
    settlement: { label: 'Settlement Thresholds', keys: NODE_CONFIG_KEYS_META.filter(m => m.group === 'settlement') },
    session: { label: 'Session Acceptance', keys: NODE_CONFIG_KEYS_META.filter(m => m.group === 'session') },
    timing: { label: 'Payment Engine Timing', keys: NODE_CONFIG_KEYS_META.filter(m => m.group === 'timing') },
  };

  return (
    <>
      {/* Backdrop */}
      <div className="fixed inset-0 z-40 bg-black/70 backdrop-blur-sm" onClick={onClose} />
      {/* Modal */}
      <div className="fixed inset-x-3 top-4 bottom-4 z-50 flex flex-col max-w-2xl mx-auto
                      border border-emerald-500/30 rounded-xl shadow-2xl overflow-hidden"
           style={{ background: modalBg }}>

        {/* Header */}
        <div className="flex-shrink-0 px-5 py-4 border-b border-slate-700/50 flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <span className="text-emerald-400 text-sm">⚙</span>
            <h3 className="text-sm font-semibold tracking-wide">Payment Config Tuner</h3>
            <span className="text-xs px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
              {phase === 1 ? 'Read First' : 'Edit Mode'}
            </span>
          </div>
          <button onClick={onClose}
            className="px-3 py-1 text-xs bg-slate-700/50 text-slate-300 border border-slate-600/30 rounded hover:bg-slate-600/50 transition font-semibold">
            ✕ Close
          </button>
        </div>

        {/* Phase 1 — Explanation */}
        {phase === 1 && (
          <div className="flex flex-col flex-1 overflow-hidden">
            <div ref={scrollRef} onScroll={handleScroll}
              className="flex-1 overflow-y-auto px-5 py-4 space-y-4 text-xs text-slate-400 leading-relaxed">

              <div className="p-3 bg-amber-500/10 border border-amber-500/30 rounded-lg">
                <p className="text-amber-300 font-semibold mb-1">⚠ Read before using</p>
                <p>These settings directly control how your node handles payments and API load. There are <strong className="text-slate-300">no hard limits enforced by the node</strong> — it will accept any value. Setting values too high can cause silent session failures. Read each section before applying.</p>
              </div>

              <div className="space-y-1">
                <p className="text-slate-300 font-semibold uppercase tracking-wider text-[10px]">Settlement Thresholds</p>
                <p>Auto-settlement sends your unsettled MYST to your Balance when a threshold is crossed. Each settlement deducts a <strong className="text-slate-300">fixed 20% Hermes network fee</strong> — this is the only fee taken at settlement. A small Polygon transaction fee applies separately when you withdraw your Balance to an external wallet, but this is typically just a few cents on Polygon. Raising your thresholds means fewer settlements, but more MYST sitting in unconfirmed promises on the node at any time. Promises are stored locally and should survive a daemon restart — but there is no guarantee during a Hermes outage. Only raise these values if you understand the exposure.</p>
              </div>

              <div className="space-y-1">
                <p className="text-slate-300 font-semibold uppercase tracking-wider text-[10px]">Payment Engine Timing</p>
                <p>These control how often your node polls consumer balances and exchanges payment promises during active sessions. At node defaults (~60–90s), a node with 50+ concurrent sessions generates hundreds of API calls per minute to Polygon RPC and Hermes endpoints — this causes rate limiting. Raising intervals to 300s reduces API pressure by roughly 5×.</p>
                <p className="mt-1 text-amber-300">Practical limits: keep <code className="bg-slate-800 px-1 rounded">balance-check-interval</code> at or below <strong>300s</strong> — beyond that offers no benefit and increases balance drift risk. Keep <code className="bg-slate-800 px-1 rounded">promise-wait-timeout</code> at or below <strong>600s</strong> — the consumer-side session timeout is 10 minutes, so values above 600s risk the consumer dropping the session before the node does.</p>
              </div>

              <div className="space-y-1">
                <p className="text-slate-300 font-semibold uppercase tracking-wider text-[10px]">Session Acceptance</p>
                <p><code className="bg-slate-800 px-1 rounded">min_promise_amount</code> controls the minimum value of a consumer's first payment promise before your node accepts the session. The higher the default, the more micro/short sessions get rejected. Setting it to 0.01 accepts nearly any session, increasing count at the cost of more low-earning connections.</p>
              </div>

              <div className="space-y-1">
                <p className="text-slate-300 font-semibold uppercase tracking-wider text-[10px]">About the High Load Preset</p>
                <p>The "High Load" preset is designed for nodes handling 50+ concurrent sessions, where default polling intervals generate hundreds of RPC calls per minute to Polygon and Hermes endpoints, causing rate limiting. Raising intervals to 300s eliminates that. <strong className="text-amber-300">Only apply this preset if you are actively experiencing rate limiting</strong> — on a low or recovering node it will make balance checks too infrequent and keep broken sessions open longer than necessary.</p>
              </div>

              <div className="space-y-1">
                <p className="text-slate-300 font-semibold uppercase tracking-wider text-[10px]">How changes are applied</p>
                <p>Settings are written via <code className="bg-slate-800 px-1 rounded">myst config set</code> to <code className="bg-slate-800 px-1 rounded">{tomlPath}</code>. The <code className="bg-slate-800 px-1 rounded">balance-check-interval</code> control writes two TOML keys simultaneously (<code className="bg-slate-800 px-1 rounded">[pingpong]</code> and <code className="bg-slate-800 px-1 rounded">[session.pingpong]</code>). <strong className="text-amber-300">All changes require a node restart to take effect.</strong> Use the Restart button in the edit panel after applying.</p>
              </div>

              {/* Scroll sentinel */}
              <div className="h-px" />
            </div>

            <div className="flex-shrink-0 px-5 py-4 border-t border-slate-700/50 space-y-3">
              {!scrolledToBottom && (
                <p className="text-xs text-slate-500 text-center">↓ Scroll to bottom to acknowledge</p>
              )}
              <label className={`flex items-center gap-3 cursor-pointer select-none transition ${scrolledToBottom ? 'opacity-100' : 'opacity-30 pointer-events-none'}`}>
                <input type="checkbox" checked={acknowledged} onChange={e => setAcknowledged(e.target.checked)}
                  className="w-4 h-4 rounded accent-violet-500" />
                <span className="text-xs text-slate-300">I have read and understood the above</span>
              </label>
              <button
                disabled={!acknowledged}
                onClick={() => setPhase(2)}
                className="w-full py-2 text-sm font-semibold bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 rounded-lg hover:bg-emerald-500/30 transition disabled:opacity-30 disabled:pointer-events-none">
                Unlock Controls →
              </button>
            </div>
          </div>
        )}

        {/* Phase 2 — Edit */}
        {phase === 2 && (
          <div className="flex flex-col flex-1 overflow-hidden">
            {/* Preset bar */}
            <div className="flex-shrink-0 px-5 py-3 border-b border-slate-700/50 flex items-center gap-2 flex-wrap">
              <span className="text-xs text-slate-500 mr-1">Load preset:</span>
              {Object.entries(PRESETS).map(([pk, pv]) => (
                <button key={pk} onClick={() => loadPreset(pk)}
                  className={`px-3 py-1 text-xs border rounded transition ${
                    pk === 'high-traffic'
                      ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30 hover:bg-emerald-500/30'
                      : 'bg-slate-600/30 text-slate-300 border-slate-500/30 hover:bg-slate-600/50'
                  }`}>
                  {pv.label}
                </button>
              ))}
              <span className="text-xs text-slate-600 ml-auto hidden sm:block">Values loaded into fields — click Apply to save</span>
            </div>

            {/* Restart warning */}
            <div className="flex-shrink-0 px-5 py-2 bg-amber-500/10 border-b border-amber-500/20 flex items-center gap-2">
              <span className="text-amber-400 text-xs">⚠</span>
              <span className="text-xs text-amber-300 font-semibold">All changes require a node restart to take effect</span>
            </div>

            {/* Settings list */}
            <div className="flex-1 overflow-y-auto px-5 py-4 space-y-5">
              {loading && <p className="text-xs text-slate-500 text-center py-8">Loading current values…</p>}
              {!loading && Object.entries(groups).map(([gk, g]) => (
                <div key={gk}>
                  <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-2">{g.label}</p>
                  <div className="space-y-2">
                    {g.keys.map(meta => {
                      const cur = currentValues[meta.key] ?? '—';
                      const pending = pendingValues[meta.key] ?? '';
                      const isDirty = String(pending) !== String(cur);
                      const res = results[meta.key];
                      const busy = applying[meta.key];
                      return (
                        <div key={meta.key} className={`p-3 rounded-lg border transition ${
                          res === 'ok' ? 'border-emerald-500/40 bg-emerald-500/5' :
                          res && res !== 'ok' ? 'border-red-500/40 bg-red-500/5' :
                          isDirty ? 'border-emerald-500/30 bg-emerald-500/5' :
                          'border-slate-700/50 bg-slate-800/20'
                        }`}>
                          <div className="flex items-start justify-between gap-2 mb-1">
                            <div>
                              <span className="text-xs font-semibold text-slate-200">{meta.label}</span>
                              <span className="text-[10px] text-slate-500 ml-2">({meta.unit})</span>
                              {isDirty && !res && <span className="text-[10px] text-emerald-400 ml-2">● modified</span>}
                              {res === 'ok' && <span className="text-[10px] text-emerald-400 ml-2">✓ applied</span>}
                              {res && res !== 'ok' && <span className="text-[10px] text-red-400 ml-2">✗ {res}</span>}
                            </div>
                            <span className="text-[10px] text-slate-500 shrink-0">current: <span className="text-slate-300 font-mono">{cur}</span></span>
                          </div>
                          <p className="text-[10px] text-slate-500 mb-2 leading-relaxed">{meta.desc}</p>
                          <div className="flex items-center gap-2">
                            <input
                              type="number"
                              step={meta.unit === 'MYST' ? '0.01' : '1'}
                              value={pending}
                              onChange={e => setPendingValues(p => ({ ...p, [meta.key]: e.target.value }))}
                              className="flex-1 min-w-0 px-2 py-1 text-xs font-mono bg-slate-900 border border-slate-600/50 rounded text-slate-200 focus:outline-none focus:border-emerald-500/60"
                            />
                            <button onClick={() => applyOne(meta.key)} disabled={!!busy}
                              className="px-3 py-1 text-xs bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 rounded hover:bg-emerald-500/30 transition disabled:opacity-40 shrink-0">
                              {busy ? '…' : 'Apply'}
                            </button>
                            <button onClick={() => resetOne(meta.key)} disabled={!!busy}
                              className="px-2 py-1 text-xs bg-slate-600/30 text-slate-400 border border-slate-600/30 rounded hover:bg-slate-600/50 transition disabled:opacity-40 shrink-0"
                              title="Reset to node default">↺</button>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>

            {/* Footer actions */}
            <div className="flex-shrink-0 px-5 py-4 border-t border-slate-700/50 flex items-center gap-2 flex-wrap">
              <button onClick={applyAll}
                className="px-4 py-2 text-xs font-semibold bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 rounded hover:bg-emerald-500/30 transition">
                Apply All Changes
              </button>
              <NodeRestartButton backendUrl={backendUrl} authHeaders={authHeaders} />
              <button onClick={() => { setPendingValues({ ...currentValues }); setResults({}); }}
                className="px-3 py-1.5 text-xs bg-slate-600/30 text-slate-400 border border-slate-600/30 rounded hover:bg-slate-600/50 transition ml-auto">
                Reset Fields
              </button>
            </div>
          </div>
        )}
      </div>
    </>
  );
};

// Small inline restart button used inside NodeConfigModal footer
const NodeRestartButton = ({ backendUrl, authHeaders }) => {
  const [status, setStatus] = React.useState(null);
  const handle = async () => {
    if (!backendUrl || !confirm('Restart the Mysterium node now? All active sessions will be dropped.')) return;
    setStatus('restarting…');
    try {
      const resp = await fetch(`${backendUrl}/node/restart`, { method: 'POST', headers: authHeaders || {} });
      const data = await resp.json();
      setStatus(data.success ? '✓ Restarting' : `✗ ${data.error}`);
    } catch (e) { setStatus(`✗ ${e.message}`); }
    setTimeout(() => setStatus(null), 8000);
  };
  return (
    <button onClick={handle} disabled={!!status}
      className="px-3 py-1.5 text-xs bg-amber-500/20 text-amber-300 border border-amber-500/30 rounded hover:bg-amber-500/30 transition disabled:opacity-50">
      {status || '⟳ Restart Node Now'}
    </button>
  );
};

const StatusCard = ({ nodeStatus, resources, earnings, clients, activeSessions, backendUrl, authHeaders, fleetNode, nodeUpdateInfo }) => {
  const [restartStatus, setRestartStatus] = React.useState(null);
  const [showConfig, setShowConfig] = React.useState(false);
  const status = nodeStatus?.status || 'offline';
  const uptime = nodeStatus?.uptime || '0s';
  const nodesOnline = nodeStatus?.nodes_online || 0;
  const nodesTotal = nodeStatus?.nodes_total || 1;
  const isOnline = status === 'online';
  const isMultiNode = nodesTotal > 1;
  const allTemps = resources?.all_temps || [];
  const natType = nodeStatus?.nat_type || '';
  const publicIp = nodeStatus?.public_ip || '';
  const nodeVersion = nodeStatus?.version || '';
  const wallet = earnings?.wallet_address || '';
  const shortWallet = wallet ? `${wallet.slice(0, 6)}...${wallet.slice(-4)}` : '';
  const connected = clients?.connected || 0;

  const handleRestart = async () => {
    if (!backendUrl || !confirm('Restart the Mysterium node? This will temporarily disconnect all clients.')) return;
    setRestartStatus('restarting...');
    try {
      const resp = await fetch(`${backendUrl}/node/restart`, { method: 'POST', headers: authHeaders || {} });
      const data = await resp.json();
      setRestartStatus(data.success ? '✓ Restarting...' : `✗ ${data.error}`);
    } catch (e) { setRestartStatus(`✗ ${e.message}`); }
    setTimeout(() => setRestartStatus(null), 8000);
  };

  return (
    <>
    {showConfig && <NodeConfigModal backendUrl={backendUrl} authHeaders={authHeaders} onClose={() => setShowConfig(false)} />}
    <div className="p-4 sm:p-6 bg-slate-800/30 border border-slate-700 rounded-lg backdrop-blur">
      <div className="flex items-start justify-between mb-3">
        <h2 className="text-sm font-semibold tracking-wide">Node Status</h2>
        <div className="flex items-center gap-2">
          <button onClick={() => setShowConfig(true)}
            className="px-2 py-1 text-xs font-semibold uppercase tracking-wider bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 rounded hover:bg-emerald-500/30 transition"
            title="Payment Config Tuner">
            ⚙ Config
          </button>
          <button onClick={handleRestart} disabled={!!restartStatus}
            className="px-2 py-1 text-xs font-semibold uppercase tracking-wider bg-amber-500/20 text-amber-300 border border-amber-500/30 rounded hover:bg-amber-500/30 transition disabled:opacity-50">
            {restartStatus || '⟳ Restart'}
          </button>
          {isOnline ? (
            <CheckCircle2 className="w-5 h-5 text-emerald-400" />
          ) : (
            <AlertCircle className="w-5 h-5 text-red-400" />
          )}
        </div>
      </div>
      <div className={`text-2xl sm:text-3xl font-bold mb-2 ${isOnline ? 'text-emerald-400' : 'text-red-400'}`}>
        {isOnline ? 'Online' : 'Offline'}
      </div>
      {allTemps.length > 0 && (
        <div className="flex flex-wrap gap-x-3 gap-y-1 mb-3">
          {allTemps.map((t, i) => {
            const tc = t.value < 60 ? 'text-emerald-300' : t.value < 80 ? 'text-amber-300' : 'text-red-400';
            return (
              <span key={i} className={`text-xs font-semibold ${tc}`} title={`${t.sensor}: ${t.label}`}>
                {t.label}: {t.value.toFixed(0)}°C
              </span>
            );
          })}
        </div>
      )}
      <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-slate-400">
        <div>Uptime: <span className="text-slate-300 font-semibold">{formatUptime(uptime)}</span></div>
        {(activeSessions > 0 || clients?.connected > 0) && (
          <div>Clients: <span className="text-emerald-300 font-semibold">{activeSessions || clients?.connected || 0}</span></div>
        )}
        {nodeVersion && nodeVersion !== 'unknown' && (
          <div>
            <div>Version: <span className="text-slate-300">{nodeVersion}</span></div>
            {nodeUpdateInfo?.update_available && (
              <div className="mt-0.5">
                <span className="text-xs text-amber-400 border border-amber-500/40 bg-amber-500/10 rounded px-1.5 py-0.5" title={`Mysterium node v${nodeUpdateInfo.latest} available`}>
                  ↑ {nodeUpdateInfo.latest} available
                </span>
              </div>
            )}
          </div>
        )}
        {isOnline && (() => {
          const NAT_LABELS = {
            none:      'Open / No NAT',
            fullcone:  'Full Cone',
            rcone:     'Restricted Cone',
            prcone:    'Port Restricted',
            symmetric: 'Symmetric',
          };
          const NAT_COLORS = {
            none:      'text-emerald-300',
            fullcone:  'text-emerald-300',
            rcone:     'text-emerald-300',
            prcone:    'text-amber-300',
            symmetric: 'text-red-400',
          };
          const nt   = (natType || '').toLowerCase();
          const label = NAT_LABELS[nt] || (natType && natType !== 'unknown' ? natType : 'Detecting\u2026');
          const color = NAT_COLORS[nt] || (natType && natType !== 'unknown' ? 'text-slate-300' : 'text-slate-500');
          return (
            <div>NAT: <span className={`font-semibold ${color}`}>{label}</span></div>
          );
        })()}
        {publicIp && (
          <div>IP: <span className="text-cyan-300 font-mono text-xs">{publicIp}</span></div>
        )}
        {shortWallet && (
          <div className="col-span-2">Identity: <span className="text-cyan-300 font-mono text-xs">{shortWallet}</span></div>
        )}
      </div>
      {isMultiNode && (
        <div className="text-xs text-slate-400 mt-2">
          Nodes: <span className={`font-semibold ${nodesOnline === nodesTotal ? 'text-emerald-300' : 'text-yellow-300'}`}>{nodesOnline}/{nodesTotal} online</span>
        </div>
      )}
    </div>
    </>
  );
};

const EarningsCard = ({ earnings, backendUrl, authHeaders }) => {
  const [settleStatus, setSettleStatus] = React.useState(null);
  const [mystPrice, setMystPrice] = React.useState(null);

  // Fetch MYST token price — refreshes every 5 minutes (matches backend cache TTL)
  React.useEffect(() => {
    if (!backendUrl) return;
    const fetchPrice = () => {
      fetch(`${backendUrl}/myst-price`, { headers: authHeaders || {} })
        .then(r => r.json())
        .then(d => { if (d.usd || d.eur) setMystPrice(d); })
        .catch(() => {});
    };
    fetchPrice();
    const id = setInterval(fetchPrice, 300_000);
    return () => clearInterval(id);
  }, [backendUrl]);

  const safeEarnings = {
    balance: Number(earnings?.balance) || 0,
    unsettled: Number(earnings?.unsettled) || 0,
    lifetime: Number(earnings?.lifetime) || 0,
    session_total: Number(earnings?.session_total) || 0,
    // Keep null as null — null means "not enough history yet", 0 means genuinely zero
    daily:   earnings?.daily   != null ? Number(earnings.daily)   : null,
    weekly:  earnings?.weekly  != null ? Number(earnings.weekly)  : null,
    monthly: earnings?.monthly != null ? Number(earnings.monthly) : null,
  };
  const walletAddr = earnings?.wallet_address || '';
  const shortWallet = walletAddr ? `${walletAddr.slice(0, 6)}...${walletAddr.slice(-4)}` : '';
  const earningsSource = earnings?.earnings_source || 'building';
  const isTracked = earningsSource === 'delta';
  const isRateLimited = earningsSource === 'rate_limited';
  const isBuilding = earningsSource === 'building' || earningsSource === 'sessions';
  const displayUnsettled = safeEarnings.unsettled > 0 ? safeEarnings.unsettled : safeEarnings.session_total;

  const fmtEarning = (val) => val != null ? val.toFixed(4) : '—';
  const earningLabel = (val) => val != null
    ? <span className="text-emerald-300 font-semibold">{val.toFixed(4)}</span>
    : <span className="text-slate-500 font-semibold">— <span className="font-normal text-slate-600 text-[10px]">building</span></span>;

  const handleSettle = async () => {
    if (!backendUrl) return;
    setSettleStatus('settling...');
    try {
      const resp = await fetch(`${backendUrl}/node/settle`, { method: 'POST', headers: authHeaders || {} });
      const data = await resp.json();
      setSettleStatus(data.success ? `✓ ${data.message}` : `✗ ${data.error}`);
    } catch (e) { setSettleStatus(`✗ ${e.message}`); }
    setTimeout(() => setSettleStatus(null), 8000);
  };

  return (
    <div className="p-6 bg-gradient-to-br from-emerald-500/10 to-slate-800/30 border border-emerald-500/30 rounded-lg backdrop-blur">
      <div className="flex items-start justify-between mb-1">
        <h2 className="text-sm font-semibold tracking-wide">Unsettled Earnings</h2>
        <button onClick={handleSettle} disabled={!!settleStatus}
          className="px-2 py-1 text-xs font-semibold uppercase tracking-wider bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 rounded hover:bg-emerald-500/30 transition disabled:opacity-50">
          {settleStatus || 'Settle'}
        </button>
      </div>
      <div className="text-4xl font-bold text-emerald-400 mb-1">
        {displayUnsettled.toFixed(4)} <span className="text-lg text-emerald-400/60">MYST</span>
        {safeEarnings.unsettled <= 0 && safeEarnings.session_total > 0 && (
          <span className="text-xs text-emerald-400/60 ml-2">(from session tokens)</span>
        )}
      </div>
      {/* Fiat value of unsettled + live token price */}
      <div className="flex items-center gap-3 mb-3 text-xs">
        {mystPrice?.eur != null ? (
          <span className="text-slate-300 font-semibold">
            ≈ €{(displayUnsettled * mystPrice.eur).toFixed(2)}
            <span className="text-slate-600 ml-1 font-normal">/ ${(displayUnsettled * mystPrice.usd).toFixed(2)}</span>
          </span>
        ) : (
          <span className="text-slate-600">fiat value loading…</span>
        )}
        {mystPrice?.eur != null && (
          <span className="text-slate-600 ml-auto">
            1 MYST = €{mystPrice.eur.toFixed(4)}
            <span className="text-slate-700 ml-1">/ ${mystPrice.usd.toFixed(4)}</span>
            {mystPrice.stale && <span className="text-amber-600 ml-1">(stale)</span>}
          </span>
        )}
      </div>
      <div className="grid grid-cols-2 gap-3 text-xs mb-3 pb-3 border-b border-slate-600/40">
        <div>
          <div className="text-slate-400">Lifetime Gross <span className="text-slate-600 text-[10px]">(pre-fee)</span></div>
          <div className="text-emerald-300 font-semibold">{safeEarnings.lifetime > 0 ? safeEarnings.lifetime.toFixed(4) + ' MYST' : '—'}</div>
        </div>
        <div>
          <div className="text-slate-400">Hermes Channel <span className="text-slate-600 text-[10px]">(unsettled buffer)</span></div>
          <div className="text-emerald-300 font-semibold">
            {safeEarnings.balance > 0
              ? safeEarnings.balance.toFixed(4) + ' MYST'
              : <span className="text-slate-500 text-xs">0.0000 <span className="text-slate-600 text-[10px]">— settled to wallet ↓</span></span>
            }
          </div>
        </div>
      </div>
      {isRateLimited && (
        <div className="mb-2 p-2 bg-red-500/10 border border-red-500/30 rounded text-xs text-red-300">
          ⚠ Identity API rate-limited — blockchain data unavailable. Showing cached session tokens only.
          Daily/weekly/monthly paused until API recovers. No snapshot recorded during this period.
        </div>
      )}
      {!isRateLimited && safeEarnings.unsettled <= 0 && safeEarnings.session_total <= 0 && (
        <div className="mb-2 p-2 bg-amber-500/10 border border-amber-500/30 rounded text-xs text-amber-300">
          ⚠ Identity API unavailable. Check node connectivity.
        </div>
      )}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 sm:gap-4 text-xs mb-2 pb-3 border-b border-slate-600/40">
        <div>
          <div className="text-slate-400">{isTracked ? 'Daily' : isRateLimited ? 'Session (cached)' : 'Session tokens (30d)'}</div>
          {isTracked
            ? earningLabel(safeEarnings.daily)
            : isRateLimited
              ? <span className="text-amber-400 font-semibold">{safeEarnings.session_total != null ? safeEarnings.session_total.toFixed(4) : '—'}</span>
              : <span className="text-emerald-300 font-semibold">{safeEarnings.session_total != null ? safeEarnings.session_total.toFixed(4) : '—'}</span>
          }
          {mystPrice?.eur != null && isTracked && safeEarnings.daily != null && (
            <div className="text-[10px] text-slate-600 mt-0.5">≈ €{(safeEarnings.daily * mystPrice.eur).toFixed(3)}</div>
          )}
        </div>
        <div>
          <div className="text-slate-400">Weekly</div>
          {earningLabel(isTracked ? safeEarnings.weekly : null)}
          {mystPrice?.eur != null && isTracked && safeEarnings.weekly != null && (
            <div className="text-[10px] text-slate-600 mt-0.5">≈ €{(safeEarnings.weekly * mystPrice.eur).toFixed(3)}</div>
          )}
        </div>
        <div>
          <div className="text-slate-400">Monthly</div>
          {earningLabel(isTracked ? safeEarnings.monthly : null)}
          {mystPrice?.eur != null && isTracked && safeEarnings.monthly != null && (
            <div className="text-[10px] text-slate-600 mt-0.5">≈ €{(safeEarnings.monthly * mystPrice.eur).toFixed(3)}</div>
          )}
        </div>
      </div>
      <div className="flex items-center gap-2 text-xs text-slate-500 mb-2">
        <span className={`px-1.5 py-0.5 rounded font-semibold uppercase tracking-wider ${
          isTracked
            ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
            : isRateLimited
              ? 'bg-red-500/20 text-red-400 border border-red-500/30'
              : 'bg-amber-500/20 text-amber-400 border border-amber-500/30'
        }`}>{isTracked ? 'TRACKED' : isRateLimited ? 'RATE LIMITED' : 'BUILDING HISTORY'}</span>
        <span>{isTracked
          ? 'Daily/weekly/monthly from balance history'
          : isRateLimited
            ? 'Identity API blocked — history paused, no bad data recorded'
            : 'Daily after 24h · Weekly after 7d · Monthly after 30d'
        }</span>
      </div>
    </div>
  );
};

const SettlementHistoryCard = ({ backendUrl, authHeaders }) => {
  const [data, setData]           = React.useState(null);
  const [loading, setLoading]     = React.useState(false);
  const [error, setError]         = React.useState(null);
  const [open, setOpen]           = React.useState(false);
  const [mystPrice, setMystPrice] = React.useState(null);

  const load = () => {
    if (!backendUrl || loading) return;
    setLoading(true);
    setError(null);
    fetch(`${backendUrl}/settle/history`, { headers: authHeaders || {} })
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then(d => { setData(d); setLoading(false); })
      .catch(e => { setError(e.message); setLoading(false); });
  };

  React.useEffect(() => {
    if (backendUrl) {
      load();
      // Fetch MYST price for wallet value display
      fetch(`${backendUrl}/myst-price`, { headers: authHeaders || {} })
        .then(r => r.json())
        .then(d => { if (d.usd || d.eur) setMystPrice(d); })
        .catch(() => {});
    }
  }, [backendUrl]);

  // Prefer on-chain transactions (Polygonscan) over TequilAPI settlements
  const onchainTxs    = data?.onchain_txs || [];
  const hasOnchain    = onchainTxs.length > 0;
  const displayTxs    = hasOnchain ? onchainTxs : (data?.settlements || []);
  const totalDisplay  = hasOnchain ? (data?.total_onchain || 0) : (data?.total_settled || 0);
  const txSource      = hasOnchain ? 'on-chain (Polygonscan)' : 'TequilAPI settle history';
  const txCount       = hasOnchain ? (data?.onchain_count || 0) : (data?.settlements?.length || 0);
  const walletBalance = data?.wallet_balance;
  const beneficiary   = data?.beneficiary || '';
  const shortBen      = beneficiary
    ? `${beneficiary.slice(0, 8)}...${beneficiary.slice(-6)}`
    : '';
  const polyWalletUrl = data?.polygonscan_wallet;
  const hasData       = data !== null;

  return (
    <div className="mb-6 p-4 bg-slate-800/30 border border-slate-700 rounded-lg backdrop-blur">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-slate-300 tracking-wide">On-Chain Wallet</h3>
        <div className="flex gap-2">
          <button onClick={load} disabled={loading}
            className="text-[10px] text-slate-600 hover:text-slate-300 px-2 py-1 rounded border border-slate-700 hover:border-slate-500 transition disabled:opacity-40"
            title="Refresh wallet balance">
            {loading ? '⟳' : '↻'}
          </button>
          <button onClick={() => setOpen(o => !o)}
            className="text-[10px] text-slate-500 hover:text-slate-300 px-2 py-1 rounded border border-slate-700 hover:border-slate-500 transition">
            {open ? 'Hide history' : `Show history (${txCount})`}
          </button>
        </div>
      </div>

      {/* Wallet balance + address */}
      <div className="grid grid-cols-2 gap-3 text-xs mb-3">
        <div>
          <div className="text-slate-500 mb-0.5">MYST balance on Polygon</div>
          {loading && !hasData
            ? <div className="text-slate-600 text-xs">loading…</div>
            : walletBalance != null
              ? <>
                  <div className="text-emerald-300 font-bold text-lg">{walletBalance.toFixed(4)} <span className="text-xs text-slate-500">MYST</span></div>
                  {mystPrice?.eur != null && (
                    <div className="text-slate-400 text-xs mt-0.5">
                      ≈ <span className="text-slate-300 font-semibold">€{(walletBalance * mystPrice.eur).toFixed(2)}</span>
                      <span className="text-slate-600 ml-1">/ ${(walletBalance * mystPrice.usd).toFixed(2)}</span>
                    </div>
                  )}
                </>
              : hasData
                ? <div className="text-slate-500 text-xs">
                    unavailable
                    <span className="block text-slate-700 text-[10px]">Polygonscan rate limited — add polygonscan_api_key to setup.json</span>
                    {beneficiary && (
                      <a href={`https://polygonscan.com/token/0x4B0181102A0112A2ef11AbEE5563bb4a3176c9d7?a=${beneficiary}`}
                        target="_blank" rel="noreferrer"
                        className="text-cyan-600 hover:text-cyan-400 text-[10px]">View on Polygonscan ↗</a>
                    )}
                  </div>
                : <div className="text-slate-600 text-xs">—</div>
          }
        </div>
        <div>
          <div className="text-slate-500 mb-0.5">Beneficiary wallet</div>
          {beneficiary
            ? <div className="font-mono text-[10px] text-cyan-400 break-all">
                {shortBen}
                {polyWalletUrl && (
                  <a href={polyWalletUrl} target="_blank" rel="noreferrer"
                    className="ml-1 text-slate-500 hover:text-cyan-300 transition">↗</a>
                )}
              </div>
            : <div className="text-slate-600 text-xs">—</div>
          }
        </div>
      </div>

      {/* Total settled summary */}
      {data && (
        <div className="flex items-center gap-3 text-xs text-slate-500 mb-3 pb-3 border-b border-slate-700/40">
          <span>{txCount} transactions</span>
          <span>·</span>
          <span>Total: <span className="text-emerald-300 font-semibold">{totalDisplay.toFixed(4)} MYST</span></span>
          <span className="text-slate-700">({txSource})</span>
        </div>
      )}

      {/* Settlement history table */}
      {open && (
        <div className="space-y-1 max-h-64 overflow-y-auto pr-1">
          {displayTxs.length === 0 && (
            <div className="text-xs text-slate-600 text-center py-4">
              {data ? 'No transactions found — add polygonscan_api_key to setup.json for on-chain data' : 'Loading…'}
            </div>
          )}
          {displayTxs.length > 0 && !hasOnchain && displayTxs.every(t => (t.amount_myst || 0) === 0) && (
            <div className="text-xs text-slate-600 mt-2 pt-2 border-t border-slate-700/30">
              ⚠ TequilAPI returns 0.0000 for these entries — this is normal for fee-only settlements.
              Add <code className="bg-slate-800 px-1 rounded">polygonscan_api_key</code> to <code className="bg-slate-800 px-1 rounded">config/setup.json</code> to see real on-chain amounts.
            </div>
          )}
          {displayTxs.map((tx, i) => {
            // Support both on-chain (date, direction) and TequilAPI (settled_at, error) format
            const dateStr    = tx.date || tx.settled_at || '—';
            const amtMyst    = tx.amount_myst || 0;
            const txHash     = tx.tx_hash || '';
            const polyUrl    = tx.polygonscan_url || (txHash ? `https://polygonscan.com/tx/${txHash}` : null);
            const isIn       = tx.direction === 'in' || !tx.direction;
            const hasError   = !!tx.error;
            const isZeroAmt  = amtMyst === 0 && !hasError;
            return (
              <div key={i} className={`flex items-center gap-2 text-xs py-1.5 border-b border-slate-700/20 last:border-0 ${hasError ? 'opacity-50' : ''} ${isZeroAmt ? 'opacity-40' : ''}`}>
                <div className="text-slate-500 w-36 flex-shrink-0">{dateStr}</div>
                <div className={`font-semibold w-24 ${hasError ? 'text-red-400' : isZeroAmt ? 'text-slate-600' : isIn ? 'text-emerald-300' : 'text-amber-300'}`}>
                  {hasError ? 'Failed' : isZeroAmt ? 'fee-only' : `${isIn ? '+' : '−'}${amtMyst.toFixed(4)}`}
                </div>
                <div className="flex-1 truncate">
                  {txHash
                    ? <a href={polyUrl} target="_blank" rel="noreferrer"
                        className="font-mono text-[10px] text-cyan-400/70 hover:text-cyan-300 transition">
                        {txHash.slice(0, 10)}…{txHash.slice(-6)} ↗
                      </a>
                    : <span className="text-slate-700 text-[10px]">no tx hash</span>
                  }
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

const ServiceToggleRow = ({ svc, backendUrl, authHeaders }) => {
  const [status, setStatus]         = React.useState(null);
  const [busy, setBusy]             = React.useState(false);
  const [confirm, setConfirm]       = React.useState(false);
  // Local override: after toggle, hold the new state for 30s to prevent
  // metrics refresh from flipping it back before the node has time to react
  const [localActive, setLocalActive] = React.useState(null);
  const localOverrideRef = React.useRef(null);

  const isActive = localActive !== null ? localActive : svc.is_active;

  const CORE_SERVICES = [];  // No core services — wireguard is internal, not user-toggleable
  const isCore = CORE_SERVICES.includes((svc.type || '').toLowerCase());
  const SERVICE_LABELS_TOGGLE = {
    wireguard:      'WireGuard (tunnel)',
    dvpn:           'VPN',
    public:         'Public',
    data_transfer:  'B2B VPN and data transfer',
    scraping:       'B2B Data Scraping',
    quic_scraping:  'QUIC Scraping',
  };
  const typeLabel = svc.label || SERVICE_LABELS_TOGGLE[svc.type] || svc.type;

  const handleToggle = async () => {
    if (!backendUrl) return;
    if (isActive && !confirm) {
      setConfirm(true);
      setTimeout(() => setConfirm(false), 4000);
      return;
    }
    setConfirm(false);
    setBusy(true);
    setStatus(null);
    try {
      let resp, data;
      if (isActive) {
        if (!svc.id) { setStatus('✗ service not running'); setBusy(false); return; }
        resp = await fetch(`${backendUrl}/services/${svc.id}/stop`, {
          method: 'POST', headers: authHeaders || {}
        });
      } else {
        resp = await fetch(`${backendUrl}/services/start`, {
          method: 'POST',
          headers: { ...(authHeaders || {}), 'Content-Type': 'application/json' },
          body: JSON.stringify({ service_type: svc.type }),
        });
      }
      data = await resp.json();
      if (data.success) {
        const newState = !isActive;
        setLocalActive(newState);
        setStatus('✓ done');
        // Hold local override for 30s then release back to server state
        if (localOverrideRef.current) clearTimeout(localOverrideRef.current);
        localOverrideRef.current = setTimeout(() => setLocalActive(null), 30000);
      } else {
        setStatus(`✗ ${data.error}`);
      }
    } catch (e) {
      setStatus(`✗ ${e.message}`);
    }
    setBusy(false);
    setTimeout(() => setStatus(null), 5000);
  };

  return (
    <div className={`flex items-center gap-3 text-sm px-4 py-3 rounded border ${
      isActive ? 'bg-emerald-500/5 border-emerald-500/20' : 'bg-slate-900/30 border-slate-700/30'
    }`}>
      {/* Toggle switch */}
      <button
        onClick={handleToggle}
        disabled={busy}
        title={isCore && isActive ? `Warning: stopping ${typeLabel} will disconnect active consumers` : ''}
        className={`relative inline-flex h-5 w-9 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 focus:outline-none disabled:opacity-40 ${
          confirm ? 'bg-red-500 animate-pulse' : isActive ? 'bg-emerald-500' : 'bg-slate-600'
        }`}
      >
        <span className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition duration-200 ${
          isActive ? 'translate-x-4' : 'translate-x-0'
        }`} />
      </button>
      <div className="flex-1">
        <span className="font-semibold text-slate-200">{typeLabel}</span>
        {busy && <span className="ml-2 text-xs text-slate-400">…</span>}
        {confirm && <span className="ml-2 text-xs text-red-400">Click again to stop</span>}
        {status && <span className={`ml-2 text-xs ${status.startsWith('✓') ? 'text-emerald-400' : 'text-red-400'}`}>{status}</span>}
      </div>
      <span className={`text-xs px-2 py-0.5 rounded ${
        isActive
          ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
          : 'bg-slate-700/50 text-slate-400 border border-slate-600'
      }`}>{isActive ? 'Running' : 'Stopped'}</span>
    </div>
  );
};

const MetricCard = ({ icon, title, value, subtitle, color }) => {
  const colorClasses = {
    emerald: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/30',
    amber: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/30',
    purple: 'text-purple-400 bg-purple-500/10 border-purple-500/30',
  };

  return (
    <div className="p-4 bg-slate-800/30 border border-slate-700 rounded-lg backdrop-blur">
      <div className={`inline-block p-2 rounded mb-3 ${colorClasses[color]}`}>
        {icon}
      </div>
      <h3 className="text-xs font-semibold text-slate-300 tracking-wide mb-2">{title}</h3>
      <div className="text-2xl font-bold mb-1">{value}</div>
      <div className="text-xs text-slate-400">{subtitle}</div>
    </div>
  );
};

const DetailCard = ({ title, value, subtitle, icon }) => {
  return (
    <div className="min-w-[140px] flex-1 p-4 bg-slate-800/30 border border-slate-700 rounded-lg backdrop-blur flex items-start gap-3">
      <div className="flex-shrink-0 mt-1">{icon}</div>
      <div className="flex-1 min-w-0">
        <h3 className="text-xs font-semibold text-slate-300 tracking-wide mb-1">{title}</h3>
        <div className="text-xl font-bold">{value}</div>
        {subtitle && <div className="text-xs text-slate-400 mt-1 truncate">{subtitle}</div>}
      </div>
    </div>
  );
};

const formatUptime = (uptime) => {
  // Handle string format from TequilAPI (e.g., "16h26m41.464696505s")
  if (typeof uptime === 'string') {
    const dayMatch = uptime.match(/(\d+)d/);
    const hourMatch = uptime.match(/(\d+)h/);
    const minMatch = uptime.match(/(\d+)m/);

    const days = dayMatch ? parseInt(dayMatch[1]) : 0;
    const hours = hourMatch ? parseInt(hourMatch[1]) : 0;
    const mins = minMatch ? parseInt(minMatch[1]) : 0;

    if (days > 0) return `${days}d ${hours}h`;
    if (hours > 0) return `${hours}h ${mins}m`;
    if (mins > 0) return `${mins}m`;
    return uptime || '0s';
  }

  // Handle numeric seconds
  const seconds = parseInt(uptime) || 0;
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
  return `${Math.floor(seconds / 86400)}d ${Math.floor((seconds % 86400) / 3600)}h`;
};

export { ErrorBoundary };
export default MysteriumDashboard;

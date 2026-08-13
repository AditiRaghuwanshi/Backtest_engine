import { useState, useEffect, useRef } from "react";
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
} from "recharts";

const API = "http://localhost:8000";

const DEFAULTS = {
  start: "2018-07-05",
  end: "2026-07-03",
  universe_size: 40,
  universe_lookback: 60,
  hold_count: 20,
  momentum_lookback: 60,
  buffer_rank: 25,
  capital: 2000000,
  max_weight: 0.08,
  stop_loss_pct: 8,
  stop_check: "close",
  rebalance: "monthly",
  cost_bps: 15,
};

// har field ka label + type -- form yahi list se banta hai
const FIELDS = [
  { key: "start",             label: "Start date",         type: "date" },
  { key: "end",               label: "End date",           type: "date" },
  { key: "universe_size",     label: "Universe size",      type: "number", help: "636 mese kitni shortlist" },
  { key: "universe_lookback", label: "Liquidity lookback", type: "number", help: "kitne din ka turnover" },
  { key: "hold_count",        label: "Hold count",         type: "number", help: "ek time pe kitni companies" },
  { key: "momentum_lookback", label: "Momentum lookback",  type: "number", help: "kitne din ka return = score" },
  { key: "buffer_rank",       label: "Buffer rank",        type: "number", help: "is rank tak purani holding rakho" },
  { key: "capital",           label: "Capital (₹)",        type: "number" },
  { key: "max_weight",        label: "Max weight",         type: "number", step: 0.01, help: "0.08 = 8% per company" },
  { key: "stop_loss_pct",     label: "Stop loss %",        type: "number", step: 0.5 },
  { key: "cost_bps",          label: "Cost (bps/side)",    type: "number", help: "15 = 0.15%" },
  { key: "stop_check",        label: "Stop checked on",    type: "select", options: ["close", "intraday"] },
  { key: "rebalance",         label: "Rebalance",          type: "select", options: ["monthly", "weekly", "daily"] },
];

const inr = (n) => (n == null ? "-" : "₹" + Math.round(n).toLocaleString("en-IN"));
const pct = (n) => (n == null ? "-" : n.toFixed(2) + "%");

export default function App() {
  const [cfg, setCfg] = useState(DEFAULTS);
  const [runId, setRunId] = useState(null);
  const [run, setRun] = useState(null);
  const [nav, setNav] = useState([]);
  const [companies, setCompanies] = useState([]);
  const [elapsed, setElapsed] = useState(0);
  const timer = useRef(null);

  const busy = run?.status === "queued" || run?.status === "running";

  function update(key, value, isNumber) {
    setCfg((c) => ({ ...c, [key]: isNumber ? Number(value) : value }));
  }

  async function startRun() {
    setRun({ status: "queued" });
    setNav([]); setCompanies([]); setElapsed(0);

    const res = await fetch(`${API}/runs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(cfg),
    });
    const data = await res.json();
    setRunId(data.run_id);
  }

  useEffect(() => {
    if (!runId) return;
    timer.current = setInterval(async () => {
      setElapsed((e) => e + 2);
      const data = await fetch(`${API}/runs/${runId}`).then((r) => r.json());
      setRun(data);
      if (data.status === "done" || data.status === "failed") {
        clearInterval(timer.current);
        if (data.status === "done") loadDetails(runId);
      }
    }, 2000);
    return () => clearInterval(timer.current);
  }, [runId]);

  async function loadDetails(id) {
    const [n, c] = await Promise.all([
      fetch(`${API}/runs/${id}/nav`).then((r) => r.json()).catch(() => []),
      fetch(`${API}/runs/${id}/companies`).then((r) => r.json()).catch(() => []),
    ]);
    setNav(Array.isArray(n) ? n : []);
    setCompanies(Array.isArray(c) ? c : []);
  }

  const s = run?.result;

  return (
    <div style={{ padding: 32, fontFamily: "system-ui", maxWidth: 1100, margin: "0 auto" }}>
      <h1 style={{ marginBottom: 24 }}>Backtest</h1>

      {/* ---------------- FORM ---------------- */}
      <div style={{ border: "1px solid #ddd", borderRadius: 10, padding: 20, marginBottom: 28 }}>
        <div style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))",
          gap: 14,
        }}>
          {FIELDS.map((f) => (
            <div key={f.key}>
              <label style={{ fontSize: 12, color: "#555", display: "block" }}>
                {f.label}
              </label>

              {f.type === "select" ? (
                <select
                  value={cfg[f.key]}
                  onChange={(e) => update(f.key, e.target.value, false)}
                  disabled={busy}
                  style={inputStyle}
                >
                  {f.options.map((o) => <option key={o} value={o}>{o}</option>)}
                </select>
              ) : (
                <input
                  type={f.type}
                  step={f.step}
                  value={cfg[f.key]}
                  onChange={(e) => update(f.key, e.target.value, f.type === "number")}
                  disabled={busy}
                  style={inputStyle}
                />
              )}

              {f.help && (
                <div style={{ fontSize: 11, color: "#999", marginTop: 2 }}>{f.help}</div>
              )}
            </div>
          ))}
        </div>

        <div style={{ marginTop: 18, display: "flex", gap: 10 }}>
          <button onClick={startRun} disabled={busy} style={btnStyle(busy)}>
            {busy ? `Running… ${elapsed}s` : "Run backtest"}
          </button>
          <button
            onClick={() => setCfg(DEFAULTS)}
            disabled={busy}
            style={{ ...btnStyle(busy), background: "#fff", color: "#333" }}
          >
            Reset
          </button>
        </div>
      </div>

      {run?.status === "failed" && (
        <pre style={{ color: "crimson", whiteSpace: "pre-wrap" }}>{run.error}</pre>
      )}

      {/* ---------------- SUMMARY ---------------- */}
      {s && (
        <>
          <div style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
            gap: 12, marginBottom: 32,
          }}>
            <Card label="Start" value={inr(s["Start NAV"])} />
            <Card label="End" value={inr(s["End NAV"])} />
            <Card label="Total return" value={pct(s["Total return %"])} />
            <Card label="CAGR" value={pct(s["CAGR %"])} />
            <Card label="Max drawdown" value={pct(s["Max drawdown %"])} bad />
            <Card label="Sharpe" value={s["Sharpe"]?.toFixed(2)} />
            <Card label="Trades" value={s["Trades"]} />
            <Card label="Costs" value={inr(s["Total costs"])} bad />
          </div>

          {nav.length > 0 && (
            <>
              <h3>Portfolio value</h3>
              <div style={{ height: 300, marginBottom: 32 }}>
                <ResponsiveContainer>
                  <LineChart data={nav}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#eee" />
                    <XAxis dataKey="date" tick={{ fontSize: 11 }} minTickGap={60} />
                    <YAxis
                      tick={{ fontSize: 11 }}
                      tickFormatter={(v) => (v / 100000).toFixed(0) + "L"}
                      domain={["auto", "auto"]}
                    />
                    <Tooltip formatter={(v) => inr(v)} />
                    <Line type="monotone" dataKey="nav" stroke="#111" dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </>
          )}

          {companies.length > 0 && (
            <>
              <h3>Company-wise P&amp;L</h3>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
                <thead>
                  <tr style={{ borderBottom: "2px solid #333", textAlign: "left" }}>
                    <th style={{ padding: 8 }}>Company</th>
                    <th style={{ padding: 8, textAlign: "right" }}>Net P&amp;L</th>
                    <th style={{ padding: 8, textAlign: "right" }}>Costs</th>
                    <th style={{ padding: 8, textAlign: "right" }}>Trades</th>
                  </tr>
                </thead>
                <tbody>
                  {companies.slice(0, 25).map((c) => (
                    <tr key={c.symbol} style={{ borderBottom: "1px solid #eee" }}>
                      <td style={{ padding: 8 }}>{c.symbol}</td>
                      <td style={{
                        padding: 8, textAlign: "right",
                        color: c.net_pnl >= 0 ? "#0a7" : "crimson",
                      }}>{inr(c.net_pnl)}</td>
                      <td style={{ padding: 8, textAlign: "right", color: "#888" }}>
                        {inr(c.costs)}
                      </td>
                      <td style={{ padding: 8, textAlign: "right" }}>{c.trades}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p style={{ color: "#888", fontSize: 13 }}>
                Showing top 25 of {companies.length}
              </p>
            </>
          )}
        </>
      )}
    </div>
  );
}

const inputStyle = {
  width: "100%", padding: "7px 9px", marginTop: 3,
  border: "1px solid #ccc", borderRadius: 5, fontSize: 14,
  boxSizing: "border-box",
};

const btnStyle = (busy) => ({
  padding: "10px 20px", fontSize: 15,
  cursor: busy ? "not-allowed" : "pointer",
  border: "1px solid #333", background: busy ? "#999" : "#111",
  color: "#fff", borderRadius: 6,
});

function Card({ label, value, bad }) {
  return (
    <div style={{ border: "1px solid #ddd", borderRadius: 8, padding: "12px 14px" }}>
      <div style={{ fontSize: 12, color: "#888" }}>{label}</div>
      <div style={{
        fontSize: 20, fontWeight: 600, marginTop: 4,
        color: bad ? "crimson" : "#111",
      }}>{value}</div>
    </div>
  );
}
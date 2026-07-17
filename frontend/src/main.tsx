import {useEffect, useRef, useState} from "react";
import {createRoot} from "react-dom/client";
import Plotly from "plotly.js-dist-min";
import {
  api, type Account, type Agent, type Chart, type ClosedTrade, type Cycle,
  type Experiment, type Fill, type JournalEvent, type JournalPage, type Learning,
  type Position, type SimulatedPosition, type SymbolQuote, type SystemStatus,
} from "./api";
import {AccountPanel, AgentCards, DecisionChain, Journal, Panel, State, SystemBar} from "./components";
import "./styles.css";

function ema(values:number[], period:number):number[] {
  if (!values.length) return [];
  const alpha = 2 / (period + 1); const output = [values[0]];
  for (let index = 1; index < values.length; index += 1) output.push(alpha * values[index] + (1 - alpha) * output[index - 1]);
  return output;
}

function StrategyTable({rows}:{rows: Learning["strategies"]}) {
  if (!rows.length) return <p>No evidence persisted yet.</p>;
  return <table><thead><tr><th>Strategy</th><th>Trades</th><th>Win rate</th><th>Profit factor</th><th>Net P&amp;L</th><th>Promotion</th></tr></thead><tbody>{rows.map(s => <tr key={`${s.status}-${s.version}`}><td>{s.version}</td><td>{s.trade_count}</td><td>{s.win_rate === null ? "—" : `${(s.win_rate * 100).toFixed(1)}%`}</td><td>{s.profit_factor === null ? "—" : s.profit_factor.toFixed(2)}</td><td>{s.net_return === null ? "—" : s.net_return.toFixed(2)}</td><td>{s.promotion_status}</td></tr>)}</tbody></table>;
}

function App() {
  const [status, setStatus] = useState<SystemStatus>();
  const [account, setAccount] = useState<Account>();
  const [quote, setQuote] = useState<SymbolQuote>();
  const [positions, setPositions] = useState<Position[]>([]);
  const [simulated, setSimulated] = useState<SimulatedPosition[]>([]);
  const [fills, setFills] = useState<Fill[]>([]);
  const [closedTrades, setClosedTrades] = useState<ClosedTrade[]>([]);
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [chart, setChart] = useState<Chart>();
  const [agents, setAgents] = useState<Agent[]>();
  const [cycle, setCycle] = useState<Cycle | null>();
  const [journal, setJournal] = useState<JournalPage>();
  const [learning, setLearning] = useState<Learning>();
  const [selected, setSelected] = useState<JournalEvent>();
  const [stream, setStream] = useState("CONNECTING");
  const [sourceErrors, setSourceErrors] = useState<Record<string, string>>({});
  const [agentFilter, setAgentFilter] = useState("");
  const [correlationFilter, setCorrelationFilter] = useState("");
  const [replayEvents, setReplayEvents] = useState<JournalEvent[]>([]);
  const [replayIndex, setReplayIndex] = useState(0);
  const [replayPlaying, setReplayPlaying] = useState(false);
  const [replaySpeed, setReplaySpeed] = useState(1);
  const chartNode = useRef<HTMLDivElement>(null);
  const lastStreamEvent = useRef(0);

  const source = <T,>(name: string, promise: Promise<T>, setter: (value: T) => void, clear?: () => void) =>
    promise.then(value => {
      setter(value);
      setSourceErrors(current => {
        if (!(name in current)) return current;
        const next = {...current}; delete next[name]; return next;
      });
    }).catch((error: unknown) => {
      clear?.();
      setSourceErrors(current => ({
        ...current, [name]: error instanceof Error ? error.message : String(error),
      }));
    });

  const load = () => Promise.all([
    source("System", api.status(), setStatus), source("Account", api.account(), setAccount, () => setAccount(undefined)),
    source("Quote", api.quote(), setQuote, () => setQuote(undefined)), source("MT5 positions", api.positions(), setPositions, () => setPositions([])),
    source("Simulated positions", api.simulatedPositions(), setSimulated),
    source("Fills", api.fills(), setFills, () => setFills([])), source("Closed trades", api.closedTrades(), setClosedTrades, () => setClosedTrades([])),
    source("Experiments", api.experiments(), setExperiments), source("Chart", api.chart(), setChart, () => setChart(undefined)),
    source("Agents", api.agents(), setAgents), source("Cycle", api.cycle(), setCycle),
    source("Learning", api.learning(), setLearning),
    source("Journal", api.journal(agentFilter, correlationFilter), setJournal),
  ]);

  useEffect(() => {
    void load(); let stopped = false; let ws: WebSocket | undefined;
    let retry: ReturnType<typeof setTimeout> | undefined;
    const refresh = setInterval(() => void load(), 15000);
    const connect = () => {
      if (stopped) return; setStream("CONNECTING"); ws = new WebSocket(api.wsUrl);
      ws.onopen = () => setStream("CONNECTED");
      ws.onmessage = message => {
        let eventId = 0;
        try { eventId = Number((JSON.parse(String(message.data)) as {event_id?: number}).event_id ?? 0); } catch { eventId = 0; }
        if (eventId && eventId <= lastStreamEvent.current) return;
        if (eventId) lastStreamEvent.current = eventId;
        void load();
      };
      ws.onclose = () => { if (!stopped) { setStream("DISCONNECTED"); retry = setTimeout(connect, 3000); } };
    };
    connect();
    return () => { stopped = true; clearInterval(refresh); if (retry) clearTimeout(retry); ws?.close(); };
  }, []);

  useEffect(() => {
    if (!chart || !chartNode.current) return;
    const closes = chart.bars.map(bar => bar.close);
    const recent = chart.bars.slice(-20);
    const support = recent.length ? Math.min(...recent.map(bar => bar.low)) : undefined;
    const resistance = recent.length ? Math.max(...recent.map(bar => bar.high)) : undefined;
    const sessionLines = chart.bars.filter(bar => [7, 13].includes(new Date(bar.timestamp).getUTCHours()) && new Date(bar.timestamp).getUTCMinutes() === 0).map(bar => ({type:"line", x0:bar.timestamp, x1:bar.timestamp, y0:0, y1:1, yref:"paper", line:{dash:"dot", color:"#31445e", width:1}}));
    const visibleMarkers = chart.markers.filter(marker => marker.timestamp);
    const markerY = visibleMarkers.map(marker => {
      const exact = chart.bars.find(bar => bar.timestamp === marker.timestamp);
      return exact?.high ?? chart.bars.at(-1)?.high ?? 0;
    });
    void Plotly.newPlot(chartNode.current, [{
      x: chart.bars.map(b => b.timestamp), open: chart.bars.map(b => b.open),
      high: chart.bars.map(b => b.high), low: chart.bars.map(b => b.low),
      close: chart.bars.map(b => b.close), type: "candlestick", name: chart.symbol,
    }, {
      x: chart.bars.map(bar => bar.timestamp), y: ema(closes, 20), type: "scatter", mode: "lines", name: "EMA 20", line: {color: "#56c2ff", width: 1.2},
    }, {
      x: chart.bars.map(bar => bar.timestamp), y: ema(closes, 50), type: "scatter", mode: "lines", name: "EMA 50", line: {color: "#d98cff", width: 1.2},
    }, {
      x: visibleMarkers.map(marker => marker.timestamp), y: markerY, type: "scatter", mode: "markers",
      name: "Agent decisions", text: visibleMarkers.map(marker => marker.label),
      customdata: visibleMarkers.map(marker => marker.correlation_id), marker: {size: 9, color: "#f5c451"},
    }], {
      paper_bgcolor: "#111a26", plot_bgcolor: "#111a26", font: {color: "#e8eef7"},
      margin: {t: 20, l: 55, r: 20, b: 35}, xaxis: {rangeslider: {visible: false}},
      shapes: [
        ...chart.markers.filter(m => m.timestamp).map(m => ({type: "line", x0: m.timestamp, x1: m.timestamp, y0: 0, y1: 1, yref: "paper", line: {dash: "dot", color: "#f5c451"}})),
        ...sessionLines,
        ...(support == null ? [] : [{type:"line", x0:0, x1:1, xref:"paper", y0:support, y1:support, line:{dash:"dash", color:"#4caf78", width:1}}]),
        ...(resistance == null ? [] : [{type:"line", x0:0, x1:1, xref:"paper", y0:resistance, y1:resistance, line:{dash:"dash", color:"#e36b6b", width:1}}]),
        ...(quote?.bid == null ? [] : [{type:"line", x0:0, x1:1, xref:"paper", y0:quote.bid, y1:quote.bid, line:{color:"#60d394", width:1}}]),
        ...(quote?.ask == null ? [] : [{type:"line", x0:0, x1:1, xref:"paper", y0:quote.ask, y1:quote.ask, line:{color:"#ff9f43", width:1}}]),
      ],
      annotations: chart.markers.filter(m => m.timestamp).map(m => ({x: m.timestamp, y: 1, yref: "paper", text: m.label, showarrow: false, textangle: -90, font: {size: 10, color: "#f5c451"}})),
    }, {responsive: true}).then(plot => {
      const interactivePlot = plot as {removeAllListeners?:(name:string)=>void;on?:(name:string, handler:(event:{points?:Array<{customdata?:string}>})=>void)=>void};
      interactivePlot.removeAllListeners?.("plotly_click");
      interactivePlot.on?.("plotly_click", (event: {points?: Array<{customdata?: string}>}) => {
        const correlation = event.points?.[0]?.customdata;
        if (!correlation) return;
        setCorrelationFilter(correlation);
        void api.replay(correlation).then(events => { setReplayEvents(events); setReplayIndex(0); setReplayPlaying(false); });
      });
    });
  }, [chart, quote]);

  useEffect(() => {
    if (!replayPlaying || !replayEvents.length) return;
    const timer = setInterval(() => setReplayIndex(index => {
      if (index >= replayEvents.length - 1) { setReplayPlaying(false); return index; }
      return index + 1;
    }), 1000 / replaySpeed);
    return () => clearInterval(timer);
  }, [replayPlaying, replaySpeed, replayEvents.length]);

  async function replay() {
    if (!correlationFilter) return;
    const events = await api.replay(correlationFilter); setReplayEvents(events); setReplayIndex(0);
  }

  const active = replayEvents[replayIndex];
  const error = Object.entries(sourceErrors).map(([name, message]) => `${name}: ${message}`).join(" · ") || undefined;
  const health = status ? Object.fromEntries(Object.entries({
    MT5: status.mt5, Database: status.database, Journal: status.journal,
    "Agent worker": status.shadow_worker, "Strategy worker": status.strategy_shadow_worker,
    "Simulation worker": status.simulation_worker, "Position manager": status.demo_position_manager,
    News: status.news, Calendar: status.calendar,
    Levi: status.levi, Backtester: status.backtester, Disk: status.disk,
  }).filter((entry): entry is [string, NonNullable<typeof entry[1]>] => entry[1] != null)) : {};

  return <main>
    <SystemBar status={status} quote={quote}/>
    {error && <p className="error">Dashboard data degraded: {error}</p>}
    <div className="layout"><div className="maincol">
      <Panel title="Live XAUUSD chart">{chart ? <div className="chartnode" ref={chartNode}/> : <div className="emptychart">Waiting for live MT5 candles…</div>}</Panel>
      <DecisionChain cycle={cycle} agents={agents}/>
      <Panel title="Actual MT5 positions">
        <table><thead><tr><th>Ticket</th><th>Side</th><th>Open</th><th>P&amp;L</th><th>R</th><th>Peak</th><th>Policy</th><th>State</th><th>Floor</th><th>Next retry</th><th>Attempts</th><th>Issue</th></tr></thead><tbody>{positions.map(p => <tr key={p.ticket}><td>{p.ticket}</td><td>{p.side}</td><td>{p.price_open}</td><td>{p.profit.toFixed(2)}</td><td>{p.current_r?.toFixed(2) ?? "—"}</td><td>{p.peak_profit?.toFixed(2) ?? "—"}</td><td>{p.active_exit_policy ?? "—"}</td><td><State value={p.profit_management_state ?? "MONITORING"}/></td><td>{p.trailing_floor?.toFixed(2) ?? p.locked_profit_floor?.toFixed(2) ?? "—"}</td><td>{p.next_retry_after?.slice(11, 16) ?? "—"}</td><td>{p.close_attempt_count}</td><td>{p.cooldown_reason ?? (p.execution_locked ? "LOCKED" : p.latest_mt5_error ? p.latest_mt5_error.slice(0, 42) : "—")}</td></tr>)}</tbody></table>
        {!positions.length && <p>No actual MT5 positions.</p>}
      </Panel>
      <Panel title="Paper positions">
        <table><thead><tr><th>State</th><th>Side</th><th>Entry</th><th>SL</th><th>TP</th><th>P&amp;L</th><th>Correlation</th></tr></thead><tbody>{simulated.map(p => <tr key={p.id}><td><State value={p.status}/></td><td>{p.side}</td><td>{p.entry_price}</td><td>{p.stop_loss}</td><td>{p.take_profit}</td><td>{p.pnl?.toFixed(2) ?? "—"}</td><td><code>{p.correlation_id.slice(0, 8)}</code></td></tr>)}</tbody></table>
        {!simulated.length && <p>No forward-only paper positions yet.</p>}
      </Panel>
      <Panel title="Recent fills"><table><thead><tr><th>Deal</th><th>Side</th><th>Volume</th><th>Price</th><th>P&amp;L</th></tr></thead><tbody>{fills.slice(0, 20).map(f => <tr key={f.deal_ticket}><td>{f.deal_ticket}</td><td>{f.side}</td><td>{f.volume}</td><td>{f.price}</td><td>{f.profit.toFixed(2)}</td></tr>)}</tbody></table>{!fills.length && <p>No fills in the selected period.</p>}</Panel>
      <Panel title="Closed trades"><table><thead><tr><th>Strategy</th><th>Session</th><th>P&amp;L</th><th>R:R</th></tr></thead><tbody>{closedTrades.slice(0, 20).map(t => <tr key={t.source_deal_ticket ?? `${t.strategy_version}-${t.closed_at}`}><td>{t.strategy_version}</td><td>{t.session}</td><td>{t.pnl.toFixed(2)}</td><td>{t.reward_risk.toFixed(2)}</td></tr>)}</tbody></table>{!closedTrades.length && <p>No broker closed trades imported yet.</p>}</Panel>
      <Panel title="Journal filters"><select value={agentFilter} onChange={e => setAgentFilter(e.target.value)}><option value="">All bots</option><option>ANNIE</option><option>MIKASA</option><option>EREN</option><option>COMMANDER_ERWIN</option><option>ARMIN</option><option>CPT_LEVI</option><option>SIMULATION</option></select><input value={correlationFilter} onChange={e => setCorrelationFilter(e.target.value)} placeholder="Correlation ID"/><button onClick={() => void load()}>Apply</button></Panel>
      <Journal events={journal?.items} onSelect={event => { setSelected(event); setCorrelationFilter(event.correlation_id); }}/>
      <Panel title="Decision replay"><button onClick={() => { setReplayIndex(0); setReplayPlaying(false); }}>Restart</button><button disabled={!replayEvents.length || replayIndex === 0} onClick={() => setReplayIndex(i => i - 1)}>Previous</button><button disabled={!replayEvents.length || replayIndex >= replayEvents.length - 1} onClick={() => setReplayIndex(i => i + 1)}>Next</button><button disabled={!replayEvents.length} onClick={() => setReplayPlaying(value => !value)}>{replayPlaying ? "Pause" : "Play"}</button><select value={replaySpeed} onChange={event => setReplaySpeed(Number(event.target.value))}><option value={0.5}>0.5×</option><option value={1}>1×</option><option value={2}>2×</option><option value={4}>4×</option></select><button onClick={() => void replay()}>Load replay</button>{active && <p>Event {replayIndex + 1} of {replayEvents.length}<br/><b>{active.bot}</b> — {active.event_type}<br/><small>{JSON.stringify(active.payload)}</small></p>}</Panel>
    </div><aside>
      <AccountPanel account={account}/>
      <Panel title="System health"><p>Browser stream <State value={stream}/></p>{Object.entries(health).map(([name, item]) => <p key={name}>{name} <State value={item.state}/><br/><small>{item.message}</small></p>)}</Panel>
      <Panel title="Experiments"><p>{experiments.length} tracked experiment(s)</p>{experiments.slice(0, 5).map(e => <p key={e.id}><b>{e.name}</b> <State value={e.status}/></p>)}</Panel>
    </aside></div>
    <Panel title="Bot status"><AgentCards agents={agents}/></Panel>
    <Panel title="Learning center"><p>{learning?.insufficient_data ? "Read-only evidence; promotion remains disabled." : "Persisted closed-trade evidence"}</p>{learning?.warnings.map(w => <p className="warning" key={w}>{w}</p>)}{learning?.recommendations.map(r => <p key={r}>{r}</p>)}<h3>Broker evidence</h3><StrategyTable rows={learning?.strategies ?? []}/><h3>Forward paper evidence</h3><StrategyTable rows={learning?.paper_strategies ?? []}/></Panel>
    {selected && <section className="drawer" role="dialog"><button onClick={() => setSelected(undefined)}>Close</button><h2>{selected.bot}: {selected.event_type}</h2><pre>{JSON.stringify(selected.payload, null, 2)}</pre></section>}
  </main>;
}

createRoot(document.getElementById("root")!).render(<App/>);

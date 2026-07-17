import type {ReactNode} from "react";
import type {Account, Agent, Cycle, JournalEvent, SymbolQuote, SystemStatus} from "./api";

export function Panel({title, children}:{title:string;children:ReactNode}) {
  return <section className="panel"><h2>{title}</h2>{children}</section>;
}

export function State({value}:{value:string}) {
  return <span className={`state state-${value.toLowerCase()}`}>{value.replaceAll("_", " ")}</span>;
}

export function SystemBar({status, quote}:{status:SystemStatus|undefined;quote:SymbolQuote|undefined}) {
  const kill = status?.kill_switch_active;
  return <header className="statusbar">
    <div><strong>{status?.platform_mode ?? "LOADING"}</strong><small>Execution: {status?.execution_enabled ? "ENABLED" : "DISABLED"}</small></div>
    <div><span>MT5</span><State value={status?.mt5.state ?? "UNKNOWN"}/></div>
    <div><span>AutoTrading</span><State value={status?.mt5_terminal_trade_allowed == null ? "UNKNOWN" : status.mt5_terminal_trade_allowed ? "ENABLED" : "DISABLED"}/></div>
    <div><span>Exploration</span><State value={status?.demo_exploration_enabled ? "ENABLED" : "DISABLED"}/></div>
    <div><span>XAUUSD</span><strong>{quote?.bid?.toFixed(2) ?? "Unavailable"} / {quote?.ask?.toFixed(2) ?? "Unavailable"}</strong></div>
    <div><span>Spread</span><strong>{quote?.spread?.toFixed(2) ?? "Unavailable"}</strong></div>
    <div><span>Kill switch</span><State value={kill == null ? "UNKNOWN" : kill ? "ACTIVE" : "INACTIVE"}/></div>
  </header>;
}

function outputSummary(output:Record<string,unknown>|null):string {
  if (!output) return "No event recorded in this cycle";
  const reasons = Array.isArray(output.reasons) ? output.reasons.join(" · ") : undefined;
  const parts = [
    output.status && `Status: ${output.status}`, output.permission && `Permission: ${output.permission}`,
    output.quality_score && `Quality: ${output.quality_score}/10`, output.regime && `Regime: ${output.regime}`,
    output.side && `Proposal: ${output.side}`,
    output.confidence && `Confidence: ${(Number(output.confidence) * 100).toFixed(0)}%`,
    output.trade_count !== undefined && `Trades reviewed: ${output.trade_count}`,
    output.summary && String(output.summary), reasons, output.reason && String(output.reason),
    output.message && String(output.message),
  ].filter(Boolean);
  return parts.join(" · ") || JSON.stringify(output);
}

function BotEvidence({agent}:{agent:Agent}) {
  const output = agent.latest_output ?? {};
  const scores = output.score_components as Record<string,unknown>|undefined;
  const events = Array.isArray(output.relevant_events) ? output.relevant_events as Array<Record<string,unknown>> : [];
  const reasons = Array.isArray(output.reasons) ? output.reasons : [];
  return <>
    {agent.name === "ANNIE" && <div className="evidence">
      <small>Verification: {String(output.status ?? "UNKNOWN")} · freshness {String(output.source_freshness_minutes ?? "unknown")} min</small>
      {events.map((event, index) => <p key={`${event.title}-${index}`}><a href={String(event.source_url ?? "#")} target="_blank" rel="noreferrer">{String(event.title ?? "Scheduled event")}</a><br/><small>{String(event.source ?? "Unverified source")} · {String(event.scheduled_at ?? "time unavailable")}</small></p>)}
    </div>}
    {agent.name === "MIKASA" && <div className="evidence"><small>Calibration: {String(output.calibration_status ?? "UNKNOWN")} · minimum {String(output.minimum_quality_required ?? "unknown")}</small>{scores && <dl>{Object.entries(scores).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{Number(value).toFixed(2)}</dd></div>)}</dl>}</div>}
    {agent.name === "EREN" && output.side && <dl className="evidence">{[["Entry", output.entry_price], ["Stop", output.stop_loss], ["Target", output.take_profit], ["Risk %", output.expected_risk_pct], ["Session", output.session]].map(([key, value]) => <div key={String(key)}><dt>{String(key)}</dt><dd>{String(value ?? "Unavailable")}</dd></div>)}</dl>}
    {agent.name === "COMMANDER_ERWIN" && <div className="evidence">{reasons.map((reason, index) => <p key={index}><small>{String(reason)}</small></p>)}</div>}
    {agent.name === "ARMIN" && <dl className="evidence">{[["Trades", output.trade_count], ["Profit factor", output.profit_factor], ["Max drawdown", output.maximum_drawdown], ["Best session", output.best_session]].map(([key, value]) => <div key={String(key)}><dt>{String(key)}</dt><dd>{String(value ?? "Insufficient data")}</dd></div>)}</dl>}
    {agent.name === "CPT_LEVI" && <div className="evidence"><small>Levi has research authority only. Execution authority: none.</small>{output.next_review_after_minutes != null && <p>Next review interval: {String(output.next_review_after_minutes)} minutes</p>}</div>}
  </>;
}

export function AgentCards({agents}:{agents:Agent[]|undefined}) {
  return <div className="cardgrid">{agents?.map(agent => <article className="card" key={agent.name}>
    <h3>{agent.name}</h3><p className="muted">{agent.role}</p><State value={agent.state}/>
    <p>{outputSummary(agent.latest_output)}</p><BotEvidence agent={agent}/>
    <small>{agent.correlation_id ?? "No cycle"}</small>
  </article>) ?? <p>Loading bot states…</p>}</div>;
}

export function AccountPanel({account}:{account:Account|undefined}) {
  return <Panel title="Account & risk"><dl>{[
    ["Account", account?.account_type], ["Balance", account?.balance], ["Equity", account?.equity],
    ["Free margin", account?.free_margin], ["Used margin", account?.used_margin], ["Margin level", account?.margin_level],
    ["Floating P&L", account?.floating_pnl], ["Exposure %", account?.current_exposure_pct],
    ["Daily P&L", account?.realized_daily_pnl], ["Weekly P&L", account?.realized_weekly_pnl],
    ["Open positions", account?.open_position_count], ["Orders sent", account?.orders_sent],
    ["Capital mode", account?.capital_mode], ["Risk / trade %", account?.configured_risk_per_trade_pct],
    ["Daily loss cap %", account?.maximum_daily_loss_pct], ["Weekly loss cap %", account?.maximum_weekly_loss_pct],
    ["Execution permission", account?.execution_permission],
  ].map(([key, value]) => <div key={String(key)}><dt>{key}</dt><dd>{value ?? "Unavailable"}</dd></div>)}</dl><p className="warning">Demo execution is controlled by MT5 AutoTrading, the kill switch, and the guarded worker.</p></Panel>;
}

export function DecisionChain({cycle, agents}:{cycle:Cycle|undefined|null;agents:Agent[]|undefined}) {
  return <Panel title="Current decision chain"><p><code>{cycle?.correlation_id ?? "No completed cycle"}</code></p>{agents?.filter(agent => ["ANNIE", "MIKASA", "EREN", "COMMANDER_ERWIN", "ARMIN", "CPT_LEVI"].includes(agent.name)).map(agent => <div className="chain" key={agent.name}><b>{agent.name}</b><State value={agent.state}/><small>{outputSummary(agent.latest_output)}</small></div>)}<p>{cycle?.final_message ?? "Waiting for a journaled cycle"}</p></Panel>;
}

export function Journal({events, onSelect}:{events:JournalEvent[]|undefined;onSelect:(event:JournalEvent)=>void}) {
  return <Panel title="Decision journal"><div className="tablewrap"><table><thead><tr><th>Time</th><th>Bot</th><th>Event</th><th>Correlation</th></tr></thead><tbody>{events?.map(event => <tr key={`${event.correlation_id}-${event.sequence}`} onClick={() => onSelect(event)}><td>{event.timestamp?.slice(11, 19) ?? "—"}</td><td>{event.bot}</td><td>{event.event_type}</td><td><code>{event.correlation_id.slice(0, 8)}</code></td></tr>)}</tbody></table></div></Panel>;
}

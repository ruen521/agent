function formatTimeLabel(isoText) {
  if (!isoText) return "--:--:--";
  const date = new Date(isoText);
  if (Number.isNaN(date.getTime())) return "--:--:--";
  const pad = (value) => String(value).padStart(2, "0");
  return `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

const MEMBER_LABEL = {
  stockout_sentinel: "缺货风险",
  replenishment_planner: "补货计划",
  exception_investigator: "异常检测",
  markdown_clearance_coach: "清仓建议"
};

const TOOL_LABEL = {
  inventory_query: "库存查询 API",
  inventory_replenishment: "补货测算 API",
  inventory_vendor_info: "供应商信息 API",
  inventory_markdown: "折扣测算 API"
};

const PHASE_LABEL = {
  team: "协同",
  member: "成员",
  tool: "工具",
  contract: "合同",
  progress: "进度",
  planner: "规划",
  execute: "执行",
  aggregate: "汇总"
};

function memberText(memberId) {
  const value = String(memberId || "").trim();
  if (!value) return "";
  return MEMBER_LABEL[value] || value;
}

function toolText(tool) {
  const value = String(tool || "").trim();
  if (!value) return "";
  return TOOL_LABEL[value] || value;
}

function phaseText(phase) {
  const value = String(phase || "").trim().toLowerCase();
  if (!value) return "流程";
  return PHASE_LABEL[value] || value;
}

function oneLine(text, max = 120) {
  const clean = String(text || "").replace(/\s+/g, " ").trim();
  if (!clean) return "";
  return clean.length > max ? `${clean.slice(0, max - 1)}…` : clean;
}

export default function DetectionWorkflowBoard({
  running = false,
  current = {},
  timeline = [],
  expanded = false,
  onToggleExpanded = () => {}
}) {
  const events = Array.isArray(timeline) ? [...timeline].slice(-60).reverse() : [];

  return (
    <div className="detection-flow-board">
      <div className={`detection-now ${running ? "running" : ""}`}>
        <span className="detection-now-dot" aria-hidden="true" />
        <div className="detection-now-main">
          <div className="detection-now-label">当前步骤</div>
          <div className="detection-now-text">{oneLine(current?.text || "等待执行", 140) || "等待执行"}</div>
          <div className="detection-now-meta">
            <span>{phaseText(current?.phase)}</span>
            {memberText(current?.member_id) ? <span>{memberText(current?.member_id)}</span> : null}
            {toolText(current?.tool) ? <span>{toolText(current?.tool)}</span> : null}
          </div>
        </div>
        <button className="ghost detection-detail-toggle" onClick={onToggleExpanded}>
          {expanded ? "收起详情" : "展开详情"}
        </button>
      </div>

      {expanded ? (
        <div className="detection-timeline">
          <div className="detection-timeline-title">协同事件时间线</div>
          {events.length ? (
            <div className="detection-timeline-list">
              {events.map((event) => (
                <div key={event.id} className={`detection-event ${String(event.level || "").toLowerCase()}`}>
                  <div className="detection-event-top">
                    <span>{formatTimeLabel(event.timestamp)}</span>
                    <span className="status-pill">{phaseText(event.phase)}</span>
                    {memberText(event.member_id) ? <span className="status-pill">{memberText(event.member_id)}</span> : null}
                    {toolText(event.tool) ? <span className="status-pill">{toolText(event.tool)}</span> : null}
                  </div>
                  <p>{event.text || "执行中"}</p>
                  {event.error_message ? <div className="export-error">{event.error_message}</div> : null}
                </div>
              ))}
            </div>
          ) : (
            <p className="muted">暂无协同事件。</p>
          )}
        </div>
      ) : null}
    </div>
  );
}

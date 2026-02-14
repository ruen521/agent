import { useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import ModeControl from "./ModeControl.jsx";
import ResultModal from "./ResultModal.jsx";
import TeamExecutionView, { teamMemberLabel, teamResultStatusLabel } from "./TeamExecutionView.jsx";

const AGENT_NAME_MAP = {
  stockout_sentinel: "缺货哨兵",
  replenishment_planner: "补货规划",
  exception_investigator: "异常侦测",
  markdown_clearance_coach: "清仓教练",
  inventory_copilot: "库存助手"
};

const EXECUTION_STATUS_LABEL = {
  PENDING: "执行中",
  RUNNING: "执行中",
  PAUSED: "已暂停",
  COMPLETED: "已完成",
  FAILED: "执行失败",
  CANCELED: "已取消"
};

const EXECUTION_STATUS_HINT = {
  PENDING: "智能体正在执行分析，请稍候。",
  RUNNING: "智能体正在执行分析，请稍候。",
  PAUSED: "任务已暂停，等待继续。",
  COMPLETED: "分析已完成，点击查看结果。",
  FAILED: "执行失败，点击查看详情。"
};

const TOOL_BUSINESS_META = {
  inventory_query: {
    label: "库存盘点与风险识别",
    purpose: "获取库存现状并识别关键风险"
  },
  inventory_replenishment: {
    label: "补货测算与采购建议",
    purpose: "结合销售与交期生成补货方案"
  },
  inventory_vendor_info: {
    label: "供应商履约信息校验",
    purpose: "核对供应商联络与交付能力"
  },
  inventory_markdown: {
    label: "折扣与清理收益测算",
    purpose: "评估折扣力度与清理收益"
  }
};

const QUERY_TYPE_LABEL = {
  all: "全量库存",
  low_stock: "低库存商品",
  stockout_risk: "缺货风险商品"
};

const URGENCY_LABEL = {
  CRITICAL: "紧急",
  HIGH: "高",
  MEDIUM: "中",
  LOW: "低"
};

const ANOMALY_TYPE_LABEL = {
  velocity_reorder_mismatch: "补货点与销量不匹配",
  price_outlier: "价格偏离同类区间",
  price_zscore_outlier: "价格波动异常",
  velocity_zscore_outlier: "销量波动异常",
  negative_margin: "毛利异常",
  zero_stock_positive_velocity: "库存与销量数据冲突",
  stale_inventory: "滞销库存积压"
};

const INVENTORY_STATUS_LABEL = {
  STOCKOUT_RISK: "缺货风险",
  HEALTHY: "健康",
  MONITOR: "观察",
  PROMOTIONAL: "促销建议",
  LIGHT_CLEARANCE: "轻度清理",
  STANDARD_CLEARANCE: "标准清理",
  AGGRESSIVE_CLEARANCE: "加速清理"
};

const COPILOT_STATUS_LABEL = {
  completed: "已完成",
  max_steps_reached: "达到最大执行步数",
  team_v1_completed: "协同完成",
  team_v1_partial: "部分完成",
  team_v1_failed: "执行失败"
};

const COLLAB_MODE_LABEL = {
  planner: "规划模式",
  team: "协同模式"
};

const TEAM_MEMBER_FLOW_LABEL = {
  stockout_sentinel: "缺货(STK)",
  replenishment_planner: "补货(REP)",
  exception_investigator: "异常(EXC)",
  markdown_clearance_coach: "清仓(MKD)"
};

const FLOW_STATUS_LABEL = {
  PENDING: "待命",
  RUNNING: "进行中",
  DONE: "完成",
  FAILED: "失败"
};

const FLOW_TOOL_LABEL = {
  inventory_query: "库存查询 API",
  inventory_replenishment: "补货测算 API",
  inventory_vendor_info: "供应商信息 API",
  inventory_markdown: "折扣测算 API",
  llm: "LLM"
};

const FLOW_PHASE_LABEL = {
  team: "协同执行",
  member: "成员执行",
  tool: "工具调用",
  llm: "模型生成",
  contract: "合同校验",
  plan: "任务规划",
  execute: "任务执行",
  progress: "进度更新"
};

function normalizeText(value) {
  return String(value || "").trim();
}

function toBusinessToolName(toolName) {
  return TOOL_BUSINESS_META[normalizeText(toolName)]?.label || "数据处理环节";
}

function summarizeHttpStatus(code) {
  const num = Number(code);
  if (Number.isNaN(num)) return "已完成";
  if (num >= 200 && num < 300) return "执行成功";
  if (num >= 400 && num < 500) return "输入需复核";
  if (num >= 500) return "服务异常";
  return "处理中";
}

function summarizeTraceFocus(toolName, args) {
  if (!args || typeof args !== "object") return "";
  if (toolName === "inventory_query") {
    const queryType = QUERY_TYPE_LABEL[normalizeText(args.query_type)] || "";
    if (queryType) return `聚焦：${queryType}`;
  }
  if (toolName === "inventory_replenishment" && args.target_days) {
    return `目标库存覆盖：${args.target_days} 天`;
  }
  if (toolName === "inventory_vendor_info" && args.vendor_id) {
    return `核对供应商：${args.vendor_id}`;
  }
  if (toolName === "inventory_markdown" && args.sku) {
    return `聚焦商品：${args.sku}`;
  }
  return "";
}

function toBusinessTraceRow(trace, index) {
  const toolName = normalizeText(trace?.tool);
  const meta = TOOL_BUSINESS_META[toolName] || {
    label: "数据处理环节",
    purpose: "执行库存运营相关计算"
  };
  const status = summarizeHttpStatus(trace?.httpStatusCode);
  const focus = summarizeTraceFocus(toolName, trace?.args);
  const outcome = focus ? `${status}，${focus}` : status;
  return {
    id: `${toolName || "trace"}-${index}`,
    step: meta.label,
    purpose: meta.purpose,
    outcome
  };
}

function toBusinessStepText(item) {
  if (typeof item === "string") return item;
  if (!item || typeof item !== "object") return "执行环节";
  const task = normalizeText(item.task);
  if (task) return task;
  return toBusinessToolName(item.tool);
}

function formatBusinessField(key, value) {
  const labelMap = {
    summary: "结论摘要",
    objective: "任务目标",
    status: "执行状态",
    plan: "规划步骤",
    past_steps: "已执行步骤",
    remaining_plan: "待执行步骤",
    risks: "风险条目",
    anomalies: "异常条目",
    markdowns: "折扣条目",
    vendors: "供应商信息"
  };
  const label = labelMap[key] || key;
  if (Array.isArray(value)) return { label, value: `${value.length} 条` };
  if (value && typeof value === "object") return { label, value: "已生成" };
  if (typeof value === "string") return { label, value: value || "-" };
  return { label, value: String(value ?? "-") };
}

function getAssistantExecutionStatus(message) {
  const raw = normalizeText(message?.meta?.execution_status).toUpperCase();
  if (raw && EXECUTION_STATUS_LABEL[raw]) return raw;
  if (normalizeText(message?.meta?.response_text)) return "COMPLETED";
  if (message?.meta?.structured_output && Object.keys(message.meta.structured_output).length > 0) return "COMPLETED";
  if (Array.isArray(message?.meta?.tool_trace) && message.meta.tool_trace.length > 0) return "COMPLETED";
  if (String(message?.content || "").includes("失败")) return "FAILED";
  return "COMPLETED";
}

function getAssistantResponseText(message) {
  const fromMeta = normalizeText(message?.meta?.response_text);
  if (fromMeta) return fromMeta;
  return normalizeText(message?.content);
}

function formatProgressTime(isoText) {
  if (!isoText) return "";
  const date = new Date(isoText);
  if (Number.isNaN(date.getTime())) return "";
  const hh = String(date.getHours()).padStart(2, "0");
  const mm = String(date.getMinutes()).padStart(2, "0");
  const ss = String(date.getSeconds()).padStart(2, "0");
  return `${hh}:${mm}:${ss}`;
}

function memberFlowLabel(memberId) {
  return TEAM_MEMBER_FLOW_LABEL[memberId] || teamMemberLabel(memberId);
}

function normalizeFlowStatus(raw) {
  const status = String(raw || "").toUpperCase();
  if (status === "SUCCESS") return "DONE";
  if (status === "TIMEOUT") return "FAILED";
  if (status === "FAILED") return "FAILED";
  if (status === "DONE") return "DONE";
  if (status === "RUNNING") return "RUNNING";
  return "PENDING";
}

function flowToolLabel(toolId) {
  return FLOW_TOOL_LABEL[toolId] || toolId || "-";
}

function flowPhaseLabel(phaseId) {
  const key = normalizeText(phaseId).toLowerCase();
  if (!key) return "执行中";
  return FLOW_PHASE_LABEL[key] || (key.includes("_") ? "执行中" : key);
}

function StreamWorkflowView({ workflow }) {
  const mode = String(workflow?.mode || "single");
  const phase = normalizeText(workflow?.phase);
  const currentMember = normalizeText(workflow?.current_member);
  const currentTool = normalizeText(workflow?.current_tool);
  const members = Array.isArray(workflow?.members) ? workflow.members.filter(Boolean) : [];
  const statusMap = workflow?.member_status && typeof workflow.member_status === "object"
    ? workflow.member_status
    : {};

  if (mode !== "team" || members.length === 0) {
    const phaseText = phase ? `当前阶段：${flowPhaseLabel(phase)}` : "当前阶段：执行中";
    const toolText = currentTool ? `当前工具：${flowToolLabel(currentTool)}` : "";
    return (
      <div className="workflow-mini">
        <span className="workflow-meta">{phaseText}{toolText ? ` · ${toolText}` : ""}</span>
      </div>
    );
  }

  return (
    <div className="workflow-mini">
      <div className="workflow-lanes">
        {members.map((memberId) => {
          const normalizedStatus = normalizeFlowStatus(statusMap?.[memberId]);
          const active = currentMember === memberId && normalizedStatus === "RUNNING";
          return (
            <div key={memberId} className={`workflow-lane ${normalizedStatus.toLowerCase()} ${active ? "active" : ""}`}>
              <span className="workflow-lane-name">{memberFlowLabel(memberId)}</span>
              <span className="workflow-lane-status">{FLOW_STATUS_LABEL[normalizedStatus] || FLOW_STATUS_LABEL.PENDING}</span>
            </div>
          );
        })}
      </div>
      <span className="workflow-meta">
        {phase ? `阶段：${flowPhaseLabel(phase)}` : "阶段：协同执行"}
        {currentTool ? ` · 工具：${flowToolLabel(currentTool)}` : ""}
      </span>
    </div>
  );
}

function StepTimeline({ structured }) {
  const isTeamMode = Array.isArray(structured?.team_plan) || Array.isArray(structured?.team_execution);
  const plan = isTeamMode
    ? (Array.isArray(structured?.team_plan) ? structured.team_plan : [])
    : (Array.isArray(structured?.plan) ? structured.plan : []);
  const pastSteps = isTeamMode
    ? (Array.isArray(structured?.team_execution) ? structured.team_execution : [])
    : (Array.isArray(structured?.past_steps) ? structured.past_steps : []);
  const remaining = isTeamMode
    ? plan.filter((memberId) => !pastSteps.some((item) => item?.member_id === memberId))
    : (Array.isArray(structured?.remaining_plan) ? structured.remaining_plan : []);

  if (!plan.length && !pastSteps.length && !remaining.length) {
    return <div className="muted">本次分析无步骤信息。</div>;
  }

  return (
    <div className="timeline-grid">
      <div>
        <h5>计划</h5>
        <ol>
          {plan.map((item, index) => (
            <li key={`plan-${index}`}>
              {isTeamMode ? teamMemberLabel(item) : toBusinessStepText(item)}
            </li>
          ))}
        </ol>
      </div>
      <div>
        <h5>已执行</h5>
        <ol>
          {pastSteps.map((item, index) => (
            <li key={`done-${index}`}>
              {isTeamMode
                ? `${teamMemberLabel(item?.member_id)}：${teamResultStatusLabel(item?.result_status)}`
                : toBusinessStepText(item)}
            </li>
          ))}
        </ol>
      </div>
      <div>
        <h5>待执行</h5>
        <ol>
          {remaining.map((item, index) => (
            <li key={`remain-${index}`}>
              {isTeamMode ? teamMemberLabel(item) : toBusinessStepText(item)}
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}

function ToolTraceTable({ traces }) {
  if (!Array.isArray(traces) || traces.length === 0) {
    return <div className="muted">本次分析未调用工具。</div>;
  }
  const rows = traces.map(toBusinessTraceRow);
  return (
    <div className="meta-table-wrap">
      <table className="meta-table">
        <thead>
          <tr>
            <th>执行环节</th>
            <th>业务目的</th>
            <th>执行结论</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id}>
              <td>{row.step}</td>
              <td>{row.purpose}</td>
              <td>{row.outcome}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function StockoutView({ structured }) {
  const risks = Array.isArray(structured?.risks) ? structured.risks : [];
  const vendors = Array.isArray(structured?.vendors) ? structured.vendors : [];
  return (
    <div className="analysis-grid">
      <div>
        <h5>风险清单</h5>
        {risks.length ? (
          <table className="meta-table">
            <thead>
              <tr>
                <th>SKU</th>
                <th>断货天数</th>
                <th>紧急度</th>
                <th>建议动作</th>
              </tr>
            </thead>
            <tbody>
              {risks.map((risk) => (
                <tr key={risk.sku}>
                  <td>{risk.sku}</td>
                  <td>{risk.days}</td>
                  <td>{URGENCY_LABEL[risk.urgency] || risk.urgency || "-"}</td>
                  <td>{Array.isArray(risk.actions) ? risk.actions.join(" / ") : "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <div className="muted">无风险项。</div>}
      </div>
      <div>
        <h5>供应商联系方式</h5>
        {vendors.length ? (
          <ul className="plain-list">
            {vendors.map((vendor) => (
              <li key={vendor.VendorID}>
                <strong>{vendor.Name || vendor.VendorID}</strong>
                <div>{vendor.PhoneNumber || "-"} / {vendor.Email || "-"}</div>
              </li>
            ))}
          </ul>
        ) : <div className="muted">无供应商信息。</div>}
      </div>
    </div>
  );
}

function ReplenishmentView({ structured }) {
  const plan = structured?.plan || {};
  const groups = Array.isArray(plan.vendor_groups) ? plan.vendor_groups : [];
  if (!groups.length) return <div className="muted">无补货计划。</div>;
  return (
    <div className="card-grid">
      {groups.map((group) => (
        <div className="mini-card" key={group.vendor_id}>
          <h5>{group.vendor_name || group.vendor_id}</h5>
          <p>总成本：${group.total_cost}</p>
          <p>起订金额：${group.minimum_order}</p>
          <p>交期：{group.lead_time_days} 天</p>
          <p>{group.meets_minimum_order ? "满足起订" : group.warning || "未满足起订"}</p>
          <div className="muted">SKU 数：{Array.isArray(group.items) ? group.items.length : 0}</div>
        </div>
      ))}
    </div>
  );
}

function ExceptionView({ structured }) {
  const anomalies = Array.isArray(structured?.anomalies) ? structured.anomalies : [];
  if (!anomalies.length) return <div className="muted">未检测到异常。</div>;
  const group = anomalies.reduce((acc, item) => {
    const key = item.type || "unknown";
    acc[key] = (acc[key] || 0) + 1;
    return acc;
  }, {});
  return (
    <div className="analysis-grid">
      <div>
        <h5>异常分布</h5>
          <ul className="plain-list">
            {Object.entries(group).map(([type, count]) => (
              <li key={type}>{ANOMALY_TYPE_LABEL[type] || type}：{count}</li>
            ))}
          </ul>
        </div>
      <div>
        <h5>修复建议</h5>
        <ul className="plain-list">
          {anomalies.slice(0, 12).map((item, index) => (
            <li key={`${item.sku}-${index}`}>
              <strong>{item.sku}</strong>：{item.recommendation}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function MarkdownView({ structured }) {
  const markdowns = Array.isArray(structured?.markdowns) ? structured.markdowns : [];
  const statusCounts = structured?.status_counts || {};
  return (
    <div className="analysis-grid">
      <div>
        <h5>折扣建议</h5>
        {markdowns.length ? (
          <table className="meta-table">
            <thead>
              <tr>
                <th>SKU</th>
                <th>折扣</th>
                <th>清理周期</th>
                <th>净收益</th>
              </tr>
            </thead>
            <tbody>
              {markdowns.map((item) => (
                <tr key={item.SKU}>
                  <td>{item.SKU}</td>
                  <td>{Math.round((item.recommended_markdown || 0) * 100)}%</td>
                  <td>{item.days_to_clear}</td>
                  <td>{item.net_benefit}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <div className="muted">暂无需要折扣的 SKU。</div>}
      </div>
      <div>
        <h5>状态统计</h5>
        <ul className="plain-list">
          {Object.keys(statusCounts).length ? (
            Object.entries(statusCounts).map(([status, count]) => (
              <li key={status}>{INVENTORY_STATUS_LABEL[status] || status}：{count}</li>
            ))
          ) : <li className="muted">无状态统计</li>}
        </ul>
      </div>
    </div>
  );
}

function CopilotView({ structured }) {
  return (
    <div className="analysis-grid">
      <div>
        <h5>任务目标</h5>
        <p>{structured?.objective || "未提供"}</p>
        <h5>执行状态</h5>
        <p>{COPILOT_STATUS_LABEL[structured?.status] || structured?.status || "进行中"}</p>
      </div>
      <div>
        <h5>执行轨迹</h5>
        <StepTimeline structured={structured} />
      </div>
    </div>
  );
}

function AgentStructuredRenderer({ message }) {
  const structured = message?.meta?.structured_output || {};
  const agentId = message?.agent_id;
  if (!structured || Object.keys(structured).length === 0) {
    return <div className="muted">暂无结构化结果。</div>;
  }
  if (agentId === "stockout_sentinel") return <StockoutView structured={structured} />;
  if (agentId === "replenishment_planner") return <ReplenishmentView structured={structured} />;
  if (agentId === "exception_investigator") return <ExceptionView structured={structured} />;
  if (agentId === "markdown_clearance_coach") return <MarkdownView structured={structured} />;
  if (agentId === "inventory_copilot") {
    if (Array.isArray(structured?.team_execution) || Array.isArray(structured?.team_plan)) {
      return <TeamExecutionView structured={structured} />;
    }
    return <CopilotView structured={structured} />;
  }
  return (
    <div className="summary-grid">
      {Object.entries(structured).map(([key, value]) => {
        const field = formatBusinessField(key, value);
        return (
          <div className="summary-item" key={key}>
            <strong>{field.label}</strong>
            <span>{field.value}</span>
          </div>
        );
      })}
    </div>
  );
}

export default function ChatPanel({
  agents,
  activeAgent,
  onAgentChange,
  messages,
  onSend,
  onQuickAction,
  onExportAnalysis,
  onDownloadExport,
  exportStates,
  isAnalysisExportable,
  loading
}) {
  const [input, setInput] = useState("");
  const [selectedId, setSelectedId] = useState("");
  const [activeTab, setActiveTab] = useState("answer");
  const [audience, setAudience] = useState("external");
  const [resultOpen, setResultOpen] = useState(false);
  const [expandedThinking, setExpandedThinking] = useState({});

  const assistantMessages = useMemo(
    () => messages.filter((item) => item.role === "assistant"),
    [messages]
  );

  useEffect(() => {
    if (!assistantMessages.length) {
      setSelectedId("");
      setResultOpen(false);
      return;
    }
    const latest = assistantMessages[assistantMessages.length - 1];
    setSelectedId(latest.id);
  }, [assistantMessages]);

  const selectedMessage = useMemo(
    () => assistantMessages.find((item) => item.id === selectedId) || assistantMessages[assistantMessages.length - 1],
    [assistantMessages, selectedId]
  );

  const openResultModal = (messageId) => {
    setSelectedId(messageId);
    setActiveTab("answer");
    setResultOpen(true);
  };

  const handleSend = () => {
    if (!input.trim()) return;
    onSend(input.trim());
    setInput("");
  };

  const exportState = selectedMessage ? exportStates[selectedMessage.id] : null;
  const selectedStatus = selectedMessage ? getAssistantExecutionStatus(selectedMessage) : "";
  const canExportCurrent = Boolean(
    selectedMessage &&
    selectedStatus === "COMPLETED" &&
    isAnalysisExportable(selectedMessage)
  );

  return (
    <div className="panel chat-panel">
      <div className="panel-header">
        <div>
          <h3>Agent中心</h3>
          <span className="panel-sub">围绕当前分析结果查看状态、过程与执行建议</span>
        </div>
      </div>

      <ModeControl
        agents={agents}
        activeAgent={activeAgent}
        onAgentChange={onAgentChange}
        onQuickAction={onQuickAction}
      />

      <div className="chat-feed">
        {messages.length === 0 ? (
          <div className="chat-empty">输入问题，触发智能体分析。</div>
        ) : (
          messages.map((message) => (
            message.role === "user" ? (
              <div key={message.id} className="chat-bubble user">
                <strong>你</strong>
                <span>{message.content}</span>
              </div>
            ) : (
              <div
                key={message.id}
                className={`chat-bubble assistant ${selectedId === message.id ? "selected" : ""}`}
              >
                {(() => {
                  const status = getAssistantExecutionStatus(message);
                  const progressLog = Array.isArray(message?.meta?.progress_log) ? message.meta.progress_log : [];
                  const latestProgress = normalizeText(
                    message?.meta?.stream_status || progressLog[progressLog.length - 1]?.text
                  ) || EXECUTION_STATUS_HINT[status] || "状态更新中。";
                  const hasThinking = progressLog.length > 0 || status === "RUNNING";
                  const expanded = Boolean(expandedThinking[message.id]);
                  return (
                    <>
                <div className="bubble-header">
                  <strong>{AGENT_NAME_MAP[message.agent_id] || "智能体"}</strong>
                  <div className="bubble-badges">
                    {message?.meta?.collab_mode ? (
                      <span className="status-pill mode">
                        {COLLAB_MODE_LABEL[String(message.meta.collab_mode).toLowerCase()] || "协同模式"}
                      </span>
                    ) : null}
                    <span className={`status-pill exec ${String(getAssistantExecutionStatus(message)).toLowerCase()}`}>
                      {EXECUTION_STATUS_LABEL[getAssistantExecutionStatus(message)] || "状态未知"}
                    </span>
                  </div>
                </div>
                {hasThinking ? (
                  <div className="thinking-panel">
                    <div className="thinking-strip">
                      {status === "RUNNING" ? <span className="thinking-pulse" aria-hidden /> : <span className="thinking-dot-static" aria-hidden />}
                      <span className="thinking-text">{latestProgress}</span>
                      {progressLog.length > 0 ? (
                        <button
                          className="thinking-toggle"
                          onClick={() =>
                            setExpandedThinking((prev) => ({ ...prev, [message.id]: !Boolean(prev[message.id]) }))
                          }
                        >
                          {expanded ? "收起步骤" : "展开步骤"}
                        </button>
                      ) : null}
                    </div>
                    <StreamWorkflowView workflow={message?.meta?.stream_workflow || {}} />
                    {expanded && progressLog.length ? (
                      <ol className="bubble-progress-list">
                        {progressLog.map((entry, index) => (
                          <li key={entry?.id || `${message.id}-progress-${index}`}>
                            <span className="bubble-progress-time">{formatProgressTime(entry?.timestamp)}</span>
                            <span className="bubble-progress-text">{normalizeText(entry?.text) || "执行中"}</span>
                          </li>
                        ))}
                      </ol>
                    ) : null}
                  </div>
                ) : null}

                {getAssistantResponseText(message) ? (
                  <div className="bubble-answer">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {getAssistantResponseText(message)}
                    </ReactMarkdown>
                  </div>
                ) : (
                  <span>{EXECUTION_STATUS_HINT[getAssistantExecutionStatus(message)] || "状态更新中。"}</span>
                )}
                <div className="bubble-actions">
                  {getAssistantExecutionStatus(message) === "COMPLETED" ? (
                    <button className="ghost" onClick={() => openResultModal(message.id)}>
                      查看详细结果
                    </button>
                  ) : null}
                  {getAssistantExecutionStatus(message) === "FAILED" ? (
                    <button className="ghost" onClick={() => openResultModal(message.id)}>
                      查看详细结果
                    </button>
                  ) : null}
                </div>
                    </>
                  );
                })()}
              </div>
            )
          ))
        )}
        {loading && <div className="chat-loading">任务执行中...</div>}
      </div>

      <div className="chat-input">
        <input
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder="输入问题..."
        />
        <button onClick={handleSend}>发送</button>
      </div>

      <ResultModal
        open={resultOpen}
        selectedMessage={selectedMessage}
        agentName={AGENT_NAME_MAP[selectedMessage?.agent_id] || "智能体"}
        activeTab={activeTab}
        onTabChange={setActiveTab}
        onClose={() => setResultOpen(false)}
        audience={audience}
        onAudienceChange={setAudience}
        canExportCurrent={canExportCurrent}
        onExportAnalysis={onExportAnalysis}
        onDownloadExport={onDownloadExport}
        exportState={exportState}
        renderSteps={<StepTimeline structured={selectedMessage?.meta?.structured_output || {}} />}
        renderTrace={<ToolTraceTable traces={selectedMessage?.meta?.tool_trace || []} />}
        renderStructured={<AgentStructuredRenderer message={selectedMessage} />}
      />
    </div>
  );
}

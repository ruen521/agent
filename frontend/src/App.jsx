import { useEffect, useMemo, useRef, useState } from "react";
import {
  createExportJob,
  downloadExport,
  fetchAgents,
  fetchInventory,
  fetchStats,
  getExportJob,
  invokeAgentStream
} from "./api/client.js";
import ChatPanel from "./components/ChatPanel.jsx";
import DetectionWorkflowBoard from "./components/DetectionWorkflowBoard.jsx";
import InventoryTable from "./components/InventoryTable.jsx";
import StatCard from "./components/StatCard.jsx";

const DEFAULT_STATS = {
  total_skus: 0,
  stockout_risks: 0,
  critical_risks: 0,
  low_stock_items: 0,
  total_categories: 0,
  categories: []
};

const ACCENTS = ["#FF6B6B", "#FFA94D", "#4ECDC4", "#45B7D1", "#96CEB4"];

const AGENT_EXPORT_TITLE_MAP = {
  stockout_sentinel: "缺货建议",
  replenishment_planner: "补货建议",
  exception_investigator: "异常修复建议",
  markdown_clearance_coach: "清仓折扣建议",
  inventory_copilot: "运营编排建议"
};

const TEAM_MEMBER_LABEL = {
  stockout_sentinel: "缺货风险",
  replenishment_planner: "补货计划",
  exception_investigator: "异常检测",
  markdown_clearance_coach: "清仓建议"
};

const DETECTION_PROMPT_PRESET = "team_detection_cycle";

const DETECTION_ORCHESTRATION = {
  member_timeout_ms: 90000,
  member_max_retries: 0,
};

const DETECTION_INTERVAL_OPTIONS = [
  { value: 5 * 60 * 1000, label: "每5分钟" },
  { value: 15 * 60 * 1000, label: "每15分钟" },
  { value: 30 * 60 * 1000, label: "每30分钟" }
];

const DETECTION_CYCLE_LABEL = {
  IDLE: "待命",
  RUNNING: "执行中",
  COMPLETED: "已完成",
  PARTIAL: "部分完成",
  STOPPED: "已停止"
};

const DETECTION_STEP_STATUS_LABEL = {
  IDLE: "待命",
  PENDING: "等待",
  RUNNING: "执行中",
  PARTIAL: "部分完成",
  DONE: "已完成",
  FAILED: "失败"
};

const TEAM_RESULT_TO_DETECTION_STATUS = {
  success: "DONE",
  partial_success: "PARTIAL",
  timeout: "FAILED",
  failed: "FAILED"
};

const RUNTIME_MEMBER_STATUS_TO_DETECTION = {
  running: "RUNNING",
  success: "DONE",
  failed: "FAILED",
  timeout: "FAILED"
};

const AGENT_NODE_LABEL = {
  load_session: "加载会话上下文",
  stockout_sentinel: "缺货哨兵分析",
  replenishment_planner: "补货规划分析",
  exception_investigator: "异常侦测分析",
  markdown_clearance_coach: "清仓教练分析",
  copilot_planner: "编排规划",
  copilot_execute: "编排执行",
  copilot_replanner: "编排重规划",
  copilot_team_v1_plan: "协同成员规划",
  copilot_team_v1_execute: "协同成员执行",
  copilot_team_v1_aggregate: "协同结果汇总",
  forced_tool_node: "调试工具执行",
  finalize: "结果落盘"
};

const TOOL_PROGRESS_LABEL = {
  inventory_query: "库存查询",
  inventory_replenishment: "补货测算",
  inventory_vendor_info: "供应商核验",
  inventory_markdown: "折扣测算"
};

const EXPORT_STATUS_TEXT = {
  PENDING: "生成中",
  RUNNING: "生成中",
  DONE: "已完成",
  FAILED: "导出失败",
  EXPIRED: "已过期"
};

function formatTitleDate(date = new Date()) {
  return `${date.getFullYear()}.${date.getMonth() + 1}.${date.getDate()}`;
}

function isAnalysisExportable(message) {
  if (!message || message.role !== "assistant" || !message.meta) return false;
  const structured = message.meta.structured_output;
  const traces = message.meta.tool_trace;
  const output = message.meta.tool_output;
  const hasStructured = structured && typeof structured === "object" && Object.keys(structured).length > 0;
  const hasTrace = Array.isArray(traces) && traces.length > 0;
  const hasToolOutput = output && typeof output === "object" && Object.keys(output).length > 0;
  return hasStructured || hasTrace || hasToolOutput;
}

function formatDateTimeLabel(isoText) {
  if (!isoText) return "-";
  const date = new Date(isoText);
  if (Number.isNaN(date.getTime())) return "-";
  const pad = (num) => String(num).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function toOneLineSummary(text, max = 92) {
  const clean = String(text || "").replace(/\s+/g, " ").trim();
  if (!clean) return "未返回有效结论";
  return clean.length > max ? `${clean.slice(0, max - 1)}…` : clean;
}

function nodeDisplayLabel(nodeName) {
  return AGENT_NODE_LABEL[String(nodeName || "").trim()] || "处理中";
}

function toolDisplayLabel(toolName) {
  return TOOL_PROGRESS_LABEL[String(toolName || "").trim()] || "业务工具";
}

function buildProgressText(event) {
  const node = String(event?.node || "");
  const nodeLabel = nodeDisplayLabel(node);
  if (node === "runtime_progress") {
    const text = String(event?.status_text || "").trim();
    if (text) return text;
    const phase = String(event?.phase || "").trim();
    if (phase === "tool") return "正在调用业务工具";
    if (phase === "llm") return "正在调用 LLM 生成分析";
    if (phase === "contract") return "正在校验协同合同";
    return "正在更新执行进度";
  }
  if (node === "copilot_team_v1_plan") {
    const teamPlan = Array.isArray(event?.team_plan) ? event.team_plan : [];
    if (teamPlan.length) {
      const memberLabels = teamPlan.map((member) => TEAM_MEMBER_LABEL[member] || member || "成员");
      return `已完成协同规划，执行顺序：${memberLabels.join(" -> ")}`;
    }
    return "正在生成协同执行计划";
  }
  if (node === "copilot_team_v1_execute" && event?.latest_step) {
    const latestStep = event.latest_step || {};
    const memberId = String(latestStep.member_id || "");
    const memberLabel = TEAM_MEMBER_LABEL[memberId] || memberId || "成员";
    const stepStatus = TEAM_RESULT_TO_DETECTION_STATUS[latestStep.result_status] || "RUNNING";
    const statusLabel = DETECTION_STEP_STATUS_LABEL[stepStatus] || "执行中";
    const traces = Array.isArray(latestStep.tool_trace) ? latestStep.tool_trace : [];
    const latestTool = String(traces[traces.length - 1]?.tool || "");
    if (latestTool) {
      return `${memberLabel}正在调用${toolDisplayLabel(latestTool)}，当前状态：${statusLabel}`;
    }
    return `${memberLabel}当前状态：${statusLabel}`;
  }
  if (node === "copilot_execute") {
    const latestTool = String(event?.latest_tool || "");
    if (latestTool) {
      return `正在调用${toolDisplayLabel(latestTool)}，并更新执行结果`;
    }
    return "正在调用业务工具并处理数据";
  }
  if (event?.latest_tool) {
    return `正在调用${toolDisplayLabel(event.latest_tool)}，执行${nodeLabel}`;
  }
  return `正在执行：${nodeLabel}`;
}

function mergeStreamWorkflowState(currentWorkflow, event) {
  const base = currentWorkflow && typeof currentWorkflow === "object"
    ? {
      mode: currentWorkflow.mode || "single",
      members: Array.isArray(currentWorkflow.members) ? [...currentWorkflow.members] : [],
      member_status: currentWorkflow.member_status && typeof currentWorkflow.member_status === "object"
        ? { ...currentWorkflow.member_status }
        : {},
      current_member: String(currentWorkflow.current_member || ""),
      current_tool: String(currentWorkflow.current_tool || ""),
      phase: String(currentWorkflow.phase || "")
    }
    : {
      mode: "single",
      members: [],
      member_status: {},
      current_member: "",
      current_tool: "",
      phase: ""
    };

  const node = String(event?.node || "");
  if (node === "copilot_team_v1_plan") {
    const teamPlan = Array.isArray(event?.team_plan) ? event.team_plan.map((m) => String(m || "")) : [];
    if (teamPlan.length) {
      base.mode = "team";
      base.members = teamPlan;
      base.member_status = {};
      teamPlan.forEach((memberId) => {
        if (memberId) base.member_status[memberId] = "PENDING";
      });
      base.current_member = teamPlan[0] || "";
      base.current_tool = "";
      base.phase = "plan";
    }
    return base;
  }

  if (node === "copilot_team_v1_execute") {
    const latestStep = event?.latest_step && typeof event.latest_step === "object" ? event.latest_step : null;
    if (latestStep) {
      const memberId = String(latestStep.member_id || "");
      if (memberId) {
        if (!base.members.includes(memberId)) {
          base.members.push(memberId);
        }
        const result = String(latestStep.result_status || "").toLowerCase();
        if (result === "success") base.member_status[memberId] = "DONE";
        else if (result === "failed" || result === "timeout") base.member_status[memberId] = "FAILED";
        else base.member_status[memberId] = "RUNNING";
        base.current_member = memberId;
        base.phase = "execute";
      }
      const traces = Array.isArray(latestStep.tool_trace) ? latestStep.tool_trace : [];
      const tool = String(traces[traces.length - 1]?.tool || "");
      if (tool) base.current_tool = tool;
    }
    return base;
  }

  if (node === "runtime_progress") {
    const memberId = String(event?.member_id || "");
    const memberStatus = String(event?.member_status || "").toLowerCase();
    const tool = String(event?.tool || "");
    const teamState = event?.team_state && typeof event.team_state === "object" ? event.team_state : {};
    const members = Array.isArray(teamState?.members) ? teamState.members.map((m) => String(m || "")) : [];
    if (members.length) {
      base.mode = "team";
      members.forEach((member) => {
        if (member && !base.members.includes(member)) base.members.push(member);
        if (member && !base.member_status[member]) base.member_status[member] = "PENDING";
      });
    }
    if (memberId) {
      if (!base.members.includes(memberId)) base.members.push(memberId);
      if (memberStatus === "success") base.member_status[memberId] = "DONE";
      else if (memberStatus === "failed") base.member_status[memberId] = "FAILED";
      else if (memberStatus === "running") base.member_status[memberId] = "RUNNING";
      base.current_member = memberId;
    }
    if (tool) base.current_tool = tool;
    base.phase = String(event?.phase || base.phase || "progress");
    return base;
  }

  if (node) {
    base.mode = "single";
    base.phase = nodeDisplayLabel(node);
  }
  return base;
}

const HEARTBEAT_TEXTS = [
  "正在理解你的问题",
  "正在读取上下文与历史会话",
  "正在调用业务工具并校验结果",
  "正在汇总分析结论"
];

function isAbortError(error) {
  const name = String(error?.name || "");
  const message = String(error?.message || "").toLowerCase();
  return (
    name === "AbortError" ||
    message.includes("aborted") ||
    message.includes("aborterror") ||
    message.includes("用户已停止执行")
  );
}

function extractResponseText(payload) {
  const primary = payload?.response?.text;
  const secondary = payload?.response_text;
  const tertiary = payload?.response?.response_text;
  const candidate = primary ?? secondary ?? tertiary;
  if (typeof candidate === "string") return candidate.trim();
  if (Array.isArray(candidate)) {
    return candidate
      .map((item) => (typeof item === "string" ? item.trim() : ""))
      .filter(Boolean)
      .join("\n")
      .trim();
  }
  if (candidate && typeof candidate === "object") {
    const text = candidate.text;
    if (typeof text === "string") return text.trim();
  }
  return "";
}

export default function App() {
  const [stats, setStats] = useState(DEFAULT_STATS);
  const [agents, setAgents] = useState([]);
  const [activeAgent, setActiveAgent] = useState("stockout_sentinel");
  const [inventoryItems, setInventoryItems] = useState([]);
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(false);
  const [sessionId] = useState(crypto.randomUUID());
  const [exportStates, setExportStates] = useState({});
  const [detectionMemberExportStates, setDetectionMemberExportStates] = useState({});
  const [detectionMemberBatchRunning, setDetectionMemberBatchRunning] = useState(false);
  const pollerRef = useRef({});
  const detectionTimerRef = useRef(null);
  const detectionRunningRef = useRef(false);
  const detectionAbortRef = useRef(null);
  const [detectionEnabled, setDetectionEnabled] = useState(false);
  const [detectionIntervalMs, setDetectionIntervalMs] = useState(DETECTION_INTERVAL_OPTIONS[1].value);
  const [detectionStatus, setDetectionStatus] = useState({
    running: false,
    last_run_at: "",
    next_run_at: "",
    cycle_status: "IDLE",
    error_message: ""
  });
  const [detectionSteps, setDetectionSteps] = useState(
    [
      {
        key: "team_orchestration",
        label: "协同编排",
        status: "IDLE",
        started_at: "",
        finished_at: "",
        summary: ""
      }
    ]
  );
  const [detectionFinalMessageId, setDetectionFinalMessageId] = useState("");
  const [detectionReportAudience, setDetectionReportAudience] = useState("external");
  const [detectionTimeline, setDetectionTimeline] = useState([]);
  const [detectionTimelineExpanded, setDetectionTimelineExpanded] = useState(false);
  const [detectionCurrent, setDetectionCurrent] = useState({
    text: "等待执行",
    phase: "team",
    member_id: "",
    tool: "",
    timestamp: ""
  });

  const agentNameMap = useMemo(
    () => ({
      stockout_sentinel: "缺货哨兵",
      replenishment_planner: "补货规划",
      exception_investigator: "异常侦测",
      markdown_clearance_coach: "清仓教练",
      inventory_copilot: "库存助手"
    }),
    []
  );

  const statCards = useMemo(
    () => [
      { label: "SKU 总数", value: stats.total_skus, accent: ACCENTS[0] },
      { label: "缺货风险", value: stats.stockout_risks, accent: ACCENTS[1] },
      { label: "紧急风险", value: stats.critical_risks, accent: ACCENTS[2] },
      { label: "低库存", value: stats.low_stock_items, accent: ACCENTS[3] },
      { label: "类目数量", value: stats.total_categories, accent: ACCENTS[4] }
    ],
    [stats]
  );

  const loadData = async () => {
    try {
      const [agentData, statsData] = await Promise.all([fetchAgents(), fetchStats()]);
      setAgents(agentData);
      setStats(statsData.stats || DEFAULT_STATS);
      if (agentData.length > 0) setActiveAgent(agentData[0].id);
    } catch (error) {
      setAgents([]);
      setStats(DEFAULT_STATS);
    }
  };

  const loadInventory = async () => {
    try {
      setInventoryItems(await fetchInventory("all", 100));
    } catch (error) {
      setInventoryItems([]);
    }
  };

  useEffect(() => {
    loadData();
    loadInventory();
  }, []);

  useEffect(() => () => {
    if (detectionAbortRef.current) {
      detectionAbortRef.current.abort();
      detectionAbortRef.current = null;
    }
    Object.values(pollerRef.current).forEach((timerId) => window.clearInterval(timerId));
    pollerRef.current = {};
    if (detectionTimerRef.current) {
      window.clearInterval(detectionTimerRef.current);
      detectionTimerRef.current = null;
    }
  }, []);

  useEffect(() => {
    if (!detectionEnabled) {
      stopDetectionSchedule();
      setDetectionStatus((prev) => ({
        ...prev,
        next_run_at: "",
        cycle_status: prev.running ? prev.cycle_status : "IDLE"
      }));
      return;
    }
    startDetectionSchedule();
    return () => stopDetectionSchedule();
  }, [detectionEnabled, detectionIntervalMs]);

  const stopPolling = (jobId) => {
    const timerId = pollerRef.current[jobId];
    if (!timerId) return;
    window.clearInterval(timerId);
    delete pollerRef.current[jobId];
  };

  const setExportState = (messageId, patch) => {
    setExportStates((prev) => ({
      ...prev,
      [messageId]: {
        ...(prev[messageId] || {}),
        ...patch
      }
    }));
  };

  const setDetectionMemberExportState = (stepKey, patch) => {
    setDetectionMemberExportStates((prev) => ({
      ...prev,
      [stepKey]: {
        ...(prev[stepKey] || {}),
        ...patch
      }
    }));
  };

  const startPolling = (jobId, messageId) => {
    stopPolling(jobId);
    const timerId = window.setInterval(async () => {
      try {
        const status = await getExportJob(jobId);
        setExportState(messageId, {
          job_id: status.job_id,
          status: status.status,
          progress: status.progress,
          error_message: status.error_message || ""
        });
        if (["DONE", "FAILED", "EXPIRED"].includes(status.status)) {
          stopPolling(jobId);
        }
      } catch (error) {
        setExportState(messageId, {
          status: "FAILED",
          progress: 100,
          error_message: "状态查询失败"
        });
        stopPolling(jobId);
      }
    }, 1500);
    pollerRef.current[jobId] = timerId;
  };

  const startPollingDetectionMemberExport = (jobId, stepKey) => {
    stopPolling(jobId);
    const timerId = window.setInterval(async () => {
      try {
        const status = await getExportJob(jobId);
        setDetectionMemberExportState(stepKey, {
          job_id: status.job_id,
          status: status.status,
          progress: status.progress,
          error_message: status.error_message || ""
        });
        if (["DONE", "FAILED", "EXPIRED"].includes(status.status)) {
          stopPolling(jobId);
        }
      } catch (error) {
        setDetectionMemberExportState(stepKey, {
          status: "FAILED",
          progress: 100,
          error_message: "状态查询失败"
        });
        stopPolling(jobId);
      }
    }, 1500);
    pollerRef.current[jobId] = timerId;
  };

  const setDetectionStep = (key, patch) => {
    setDetectionSteps((prev) =>
      prev.map((item) => (item.key === key ? { ...item, ...patch } : item))
    );
  };

  const pushDetectionEvent = (event, overrideText = "") => {
    const timestamp = String(event?.timestamp || new Date().toISOString());
    const text = String(overrideText || buildProgressText(event) || "").trim();
    if (!text) return;
    const node = String(event?.node || "");
    const phase = String(event?.phase || (node === "runtime_progress" ? "progress" : node) || "");
    const memberId = String(event?.member_id || event?.latest_step?.member_id || "").trim();
    const memberStatus = String(event?.member_status || event?.latest_step?.result_status || "").trim();
    const tool = String(
      event?.tool
      || event?.latest_tool
      || (Array.isArray(event?.latest_step?.tool_trace)
        ? event.latest_step.tool_trace[event.latest_step.tool_trace.length - 1]?.tool
        : "")
      || ""
    ).trim();
    const errorCode = String(event?.error_code || event?.latest_step?.error_code || "").trim();
    const errorMessage = String(event?.error_message || event?.latest_step?.error_message || "").trim();

    setDetectionCurrent({
      text,
      phase,
      member_id: memberId,
      member_status: memberStatus,
      tool,
      error_code: errorCode,
      error_message: errorMessage,
      timestamp
    });

    setDetectionTimeline((prev) => {
      const current = Array.isArray(prev) ? prev : [];
      const last = current[current.length - 1];
      if (
        last
        && last.text === text
        && String(last.phase || "") === phase
        && String(last.member_id || "") === memberId
        && String(last.tool || "") === tool
      ) {
        return current;
      }
      const next = [
        ...current,
        {
          id: crypto.randomUUID(),
          timestamp,
          text,
          node,
          phase,
          member_id: memberId,
          member_status: memberStatus,
          tool,
          error_code: errorCode,
          error_message: errorMessage,
          level: errorCode || errorMessage ? "failed" : (String(memberStatus).toLowerCase() === "failed" ? "failed" : "info"),
        }
      ];
      return next.slice(-240);
    });
  };

  const resetDetectionSteps = () => {
    Object.values(detectionMemberExportStates).forEach((state) => {
      if (state?.job_id) {
        stopPolling(state.job_id);
      }
    });
    setDetectionMemberExportStates({});
    setDetectionTimeline([]);
    setDetectionTimelineExpanded(false);
    setDetectionCurrent({
      text: "等待执行",
      phase: "team",
      member_id: "",
      member_status: "",
      tool: "",
      error_code: "",
      error_message: "",
      timestamp: ""
    });
    setDetectionSteps([
      {
        key: "team_orchestration",
        label: "协同编排",
        status: "PENDING",
        started_at: "",
        finished_at: "",
        summary: "等待执行"
      }
    ]);
  };

  const runDetectionCycle = async (trigger = "manual") => {
    if (detectionRunningRef.current) return;
    detectionRunningRef.current = true;
    const abortController = new AbortController();
    detectionAbortRef.current = abortController;
    const startedAt = new Date().toISOString();
    try {
      resetDetectionSteps();
      setDetectionStatus((prev) => ({
        ...prev,
        running: true,
        cycle_status: "RUNNING",
        error_message: "",
        last_run_at: startedAt
      }));

      const stepStartedAt = new Date().toISOString();
      setDetectionStep("team_orchestration", {
        status: "RUNNING",
        started_at: stepStartedAt,
        summary: "执行中"
      });
      pushDetectionEvent(
        {
          node: "runtime_progress",
          phase: "team",
          status_text: "协同任务已启动，正在初始化成员与上下文",
          timestamp: stepStartedAt
        },
        "协同任务已启动，正在初始化成员与上下文"
      );

      const response = await invokeAgentStream(
        {
          agent: "inventory_copilot",
          input: "执行固定巡检",
          session_id: sessionId,
          parameters: {
            mode: "team",
            prompt_preset: DETECTION_PROMPT_PRESET,
            orchestration: DETECTION_ORCHESTRATION,
          }
        },
        {
          signal: abortController.signal,
          onUpdate: (event) => {
            pushDetectionEvent(event);
            const node = String(event?.node || "");
            if (node === "runtime_progress") {
              const nowIso = new Date().toISOString();
              const statusText = String(event?.status_text || "").trim();
              const memberId = String(event?.member_id || "");
              const memberStatus = String(event?.member_status || "").toLowerCase();
              const toolName = String(event?.tool || "");
              const teamState = event?.team_state && typeof event.team_state === "object" ? event.team_state : {};
              const runtimeMembers = Array.isArray(teamState?.members)
                ? teamState.members.map((item) => String(item || "")).filter(Boolean)
                : [];
              const runtimeStatus = RUNTIME_MEMBER_STATUS_TO_DETECTION[memberStatus] || "";

              setDetectionSteps((prev) => {
                const current = Array.isArray(prev) ? prev.map((item) => ({ ...item })) : [];
                const hasTeamStep = current.some((item) => item.key === "team_orchestration");
                const next = hasTeamStep
                  ? current
                  : [
                    {
                      key: "team_orchestration",
                      label: "协同编排",
                      status: "RUNNING",
                      started_at: stepStartedAt,
                      finished_at: "",
                      summary: "执行中"
                    },
                    ...current
                  ];

                if (runtimeMembers.length) {
                  runtimeMembers.forEach((agentId, index) => {
                    if (!agentId) return;
                    const exists = next.some((item) => item.agent_id === agentId);
                    if (exists) return;
                    next.push({
                      key: `${agentId}-${index}`,
                      label: TEAM_MEMBER_LABEL[agentId] || agentId || `成员${index + 1}`,
                      agent_id: agentId,
                      status: "PENDING",
                      started_at: "",
                      finished_at: "",
                      summary: "等待执行",
                      result_status: "",
                      error_code: "",
                      response_text: "",
                      structured_output: {},
                      tool_trace: [],
                      tool_output: {},
                    });
                  });
                }

                if (memberId) {
                  let targetIndex = next.findIndex((item) => item.agent_id === memberId);
                  if (targetIndex < 0) {
                    next.push({
                      key: memberId,
                      label: TEAM_MEMBER_LABEL[memberId] || memberId,
                      agent_id: memberId,
                      status: runtimeStatus || "RUNNING",
                      started_at: nowIso,
                      finished_at: runtimeStatus === "DONE" || runtimeStatus === "FAILED" ? nowIso : "",
                      summary: statusText || (toolName ? `正在调用${toolDisplayLabel(toolName)}` : "执行中"),
                      result_status: memberStatus || "",
                      error_code: "",
                      response_text: "",
                      structured_output: {},
                      tool_trace: [],
                      tool_output: {},
                    });
                    targetIndex = next.length - 1;
                  } else {
                    const oldItem = next[targetIndex];
                    next[targetIndex] = {
                      ...oldItem,
                      status: runtimeStatus || oldItem.status || "RUNNING",
                      started_at: oldItem.started_at || nowIso,
                      finished_at:
                        runtimeStatus === "DONE" || runtimeStatus === "FAILED"
                          ? nowIso
                          : oldItem.finished_at || "",
                      summary: statusText || oldItem.summary || (toolName ? `正在调用${toolDisplayLabel(toolName)}` : "执行中"),
                      result_status: memberStatus || oldItem.result_status || "",
                    };
                  }

                  if (runtimeStatus === "RUNNING") {
                    next.forEach((item, index) => {
                      if (index === targetIndex) return;
                      if (!item.agent_id) return;
                      if (item.status === "DONE" || item.status === "FAILED") return;
                      if (item.status === "RUNNING") {
                        next[index] = {
                          ...item,
                          status: "PENDING",
                          summary: item.summary && item.summary !== "执行中" ? item.summary : "等待执行"
                        };
                      }
                    });
                  }
                }

                const teamIndex = next.findIndex((item) => item.key === "team_orchestration");
                if (teamIndex >= 0) {
                  const oldTeam = next[teamIndex];
                  next[teamIndex] = {
                    ...oldTeam,
                    status: "RUNNING",
                    started_at: oldTeam.started_at || stepStartedAt,
                    summary: statusText || (toolName ? `正在调用${toolDisplayLabel(toolName)}` : oldTeam.summary || "执行中"),
                  };
                }

                return next;
              });
              return;
            }

            if (node === "copilot_team_v1_plan") {
              const plannedMembers = Array.isArray(event?.team_plan) ? event.team_plan : [];
              if (plannedMembers.length) {
                setDetectionSteps(
                  [
                    {
                      key: "team_orchestration",
                      label: "协同编排",
                      status: "RUNNING",
                      started_at: new Date().toISOString(),
                      finished_at: "",
                      summary: "协同规划完成，等待成员执行"
                    },
                    ...plannedMembers.map((memberId, index) => ({
                      key: `${memberId}-${index}`,
                      label: TEAM_MEMBER_LABEL[memberId] || memberId || `成员${index + 1}`,
                      agent_id: memberId,
                      status: "PENDING",
                      started_at: "",
                      finished_at: "",
                      summary: "等待执行",
                      result_status: "",
                      error_code: "",
                      response_text: "",
                      structured_output: {},
                      tool_trace: [],
                      tool_output: {},
                    }))
                  ]
                );
              }
              return;
            }

            if (node === "copilot_team_v1_execute") {
              const latest = event?.latest_step || {};
              const memberId = String(latest?.member_id || "");
              if (!memberId) return;
              const nowIso = new Date().toISOString();
              const status = TEAM_RESULT_TO_DETECTION_STATUS[latest?.result_status] || "DONE";
              const summary = latest?.summary || latest?.response_text || latest?.error_code || "完成";
              const nextMember = Array.isArray(event?.remaining) ? String(event.remaining[0] || "") : "";

              setDetectionSteps((prev) => {
                const next = prev.map((item) => ({ ...item }));
                const foundIndex = next.findIndex((item) => item.agent_id === memberId);
                const target = {
                  key: memberId,
                  label: TEAM_MEMBER_LABEL[memberId] || memberId,
                  agent_id: memberId,
                  status,
                  summary,
                  started_at: latest?.started_at || nowIso,
                  finished_at: latest?.ended_at || nowIso,
                  result_status: latest?.result_status || "",
                  error_code: latest?.error_code || "",
                  response_text: latest?.response_text || "",
                  structured_output: latest?.structured_output || {},
                  tool_trace: Array.isArray(latest?.tool_trace) ? latest.tool_trace : [],
                  tool_output:
                    latest?.tool_outputs && typeof latest.tool_outputs === "object"
                      ? latest.tool_outputs
                      : latest?.tool_output && typeof latest.tool_output === "object"
                        ? latest.tool_output
                        : {},
                };
                if (foundIndex >= 0) {
                  next[foundIndex] = { ...next[foundIndex], ...target };
                } else {
                  next.push(target);
                }

                if (nextMember) {
                  const nextIdx = next.findIndex((item) => item.agent_id === nextMember);
                  if (nextIdx >= 0 && next[nextIdx].status === "PENDING") {
                    next[nextIdx] = {
                      ...next[nextIdx],
                      status: "RUNNING",
                      started_at: next[nextIdx].started_at || nowIso,
                      summary: "执行中"
                    };
                  }
                }
                return next;
              });
              return;
            }

            if (node === "copilot_team_v1_aggregate") {
              setDetectionStatus((prev) => ({
                ...prev,
                cycle_status: "RUNNING",
                error_message: ""
              }));
              pushDetectionEvent(event, "正在汇总成员执行结果并生成综合结论");
              return;
            }

            setDetectionStep("team_orchestration", {
              status: "RUNNING",
              summary: `执行节点：${nodeDisplayLabel(node)}`
            });
          }
        }
      );

      const structured = response?.response?.structured_output || {};
      const teamExecution = Array.isArray(structured?.team_execution) ? structured.team_execution : [];
      const executionFinishedAt = new Date().toISOString();

      const workflowResults = teamExecution.map((item, index) => {
        const memberId = String(item?.member_id || "");
        const status = TEAM_RESULT_TO_DETECTION_STATUS[item?.result_status] || "DONE";
        const summary = item?.summary || item?.response_text || item?.error_code || "完成";
        return {
          key: `${memberId || "member"}-${index}`,
          label: TEAM_MEMBER_LABEL[memberId] || memberId || `成员${index + 1}`,
          agent_id: memberId,
          status,
          summary,
          started_at: item?.started_at || stepStartedAt,
          finished_at: item?.ended_at || executionFinishedAt,
          result_status: item?.result_status || "",
          error_code: item?.error_code || "",
          response_text: item?.response_text || "",
          structured_output: item?.structured_output || {},
          tool_trace: Array.isArray(item?.tool_trace) ? item.tool_trace : [],
          tool_output:
            item?.tool_outputs && typeof item.tool_outputs === "object"
              ? item.tool_outputs
              : item?.tool_output && typeof item.tool_output === "object"
                ? item.tool_output
                : {},
        };
      });

      if (workflowResults.length) {
        setDetectionSteps(workflowResults);
      } else {
        setDetectionSteps([
          {
            key: "team_orchestration",
            label: "协同编排",
            status: "DONE",
            started_at: stepStartedAt,
            finished_at: executionFinishedAt,
            summary: "已完成"
          }
        ]);
      }

      const failedCount = Number(
        structured?.team_summary?.failure_count
          ?? workflowResults.filter((item) => item.status === "FAILED").length
      );
      const finalStatus =
        structured?.status === "team_v1_failed"
          ? "FAILED"
          : structured?.status === "team_v1_partial" || failedCount > 0
            ? "PARTIAL"
            : "COMPLETED";
      const finalAnswer = extractResponseText(response);
      if (!finalAnswer) {
        throw new Error("模型返回空内容");
      }
      const now = new Date().toISOString();
      const finalMessageId = crypto.randomUUID();

      setMessages((prev) => [
        ...prev,
        {
          id: finalMessageId,
          role: "assistant",
          content: "已完成",
          created_at: now,
          agent_id: "inventory_copilot",
          meta: {
            source_input: `preset:${DETECTION_PROMPT_PRESET}`,
            response_text: finalAnswer,
            reasoning: response?.response?.reasoning || "",
            structured_output: structured,
            tool_trace: response?.response?.tool_trace || [],
            tool_output: response?.response?.tool_output || {
              workflow_results: workflowResults,
              rag_corpus: [],
              rag_retrieval_trace: [],
              trigger
            },
            request_id: response?.request_id || `detection-${crypto.randomUUID().slice(0, 8)}`,
            model: response?.model || "inventory_copilot",
            timestamp: response?.timestamp || now,
            collab_mode: response?.collab_mode || "team",
            execution_status: "COMPLETED"
          }
        }
      ]);
      setDetectionFinalMessageId(finalMessageId);

      setDetectionStatus((prev) => ({
        ...prev,
        running: false,
        cycle_status: finalStatus,
        error_message: failedCount > 0 ? `${failedCount} 个环节执行失败` : "",
        last_run_at: now,
        next_run_at: detectionEnabled ? new Date(Date.now() + detectionIntervalMs).toISOString() : ""
      }));
      pushDetectionEvent(
        {
          node: "runtime_progress",
          phase: "team",
          member_status: failedCount > 0 ? "failed" : "success",
          status_text: failedCount > 0 ? `协同执行完成，但有 ${failedCount} 个失败环节` : "协同执行完成",
          timestamp: now
        },
        failedCount > 0 ? `协同执行完成，但有 ${failedCount} 个失败环节` : "协同执行完成"
      );
    } catch (error) {
      if (isAbortError(error)) {
        const stoppedAt = new Date().toISOString();
        setDetectionSteps([
          {
            key: "team_orchestration",
            label: "协同编排",
            status: "FAILED",
            started_at: startedAt,
            finished_at: stoppedAt,
            summary: "执行已停止"
          }
        ]);
        setDetectionStatus((prev) => ({
          ...prev,
          running: false,
          cycle_status: "STOPPED",
          error_message: "用户已停止执行",
          last_run_at: stoppedAt
        }));
        pushDetectionEvent(
          {
            node: "runtime_progress",
            phase: "team",
            member_status: "failed",
            error_code: "DETECTION_ABORTED",
            error_message: "用户已停止执行",
            status_text: "执行已停止",
            timestamp: stoppedAt
          },
          "执行已停止"
        );
        return;
      }
      const reason = String(error?.message || "未知错误");
      setDetectionSteps([
        {
            key: "team_orchestration",
            label: "协同编排",
          status: "FAILED",
          started_at: startedAt,
          finished_at: new Date().toISOString(),
          summary: `执行失败：${reason}`
        }
      ]);
      setDetectionStatus((prev) => ({
        ...prev,
        running: false,
        cycle_status: "PARTIAL",
        error_message: reason,
        last_run_at: new Date().toISOString()
      }));
      pushDetectionEvent(
        {
          node: "runtime_progress",
          phase: "team",
          member_status: "failed",
          error_code: "DETECTION_RUN_ERROR",
          error_message: reason,
          status_text: `协同执行失败：${reason}`,
          timestamp: new Date().toISOString()
        },
        `协同执行失败：${reason}`
      );
    } finally {
      detectionRunningRef.current = false;
      detectionAbortRef.current = null;
    }
  };

  const stopDetectionRun = () => {
    if (!detectionRunningRef.current || !detectionAbortRef.current) return;
    const nowIso = new Date().toISOString();
    pushDetectionEvent(
      {
        node: "runtime_progress",
        phase: "team",
        status_text: "收到停止指令，正在中断当前执行",
        timestamp: nowIso
      },
      "收到停止指令，正在中断当前执行"
    );
    setDetectionCurrent((prev) => ({
      ...prev,
      text: "收到停止指令，正在中断当前执行",
      phase: "team",
      timestamp: nowIso
    }));
    detectionAbortRef.current.abort(new DOMException("用户已停止执行", "AbortError"));
  };

  const stopDetectionSchedule = () => {
    if (!detectionTimerRef.current) return;
    window.clearInterval(detectionTimerRef.current);
    detectionTimerRef.current = null;
  };

  const startDetectionSchedule = () => {
    stopDetectionSchedule();
    const timerId = window.setInterval(() => {
      void runDetectionCycle("scheduled");
    }, detectionIntervalMs);
    detectionTimerRef.current = timerId;
    setDetectionStatus((prev) => ({
      ...prev,
      next_run_at: new Date(Date.now() + detectionIntervalMs).toISOString()
    }));
  };

  const createAnalysisExport = async (messageId, format, audience) => {
    const target = messages.find((message) => message.id === messageId);
    if (!target || !isAnalysisExportable(target)) return;
    try {
      const agentLabel = agentNameMap[target.agent_id] || target.agent_id || "智能体";
      const titlePrefix = AGENT_EXPORT_TITLE_MAP[target.agent_id] || `${agentLabel}建议`;
      const response = await createExportJob({
        format,
        scope: "analysis",
        audience,
        session_id: sessionId,
        agent_id: target.agent_id || activeAgent,
        title: `${titlePrefix}-${formatTitleDate(new Date())}`,
        payload: {
          analysis: {
            agent_id: target.agent_id || activeAgent,
            question: target.meta?.source_input || "",
            answer: target.meta?.response_text || target.content || "",
            reasoning: target.meta?.reasoning || "",
            structured_output: target.meta?.structured_output || {},
            tool_trace: target.meta?.tool_trace || [],
            tool_output: target.meta?.tool_output || {},
            request_id: target.meta?.request_id || "",
            model: target.meta?.model || "",
            timestamp: target.created_at || new Date().toISOString()
          }
        }
      });
      setExportState(messageId, {
        job_id: response.job_id,
        status: response.status,
        progress: 0,
        error_message: ""
      });
      startPolling(response.job_id, messageId);
    } catch (error) {
      setExportState(messageId, {
        status: "FAILED",
        progress: 100,
        error_message: "导出任务创建失败"
      });
    }
  };

  const downloadAnalysisExport = async (messageId) => {
    const state = exportStates[messageId];
    if (!state?.job_id) return;
    try {
      const { blob, filename } = await downloadExport(state.job_id);
      const url = window.URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.URL.revokeObjectURL(url);
    } catch (error) {
      setExportState(messageId, {
        status: "FAILED",
        progress: 100,
        error_message: "下载失败，请稍后重试"
      });
    }
  };

  const createDetectionMemberExport = async (stepKey, format = "pdf", audience = detectionReportAudience) => {
    const step = detectionSteps.find((item) => item.key === stepKey);
    if (!step?.agent_id) return;
    try {
      const titlePrefix = AGENT_EXPORT_TITLE_MAP[step.agent_id] || `${step.label || step.agent_id}建议`;
      const response = await createExportJob({
        format,
        scope: "analysis",
        audience,
        session_id: sessionId,
        agent_id: step.agent_id,
        title: `${titlePrefix}-${formatTitleDate(new Date())}`,
        payload: {
          analysis: {
            agent_id: step.agent_id,
            question: `智能检测成员任务：${step.label || step.agent_id}`,
            answer: step.response_text || step.summary || "",
            reasoning: "",
            structured_output: step.structured_output || {},
            tool_trace: step.tool_trace || [],
            tool_output: step.tool_output || {},
            request_id: detectionFinalMessage?.meta?.request_id || "",
            model: detectionFinalMessage?.meta?.model || "",
            timestamp: step.finished_at || new Date().toISOString(),
          },
        },
      });

      setDetectionMemberExportState(stepKey, {
        job_id: response.job_id,
        status: response.status,
        progress: 0,
        error_message: ""
      });
      startPollingDetectionMemberExport(response.job_id, stepKey);
    } catch (error) {
      setDetectionMemberExportState(stepKey, {
        status: "FAILED",
        progress: 100,
        error_message: "导出任务创建失败"
      });
    }
  };

  const downloadDetectionMemberExport = async (stepKey) => {
    const state = detectionMemberExportStates[stepKey];
    if (!state?.job_id) return;
    try {
      const { blob, filename } = await downloadExport(state.job_id);
      const url = window.URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.URL.revokeObjectURL(url);
    } catch (error) {
      setDetectionMemberExportState(stepKey, {
        status: "FAILED",
        progress: 100,
        error_message: "下载失败，请稍后重试"
      });
    }
  };

  const exportAllDetectionMembers = async (format = "pdf", audience = detectionReportAudience) => {
    const exportableSteps = detectionSteps.filter((item) => item.agent_id);
    if (!exportableSteps.length) return;
    setDetectionMemberBatchRunning(true);
    try {
      for (const step of exportableSteps) {
        await createDetectionMemberExport(step.key, format, audience);
      }
    } finally {
      setDetectionMemberBatchRunning(false);
    }
  };

  const runDetectionNow = async () => {
    await runDetectionCycle("manual");
  };

  const toggleDetection = () => {
    setDetectionEnabled((prev) => !prev);
  };

  const detectionFinalMessage = detectionFinalMessageId
    ? messages.find((item) => item.id === detectionFinalMessageId) || null
    : null;
  const detectionFinalExportState = detectionFinalMessageId
    ? exportStates[detectionFinalMessageId] || null
    : null;

  const exportDetectionFinalReport = async (format = "pdf", audience = detectionReportAudience) => {
    if (!detectionFinalMessageId || !detectionFinalMessage) return;
    await createAnalysisExport(detectionFinalMessageId, format, audience);
  };

  const downloadDetectionFinalReport = async () => {
    if (!detectionFinalMessageId) return;
    await downloadAnalysisExport(detectionFinalMessageId);
  };

  const hasExportableDetectionMembers = detectionSteps.some((step) => Boolean(step.agent_id));

  const handleSend = async (text, options = {}) => {
    const targetAgent = options.agentId || activeAgent;
    if (targetAgent !== activeAgent) setActiveAgent(targetAgent);
    const pendingId = crypto.randomUUID();
    const now = new Date().toISOString();
    setMessages((prev) => [
      ...prev,
      {
        id: crypto.randomUUID(),
        role: "user",
        content: text,
        created_at: now,
        agent_id: targetAgent,
        meta: null
      },
      {
        id: pendingId,
        role: "assistant",
        content: "执行中",
        created_at: now,
        agent_id: targetAgent,
        meta: {
          source_input: text,
          response_text: "",
          reasoning: "",
          structured_output: {},
          tool_trace: [],
          tool_output: {},
          request_id: "",
          model: "",
          timestamp: now,
          progress_log: [
            {
              id: crypto.randomUUID(),
              text: "已接收问题，正在准备分析",
              timestamp: now
            }
          ],
          execution_status: "RUNNING"
        }
      }
    ]);
    setLoading(true);
    const patchPending = (metaPatch = {}, contentPatch = "执行中") => {
      setMessages((prev) =>
        prev.map((item) => {
          if (item.id !== pendingId) return item;
          return {
            ...item,
            content: contentPatch,
            meta: {
              ...(item.meta || {}),
              ...metaPatch
            }
          };
        })
      );
    };
    const appendPendingProgress = (text) => {
      const normalized = String(text || "").trim();
      if (!normalized) return;
      setMessages((prev) =>
        prev.map((item) => {
          if (item.id !== pendingId) return item;
          const currentLog = Array.isArray(item?.meta?.progress_log) ? item.meta.progress_log : [];
          const lastText = String(currentLog[currentLog.length - 1]?.text || "");
          if (lastText === normalized) {
            return item;
          }
          const nextLog = [
            ...currentLog,
            {
              id: crypto.randomUUID(),
              text: normalized,
              timestamp: new Date().toISOString()
            }
          ].slice(-20);
          return {
            ...item,
            meta: {
              ...(item.meta || {}),
              stream_status: normalized,
              progress_log: nextLog
            }
          };
        })
      );
    };
    const streamReplyText = async (fullText, metaBase) => {
      const normalized = String(fullText || "").trim();
      if (!normalized) return;
      const length = normalized.length;
      let cursor = 0;

      while (cursor < length) {
        const remain = length - cursor;
        let step = 1;
        if (remain > 480) step = 6;
        else if (remain > 240) step = 4;
        else if (remain > 120) step = 3;
        else if (remain > 60) step = 2;
        cursor = Math.min(length, cursor + step);
        const partial = normalized.slice(0, cursor);
        setMessages((prev) =>
          prev.map((item) => {
            if (item.id !== pendingId) return item;
            return {
              ...item,
              content: partial,
              meta: {
                ...(item.meta || {}),
                ...metaBase,
                response_text: partial,
                stream_status: cursor >= length ? "执行完成" : "正在输出回答",
                execution_status: cursor >= length ? "COMPLETED" : "RUNNING",
              }
            };
          })
        );
        await new Promise((resolve) => window.setTimeout(resolve, 18));
      }
    };

    let lastNodeUpdateAt = Date.now();
    let heartbeatIndex = 0;
    const heartbeatTimer = window.setInterval(() => {
      const nowTs = Date.now();
      if (nowTs - lastNodeUpdateAt < 1800) return;
      const textLine = HEARTBEAT_TEXTS[heartbeatIndex % HEARTBEAT_TEXTS.length];
      heartbeatIndex += 1;
      patchPending(
        {
          stream_status: textLine,
          execution_status: "RUNNING"
        },
        "执行中"
      );
      appendPendingProgress(textLine);
      lastNodeUpdateAt = nowTs;
    }, 1200);

    try {
      const response = await invokeAgentStream(
        {
          agent: targetAgent,
          input: text,
          session_id: sessionId,
          parameters: options.parameters
        },
        {
          onStart: (event) => {
            patchPending(
              {
                request_id: event?.request_id || "",
                collab_mode: event?.collab_mode || "",
                stream_status: "任务已启动，准备执行。",
                execution_status: "RUNNING",
                stream_workflow: {
                  mode: event?.collab_mode === "team" ? "team" : "single",
                  members: [],
                  member_status: {},
                  current_member: "",
                  current_tool: "",
                  phase: "start"
                }
              },
              "执行中"
            );
            appendPendingProgress("任务已启动，正在载入上下文");
            lastNodeUpdateAt = Date.now();
          },
          onUpdate: (event) => {
            const node = String(event?.node || "");
            const statusLine = buildProgressText(event);
            setMessages((prev) =>
              prev.map((item) => {
                if (item.id !== pendingId) return item;
                const existingMeta = item.meta || {};
                const nextWorkflow = mergeStreamWorkflowState(existingMeta.stream_workflow, event);
                return {
                  ...item,
                  content: "执行中",
                  meta: {
                    ...existingMeta,
                    stream_status: statusLine,
                    stream_node: node,
                    stream_event: event,
                    stream_workflow: nextWorkflow,
                    execution_status: "RUNNING"
                  }
                };
              })
            );
            appendPendingProgress(statusLine);
            lastNodeUpdateAt = Date.now();
          }
        }
      );
      const reply = extractResponseText(response);
      if (!reply) {
        throw new Error("模型返回空内容");
      }
      window.clearInterval(heartbeatTimer);
      appendPendingProgress("分析完成，正在输出回答");
      const baseMeta = {
        source_input: text,
        reasoning: response?.response?.reasoning || "",
        structured_output: response?.response?.structured_output || {},
        tool_trace: response?.response?.tool_trace || [],
        tool_output: response?.response?.tool_output || {},
        collab_mode: response?.collab_mode || "",
        request_id: response?.request_id || "",
        model: response?.model || "",
        timestamp: response?.timestamp || ""
      };
      setMessages((prev) =>
        prev.map((item) => {
          if (item.id !== pendingId) return item;
          const oldProgress = Array.isArray(item?.meta?.progress_log) ? item.meta.progress_log : [];
          const finalProgress = [
            ...oldProgress,
            {
              id: crypto.randomUUID(),
              text: "分析完成，正在输出回答",
              timestamp: new Date().toISOString()
            }
          ].slice(-20);
          return {
            ...item,
            content: "",
            created_at: new Date().toISOString(),
            meta: {
              ...baseMeta,
              progress_log: finalProgress,
              response_text: "",
              stream_status: "正在输出回答",
              stream_workflow: item?.meta?.stream_workflow || {},
              execution_status: "RUNNING"
            }
          };
        })
      );
      await streamReplyText(reply, baseMeta);
      setMessages((prev) =>
        prev.map((item) => {
          if (item.id !== pendingId) return item;
          const finalProgress = Array.isArray(item?.meta?.progress_log) ? item.meta.progress_log : [];
          return {
            ...item,
            created_at: new Date().toISOString(),
            meta: {
              ...(item.meta || {}),
              ...baseMeta,
              response_text: reply,
              progress_log: finalProgress,
              stream_status: "执行完成",
              stream_workflow: item?.meta?.stream_workflow || {},
              execution_status: "COMPLETED"
            }
          };
        })
      );
    } catch (error) {
      window.clearInterval(heartbeatTimer);
      const reason = String(error?.message || "未知错误");
      setMessages((prev) =>
        prev.map((item) => {
          if (item.id !== pendingId) return item;
          const oldProgress = Array.isArray(item?.meta?.progress_log) ? item.meta.progress_log : [];
          const finalProgress = [
            ...oldProgress,
            {
              id: crypto.randomUUID(),
              text: `执行失败：${reason}`,
              timestamp: new Date().toISOString()
            }
          ].slice(-20);
          return {
            ...item,
            content: `执行失败：${reason}`,
            created_at: new Date().toISOString(),
            meta: {
              source_input: text,
              response_text: `执行失败：${reason}`,
              reasoning: "",
              structured_output: {},
              tool_trace: [],
              tool_output: {},
              collab_mode: options?.parameters?.mode || "",
              stream_status: "执行失败",
              stream_workflow: item?.meta?.stream_workflow || {},
              request_id: "",
              model: "",
              timestamp: new Date().toISOString(),
              progress_log: finalProgress,
              execution_status: "FAILED"
            }
          };
        })
      );
    } finally {
      window.clearInterval(heartbeatTimer);
      setLoading(false);
    }
  };

  const handleQuickAction = (agentId, text) => handleSend(text, { agentId });

  return (
    <div className="app">
      <header className="hero">
        <div>
          <p className="hero-eyebrow">库存智控台</p>
          <h1>跨境库存运营与决策</h1>
          <p className="hero-sub">围绕当前分析结果展开洞察、执行与报告输出。</p>
        </div>
        <div className="hero-meta">
          <div>
            <span>会话</span>
            <strong>{sessionId.slice(0, 8)}</strong>
          </div>
          <div>
            <span>状态</span>
            <strong>{loading ? "分析中" : "待命"}</strong>
          </div>
        </div>
      </header>

      <section className="stats-grid">
        {statCards.map((card) => (
          <StatCard key={card.label} {...card} />
        ))}
      </section>

      <section className="agent-centered-layout">
        <div className="agent-main">
          <ChatPanel
            agents={agents}
            activeAgent={activeAgent}
            onAgentChange={setActiveAgent}
            messages={messages}
            onSend={handleSend}
            onQuickAction={handleQuickAction}
            onExportAnalysis={createAnalysisExport}
            onDownloadExport={downloadAnalysisExport}
            exportStates={exportStates}
            isAnalysisExportable={isAnalysisExportable}
            loading={loading}
          />
        </div>
        <aside className="agent-spotlight">
          <div className="panel detection-panel">
            <div className="panel-header">
              <h3>智能检测</h3>
              <span className={`status-chip ${String(detectionStatus.cycle_status).toLowerCase()}`}>
                {DETECTION_CYCLE_LABEL[detectionStatus.cycle_status] || detectionStatus.cycle_status}
              </span>
            </div>
            <div className="detection-controls">
              <span className="detection-mode-note">执行模式：协同编排（固定提示词由后端预设注入）</span>
              <label>
                检测频率
                <select
                  value={detectionIntervalMs}
                  onChange={(event) => setDetectionIntervalMs(Number(event.target.value))}
                  disabled={detectionStatus.running}
                >
                  {DETECTION_INTERVAL_OPTIONS.map((item) => (
                    <option value={item.value} key={item.value}>{item.label}</option>
                  ))}
                </select>
              </label>
              <div className="detection-buttons">
                <button className="ghost" onClick={toggleDetection}>
                  {detectionEnabled ? "停止巡检" : "启动巡检"}
                </button>
                <button className="ghost" onClick={runDetectionNow} disabled={detectionStatus.running}>
                  {detectionStatus.running ? "执行中..." : "立即执行"}
                </button>
                <button className="ghost" onClick={stopDetectionRun} disabled={!detectionStatus.running}>
                  停止执行
                </button>
              </div>
            </div>
            <div className="detection-meta">
              <span>上次执行：{formatDateTimeLabel(detectionStatus.last_run_at)}</span>
              <span>下次执行：{formatDateTimeLabel(detectionStatus.next_run_at)}</span>
            </div>
            {detectionStatus.error_message ? (
              <div className="export-error">{detectionStatus.error_message}</div>
            ) : null}

            <div className="export-inline">
              <button
                className="ghost"
                onClick={() => exportAllDetectionMembers("pdf")}
                disabled={!hasExportableDetectionMembers || detectionMemberBatchRunning}
              >
                {detectionMemberBatchRunning ? "批量导出中..." : "一键导出成员PDF"}
              </button>
              <button
                className="ghost"
                onClick={() => exportAllDetectionMembers("xlsx")}
                disabled={!hasExportableDetectionMembers || detectionMemberBatchRunning}
              >
                {detectionMemberBatchRunning ? "批量导出中..." : "一键导出成员Excel"}
              </button>
            </div>

            <DetectionWorkflowBoard
              running={Boolean(detectionStatus.running)}
              current={detectionCurrent}
              timeline={detectionTimeline}
              expanded={detectionTimelineExpanded}
              onToggleExpanded={() => setDetectionTimelineExpanded((prev) => !prev)}
            />

            <div className="detection-final-report">
              <strong>最终报告</strong>
              {detectionFinalMessage ? (
                <>
                  <p className="detection-final-summary">
                    {toOneLineSummary(detectionFinalMessage.meta?.response_text || "已生成智能检测结果", 128)}
                  </p>
                  <div className="export-inline">
                    <select value={detectionReportAudience} onChange={(event) => setDetectionReportAudience(event.target.value)}>
                      <option value="external">外部版</option>
                      <option value="internal">内部版</option>
                    </select>
                    <button className="ghost" onClick={() => exportDetectionFinalReport("pdf")}>
                      导出PDF
                    </button>
                    <button className="ghost" onClick={() => exportDetectionFinalReport("xlsx")}>
                      导出Excel
                    </button>
                    {detectionFinalExportState?.status === "DONE" ? (
                      <button className="ghost" onClick={downloadDetectionFinalReport}>
                        下载
                      </button>
                    ) : null}
                    {detectionFinalExportState?.status ? (
                      <span className={`status-pill ${String(detectionFinalExportState.status).toLowerCase()}`}>
                        {EXPORT_STATUS_TEXT[detectionFinalExportState.status] || detectionFinalExportState.status}{" "}
                        {typeof detectionFinalExportState.progress === "number" ? `${detectionFinalExportState.progress}%` : ""}
                      </span>
                    ) : null}
                  </div>
                </>
              ) : (
                <p className="muted">完成后可导出最终报告。</p>
              )}
            </div>
          </div>
        </aside>
      </section>

      <section className="inventory-stage">
        <div className="inventory-stage-header">
          <div>
            <h3>商品与库存明细</h3>
            <p className="panel-sub">保留商品展示，作为分析执行的底座数据</p>
          </div>
        </div>
        <InventoryTable items={inventoryItems} categories={stats.categories} />
      </section>
    </div>
  );
}

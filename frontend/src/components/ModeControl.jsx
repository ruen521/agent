const AGENT_NAME_MAP = {
  stockout_sentinel: "缺货哨兵",
  replenishment_planner: "补货规划",
  exception_investigator: "异常侦测",
  markdown_clearance_coach: "清仓教练",
  inventory_copilot: "库存助手"
};

export default function ModeControl({
  agents,
  activeAgent,
  onAgentChange,
  onQuickAction,
}) {
  return (
    <div className="chat-toolbar">
      <label>
        当前智能体
        <select value={activeAgent} onChange={(event) => onAgentChange(event.target.value)}>
          {agents.map((agent) => (
            <option key={agent.id} value={agent.id}>
              {AGENT_NAME_MAP[agent.id] || agent.friendly_name}
            </option>
          ))}
        </select>
      </label>
      <div className="lifecycle-info">
        <span>状态：就绪</span>
        <span>版本：v1</span>
        <span>别名：demo展示</span>
      </div>

      <div className="chat-actions">
        <button className="ghost" onClick={() => onQuickAction("stockout_sentinel", "展示缺货风险并给出处置建议")}>
          缺货风险
        </button>
        <button className="ghost" onClick={() => onQuickAction("replenishment_planner", "生成补货计划并按供应商分组")}>
          补货计划
        </button>
        <button className="ghost" onClick={() => onQuickAction("exception_investigator", "检查库存异常并给修复建议")}>
          异常检测
        </button>
        <button className="ghost" onClick={() => onQuickAction("markdown_clearance_coach", "给出清仓折扣和收益分析")}>
          清仓建议
        </button>
      </div>

    </div>
  );
}

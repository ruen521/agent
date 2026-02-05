import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export default function ChatPanel({
  agents,
  activeAgent,
  onAgentChange,
  messages,
  onSend,
  onQuickAction,
  loading
}) {
  const [input, setInput] = useState("");
  const agentNameMap = {
    stockout_sentinel: "缺货哨兵",
    replenishment_planner: "补货规划",
    exception_investigator: "异常侦测",
    markdown_clearance_coach: "清仓教练",
    inventory_copilot: "库存助手"
  };

  const handleSend = () => {
    if (!input.trim()) return;
    onSend(input.trim());
    setInput("");
  };

  const looksLikeMarkdown = (text) =>
    /(^|\n)#{1,6}\s|\|[- :]+\|/m.test(text) ||
    /```/.test(text) ||
    /(^|\n)(- |\* |\d+\. )/.test(text);

  return (
    <div className="panel chat-panel">
      <div className="panel-header">
        <h3>多智能体指挥舱</h3>
        <span className="panel-sub">实时切换智能体并提问。</span>
      </div>
      <div className="chat-toolbar">
        <label>
          当前智能体
          <select value={activeAgent} onChange={(event) => onAgentChange(event.target.value)}>
            {agents.map((agent) => (
              <option key={agent.id} value={agent.id}>
                {agentNameMap[agent.id] || agent.friendly_name}
              </option>
            ))}
          </select>
        </label>
        <div className="chat-actions">
          <button
            className="ghost"
            onClick={() => onQuickAction("stockout_sentinel", "展示缺货风险")}
          >
            缺货风险
          </button>
          <button
            className="ghost"
            onClick={() => onQuickAction("replenishment_planner", "生成补货计划")}
          >
            补货计划
          </button>
          <button
            className="ghost"
            onClick={() => onQuickAction("exception_investigator", "查找异常")}
          >
            异常检测
          </button>
          <button
            className="ghost"
            onClick={() => onQuickAction("markdown_clearance_coach", "给出清仓折扣建议")}
          >
            清仓建议
          </button>
        </div>
      </div>
      <div className="chat-feed">
        {messages.length === 0 ? (
          <div className="chat-empty">输入问题，获取实时分析。</div>
        ) : (
          messages.map((message, idx) => (
            <div key={idx} className={`chat-bubble ${message.role}`}>
              {looksLikeMarkdown(message.content) ? (
                <div className="markdown-content">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {message.content}
                  </ReactMarkdown>
                </div>
              ) : (
                <span>{message.content}</span>
              )}
            </div>
          ))
        )}
        {loading && <div className="chat-loading">智能体正在思考...</div>}
      </div>
      <div className="chat-input">
        <input
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder="输入库存、供应商、折扣等问题..."
        />
        <button onClick={handleSend}>发送</button>
      </div>
    </div>
  );
}

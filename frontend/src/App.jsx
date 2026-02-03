import { useEffect, useMemo, useState } from "react";
import { fetchAgents, fetchStats, fetchRisks, fetchInventory, invokeAgent } from "./api/client.js";
import StatCard from "./components/StatCard.jsx";
import RiskTable from "./components/RiskTable.jsx";
import InventoryTable from "./components/InventoryTable.jsx";
import ChatPanel from "./components/ChatPanel.jsx";

const DEFAULT_STATS = {
  total_skus: 0,
  stockout_risks: 0,
  critical_risks: 0,
  low_stock_items: 0,
  total_categories: 0,
  categories: []
};

const ACCENTS = ["#FF6B6B", "#FFA94D", "#4ECDC4", "#45B7D1", "#96CEB4"];

export default function App() {
  const [stats, setStats] = useState(DEFAULT_STATS);
  const [agents, setAgents] = useState([]);
  const [activeAgent, setActiveAgent] = useState("stockout_sentinel");
  const [risks, setRisks] = useState([]);
  const [inventoryItems, setInventoryItems] = useState([]);
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(false);
  const [sessionId] = useState(crypto.randomUUID());

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
      if (agentData.length > 0) {
        setActiveAgent(agentData[0].id);
      }
    } catch (error) {
      setAgents([]);
      setStats(DEFAULT_STATS);
    }
  };

  const loadRisks = async () => {
    try {
      const riskList = await fetchRisks(100);
      setRisks(riskList);
    } catch (error) {
      console.error("加载风险数据失败:", error);
      setRisks([]);
    }
  };

  const loadInventory = async () => {
    try {
      const items = await fetchInventory("all", 100);
      setInventoryItems(items);
    } catch (error) {
      console.error("加载库存数据失败:", error);
      setInventoryItems([]);
    }
  };

  useEffect(() => {
    loadData();
    loadRisks();
    loadInventory();
  }, []);

  const handleSend = async (text, options = {}) => {
    const targetAgent = options.agentId || activeAgent;
    if (targetAgent !== activeAgent) {
      setActiveAgent(targetAgent);
    }
    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setLoading(true);
    try {
      const response = await invokeAgent({
        agent: targetAgent,
        input: text,
        session_id: sessionId,
        parameters: options.parameters
      });
      const reply = response?.response?.text || "没有返回内容";
      setMessages((prev) => [...prev, { role: "assistant", content: reply }]);
      if (targetAgent === "stockout_sentinel") {
        const riskList = response?.response?.structured_output?.risks || [];
        if (riskList.length) setRisks(riskList);
      }
    } catch (error) {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: "请求失败，请检查接口连通性。" }
      ]);
    } finally {
      setLoading(false);
    }
  };

  const handleQuickAction = (agentId, text) => {
    handleSend(text, { agentId });
  };

  return (
    <div className="app">
      <header className="hero">
        <div>
          <p className="hero-eyebrow">跨境库存智能指挥舱</p>
          <h1>全球库存态势与运营决策</h1>
          <p className="hero-sub">
            实时掌控缺货风险、补货策略与价格健康度。
          </p>
        </div>
        <div className="hero-meta">
          <div>
            <span>会话</span>
            <strong>{sessionId.slice(0, 8)}</strong>
          </div>
          <div>
            <span>状态</span>
            <strong>运行中</strong>
          </div>
        </div>
      </header>

      <section className="stats-grid">
        {statCards.map((card) => (
          <StatCard key={card.label} {...card} />
        ))}
      </section>

      <section className="main-grid">
        <RiskTable risks={risks} />
        <ChatPanel
          agents={agents}
          activeAgent={activeAgent}
          onAgentChange={setActiveAgent}
          messages={messages}
          onSend={handleSend}
          onQuickAction={handleQuickAction}
          loading={loading}
        />
      </section>

      <section className="insights">
        <div className="panel">
          <div className="panel-header">
            <h3>类目概览</h3>
            <span className="panel-sub">当前活跃类目</span>
          </div>
          <div className="chips">
            {stats.categories.map((category) => (
              <span key={category} className="chip">{category}</span>
            ))}
          </div>
        </div>
        <div className="panel highlight">
          <div className="panel-header">
            <h3>今日行动建议</h3>
            <span className="panel-sub">快速决策提示</span>
          </div>
          <ul className="action-list">
            <li>48 小时内加急高风险供应商订单。</li>
            <li>为 90 天以上库存启动清仓策略。</li>
            <li>复核高销量电子品类的补货点设置。</li>
          </ul>
        </div>
      </section>

      <section className="main-grid full">
        <InventoryTable items={inventoryItems} categories={stats.categories} />
      </section>
    </div>
  );
}

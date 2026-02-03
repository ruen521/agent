import { useState, useMemo } from "react";
import { PieChart, Pie, Cell, ResponsiveContainer, Legend, Tooltip, BarChart, Bar, XAxis, YAxis, CartesianGrid } from "recharts";

export default function RiskTable({ risks }) {
  const [currentPage, setCurrentPage] = useState(1);
  const [viewMode, setViewMode] = useState("chart"); // "chart" or "table"
  const itemsPerPage = 10;

  const urgencyMap = {
    critical: "紧急",
    high: "高",
    medium: "中",
    low: "低"
  };

  const urgencyColors = {
    critical: "#FF6B6B",
    high: "#FFA94D",
    medium: "#4ECDC4",
    low: "#96CEB4"
  };

  // 统计各紧急度数量
  const urgencyStats = useMemo(() => {
    const stats = { critical: 0, high: 0, medium: 0, low: 0 };
    risks.forEach(risk => {
      const urgency = risk.urgency.toLowerCase();
      if (stats[urgency] !== undefined) {
        stats[urgency]++;
      }
    });
    return Object.entries(stats)
      .filter(([_, count]) => count > 0)
      .map(([urgency, count]) => ({
        name: urgencyMap[urgency],
        value: count,
        color: urgencyColors[urgency]
      }));
  }, [risks]);

  // 收入风险排行（前10）
  const topRevenueRisks = useMemo(() => {
    return [...risks]
      .sort((a, b) => b.revenue_at_risk - a.revenue_at_risk)
      .slice(0, 10)
      .map(risk => ({
        sku: risk.sku.length > 12 ? risk.sku.substring(0, 12) + "..." : risk.sku,
        revenue: risk.revenue_at_risk,
        urgency: urgencyMap[risk.urgency.toLowerCase()]
      }));
  }, [risks]);

  // 分页逻辑
  const totalPages = Math.ceil(risks.length / itemsPerPage);
  const paginatedRisks = useMemo(() => {
    const start = (currentPage - 1) * itemsPerPage;
    return risks.slice(start, start + itemsPerPage);
  }, [risks, currentPage]);

  const handlePageChange = (page) => {
    setCurrentPage(Math.max(1, Math.min(page, totalPages)));
  };

  return (
    <div className="panel risk-panel">
      <div className="panel-header">
        <div>
          <h3>缺货风险雷达</h3>
          <span className="panel-sub">共 {risks.length} 个风险 SKU</span>
        </div>
        <div className="view-toggle">
          <button
            className={viewMode === "chart" ? "active" : "ghost"}
            onClick={() => setViewMode("chart")}
          >
            图表视图
          </button>
          <button
            className={viewMode === "table" ? "active" : "ghost"}
            onClick={() => setViewMode("table")}
          >
            列表视图
          </button>
        </div>
      </div>

      {risks.length === 0 ? (
        <div className="table-empty">暂无风险数据</div>
      ) : (
        <>
          {viewMode === "chart" ? (
            <div className="charts-container">
              <div className="chart-box">
                <h4 className="chart-title">风险等级分布</h4>
                <ResponsiveContainer width="100%" height={240}>
                  <PieChart>
                    <Pie
                      data={urgencyStats}
                      cx="50%"
                      cy="50%"
                      labelLine={false}
                      label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}
                      outerRadius={80}
                      fill="#8884d8"
                      dataKey="value"
                    >
                      {urgencyStats.map((entry, index) => (
                        <Cell key={`cell-${index}`} fill={entry.color} />
                      ))}
                    </Pie>
                    <Tooltip
                      contentStyle={{
                        background: 'rgba(17, 20, 27, 0.95)',
                        border: '1px solid rgba(78, 205, 196, 0.3)',
                        borderRadius: '8px',
                        color: '#f4f2f0'
                      }}
                    />
                  </PieChart>
                </ResponsiveContainer>
              </div>

              <div className="chart-box">
                <h4 className="chart-title">收入风险 TOP 10</h4>
                <ResponsiveContainer width="100%" height={240}>
                  <BarChart data={topRevenueRisks} margin={{ top: 5, right: 10, left: 10, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.1)" />
                    <XAxis
                      dataKey="sku"
                      tick={{ fill: '#f4f2f0', fontSize: 11 }}
                      angle={-45}
                      textAnchor="end"
                      height={60}
                    />
                    <YAxis tick={{ fill: '#f4f2f0', fontSize: 11 }} />
                    <Tooltip
                      contentStyle={{
                        background: 'rgba(17, 20, 27, 0.95)',
                        border: '1px solid rgba(78, 205, 196, 0.3)',
                        borderRadius: '8px',
                        color: '#f4f2f0'
                      }}
                      formatter={(value) => `$${value.toLocaleString()}`}
                    />
                    <Bar dataKey="revenue" fill="#4ECDC4" radius={[8, 8, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          ) : (
            <>
              <div className="table">
                <div className="table-row table-head">
                  <span>SKU</span>
                  <span>剩余天数</span>
                  <span>缺口</span>
                  <span>风险收入</span>
                  <span>紧急度</span>
                </div>
                {paginatedRisks.map((risk) => (
                  <div className="table-row" key={risk.sku}>
                    <span>{risk.sku}</span>
                    <span>{risk.days} 天</span>
                    <span>{risk.shortage}</span>
                    <span>${risk.revenue_at_risk.toLocaleString()}</span>
                    <span className={`pill ${risk.urgency.toLowerCase()}`}>
                      {urgencyMap[risk.urgency.toLowerCase()] || risk.urgency}
                    </span>
                  </div>
                ))}
              </div>

              {totalPages > 1 && (
                <div className="pagination">
                  <button
                    onClick={() => handlePageChange(currentPage - 1)}
                    disabled={currentPage === 1}
                    className="ghost"
                  >
                    上一页
                  </button>
                  <span className="page-info">
                    第 {currentPage} / {totalPages} 页
                  </span>
                  <button
                    onClick={() => handlePageChange(currentPage + 1)}
                    disabled={currentPage === totalPages}
                    className="ghost"
                  >
                    下一页
                  </button>
                </div>
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}

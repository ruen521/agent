import { useMemo, useState } from "react";

export default function InventoryTable({ items, categories }) {
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("全部");
  const [vendor, setVendor] = useState("全部");
  const [urgency, setUrgency] = useState("全部");
  const [lowStockOnly, setLowStockOnly] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  const vendorOptions = useMemo(() => {
    const ids = new Map();
    items.forEach((item) => {
      if (item.VendorID) ids.set(item.VendorID, item.vendor_name || "");
    });
    return Array.from(ids.entries());
  }, [items]);

  const filtered = useMemo(() => {
    const keyword = search.trim().toLowerCase();
    return items.filter((item) => {
      const matchSearch = keyword
        ? `${item.SKU} ${item.Name} ${item.Category}`.toLowerCase().includes(keyword)
        : true;
      const matchCategory = category === "全部" ? true : item.Category === category;
      const matchVendor = vendor === "全部" ? true : item.VendorID === vendor;
      const matchUrgency = urgency === "全部" ? true : item.urgency_level === urgency;
      const matchLowStock = lowStockOnly
        ? item.CurrentStock <= item.ReorderPoint
        : true;
      return matchSearch && matchCategory && matchVendor && matchUrgency && matchLowStock;
    });
  }, [items, search, category, vendor, urgency, lowStockOnly]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const currentPage = Math.min(page, totalPages);
  const pageItems = filtered.slice(
    (currentPage - 1) * pageSize,
    currentPage * pageSize
  );

  const urgencyLabel = {
    CRITICAL: "紧急",
    HIGH: "高",
    MEDIUM: "中",
    LOW: "低"
  };

  const handlePageSizeChange = (event) => {
    setPageSize(Number(event.target.value));
    setPage(1);
  };

  const resetPage = () => setPage(1);

  return (
    <div className="panel">
      <div className="panel-header">
        <h3>库存明细</h3>
        <span className="panel-sub">展示核心字段 + 风险与供应信息</span>
      </div>
      <div className="table-toolbar">
        <div className="filter-group">
          <label>
            搜索
            <input
              value={search}
              onChange={(event) => {
                setSearch(event.target.value);
                resetPage();
              }}
              placeholder="SKU / 名称 / 类目"
            />
          </label>
          <label>
            类目
            <select
              value={category}
              onChange={(event) => {
                setCategory(event.target.value);
                resetPage();
              }}
            >
              <option value="全部">全部</option>
              {categories.map((cat) => (
                <option key={cat} value={cat}>{cat}</option>
              ))}
            </select>
          </label>
          <label>
            供应商
            <select
              value={vendor}
              onChange={(event) => {
                setVendor(event.target.value);
                resetPage();
              }}
            >
              <option value="全部">全部</option>
              {vendorOptions.map(([id, name]) => (
                <option key={id} value={id}>{`${id}${name ? ` · ${name}` : ""}`}</option>
              ))}
            </select>
          </label>
          <label>
            紧急度
            <select
              value={urgency}
              onChange={(event) => {
                setUrgency(event.target.value);
                resetPage();
              }}
            >
              <option value="全部">全部</option>
              <option value="CRITICAL">紧急</option>
              <option value="HIGH">高</option>
              <option value="MEDIUM">中</option>
              <option value="LOW">低</option>
            </select>
          </label>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={lowStockOnly}
              onChange={(event) => {
                setLowStockOnly(event.target.checked);
                resetPage();
              }}
            />
            仅低库存
          </label>
        </div>
        <div className="pagination">
          <span>共 {filtered.length} 条</span>
          <label>
            每页
            <select value={pageSize} onChange={handlePageSizeChange}>
              <option value={20}>20</option>
              <option value={50}>50</option>
              <option value={100}>100</option>
            </select>
          </label>
          <button
            className="ghost"
            onClick={() => setPage(Math.max(1, currentPage - 1))}
            disabled={currentPage === 1}
          >
            上一页
          </button>
          <span>
            {currentPage} / {totalPages}
          </span>
          <button
            className="ghost"
            onClick={() => setPage(Math.min(totalPages, currentPage + 1))}
            disabled={currentPage === totalPages}
          >
            下一页
          </button>
        </div>
      </div>
      <div className="table table-wide">
        <div className="table-row table-head">
          <span>SKU</span>
          <span>名称</span>
          <span>类目</span>
          <span>库存</span>
          <span>补货点</span>
          <span>日销量</span>
          <span>成本</span>
          <span>供应商</span>
          <span>供应商名</span>
          <span>交期</span>
          <span>缺货天数</span>
          <span>紧急度</span>
          <span>缺口</span>
          <span>风险收入</span>
          <span>更新日期</span>
        </div>
        {pageItems.length === 0 ? (
          <div className="table-empty">暂无数据。</div>
        ) : (
          pageItems.map((item) => (
            <div className="table-row" key={item.SKU}>
              <span>{item.SKU}</span>
              <span>{item.Name}</span>
              <span>{item.Category}</span>
              <span>{item.CurrentStock}</span>
              <span>{item.ReorderPoint}</span>
              <span>{item.DailySalesVelocity}</span>
              <span>${item.UnitCost}</span>
              <span>{item.VendorID}</span>
              <span>{item.vendor_name || ""}</span>
              <span>{item.LeadTimeDays}</span>
              <span>{item.days_until_stockout ?? ""}</span>
              <span className={`pill ${String(item.urgency_level || "").toLowerCase()}`}>
                {urgencyLabel[item.urgency_level] || item.urgency_level || ""}
              </span>
              <span>{item.shortage_amount ?? ""}</span>
              <span>{item.revenue_at_risk ? `$${item.revenue_at_risk}` : ""}</span>
              <span>{item.LastUpdated || ""}</span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

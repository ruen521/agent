import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

const EXPORT_STATUS_LABEL = {
  PENDING: "生成中",
  RUNNING: "生成中",
  DONE: "已完成",
  FAILED: "下载失败",
  EXPIRED: "已过期"
};

export default function ResultModal({
  open,
  selectedMessage,
  agentName,
  activeTab,
  onTabChange,
  onClose,
  audience,
  onAudienceChange,
  canExportCurrent,
  onExportAnalysis,
  onDownloadExport,
  exportState,
  renderSteps,
  renderTrace,
  renderStructured,
}) {
  if (!open || !selectedMessage) return null;

  return (
    <div className="result-modal-backdrop" onClick={onClose}>
      <section className="result-modal" onClick={(event) => event.stopPropagation()}>
        <div className="workbench-header">
          <strong>当前结果：{agentName || "智能体"}</strong>
          <div className="export-inline">
            {canExportCurrent ? (
              <>
                <select value={audience} onChange={(event) => onAudienceChange(event.target.value)}>
                  <option value="external">外部版</option>
                  <option value="internal">内部版</option>
                </select>
                <button className="ghost" onClick={() => onExportAnalysis(selectedMessage.id, "pdf", audience)}>
                  导出PDF
                </button>
                <button className="ghost" onClick={() => onExportAnalysis(selectedMessage.id, "xlsx", audience)}>
                  导出Excel
                </button>
                {exportState?.status === "DONE" ? (
                  <button className="ghost" onClick={() => onDownloadExport(selectedMessage.id)}>
                    下载
                  </button>
                ) : null}
                {exportState?.status ? (
                  <span className={`status-pill ${String(exportState.status).toLowerCase()}`}>
                    {EXPORT_STATUS_LABEL[exportState.status] || exportState.status}{" "}
                    {typeof exportState.progress === "number" ? `${exportState.progress}%` : ""}
                  </span>
                ) : null}
              </>
            ) : (
              <span className="muted">当前消息为闲聊或无结构化输出，不支持导出。</span>
            )}
            <button className="ghost" onClick={onClose}>
              关闭
            </button>
          </div>
          {exportState?.error_message ? (
            <span className="export-error">{exportState.error_message}</span>
          ) : null}
        </div>

        <div className="tab-bar">
          <button className={activeTab === "answer" ? "active" : "ghost"} onClick={() => onTabChange("answer")}>
            自然回答
          </button>
          <button className={activeTab === "steps" ? "active" : "ghost"} onClick={() => onTabChange("steps")}>
            执行步骤
          </button>
          <button className={activeTab === "trace" ? "active" : "ghost"} onClick={() => onTabChange("trace")}>
            执行过程
          </button>
          <button className={activeTab === "structured" ? "active" : "ghost"} onClick={() => onTabChange("structured")}>
            结构化结果
          </button>
        </div>

        <div className="tab-panel">
          {activeTab === "answer" ? (
            <div className="markdown-content">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {selectedMessage.meta?.response_text || selectedMessage.content || "暂无自然回答"}
              </ReactMarkdown>
            </div>
          ) : null}
          {activeTab === "steps" ? renderSteps : null}
          {activeTab === "trace" ? renderTrace : null}
          {activeTab === "structured" ? renderStructured : null}
        </div>
      </section>
    </div>
  );
}

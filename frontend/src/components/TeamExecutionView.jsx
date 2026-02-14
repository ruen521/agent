const COPILOT_STATUS_LABEL = {
  completed: "已完成",
  max_steps_reached: "达到最大执行步数",
  team_v1_completed: "协同完成",
  team_v1_partial: "部分完成",
  team_v1_failed: "执行失败"
};

const TEAM_MEMBER_LABEL = {
  stockout_sentinel: "缺货哨兵",
  replenishment_planner: "补货规划",
  exception_investigator: "异常侦测",
  markdown_clearance_coach: "清仓教练"
};

const TEAM_RESULT_STATUS_LABEL = {
  success: "成功",
  partial_success: "部分成功",
  failed: "失败",
  timeout: "超时"
};

export const teamMemberLabel = (memberId) => TEAM_MEMBER_LABEL[memberId] || memberId || "-";

export const teamResultStatusLabel = (status) => TEAM_RESULT_STATUS_LABEL[status] || status || "-";

export default function TeamExecutionView({ structured }) {
  const teamPlan = Array.isArray(structured?.team_plan) ? structured.team_plan : [];
  const execution = Array.isArray(structured?.team_execution) ? structured.team_execution : [];
  const summary = structured?.team_summary || {};
  const audit = structured?.audit || {};

  if (!teamPlan.length && !execution.length) {
    return <div className="muted">暂无协同执行数据。</div>;
  }

  return (
    <div className="team-view">
      <div className="team-kpis">
        <div className="team-kpi">
          <span>执行状态</span>
          <strong>{COPILOT_STATUS_LABEL[structured?.status] || structured?.status || "未知"}</strong>
        </div>
        <div className="team-kpi">
          <span>成功成员</span>
          <strong>{summary.success_count ?? 0}</strong>
        </div>
        <div className="team-kpi">
          <span>部分成功成员</span>
          <strong>{summary.partial_success_count ?? 0}</strong>
        </div>
        <div className="team-kpi">
          <span>失败成员</span>
          <strong>{summary.failure_count ?? 0}</strong>
        </div>
        <div className="team-kpi">
          <span>总耗时</span>
          <strong>{Number(audit.latency_ms || 0).toFixed(0)} ms</strong>
        </div>
      </div>
      <div className="team-audit">
        <span>Run ID：{audit.run_id || "-"}</span>
        <span>重试次数：{audit.retry_count ?? 0}</span>
        <span>已执行成员：{audit.executed_count ?? execution.length}</span>
      </div>
      <div>
        <h5>成员执行顺序</h5>
        <ol className="plain-list">
          {teamPlan.map((member) => (
            <li key={member}>{teamMemberLabel(member)}</li>
          ))}
        </ol>
      </div>
      <div className="meta-table-wrap">
        <table className="meta-table">
          <thead>
            <tr>
              <th>成员</th>
              <th>结果</th>
              <th>耗时(ms)</th>
              <th>尝试次数</th>
              <th>重试次数</th>
              <th>错误码</th>
            </tr>
          </thead>
          <tbody>
            {execution.map((item, index) => (
              <tr key={`${item.member_id || "member"}-${index}`}>
                <td>{teamMemberLabel(item.member_id)}</td>
                <td>{teamResultStatusLabel(item.result_status)}</td>
                <td>{Number(item.latency_ms || 0).toFixed(2)}</td>
                <td>{item.attempts ?? 0}</td>
                <td>{item.retry_count ?? 0}</td>
                <td>{item.error_code || "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

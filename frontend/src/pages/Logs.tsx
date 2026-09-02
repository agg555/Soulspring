import { useEffect, useState } from "react";
import { api } from "../api";
import type { UsageRow } from "../types";

export default function LogsPage() {
  const [logs, setLogs] = useState<UsageRow[] | null>(null);
  const [error, setError] = useState("");

  const load = () => {
    api.usageLogs(100).then((r) => setLogs(r.logs)).catch((e) => setError(String(e.message || e)));
  };
  useEffect(load, []);

  return (
    <div>
      <h2>日志(F14 雏形)</h2>
      <p className="muted">
        AiUsageLog 回查;AgentRun 明细走接口 /api/usage/runs(四件套查看器第 6 周补全)。
        <button className="link" onClick={load}>刷新</button>
      </p>
      {error && <p className="error">{error}</p>}
      {logs && logs.length === 0 && <p className="muted">还没有调用记录。</p>}
      {logs && logs.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>时间(UTC)</th>
              <th>action</th>
              <th>模型</th>
              <th>入 tok</th>
              <th>出 tok</th>
              <th>成本 ¥</th>
              <th>耗时 ms</th>
            </tr>
          </thead>
          <tbody>
            {logs.map((r) => (
              <tr key={r.id}>
                <td>{r.created_at.replace("T", " ").slice(0, 19)}</td>
                <td>{r.action}</td>
                <td>{r.model}</td>
                <td>{r.request_tokens}</td>
                <td>{r.response_tokens}</td>
                <td>{r.cost_total.toFixed(6)}</td>
                <td>{r.duration_ms}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

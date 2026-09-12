import { api } from "../../api";
import type { Settings } from "../../types";

/**
 * 设置页·运维区(大文件拆分批 2026-09-10 自 pages/Settings.tsx 抽出;纯 JSX 搬动零行为变化):
 * 手动快照/推送备份 + MCP 服务器配置表与 JSON 导入。
 * backupBusy 的三态(空/snap/push)与 mcpJson/mcpError 仍在 Settings 里,本件只画与转发。
 */
export default function SettingsMaintenance({
  s, backupBusy, setBackupBusy, flash, setError,
  mcpJson, setMcpJson, mcpError, toggleServer, removeServer, importMcp,
}: {
  s: Settings;
  backupBusy: "" | "snap" | "push";
  setBackupBusy: (v: "" | "snap" | "push") => void;
  flash: (text: string) => void;
  setError: (msg: string) => void;
  mcpJson: string;
  setMcpJson: (v: string) => void;
  mcpError: string;
  toggleServer: (index: number, enabled: boolean) => void;
  removeServer: (index: number) => void;
  importMcp: () => void;
}) {
  return (
    <>
      <details className="set-sec">
        <summary>💾 备份</summary>
      <p className="muted">
        服务每天自动快照数据库到 data\backups\(保留 14 份);下面两个按钮是手动兜底。
      </p>
      <div className="row">
        <button disabled={backupBusy !== ""}
          onClick={async () => {
            setBackupBusy("snap");
            try {
              const r = await api.backupNow();
              flash(`快照完成:${r.file}`);
            } catch (e) { setError(String((e as Error).message || e)); }
            finally { setBackupBusy(""); }
          }}>{backupBusy === "snap" ? "⏳ 快照中…" : "立即快照"}</button>
        <button disabled={backupBusy !== ""}
          onClick={async () => {
            setBackupBusy("push");
            try {
              const r = await api.pushBackup();
              if (r.ok) flash("已推送到备份仓 beifen");
              else setError(`推送失败(${r.code}):${r.output}`);
            } catch (e) { setError(String((e as Error).message || e)); }
            finally { setBackupBusy(""); }
          }}>{backupBusy === "push" ? "⏳ 推送中…" : "推送到备份仓"}</button>
      </div>

      </details>
      <details className="set-sec">
        <summary>MCP 服务器（暂未启用）</summary>
      <p className="muted">
        只做配置存取与展示;启用开关也仅是配置位——实际连接要等 M5 SDK 白名单制查证基座接通。
        命令行型(stdio)最终仍受任务书 §3 命令白名单约束。
      </p>
      <table className="table">
        <thead>
          <tr>
            <th>名称</th>
            <th>传输</th>
            <th>目标(URL / 命令)</th>
            <th>启用</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {s.mcp.servers.map((srv, i) => (
            <tr key={srv.name}>
              <td><code>{srv.name}</code></td>
              <td>{srv.transport ?? "stdio"}</td>
              <td className="muted small">
                {srv.url ?? [srv.command, ...(srv.args ?? [])].join(" ")}
              </td>
              <td>
                <input
                  type="checkbox"
                  checked={srv.enabled}
                  onChange={(e) => toggleServer(i, e.target.checked)}
                />
              </td>
              <td><button className="link" onClick={() => removeServer(i)}>删</button></td>
            </tr>
          ))}
          {s.mcp.servers.length === 0 && (
            <tr><td colSpan={5} className="muted">暂无服务端,用下方 JSON 导入。</td></tr>
          )}
        </tbody>
      </table>

      <h4>导入 mcpServers JSON</h4>
      <p className="muted">
        兼容通用格式:{"{"}"mcpServers": {"{"} 名称: {"{"}command, args, env{"}"} 或 {"{"}url, headers{"}"} {"}"}{"}"}。
        敏感字段(key / token / authorization / api_key)会自动剥离进本地 secrets 文件,不入库不入 git;
        导入的服务端默认为「停用」。非法 JSON 会在上方报错,不会半写。
      </p>
      <textarea
        rows={6}
        value={mcpJson}
        onChange={(e) => setMcpJson(e.target.value)}
        placeholder={'{\n  "mcpServers": {\n    "fetch": { "command": "mcp-server-fetch", "args": [] },\n    "docs": { "url": "http://127.0.0.1:8722/mcp", "headers": { "Authorization": "Bearer sk-…" } }\n  }\n}'}
      />
      {mcpError && <p className="error">{mcpError}</p>}
      <div className="row">
        <button onClick={importMcp} disabled={!mcpJson.trim()}>解析并导入</button>
      </div>

      {/* 批次七⑨:关于页与更新日志(P0-P3 抛光件) */}
      </details>
    </>
  );
}

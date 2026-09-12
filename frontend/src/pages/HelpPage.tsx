/**
 * 帮助页(二期④):快速上手 / FAQ / BYOK 充值教程——发行前小件,软件内可达。
 * 全静态,零依赖;内容口径与 README/设置页一致。
 */
export default function HelpPage() {
  return (
    <div className="help-page">
      <h2>帮助</h2>

      <h3>🚀 快速上手(五步写出第一章)</h3>
      <ol className="help-ol">
        <li><b>建书</b>:总览 →「+ 新建书」走向导,填书名/类型/主角等(能填多少填多少,后面可改)。</li>
        <li><b>配 AI</b>:设置 → 服务商卡一键切换(GLM/DeepSeek/千问),填一次 API Key,点「检测连接」确认连通。</li>
        <li><b>搭大纲</b>:书工作区左栏「大纲树」→ +总纲 → +卷 → +章;或在中栏对话台点「帮铺大纲」让 AI 出建议,逐条采纳。</li>
        <li><b>写章</b>:左栏点章标题进详情 →「去工作台」→ 生成草稿(AI 写)→ 人改 → 保存 → 通过送终审。写前可开「📌 本章卡」记本章人物/事件。</li>
        <li><b>定稿</b>:终审对话台确认后定稿;状态随时可回退(定稿也能解封改)。</li>
      </ol>

      <h3>🔑 BYOK 教程(自带 Key,成本透明)</h3>
      <p className="muted small">
        原理:软件不收 AI 差价、不经手你的 key;你去厂商官网注册充值,把 key 填进设置页即可,
        生成成本按厂商牌价直接扣你的账户(设置页可看每章成本)。
      </p>
      <ul className="help-ul">
        <li><b>智谱 GLM</b>:open.bigmodel.cn → 注册 → API Keys 页创建 → 充值(有免费额度的 flash 档)。
          回设置页:点 GLM 卡 → 粘贴 key → 检测连接。</li>
        <li><b>DeepSeek</b>:platform.deepseek.com → 注册充值 → 创建 key。回设置页点 DeepSeek 卡粘贴。</li>
        <li><b>通义千问</b>:阿里云百炼开通 → 建 key(dashscope 兼容模式已内置)。</li>
        <li>key 只存本机 <code>data/secrets.local.json</code>(git 忽略),绝不入库不上传;
          多家 key 可同时存档,切换不丢。</li>
      </ul>

      <h3>❓ FAQ</h3>
      <dl className="help-dl">
        <dt>数据存在哪?会丢吗?</dt>
        <dd>本机 SQLite(<code>data/soulspring.db</code>)正文另有 md 镜像;仓库 git 跟踪即备份。
          软件不经手你的任何云。</dd>
        <dt>写一章大概多少钱?</dt>
        <dd>取决于模型与上下文。实测参考:qwen3.8-flash 约 ¥0.013/章(计划卡+草稿);
          免费档模型可零成本。总览页有每日成本与调用数。</dd>
        <dt>生成卡住了/失败了?</dt>
        <dd>生成是后台任务,切页签不打断;失败在任务卡可见原因。限流会自动退避,
          连续失败先「检测连接」。</dd>
        <dt>原生弹窗怎么没了?</dt>
        <dd>确认/输入统一走页面内的行内确认条(吸顶),内嵌浏览器与普通浏览器都好用。</dd>
        <dt>想换写作风格?</dt>
        <dd>设置 → 温度预设:稳健(精修)/标准(默认)/灵感(发散),一键切换随时改。</dd>
        <dt>支持 Windows/macOS 吗?</dt>
        <dd>当前以 Windows 为主(macOS 需自行跑源码);打包发行在路线图中。</dd>
      </dl>

      <h3>🧭 更多</h3>
      <ul className="help-ul">
        <li>版本与更新日志:设置页底部「关于 Soulspring」。</li>
        <li>问题反馈:先把 <code>data/logs</code> 里最近的日志一并附上。</li>
      </ul>
    </div>
  );
}

import ChatPanel from "../components/ChatPanel";

/**
 * 测试对话(M1 连通性验证入口,A3 换装):
 * 换用统一 ChatPanel——多线会话留痕、发送任务化、逐条记账(action=chat_test)。
 */
export default function ChatTestPage() {
  return (
    <div>
      <h2>测试对话</h2>
      <p className="muted">
        连通性验证入口。换用统一对话组件:消息留痕、发送任务化(切页签不打断)、逐条记账。
      </p>
      <ChatPanel
        projectId={null}
        ownerType="chat_test"
        ownerId=""
        defaultSessionName="测试线"
        emptyHint="当前对话线还没有消息;若列表为空,先点上方「+新对话线」开一条,再发送消息验证连通性。"
      />
    </div>
  );
}

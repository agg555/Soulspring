import type { GenStage } from "./types";

// 生成任务阶段 → 文案(需求1);顶栏徽标与工作台进度共用
export const STAGE_LABELS: Record<GenStage, string> = {
  queued: "排队中",
  plan: "生成计划卡",
  draft: "撰写草稿",
  normalize: "字数规整",
  audit: "代码层审计",
  review: "AI 评审",
  repair: "AI 自修",
  done: "完成",
  error: "失败",
};

// 节点元信息：中文标签 + 所属步骤索引（对应底部 Agent 状态栏）

export const STEPS = ['解析', '求解', '验证', '讲解', '反馈'] as const

export interface NodeMeta {
  label: string
  step: number
}

export const NODE_META: Record<string, NodeMeta> = {
  detect_input: { label: '识别输入', step: 0 },
  ocr_node: { label: '识别图片', step: 0 },
  asr_node: { label: '识别语音', step: 0 },
  guardrail_agent: { label: '安全校验', step: 0 },
  parser_agent: { label: '解析题目', step: 0 },
  retrieve_ltm: { label: '检索记忆', step: 0 },
  intent_router: { label: '意图路由', step: 0 },
  solver_agent: { label: '求解问题', step: 1 },
  tool_node: { label: '调用工具', step: 1 },
  verifier_agent: { label: '验证答案', step: 2 },
  safety_agent: { label: '安全检查', step: 2 },
  explainer_agent: { label: '生成讲解', step: 3 },
  direct_response_node: { label: '生成回答', step: 3 },
  store_ltm: { label: '更新记忆', step: 3 },
  hitl_node: { label: '等待反馈', step: 4 },
}

export function nodeLabel(node: string): string {
  return NODE_META[node]?.label ?? node
}

export function nodeStep(node: string): number {
  return NODE_META[node]?.step ?? -1
}

export interface SessionInfo {
  student_id: string
  thread_id: string
}

export interface AuthInfo {
  student_id: string
  thread_id: string
  email: string
  display_name: string
}

export interface HitlPayload {
  hitl_type?: string
  prompt?: string
  message?: string
  [key: string]: unknown
}

export type MessageRole = 'user' | 'assistant'

export interface ChatMessage {
  id: string
  role: MessageRole
  content: string
  imageUrl?: string
  fileName?: string
  inputType?: 'image' | 'audio'
  status?: 'awaiting_human' | 'completed'
  hitl?: HitlPayload | null
  streaming?: boolean
  thinking?: ThinkingEntry[]
}

export interface ThinkingEntry {
  node: string
  summary: string
  fields: Record<string, string>
}

export interface ThinkingState {
  active: boolean
  entries: ThinkingEntry[]
  currentNode: string
}

export interface StreamEvent {
  type: 'thinking' | 'node' | 'done' | 'error'
  node?: string
  summary?: string
  fields?: Record<string, string>
  thread_id?: string
  status?: string
  answer?: string
  intent?: string
  topic?: string
  hitl?: HitlPayload | null
  activity?: ThinkingEntry[]
  message?: string
}

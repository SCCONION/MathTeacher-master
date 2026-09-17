import type { AuthInfo, SessionInfo, StreamEvent } from './types'

const BASE = '/api/v1'

export async function googleLogin(credential: string): Promise<AuthInfo> {
  const res = await fetch(`${BASE}/auth/google`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ credential }),
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`Google 登录失败 (${res.status}) ${text}`)
  }
  return res.json()
}

export async function createSession(
  email = 'student@demo.com',
  displayName = '学生',
): Promise<SessionInfo> {
  const res = await fetch(`${BASE}/sessions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, display_name: displayName }),
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`创建会话失败 (${res.status}) ${text}`)
  }
  return res.json()
}

async function* streamSSE(
  url: string,
  init: RequestInit,
): AsyncGenerator<StreamEvent> {
  const res = await fetch(url, init)
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`请求失败 (${res.status}) ${text}`)
  }
  if (!res.body) throw new Error('响应无内容')

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    let idx: number
    while ((idx = buffer.indexOf('\n\n')) !== -1) {
      const chunk = buffer.slice(0, idx)
      buffer = buffer.slice(idx + 2)
      for (const line of chunk.split('\n')) {
        if (line.startsWith('data: ')) {
          try {
            yield JSON.parse(line.slice(6)) as StreamEvent
          } catch {
            /* ignore malformed chunk */
          }
        }
      }
    }
  }
}

export function streamTextChat(
  session: SessionInfo,
  message: string,
): AsyncGenerator<StreamEvent> {
  return streamSSE(`${BASE}/chat/text/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      student_id: session.student_id,
      thread_id: session.thread_id,
      message,
    }),
  })
}

export function streamResumeChat(
  session: SessionInfo,
  response: Record<string, unknown>,
): AsyncGenerator<StreamEvent> {
  return streamSSE(`${BASE}/hitl/resume/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      student_id: session.student_id,
      thread_id: session.thread_id,
      response,
    }),
  })
}

export async function uploadFileChat(
  session: SessionInfo,
  file: File,
  inputType: 'image' | 'audio',
): Promise<{
  thread_id: string
  status: string
  answer?: string
  intent?: string
  topic?: string
  hitl?: unknown
  activity?: unknown[]
}> {
  const fd = new FormData()
  fd.append('student_id', session.student_id)
  fd.append('thread_id', session.thread_id)
  fd.append('input_type', inputType)
  fd.append('file', file)

  const res = await fetch(`${BASE}/chat/file`, { method: 'POST', body: fd })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`上传失败 (${res.status}) ${text}`)
  }
  return res.json()
}

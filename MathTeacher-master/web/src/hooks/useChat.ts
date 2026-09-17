import { useCallback, useRef, useState } from 'react'
import type {
  AuthInfo,
  ChatMessage,
  HitlPayload,
  SessionInfo,
  StreamEvent,
  ThinkingEntry,
  ThinkingState,
} from '../types'
import { nodeStep, STEPS } from '../meta'
import { createSession, googleLogin, streamResumeChat, streamTextChat, uploadFileChat } from '../api'

const uid = () =>
  typeof crypto !== 'undefined' && crypto.randomUUID
    ? crypto.randomUUID()
    : Math.random().toString(36).slice(2)

const AUTH_KEY = 'mathteacher.auth'

function loadAuth(): AuthInfo | null {
  try {
    const raw = localStorage.getItem(AUTH_KEY)
    return raw ? (JSON.parse(raw) as AuthInfo) : null
  } catch {
    return null
  }
}

export function useChat() {
  const [auth, setAuth] = useState<AuthInfo | null>(loadAuth)
  const [authLoading, setAuthLoading] = useState(false)
  const [session, setSession] = useState<SessionInfo | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [thinking, setThinking] = useState<ThinkingState>({
    active: false,
    entries: [],
    currentNode: '',
  })
  const [agentStep, setAgentStep] = useState(-1)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const sessionRef = useRef<SessionInfo | null>(
    auth ? { student_id: auth.student_id, thread_id: auth.thread_id } : null,
  )

  const loginWithGoogle = useCallback(async (credential: string) => {
    setAuthLoading(true)
    setError(null)
    try {
      const info = await googleLogin(credential)
      setAuth(info)
      try {
        localStorage.setItem(AUTH_KEY, JSON.stringify(info))
      } catch {
        /* ignore */
      }
      const s: SessionInfo = {
        student_id: info.student_id,
        thread_id: info.thread_id,
      }
      sessionRef.current = s
      setSession(s)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setAuthLoading(false)
    }
  }, [])

  const logout = useCallback(() => {
    setAuth(null)
    try {
      localStorage.removeItem(AUTH_KEY)
    } catch {
      /* ignore */
    }
    sessionRef.current = null
    setSession(null)
    setMessages([])
    setThinking({ active: false, entries: [], currentNode: '' })
    setAgentStep(-1)
    setError(null)
  }, [])

  const ensureSession = useCallback(async (): Promise<SessionInfo> => {
    if (sessionRef.current) return sessionRef.current
    const s = await createSession()
    sessionRef.current = s
    setSession(s)
    return s
  }, [])

  const startThinking = useCallback(() => {
    setThinking({ active: true, entries: [], currentNode: '' })
  }, [])

  const stopThinking = useCallback(() => {
    setThinking((t) => ({ ...t, active: false }))
  }, [])

  // 消费 SSE 流：把思考事件累积，最终落地为一条 assistant 消息
  const consumeStream = useCallback(
    async (stream: AsyncGenerator<StreamEvent>) => {
      const assistantId = uid()
      setMessages((p) => [
        ...p,
        { id: assistantId, role: 'assistant', content: '', streaming: true },
      ])

      const entries: ThinkingEntry[] = []
      let answer = ''
      let status = 'completed'
      let hitl: HitlPayload | null = null

      const patch = (partial: Partial<ChatMessage>) =>
        setMessages((msgs) =>
          msgs.map((m) => (m.id === assistantId ? { ...m, ...partial } : m)),
        )

      for await (const ev of stream) {
        if (ev.type === 'thinking') {
          const entry: ThinkingEntry = {
            node: ev.node ?? '',
            summary: ev.summary ?? '',
            fields: ev.fields ?? {},
          }
          entries.push(entry)
          setThinking({
            active: true,
            currentNode: entry.node,
            entries: entries.slice(),
          })
          const s = nodeStep(entry.node)
          if (s >= 0) setAgentStep((prev) => Math.max(prev, s))
        } else if (ev.type === 'node') {
          setThinking((t) => ({ ...t, active: true, currentNode: ev.node ?? '' }))
          const s = nodeStep(ev.node ?? '')
          if (s >= 0) setAgentStep((prev) => Math.max(prev, s))
        } else if (ev.type === 'done') {
          answer = ev.answer ?? ''
          status = ev.status ?? 'completed'
          hitl = ev.hitl ?? null
          // 图完全结束 → 所有步骤标记完成；等待人工反馈 → 停在反馈步骤
          if (status === 'completed') setAgentStep(STEPS.length)
          else if (status === 'awaiting_human') setAgentStep(STEPS.length - 1)
        } else if (ev.type === 'error') {
          setError(ev.message ?? '未知错误')
        }
      }

      if (hitl && !answer) {
        const hint = (hitl.prompt || hitl.message || '').trim()
        if (hint) answer = `> 🤔 ${hint}`
      }

      patch({
        content: answer || '（未获得回复）',
        streaming: false,
        status: status as ChatMessage['status'],
        hitl,
        thinking: entries,
      })
    },
    [],
  )

  const sendText = useCallback(
    async (text: string) => {
      const trimmed = text.trim()
      if (!trimmed || sending) return
      setError(null)
      setSending(true)
      startThinking()
      try {
        const s = await ensureSession()
        setMessages((p) => [
          ...p,
          { id: uid(), role: 'user', content: trimmed },
        ])
        await consumeStream(streamTextChat(s, trimmed))
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
      } finally {
        setSending(false)
        stopThinking()
      }
    },
    [sending, ensureSession, startThinking, stopThinking, consumeStream],
  )

  const resume = useCallback(
    async (response: Record<string, unknown>, displayText: string) => {
      if (sending) return
      setError(null)
      setSending(true)
      startThinking()
      try {
        const s = await ensureSession()
        setMessages((p) => [
          ...p,
          { id: uid(), role: 'user', content: displayText },
        ])
        await consumeStream(streamResumeChat(s, response))
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
      } finally {
        setSending(false)
        stopThinking()
      }
    },
    [sending, ensureSession, startThinking, stopThinking, consumeStream],
  )

  const sendFile = useCallback(
    async (file: File, inputType: 'image' | 'audio') => {
      if (sending) return
      setError(null)
      setSending(true)
      startThinking()
      try {
        const s = await ensureSession()
        const imageUrl =
          inputType === 'image' ? URL.createObjectURL(file) : undefined
        setMessages((p) => [
          ...p,
          {
            id: uid(),
            role: 'user',
            content:
              inputType === 'image' ? '上传了一张图片，请帮我解答' : '发送了一段语音，请帮我解答',
            imageUrl,
            fileName: file.name,
            inputType,
          },
        ])
        const res = await uploadFileChat(s, file, inputType)
        const answer = res.answer ?? ''
        const hitl = (res.hitl as HitlPayload) ?? null
        const content =
          answer || (hitl?.prompt ? `> 🤔 ${hitl.prompt}` : '（未获得回复）')
        setMessages((p) => [
          ...p,
          {
            id: uid(),
            role: 'assistant',
            content,
            status: res.status as ChatMessage['status'],
            hitl,
          },
        ])
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
      } finally {
        setSending(false)
        stopThinking()
      }
    },
    [sending, ensureSession, startThinking, stopThinking],
  )

  const newChat = useCallback(() => {
    setMessages([])
    setThinking({ active: false, entries: [], currentNode: '' })
    setAgentStep(-1)
    setError(null)
  }, [])

  return {
    auth,
    authLoading,
    loginWithGoogle,
    logout,
    session,
    messages,
    thinking,
    agentStep,
    sending,
    error,
    sendText,
    sendFile,
    resume,
    newChat,
  }
}

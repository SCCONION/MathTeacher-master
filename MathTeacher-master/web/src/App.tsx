import { useEffect, useRef } from 'react'
import { useChat } from './hooks/useChat'
import Sidebar from './components/Sidebar'
import AgentStatusBar from './components/AgentStatusBar'
import ChatInput from './components/ChatInput'
import ChatMessage from './components/ChatMessage'
import ThinkingCard from './components/ThinkingCard'
import HitlBar from './components/HitlBar'
import LoginScreen from './components/LoginScreen'
import Logo from './components/Logo'

const RECENT = [
  { id: '1', title: '一元二次方程', icon: '📐' },
  { id: '2', title: '二次函数', icon: '📊' },
  { id: '3', title: '不定积分', icon: '∫' },
]

const ABILITIES = [
  { name: '代数', level: 80 },
  { name: '几何', level: 50 },
  { name: '概率', level: 65 },
]

const SAMPLES = [
  '求解 x² - 5x + 6 = 0',
  '求 ∫ x² sin(x) dx',
  '什么是贝叶斯定理？',
]

function EmptyState({ onPick }: { onPick: (s: string) => void }) {
  return (
    <div className="empty-state">
      <div className="empty-logo">
        <Logo size={56} />
      </div>
      <h2 className="empty-title">AI 数学老师</h2>
      <p className="empty-sub">告诉我你的问题，我会逐步讲解、实时展示思考过程</p>
      <div className="sample-grid">
        {SAMPLES.map((s) => (
          <button key={s} className="sample-btn" onClick={() => onPick(s)}>
            {s}
          </button>
        ))}
      </div>
    </div>
  )
}

export default function App() {
  const {
    auth,
    authLoading,
    loginWithGoogle,
    logout,
    messages,
    thinking,
    agentStep,
    sending,
    error,
    sendText,
    sendFile,
    resume,
    newChat,
  } = useChat()

  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
  }, [messages, thinking.entries.length])

  const last = messages[messages.length - 1]
  const showHitl =
    last?.role === 'assistant' && last.status === 'awaiting_human' && last.hitl

  if (!auth) {
    return (
      <LoginScreen
        onLogin={loginWithGoogle}
        loading={authLoading}
        error={error}
      />
    )
  }

  return (
    <div className="app">
      <header className="header">
        <div className="header-brand">
          <span className="brand-logo">
            <Logo size={34} />
          </span>
          <span className="brand-name">MathTeacher AI</span>
        </div>
        <div className="header-user">
          <span className="user-avatar">👤</span>
          <span className="user-name">{auth.display_name}</span>
          <span className="user-email">{auth.email}</span>
          <button className="logout-btn" onClick={logout} title="退出登录">
            退出
          </button>
        </div>
      </header>

      <div className="main">
        <Sidebar onNewChat={newChat} recent={RECENT} abilities={ABILITIES} />

        <section className="chat">
          <div className="chat-header">
            <h2 className="chat-title">AI 数学老师</h2>
            <p className="chat-subtitle">逐步讲解 · 因材施教 · 实时思考</p>
          </div>

          <div className="messages" ref={scrollRef}>
            {messages.length === 0 && !thinking.active && (
              <EmptyState onPick={sendText} />
            )}
            {messages.map((m) => (
              <ChatMessage key={m.id} message={m} />
            ))}
            {thinking.active && <ThinkingCard thinking={thinking} />}
            {error && <div className="error-banner">⚠️ {error}</div>}
          </div>

          <div className="input-area">
            {showHitl ? (
              <HitlBar hitl={last!.hitl!} onResume={resume} />
            ) : (
              <ChatInput
                disabled={sending}
                onSendText={sendText}
                onSendFile={sendFile}
              />
            )}
          </div>
        </section>
      </div>

      <AgentStatusBar step={agentStep} active={thinking.active} />
    </div>
  )
}

import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import type { ChatMessage } from '../types'
import { nodeLabel } from '../meta'

// 后端个别地方用了三美元号包裹块级公式，这里归一化为 $$
function normalizeMath(md: string): string {
  return md.replace(/\$\$\$/g, '$$')
}

function MarkdownView({ content }: { content: string }) {
  return (
    <div className="markdown">
      <ReactMarkdown
        remarkPlugins={[remarkMath]}
        rehypePlugins={[rehypeKatex]}
      >
        {normalizeMath(content)}
      </ReactMarkdown>
    </div>
  )
}

function ThinkingCollapsed({ thinking }: { thinking: ChatMessage['thinking'] }) {
  const [open, setOpen] = useState(false)
  if (!thinking || thinking.length === 0) return null
  return (
    <div className="thinking-collapsed">
      <button className="thinking-toggle" onClick={() => setOpen((o) => !o)}>
        🧠 思考过程（{thinking.length} 步）{open ? '▾' : '▸'}
      </button>
      {open && (
        <div className="thinking-collapsed-body">
          {thinking.map((t, i) => (
            <div className="thinking-collapsed-row" key={i}>
              <span className="thinking-collapsed-node">{nodeLabel(t.node)}</span>
              <span className="thinking-collapsed-summary">{t.summary}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default function ChatMessage({ message }: { message: ChatMessage }) {
  if (message.role === 'user') {
    return (
      <div className="msg-row user">
        <div className="msg-bubble user">
          {message.imageUrl && (
            <img className="msg-image" src={message.imageUrl} alt={message.fileName ?? '图片'} />
          )}
          {message.inputType && (
            <div className="msg-meta">
              {message.inputType === 'image' ? '📷' : '🎤'} {message.fileName}
            </div>
          )}
          <div className="msg-content">{message.content}</div>
        </div>
        <div className="msg-avatar user">👨‍🎓</div>
      </div>
    )
  }

  return (
    <div className="msg-row assistant">
      <div className="msg-avatar assistant">🤖</div>
      <div className="msg-stack">
        <ThinkingCollapsed thinking={message.thinking} />
        <div className="msg-bubble assistant">
          {message.streaming && !message.content ? (
            <div className="typing">
              <span />
              <span />
              <span />
            </div>
          ) : (
            <MarkdownView content={message.content} />
          )}
        </div>
      </div>
    </div>
  )
}

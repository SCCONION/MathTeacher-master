import { useState } from 'react'
import type { HitlPayload } from '../types'

interface Props {
  hitl: HitlPayload
  onResume: (response: Record<string, unknown>, displayText: string) => void
}

export default function HitlBar({ hitl, onResume }: Props) {
  const [text, setText] = useState('')
  const type = hitl.hitl_type ?? 'clarification'
  const prompt = (hitl.prompt || hitl.message || '请提供所需信息。') as string

  const needsText = type === 'clarification' || type === 'bad_input'

  const submitText = () => {
    if (!text.trim()) return
    const display = `💬 ${text.trim()}`
    onResume(
      type === 'bad_input'
        ? { raw_text: text.trim() }
        : { corrected_text: text.trim() },
      display,
    )
    setText('')
  }

  const markVerification = (isCorrect: boolean) => {
    const fixHint = text.trim()
    onResume(
      isCorrect
        ? { is_correct: true }
        : { is_correct: false, fix_hint: fixHint || undefined },
      isCorrect ? '✅ 我认为答案正确' : `❌ 我认为答案不正确${fixHint ? `：${fixHint}` : ''}`,
    )
    setText('')
  }

  const markSatisfaction = (satisfied: boolean) => {
    const followUp = text.trim()
    onResume(
      { satisfied, follow_up: followUp || undefined },
      satisfied ? '👍 满意，讲解很清楚' : `👎 不满意${followUp ? `：${followUp}` : ''}`,
    )
    setText('')
  }

  return (
    <div className="hitl-bar">
      <div className="hitl-prompt">{prompt}</div>

      {needsText && (
        <div className="hitl-row">
          <input
            className="hitl-input"
            placeholder="在这里补充你的问题…"
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && submitText()}
          />
          <button className="send-btn" onClick={submitText} disabled={!text.trim()}>
            继续
          </button>
        </div>
      )}

      {type === 'verification' && (
        <div className="hitl-row">
          <input
            className="hitl-input"
            placeholder="（可选）如答案不正确，说明原因…"
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          <button className="hitl-btn ok" onClick={() => markVerification(true)}>
            ✓ 答案正确
          </button>
          <button className="hitl-btn bad" onClick={() => markVerification(false)}>
            ✗ 答案不正确
          </button>
        </div>
      )}

      {type === 'satisfaction' && (
        <div className="hitl-row">
          <input
            className="hitl-input"
            placeholder="（可选）哪里还不清楚？"
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && markSatisfaction(true)}
          />
          <button className="hitl-btn ok" onClick={() => markSatisfaction(true)}>
            👍 满意
          </button>
          <button className="hitl-btn bad" onClick={() => markSatisfaction(false)}>
            👎 不满意
          </button>
        </div>
      )}
    </div>
  )
}

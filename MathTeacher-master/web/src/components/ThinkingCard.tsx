import { useEffect, useRef } from 'react'
import type { ThinkingState } from '../types'
import { nodeLabel } from '../meta'

export default function ThinkingCard({ thinking }: { thinking: ThinkingState }) {
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [thinking.entries.length])

  const current = nodeLabel(thinking.currentNode)

  return (
    <div className="thinking">
      <div className="thinking-title">
        <span className="spinner" />
        <span>AI 正在思考</span>
        {thinking.currentNode && (
          <span className="thinking-current">· {current}</span>
        )}
      </div>

      {thinking.entries.length === 0 ? (
        <div className="thinking-empty">正在分析你的问题…</div>
      ) : (
        <div className="thinking-list">
          {thinking.entries.map((t, i) => (
            <div className="thinking-entry" key={i}>
              <div className="thinking-node">{nodeLabel(t.node)}</div>
              {t.summary && (
                <div className="thinking-summary">{t.summary}</div>
              )}
              {Object.keys(t.fields).length > 0 && (
                <div className="thinking-fields">
                  {Object.entries(t.fields).map(([k, v]) => (
                    <div className="field-row" key={k}>
                      <span className="field-key">{k}</span>
                      <span className="field-value">{v}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
          <div ref={bottomRef} />
        </div>
      )}
    </div>
  )
}

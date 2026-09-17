import { STEPS } from '../meta'

interface Props {
  step: number
  active: boolean
}

export default function AgentStatusBar({ step, active }: Props) {
  return (
    <footer className="status-bar">
      <span className="status-label">Agent 状态</span>
      <div className="status-steps">
        {STEPS.map((label, i) => {
          const state = i < step ? 'done' : i === step && active ? 'active' : 'pending'
          return (
            <div className={`status-step ${state}`} key={label}>
              <span className="step-dot">
                {state === 'done' ? '✓' : state === 'active' ? '●' : '○'}
              </span>
              <span className="step-label">{label}</span>
              {i < STEPS.length - 1 && <span className="step-line" />}
            </div>
          )
        })}
      </div>
    </footer>
  )
}

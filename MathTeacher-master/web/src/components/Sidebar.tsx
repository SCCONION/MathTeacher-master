export interface RecentTopic {
  id: string
  title: string
  icon: string
}

export interface Ability {
  name: string
  level: number
}

interface Props {
  onNewChat: () => void
  recent: RecentTopic[]
  abilities: Ability[]
}

export default function Sidebar({ onNewChat, recent, abilities }: Props) {
  return (
    <aside className="sidebar">
      <div className="sidebar-title">学习空间</div>

      <button className="new-chat-btn" onClick={onNewChat}>
        <span>＋</span> 新对话
      </button>

      <div className="sidebar-group">
        <div className="sidebar-group-title">最近学习</div>
        {recent.map((r) => (
          <div className="recent-item" key={r.id}>
            <span className="recent-icon">{r.icon}</span>
            <span className="recent-title">{r.title}</span>
          </div>
        ))}
      </div>

      <div className="sidebar-group">
        <div className="sidebar-group-title">学习能力</div>
        {abilities.map((a) => (
          <div className="ability-row" key={a.name}>
            <div className="ability-top">
              <span className="ability-name">{a.name}</span>
              <span className="ability-value">{a.level}%</span>
            </div>
            <div className="ability-track">
              <div className="ability-fill" style={{ width: `${a.level}%` }} />
            </div>
          </div>
        ))}
      </div>
    </aside>
  )
}

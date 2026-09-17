import { useEffect, useRef } from 'react'
import Logo from './Logo'

const GOOGLE_CLIENT_ID =
  '884766496961-u1tu99am3reupotc2f2rco5immul37sb.apps.googleusercontent.com'

interface GoogleCredentialResponse {
  credential?: string
}

interface Props {
  onLogin: (credential: string) => void
  loading: boolean
  error?: string | null
}

export default function LoginScreen({ onLogin, loading, error }: Props) {
  const btnRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const scriptId = 'gsi-client'

    const render = () => {
      const google = (window as any).google
      if (!google?.accounts?.id || !btnRef.current) return

      google.accounts.id.initialize({
        client_id: GOOGLE_CLIENT_ID,
        callback: (resp: GoogleCredentialResponse) => {
          if (resp?.credential) onLogin(resp.credential)
        },
      })

      google.accounts.id.renderButton(btnRef.current, {
        theme: 'outline',
        size: 'large',
        shape: 'pill',
        text: 'signin_with',
        width: 280,
      })
    }

    if ((window as any).google?.accounts?.id) {
      render()
      return
    }

    const existing = document.getElementById(scriptId) as HTMLScriptElement | null
    if (existing) {
      existing.addEventListener('load', render)
      return
    }

    const script = document.createElement('script')
    script.id = scriptId
    script.src = 'https://accounts.google.com/gsi/client'
    script.async = true
    script.defer = true
    script.onload = render
    document.head.appendChild(script)

    return () => {
      if (script.onload === render) script.onload = null
    }
  }, [onLogin])

  return (
    <div className="login-screen">
      <div className="login-card">
        <div className="login-logo">
          <Logo size={64} />
        </div>
        <h1 className="login-title">数学智能辅导助手</h1>
        <p className="login-subtitle">
          AI 分步解题，根据你的学习情况个性化讲解
        </p>

        <div className="feature-row">
          <span className="feature-pill">📐 全知识点覆盖</span>
          <span className="feature-pill">🧠 跨会话记忆</span>
          <span className="feature-pill">🎬 可视化讲解</span>
        </div>

        <div className="login-btn-wrap" ref={btnRef} />

        {loading && <div className="login-loading">正在登录…</div>}
        {error && <div className="login-error">⚠️ {error}</div>}

        <div className="trust-row">
          <span>🔒 Google OAuth 2.0 认证</span>
          <span>🛡️ 不存储密码</span>
          <span>☁️ 加密会话</span>
        </div>
      </div>
    </div>
  )
}

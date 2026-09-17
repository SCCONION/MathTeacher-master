import { useRef, useState } from 'react'

interface Props {
  disabled: boolean
  onSendText: (text: string) => void
  onSendFile: (file: File, type: 'image' | 'audio') => void
}

export default function ChatInput({ disabled, onSendText, onSendFile }: Props) {
  const [text, setText] = useState('')
  const [recording, setRecording] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const recorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])

  const submit = () => {
    if (!text.trim() || disabled) return
    onSendText(text)
    setText('')
  }

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  const pickImage = () => fileInputRef.current?.click()

  const onFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) onSendFile(file, 'image')
    e.target.value = ''
  }

  const toggleRecord = async () => {
    if (recording) {
      recorderRef.current?.stop()
      setRecording(false)
      return
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const recorder = new MediaRecorder(stream)
      chunksRef.current = []
      recorder.ondataavailable = (e) => chunksRef.current.push(e.data)
      recorder.onstop = () => {
        stream.getTracks().forEach((t) => t.stop())
        const blob = new Blob(chunksRef.current, { type: 'audio/webm' })
        if (blob.size > 0) {
          const file = new File([blob], `录音-${Date.now()}.webm`, {
            type: 'audio/webm',
          })
          onSendFile(file, 'audio')
        }
      }
      recorder.start()
      recorderRef.current = recorder
      setRecording(true)
    } catch {
      /* 用户拒绝麦克风权限时静默处理 */
    }
  }

  return (
    <div className="input-bar">
      <div className="input-actions">
        <button
          className="attach-btn"
          onClick={pickImage}
          title="上传图片"
          disabled={disabled}
        >
          📎 图片
        </button>
        <button
          className={`attach-btn ${recording ? 'recording' : ''}`}
          onClick={toggleRecord}
          title="语音输入"
          disabled={disabled}
        >
          {recording ? '⏹ 停止' : '🎤 语音'}
        </button>
      </div>

      <textarea
        className="input-box"
        placeholder="输入问题…（例如：求解 x² - 5x + 6 = 0）"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKeyDown}
        rows={1}
        disabled={disabled}
      />

      <button
        className="send-btn"
        onClick={submit}
        disabled={disabled || !text.trim()}
      >
        发送 ➤
      </button>

      <input
        ref={fileInputRef}
        type="file"
        accept="image/*"
        style={{ display: 'none' }}
        onChange={onFileChange}
      />
    </div>
  )
}

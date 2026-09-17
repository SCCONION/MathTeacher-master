import { useRef } from 'react'

// 模块级自增计数器：为每个实例生成唯一的渐变 id，避免同页多个 Logo 时 id 冲突
let _uid = 0

interface LogoProps {
  size?: number
}

export default function Logo({ size = 34 }: LogoProps) {
  const idRef = useRef(`logo-grad-${_uid++}`)

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 100 100"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
      style={{ display: 'block' }}
    >
      <defs>
        <linearGradient id={idRef.current} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#6366f1" />
          <stop offset="1" stopColor="#8b5cf6" />
        </linearGradient>
      </defs>
      <rect width="100" height="100" rx="24" fill={`url(#${idRef.current})`} />
      {/* π 符号（大写 Π）：两条竖线 + 顶部横线 */}
      <path
        d="M35 72 V32 H65 V72"
        fill="none"
        stroke="#ffffff"
        strokeWidth="9"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

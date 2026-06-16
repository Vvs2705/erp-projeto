import React from 'react'

interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  children: React.ReactNode
}

export function Card({ children, className = '', ...props }: CardProps) {
  return (
    <div 
      className={`glass-panel p-5 rounded-xl border border-slate-800 ${className}`} 
      {...props}
    >
      {children}
    </div>
  )
}

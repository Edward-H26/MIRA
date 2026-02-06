import { useEffect, useState } from "react"

const mockSuggestions = [
  "Discover more",
  "Improve your productivity",
  "Summarize this conversation",
  "Generate a new idea"
]

function useTypingIndicator(isThinking) {
  const [dots, setDots] = useState(1)

  useEffect(() => {
    if (!isThinking) return
    const interval = setInterval(() => {
      setDots(prev => (prev % 3) + 1)
    }, 400)
    return () => clearInterval(interval)
  }, [isThinking])

  return ".".repeat(dots)
}

export function ChatPane() {
  const [messages, setMessages] = useState([
    {
      id: 1,
      role: "assistant",
      content: "Hello! I'm Memoria. Ask me anything or create a new memory."
    }
  ])
  const [input, setInput] = useState("")
  const [isThinking, setIsThinking] = useState(false)
  const [showSuggestions, setShowSuggestions] = useState(true)

  const typingDots = useTypingIndicator(isThinking)

  const sendMessage = () => {
    const trimmed = input.trim()
    if (!trimmed) return
    const userMessage = {
      id: Date.now(),
      role: "user",
      content: trimmed
    }
    setMessages(prev => [...prev, userMessage])
    setInput("")
    setShowSuggestions(false)
    setIsThinking(true)

    setTimeout(() => {
      setMessages(prev => [
        ...prev,
        {
          id: Date.now() + 1,
          role: "assistant",
          content: "Here's a quick answer based on your request."
        }
      ])
      setIsThinking(false)
    }, 1200)
  }

  const handleKeyDown = (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault()
      sendMessage()
    }
  }

  return (
    <div className="h-full flex flex-col">
      <div className="flex-1 overflow-y-auto pr-1">
        <div className="space-y-4">
          {messages.map(message => (
            <div
              key={message.id}
              className={`max-w-[80%] rounded-2xl px-4 py-3 text-sm leading-6 ${
                message.role === "assistant"
                  ? "bg-white/70 text-[#1b1b1b] shadow-sm"
                  : "ml-auto bg-bg-dark text-text-light"
              }`}
            >
              {message.content}
            </div>
          ))}
          {isThinking && (
            <div className="max-w-[80%] rounded-2xl px-4 py-3 text-sm leading-6 bg-white/70 text-[#1b1b1b] shadow-sm">
              <span className="thinking-dots"><span></span><span></span><span></span></span>
              <span className="ml-2">Thinking{typingDots}</span>
            </div>
          )}
        </div>
      </div>

      {showSuggestions && (
        <div className="mt-4 flex flex-wrap gap-2">
          {mockSuggestions.map((text, idx) => (
            <button
              key={idx}
              className="rounded-full border border-black/10 bg-white/70 px-4 py-2 text-xs font-medium text-text-secondary hover:bg-white/90"
              onClick={() => setInput(text)}
            >
              {text}
            </button>
          ))}
        </div>
      )}

      <div className="mt-4">
        <div className="flex items-center gap-2 rounded-2xl bg-white/70 px-4 py-3 shadow-sm">
          <textarea
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={handleKeyDown}
            rows={1}
            placeholder="Type your message..."
            className="flex-1 resize-none bg-transparent text-sm leading-6 text-[#1b1b1b] focus:outline-none"
          ></textarea>
          <button
            onClick={sendMessage}
            className="rounded-full bg-bg-dark px-4 py-2 text-xs font-medium text-text-light"
          >
            Send
          </button>
        </div>
      </div>
    </div>
  )
}

export function mountChatPane(root) {
  import("react-dom/client").then(({ createRoot }) => {
    const container = createRoot(root)
    container.render(<ChatPane />)
  })
}
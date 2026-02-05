import { useState, useRef, useEffect } from "react"
import { createRoot } from "react-dom/client"

function ChatPane({ initialMessages = [] }) {
    const [messages, setMessages] = useState(initialMessages)
    const [isThinking, setIsThinking] = useState(false)
    const [inputValue, setInputValue] = useState("")
    const messagesEndRef = useRef(null)
    const chatContainerRef = useRef(null)

    useEffect(() => {
        if (chatContainerRef.current) {
            chatContainerRef.current.scrollTop = chatContainerRef.current.scrollHeight
        }
    }, [messages, isThinking])

    useEffect(() => {
        const handleNewChat = () => {
            setMessages([])
            setInputValue("")
            setIsThinking(false)
        }
        window.addEventListener("newChatCreated", handleNewChat)
        return () => window.removeEventListener("newChatCreated", handleNewChat)
    }, [])

    function sendMessage() {
        const trimmed = inputValue.trim()
        if (!trimmed) return

        setMessages(prev => [...prev, { role: "user", content: trimmed }])
        setInputValue("")
        setIsThinking(true)

        setTimeout(() => {
            setIsThinking(false)
            setMessages(prev => [
                ...prev,
                { role: "assistant", content: "Thanks for your message! This is a demo response from the AI assistant." }
            ])
        }, 1500)
    }

    function handleKeyDown(e) {
        if (e.key === "Enter") {
            e.preventDefault()
            sendMessage()
        }
    }

    const hasMessages = messages.length > 0

    return (
        <div className="flex flex-col h-full">
            {hasMessages ? (
                <div ref={chatContainerRef} className="scroll-container flex-1">
                    <div className="mx-auto max-w-2xl space-y-4 py-4">
                        {messages.map((msg, i) => (
                            <div key={i} className="group py-2">
                                <div
                                    className={`text-sm leading-relaxed ${msg.role === "user" ? "text-bg-dark font-medium" : "text-text-secondary"}`}
                                    dangerouslySetInnerHTML={{ __html: msg.content }}
                                />
                            </div>
                        ))}
                        {isThinking && (
                            <div className="group py-2">
                                <div className="flex items-center gap-3">
                                    <div className="thinking-dots">
                                        <span></span>
                                        <span></span>
                                        <span></span>
                                    </div>
                                    <span className="text-sm text-text-secondary">AI is thinking...</span>
                                </div>
                            </div>
                        )}
                        <div ref={messagesEndRef} />
                    </div>
                </div>
            ) : (
                <div className="flex-1 flex items-center justify-center w-full">
                    <h1 className="font-inter font-semibold text-3xl md:text-4xl text-bg-dark text-center">
                        Start your project here,
                    </h1>
                </div>
            )}

            <div className="flex flex-col items-center w-full max-w-2xl mx-auto px-4 pb-8 flex-shrink-0">
                <input
                    type="text"
                    value={inputValue}
                    onChange={e => setInputValue(e.target.value)}
                    onKeyDown={handleKeyDown}
                    placeholder="Enter what you think here..."
                    className="w-full h-12 rounded-button bg-white/80 px-6 text-sm text-bg-dark placeholder:text-placeholder focus:outline-none shadow-sm"
                />
                <div className="flex items-center justify-between w-full mt-4">
                    <button className="flex items-center gap-2 px-5 py-2.5 rounded-button border border-black/10 bg-white text-sm text-text-secondary font-inter font-medium hover:bg-black/5 transition-colors">
                        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 4v16m8-8H4" />
                        </svg>
                        Add something...
                    </button>
                    <button
                        onClick={sendMessage}
                        className="px-8 py-2.5 rounded-button bg-bg-dark text-text-light text-sm font-inter font-medium hover:bg-bg-dark/90 transition-colors"
                    >
                        Continue
                    </button>
                </div>
            </div>
        </div>
    )
}

export function mountChatPane(element) {
    let initialMessages = []
    const dataAttr = element.getAttribute("data-initial-messages")
    if (dataAttr) {
        initialMessages = JSON.parse(dataAttr)
    }
    const root = createRoot(element)
    root.render(<ChatPane initialMessages={initialMessages} />)
}

export default ChatPane

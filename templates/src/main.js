import "./main.css"
import { initSidebar } from "./sidebar.js"
import { mountChatPane } from "./components/ChatPane.jsx"

document.addEventListener("DOMContentLoaded", () => {
    initSidebar()
    const chatRoot = document.getElementById("chat-root")
    if (chatRoot) {
        mountChatPane(chatRoot)
    }
})

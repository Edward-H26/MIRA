export function initSidebar() {
    const sidebar = document.getElementById("sidebar")
    const sidebarOverlay = document.getElementById("sidebar-overlay")
    const mainContent = document.getElementById("main-content")
    const collapseArrow = document.getElementById("collapse-arrow")
    const expandArrow = document.getElementById("expand-arrow")
    const collapseBtn = document.getElementById("collapse-btn")
    const newChatText = document.getElementById("new-chat-text")
    const newChatContainer = document.getElementById("new-chat-container")

    if (!sidebar || !mainContent) return

    const menuLabels = document.querySelectorAll(".sidebar-menu-label")
    const sectionLabels = document.querySelectorAll(".sidebar-section-label")
    const conversationItems = document.querySelectorAll(".conversation-item")
    const conversationActions = document.querySelectorAll(".conversation-actions")

    function setSidebarExpanded() {
        sidebar.classList.remove("collapsed")
        menuLabels.forEach(el => el.style.opacity = "1")
        sectionLabels.forEach(el => el.classList.remove("hidden"))
        conversationItems.forEach(el => el.classList.remove("hidden"))
        conversationActions.forEach(el => el.classList.remove("hidden"))
        if (newChatText) newChatText.classList.remove("hidden")
        if (newChatContainer) newChatContainer.classList.remove("hidden")
    }

    function setSidebarCollapsed() {
        sidebar.classList.add("collapsed")
        menuLabels.forEach(el => el.style.opacity = "0")
        sectionLabels.forEach(el => el.classList.add("hidden"))
        conversationItems.forEach(el => el.classList.add("hidden"))
        conversationActions.forEach(el => el.classList.add("hidden"))
        if (newChatText) newChatText.classList.add("hidden")
        if (newChatContainer) newChatContainer.classList.add("hidden")
    }

    function toggleSidebarCollapse() {
        const isCollapsed = sidebar.dataset.collapsed === "true"

        if (isCollapsed) {
            sidebar.dataset.collapsed = "false"
            mainContent.style.left = "244px"
            if (collapseArrow) collapseArrow.classList.remove("hidden")
            if (expandArrow) expandArrow.classList.add("hidden")
            if (collapseBtn) collapseBtn.title = "Collapse sidebar"
            setSidebarExpanded()
        } else {
            sidebar.dataset.collapsed = "true"
            mainContent.style.left = "80px"
            if (collapseArrow) collapseArrow.classList.add("hidden")
            if (expandArrow) expandArrow.classList.remove("hidden")
            if (collapseBtn) collapseBtn.title = "Expand sidebar"
            setSidebarCollapsed()
        }
    }

    function openSidebar() {
        sidebar.classList.add("sidebar-open")
        sidebar.dataset.collapsed = "false"
        if (sidebarOverlay) sidebarOverlay.classList.remove("hidden")
        setSidebarExpanded()
    }

    function closeSidebar() {
        if (window.innerWidth < 1024) {
            sidebar.classList.remove("sidebar-open")
            if (sidebarOverlay) sidebarOverlay.classList.add("hidden")
        }
    }

    function selectConversation(id, shouldCloseSidebar = true) {
        document.querySelectorAll(".conversation-item").forEach(item => {
            const isSelected = item.dataset.id === id
            item.dataset.selected = isSelected
            const content = item.querySelector(".conversation-content")
            if (isSelected) {
                content.classList.add("bg-black/5")
                content.classList.remove("hover:bg-black/5")
            } else {
                content.classList.remove("bg-black/5")
                content.classList.add("hover:bg-black/5")
            }
        })

        if (shouldCloseSidebar && window.innerWidth < 1024) {
            closeSidebar()
        }
    }

    function renameConversation(id) {
        const item = document.querySelector(`.conversation-item[data-id="${id}"]`)
        const titleEl = item.querySelector(".conversation-title")
        const actionsEl = item.querySelector(".conversation-actions")
        const currentTitle = titleEl.textContent

        if (actionsEl) actionsEl.style.display = "none"

        const contentEl = item.querySelector(".conversation-content")
        const originalContent = contentEl.innerHTML

        const wrapper = document.createElement("div")
        wrapper.className = "flex items-center gap-2"

        const input = document.createElement("input")
        input.type = "text"
        input.value = currentTitle
        input.className = "flex-1 min-w-0 rounded border border-black/20 bg-white px-2 py-1 text-sm font-inter focus:outline-none focus:border-blue-400"

        const saveBtn = document.createElement("button")
        saveBtn.innerHTML = `<svg class="w-4 h-4 text-green-600" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" /></svg>`
        saveBtn.className = "flex-shrink-0 p-1 rounded hover:bg-black/10"

        wrapper.appendChild(input)
        wrapper.appendChild(saveBtn)

        contentEl.innerHTML = ""
        contentEl.appendChild(wrapper)

        input.focus()
        input.select()

        const saveEdit = () => {
            const newTitle = input.value.trim() || "New Chat"
            contentEl.innerHTML = originalContent
            contentEl.querySelector(".conversation-title").textContent = newTitle
            if (actionsEl) actionsEl.style.display = ""
        }

        const cancelEdit = () => {
            contentEl.innerHTML = originalContent
            if (actionsEl) actionsEl.style.display = ""
        }

        saveBtn.onclick = saveEdit
        input.onkeydown = (e) => {
            if (e.key === "Enter") saveEdit()
            if (e.key === "Escape") cancelEdit()
        }
        input.onblur = (e) => {
            if (e.relatedTarget !== saveBtn) {
                saveEdit()
            }
        }
    }

    function deleteConversation(id) {
        if (confirm("Are you sure you want to delete this conversation?")) {
            const item = document.querySelector(`.conversation-item[data-id="${id}"]`)
            item.remove()
        }
    }

    function createNewChat() {
        window.location.href = "/home/"
    }

    window.addEventListener("resize", () => {
        if (window.innerWidth >= 1024) {
            sidebar.classList.remove("sidebar-open")
            if (sidebarOverlay) sidebarOverlay.classList.add("hidden")
        }
    })

    document.addEventListener("keydown", function(e) {
        if ((e.ctrlKey || e.metaKey) && e.key === "n") {
            e.preventDefault()
            createNewChat()
        }
        if (e.key === "Escape" && sidebarOverlay && !sidebarOverlay.classList.contains("hidden")) {
            closeSidebar()
        }
    })

    if (window.innerWidth < 1024) {
        mainContent.style.left = "0"
    }

    window.toggleSidebarCollapse = toggleSidebarCollapse
    window.openSidebar = openSidebar
    window.closeSidebar = closeSidebar
    window.selectConversation = selectConversation
    window.renameConversation = renameConversation
    window.deleteConversation = deleteConversation
    window.createNewChat = createNewChat
}

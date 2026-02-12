function getCSRFToken() {
    const cookie = document.cookie.split("; ").find(c => c.startsWith("csrftoken="))
    if (cookie) return cookie.split("=")[1]
    const meta = document.querySelector('meta[name="csrf-token"]')
    if (meta) return meta.content
    const input = document.querySelector('input[name="csrfmiddlewaretoken"]')
    if (input) return input.value
    return ""
}

function initSidebar() {
    const SIDEBAR_COLLAPSED_KEY = "sidebarCollapsed"
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
    const navItems = document.querySelectorAll("[data-nav]")
    const sidebarContent = sidebar.querySelector(".sidebar-content")
    const searchModalPanel = document.getElementById("search-modal-panel")

    function getCollapsedMainOffset() {
        const path = window.location.pathname
        const isMemoryPage = path.startsWith("/chat/memory") || path.startsWith("/chat/m/")
        return isMemoryPage ? "80px" : "0"
    }

    function syncSearchModalPosition() {
        if (!searchModalPanel) return
        const isDesktop = window.innerWidth >= 1024
        const isCollapsed = sidebar.dataset.collapsed === "true"
        searchModalPanel.style.left = (isDesktop && !isCollapsed)
            ? "calc((20vw + 100vw) / 2)"
            : "50%"
    }

    function setSidebarExpanded() {
        sidebar.classList.remove("collapsed")
        menuLabels.forEach(el => el.style.opacity = "1")
        sectionLabels.forEach(el => el.classList.remove("hidden"))
        conversationItems.forEach(el => el.classList.remove("hidden"))
        conversationActions.forEach(el => el.classList.remove("hidden"))
        if (newChatText) newChatText.classList.remove("hidden")
        if (newChatContainer) newChatContainer.classList.remove("hidden")
        syncSearchModalPosition()
    }

    function setSidebarCollapsed() {
        sidebar.classList.add("collapsed")
        menuLabels.forEach(el => el.style.opacity = "0")
        sectionLabels.forEach(el => el.classList.add("hidden"))
        conversationItems.forEach(el => el.classList.add("hidden"))
        conversationActions.forEach(el => el.classList.add("hidden"))
        if (newChatText) newChatText.classList.add("hidden")
        if (newChatContainer) newChatContainer.classList.add("hidden")
        syncSearchModalPosition()
    }

    function toggleSidebarCollapse() {
        const isCollapsed = sidebar.dataset.collapsed === "true"

        if (isCollapsed) {
            sidebar.dataset.collapsed = "false"
            sessionStorage.setItem(SIDEBAR_COLLAPSED_KEY, "false")
            mainContent.style.left = "20vw"
            if (collapseArrow) collapseArrow.classList.remove("hidden")
            if (expandArrow) expandArrow.classList.add("hidden")
            if (collapseBtn) collapseBtn.title = "Collapse sidebar"
            setSidebarExpanded()
        } else {
            sidebar.dataset.collapsed = "true"
            sessionStorage.setItem(SIDEBAR_COLLAPSED_KEY, "true")
            mainContent.style.left = getCollapsedMainOffset()
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
        if (!item) return
        const titleEl = item.querySelector(".conversation-title")
        const actionsEl = item.querySelector(".conversation-actions")
        const currentTitle = titleEl.textContent.trim()

        if (actionsEl) actionsEl.style.display = "none"

        const contentEl = item.querySelector(".conversation-content")
        const originalContent = contentEl.innerHTML

        const wrapper = document.createElement("div")
        wrapper.className = "flex items-center gap-2"
        wrapper.style.padding = "4px"

        const input = document.createElement("input")
        input.type = "text"
        input.value = currentTitle
        input.className = "flex-1 min-w-0 rounded border border-black/20 bg-white px-2 py-1 text-sm font-inter focus:outline-none focus:border-blue-400"

        const saveBtn = document.createElement("button")
        saveBtn.innerHTML = '<svg class="w-4 h-4 text-green-600" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" /></svg>'
        saveBtn.className = "flex-shrink-0 p-1 rounded hover:bg-black/10"

        wrapper.appendChild(input)
        wrapper.appendChild(saveBtn)

        contentEl.innerHTML = ""
        contentEl.appendChild(wrapper)

        input.focus()
        input.select()

        const saveEdit = async () => {
            const newTitle = input.value.trim() || "New Chat"
            contentEl.innerHTML = originalContent
            contentEl.querySelector(".conversation-title").textContent = newTitle
            if (actionsEl) actionsEl.style.display = ""
            try {
                const formData = new FormData()
                formData.append("title", newTitle)
                await fetch(`/chat/c/${id}/rename/`, {
                    method: "POST",
                    headers: { "X-CSRFToken": getCSRFToken() },
                    body: formData
                })
            } catch (_) {}
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
        if (!confirm("Are you sure you want to delete this conversation?")) return
        const item = document.querySelector(`.conversation-item[data-id="${id}"]`)
        if (item) item.remove()
        fetch(`/chat/c/${id}/delete/`, {
            method: "POST",
            headers: { "X-CSRFToken": getCSRFToken() }
        }).then(res => {
            if (res.ok) {
                const match = window.location.pathname.match(/\/chat\/c\/(\d+)\//)
                if (match && match[1] === String(id)) {
                    window.location.href = "/home/"
                }
            }
        }).catch(() => {})
    }

    function createNewChat() {
        window.location.href = "/home/"
    }

    function setActiveNav() {
        if (!navItems.length) return
        const path = window.location.pathname
        let activeKey = ""

        if (path === "/home/" || path === "/home") {
            activeKey = "new-chat"
        } else if (path.startsWith("/chat/memory") || path.startsWith("/chat/m/")) {
            activeKey = "memory"
        } else if (path.startsWith("/chat/analytics")) {
            activeKey = "analytics"
        }

        navItems.forEach(item => {
            const isActive = item.dataset.nav === activeKey
            item.classList.toggle("is-active", isActive)
        })

        const conversationMatch = path.match(/\/chat\/c\/(\d+)\//)
        if (conversationMatch) {
            selectConversation(conversationMatch[1], false)
        }
    }

    function restoreSidebarScroll() {
        if (!sidebarContent) return
        const stored = sessionStorage.getItem("sidebarScrollTop")
        if (stored) {
            const top = Number(stored)
            if (!Number.isNaN(top)) {
                requestAnimationFrame(() => {
                    sidebarContent.scrollTop = top
                })
            }
            sessionStorage.removeItem("sidebarScrollTop")
        }
    }

    function bindSidebarScrollPersistence() {
        if (!sidebarContent) return
        sidebarContent.querySelectorAll("a").forEach(link => {
            link.addEventListener("click", () => {
                sessionStorage.setItem("sidebarScrollTop", String(sidebarContent.scrollTop))
            })
        })
    }

    window.addEventListener("resize", () => {
        if (window.innerWidth >= 1024) {
            sidebar.classList.remove("sidebar-open")
            if (sidebarOverlay) sidebarOverlay.classList.add("hidden")
        }
        syncSearchModalPosition()
    })

    document.addEventListener("keydown", function(e) {
        if ((e.ctrlKey || e.metaKey) && e.key === "n") {
            e.preventDefault()
            createNewChat()
        }
        if ((e.ctrlKey || e.metaKey) && e.key === "k") {
            e.preventDefault()
            openSearchModal()
        }
        if (e.key === "Escape" && sidebarOverlay && !sidebarOverlay.classList.contains("hidden")) {
            closeSidebar()
        }
    })

    if (window.innerWidth < 1024) {
        mainContent.style.left = "0"
    } else {
        const persistedCollapsed = sessionStorage.getItem(SIDEBAR_COLLAPSED_KEY) === "true"
        if (persistedCollapsed) {
            sidebar.dataset.collapsed = "true"
            mainContent.style.left = getCollapsedMainOffset()
            if (collapseArrow) collapseArrow.classList.add("hidden")
            if (expandArrow) expandArrow.classList.remove("hidden")
            if (collapseBtn) collapseBtn.title = "Expand sidebar"
            setSidebarCollapsed()
        } else {
            sidebar.dataset.collapsed = "false"
            mainContent.style.left = "20vw"
            if (collapseArrow) collapseArrow.classList.remove("hidden")
            if (expandArrow) expandArrow.classList.add("hidden")
            if (collapseBtn) collapseBtn.title = "Collapse sidebar"
            setSidebarExpanded()
        }
    }
    syncSearchModalPosition()

    window.toggleSidebarCollapse = toggleSidebarCollapse
    window.openSidebar = openSidebar
    window.closeSidebar = closeSidebar
    window.selectConversation = selectConversation
    window.renameConversation = renameConversation
    window.deleteConversation = deleteConversation
    window.createNewChat = createNewChat

    setActiveNav()
    restoreSidebarScroll()
    bindSidebarScrollPersistence()
}

function initSearchModal() {
    const modal = document.getElementById("search-modal")
    const input = document.getElementById("search-modal-input")
    const resultsEl = document.getElementById("search-modal-results")
    const emptyEl = document.getElementById("search-modal-empty")
    if (!modal || !input) return

    let debounceTimer = null

    function open() {
        modal.classList.remove("hidden")
        input.value = ""
        resultsEl.innerHTML = ""
        emptyEl.classList.add("hidden")
        setTimeout(() => input.focus(), 50)
    }

    function close() {
        modal.classList.add("hidden")
        input.value = ""
        resultsEl.innerHTML = ""
        emptyEl.classList.add("hidden")
    }

    modal.addEventListener("click", (e) => {
        if (e.target === modal) close()
    })

    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && !modal.classList.contains("hidden")) {
            e.stopPropagation()
            close()
        }
    })

    input.addEventListener("input", () => {
        clearTimeout(debounceTimer)
        const q = input.value.trim()
        if (!q) {
            resultsEl.innerHTML = ""
            emptyEl.classList.add("hidden")
            return
        }
        debounceTimer = setTimeout(() => {
            fetch(`/chat/api/sessions/?q=${encodeURIComponent(q)}`)
                .then(r => r.json())
                .then(data => {
                    resultsEl.innerHTML = ""
                    if (!data.results || data.results.length === 0) {
                        emptyEl.classList.remove("hidden")
                        return
                    }
                    emptyEl.classList.add("hidden")
                    data.results.forEach(s => {
                        const a = document.createElement("a")
                        a.href = s.url
                        a.style.cssText = "display: flex; flex-direction: column; gap: 2px; padding: 10px 12px; border-radius: 8px; text-decoration: none; color: inherit; transition: background 0.15s;"
                        a.onmouseenter = () => { a.style.background = "rgba(0,0,0,0.04)" }
                        a.onmouseleave = () => { a.style.background = "transparent" }
                        const title = document.createElement("span")
                        title.style.cssText = "font-family: Inter, sans-serif; font-size: 14px; font-weight: 500; color: #333;"
                        title.textContent = s.title || "Untitled"
                        const time = document.createElement("span")
                        time.style.cssText = "font-family: Inter, sans-serif; font-size: 12px; color: #999;"
                        time.textContent = new Date(s.updated_at).toLocaleDateString()
                        a.appendChild(title)
                        a.appendChild(time)
                        resultsEl.appendChild(a)
                    })
                })
                .catch(() => {
                    emptyEl.classList.remove("hidden")
                })
        }, 250)
    })

    window.openSearchModal = open
    window.closeSearchModal = close
}

document.addEventListener("DOMContentLoaded", () => {
    initSidebar()
    initSearchModal()

    const conversationScroll = document.querySelector(".conversation-messages")
    const form = document.querySelector(".conversation-input")
    if (conversationScroll && form) {
        const input = form.querySelector('input[name="message"]')
        const csrf = form.querySelector('input[name="csrfmiddlewaretoken"]')

        const appendMessage = (role, content) => {
            const row = document.createElement("div")
            row.className = `message-row ${role === "user" ? "is-user" : "is-agent"}`

            const bubble = document.createElement("div")
            bubble.className = `message-bubble ${role === "user" ? "bubble-user" : "bubble-agent"}`
            bubble.textContent = content
            row.appendChild(bubble)
            conversationScroll.appendChild(row)
        }

        form.addEventListener("submit", async (event) => {
            event.preventDefault()
            if (!input) return
            const message = input.value.trim()
            if (!message) return

            try {
                const formData = new FormData(form)
                formData.set("message", message)
                const response = await fetch(form.action || window.location.href, {
                    method: "POST",
                    headers: {
                        "X-Requested-With": "XMLHttpRequest",
                        "X-CSRFToken": csrf ? csrf.value : ""
                    },
                    body: formData
                })
                if (!response.ok) {
                    form.submit()
                    return
                }
                const data = await response.json()
                if (Array.isArray(data.messages)) {
                    data.messages.forEach(item => appendMessage(item.role, item.content))
                    conversationScroll.scrollTo({
                        top: conversationScroll.scrollHeight,
                        behavior: "smooth"
                    })
                    input.value = ""
                    if (data.session_id) {
                        const list = document.getElementById("conversations-list")
                        const item = document.querySelector(`.conversation-item[data-id="${data.session_id}"]`)
                        if (list && item) {
                            const timeEl = item.querySelector(".conversation-time")
                            if (timeEl) {
                                timeEl.textContent = "Just now"
                            }
                            list.prepend(item)
                        }
                    }
                }
            } catch (error) {
                form.submit()
            }
        })
    }

    const filterButton = document.getElementById("memory-filter-btn")
    const filterMenu = document.getElementById("memory-filter-menu")
    const filterInput = document.getElementById("memory-type-input")
    const sortButton = document.getElementById("memory-sort-btn")
    const sortMenu = document.getElementById("memory-sort-menu")
    const sortInput = document.getElementById("memory-sort-input")
    if (filterButton && filterMenu && filterInput) {
        filterButton.addEventListener("click", (event) => {
            event.stopPropagation()
            const isOpen = filterMenu.classList.contains("is-open")
            filterMenu.classList.toggle("is-open", !isOpen)
            filterButton.setAttribute("aria-expanded", String(!isOpen))
        })
        filterMenu.querySelectorAll(".memory-filter-item").forEach((item) => {
            item.addEventListener("click", () => {
                filterInput.value = item.dataset.value || ""
                filterMenu.classList.remove("is-open")
                filterButton.setAttribute("aria-expanded", "false")
                if (filterButton.closest("form")) {
                    filterButton.closest("form").submit()
                }
            })
        })
        document.addEventListener("click", () => {
            filterMenu.classList.remove("is-open")
            filterButton.setAttribute("aria-expanded", "false")
        })
    }

    if (sortButton && sortMenu && sortInput) {
        sortButton.addEventListener("click", (event) => {
            event.stopPropagation()
            const isOpen = sortMenu.classList.contains("is-open")
            sortMenu.classList.toggle("is-open", !isOpen)
            sortButton.setAttribute("aria-expanded", String(!isOpen))
        })
        sortMenu.querySelectorAll(".memory-sort-item").forEach((item) => {
            item.addEventListener("click", () => {
                sortInput.value = item.dataset.value || ""
                sortMenu.classList.remove("is-open")
                sortButton.setAttribute("aria-expanded", "false")
                if (sortButton.closest("form")) {
                    sortButton.closest("form").submit()
                }
            })
        })
        document.addEventListener("click", () => {
            sortMenu.classList.remove("is-open")
            sortButton.setAttribute("aria-expanded", "false")
        })
    }
})

function getCSRFToken() {
    const cookie = document.cookie.split("; ").find(c => c.startsWith("csrftoken="))
    if (cookie) return cookie.split("=")[1]
    const meta = document.querySelector("meta[name='csrf-token']")
    if (meta) return meta.content
    const input = document.querySelector("input[name='csrfmiddlewaretoken']")
    if (input) return input.value
    return ""
}

function getAppRoutes() {
    const defaults = {
        home: "/home/",
        chatMemory: "/chat/memory/",
        chatAnalytics: "/chat/analytics/",
        chatDashboard: "/chat/dashboard/",
        chatMyAgent: "/chat/agents/my/",
        chatActivityLog: "/chat/activity/",
        chatDocumentUpload: "/chat/document/upload/",
        chatSessionsApi: "/chat/api/sessions/",
        chatSemanticSearchApi: "/chat/api/semantic-search/",
        chatConversationDetailTemplate: "/chat/c/0/",
        chatSessionRenameTemplate: "/chat/c/0/rename/",
        chatSessionDeleteTemplate: "/chat/c/0/delete/",
        chatMemoryDetailTemplate: "/chat/m/0/",
    }
    return { ...defaults, ...(window.APP_ROUTES || {}) }
}

function routeFromTemplate(template, id) {
    return template.replace("/0/", `/${id}/`)
}

function initHeaderNav() {
    const path = window.location.pathname
    const routes = getAppRoutes()
    const headerLinks = document.querySelectorAll("[data-header-nav]")

    headerLinks.forEach(link => {
        const key = link.dataset.headerNav
        let isActive = false

        if (key === "chat") {
            const homeNoSlash = routes.home.endsWith("/") ? routes.home.slice(0, -1) : routes.home
            const convPrefix = routes.chatConversationDetailTemplate.replace("0/", "")
            isActive = path === routes.home || path === homeNoSlash || path.startsWith(convPrefix)
        } else if (key === "analytics") {
            isActive = path.startsWith(routes.chatAnalytics)
        } else if (key === "agents") {
            isActive = path.startsWith("/chat/agents/")
        }

        if (isActive) {
            link.classList.remove("text-mm-muted")
            link.classList.add("text-mm-primary")
        } else {
            link.classList.add("text-mm-muted")
            link.classList.remove("text-mm-primary")
        }
    })
}

function initSidebarNav() {
    const path = window.location.pathname
    const routes = getAppRoutes()
    const sidebarLinks = document.querySelectorAll("[data-sidebar-nav]")

    sidebarLinks.forEach(link => {
        const key = link.dataset.sidebarNav
        let isActive = false

        if (key === "chat") {
            const homeNoSlash = routes.home.endsWith("/") ? routes.home.slice(0, -1) : routes.home
            const convPrefix = routes.chatConversationDetailTemplate.replace("0/", "")
            isActive = path === routes.home || path === homeNoSlash || path.startsWith(convPrefix)
        } else if (key === "memory") {
            const memoryDetailPrefix = routes.chatMemoryDetailTemplate.replace("0/", "")
            isActive = path.startsWith(routes.chatMemory) || path.startsWith(memoryDetailPrefix)
        } else if (key === "analytics") {
            isActive = path.startsWith(routes.chatAnalytics)
        } else if (key === "dashboard") {
            isActive = path.startsWith(routes.chatDashboard)
        } else if (key === "agents") {
            isActive = path.startsWith("/chat/agents/") && !path.startsWith("/chat/agents/marketplace")
        } else if (key === "activity") {
            isActive = path.startsWith(routes.chatActivityLog)
        } else if (key === "documents") {
            isActive = path.startsWith(routes.chatDocumentUpload)
        } else if (key === "teams") {
            isActive = path.startsWith("/chat/agents/marketplace")
        } else if (key === "groups") {
            isActive = path.startsWith("/chat/groups")
        }

        link.classList.toggle("is-active", isActive)
    })
}

function renameConversation(id) {
    const routes = getAppRoutes()
    const item = document.querySelector(`.conv-sidebar-item[data-id="${id}"]`)
    if (!item) return
    const actionsEl = item.querySelector(".conv-sidebar-actions")
    const currentTitle = item.querySelector(".conv-sidebar-title").textContent.trim()

    if (actionsEl) actionsEl.style.display = "none"

    const contentEl = item.querySelector(".conv-sidebar-content")
    const originalContent = contentEl.innerHTML

    const wrapper = document.createElement("div")
    wrapper.className = "flex items-center gap-2 px-1"

    const input = document.createElement("input")
    input.type = "text"
    input.value = currentTitle
    input.className = "flex-1 min-w-0 rounded border border-mm-border bg-white px-2 py-1 text-sm font-inter focus:outline-none focus:ring-1 focus:ring-mm-primary"

    const saveBtn = document.createElement("button")
    saveBtn.innerHTML = '<svg class="w-4 h-4 text-green-600" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" /></svg>'
    saveBtn.className = "flex-shrink-0 p-1 rounded hover:bg-mm-hover"

    wrapper.appendChild(input)
    wrapper.appendChild(saveBtn)

    contentEl.innerHTML = ""
    contentEl.appendChild(wrapper)

    input.focus()
    input.select()

    let isSaving = false

    const saveEdit = async () => {
        if (isSaving) return
        const newTitle = input.value.trim()
        if (!newTitle) {
            cancelEdit()
            return
        }
        isSaving = true
        try {
            const formData = new FormData()
            formData.append("title", newTitle)
            const res = await fetch(routeFromTemplate(routes.chatSessionRenameTemplate, id), {
                method: "POST",
                headers: { "X-CSRFToken": getCSRFToken() },
                body: formData,
            })
            const data = await res.json()
            if (!res.ok || !data.ok) {
                cancelEdit()
                return
            }
            const confirmedTitle = data.title
            contentEl.innerHTML = originalContent
            const titleEl = contentEl.querySelector(".conv-sidebar-title")
            if (titleEl) titleEl.textContent = confirmedTitle
            const avatarEl = item.querySelector(".conv-sidebar-avatar")
            if (avatarEl) avatarEl.textContent = confirmedTitle.charAt(0)
            if (actionsEl) actionsEl.style.display = ""
            syncHeaderTitle(id, confirmedTitle)
        } catch (_) {
            cancelEdit()
        }
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
        if (e.relatedTarget !== saveBtn) saveEdit()
    }
}

function syncHeaderTitle(sessionId, title) {
    const headerTitle = document.getElementById("conv-header-title")
    if (headerTitle && headerTitle.dataset.sessionId === String(sessionId)) {
        headerTitle.textContent = title
    }
}

function handleAutoTitle(sessionId, title) {
    const sidebarItem = document.querySelector(`.conv-sidebar-item[data-id="${sessionId}"]`)
    if (sidebarItem) {
        const titleEl = sidebarItem.querySelector(".conv-sidebar-title")
        if (titleEl) titleEl.textContent = title
        const avatarEl = sidebarItem.querySelector(".conv-sidebar-avatar")
        if (avatarEl) avatarEl.textContent = title.charAt(0)
    }
    syncHeaderTitle(sessionId, title)
}

function deleteConversation(id) {
    const routes = getAppRoutes()
    if (!confirm("Are you sure you want to delete this conversation?")) return
    const item = document.querySelector(`.conv-sidebar-item[data-id="${id}"]`)
    if (item) item.remove()
    fetch(routeFromTemplate(routes.chatSessionDeleteTemplate, id), {
        method: "POST",
        headers: { "X-CSRFToken": getCSRFToken() }
    }).then(res => {
        if (res.ok) {
            const conversationPrefix = routes.chatConversationDetailTemplate.replace("0/", "")
            const pattern = new RegExp(`^${conversationPrefix.replace(/\//g, "\\/")}(\\d+)\\/`)
            const match = window.location.pathname.match(pattern)
            if (match && match[1] === String(id)) {
                const remaining = document.querySelectorAll(".conv-sidebar-item")
                if (remaining.length > 0) {
                    const firstLink = remaining[0].querySelector("a")
                    if (firstLink) {
                        window.location.href = firstLink.href
                        return
                    }
                }
                window.location.href = routes.home
            }
        }
    }).catch(() => {})
}

function initContextMenu() {
    const sidebar = document.querySelector("[data-conv-sidebar]")
    const menu = document.getElementById("conv-context-menu")
    const overlay = document.getElementById("conv-context-overlay")
    if (!sidebar || !menu || !overlay) return

    let activeConversationId = null

    function showContextMenu(e, conversationId) {
        e.preventDefault()
        e.stopPropagation()
        activeConversationId = conversationId

        const sidebarRect = sidebar.getBoundingClientRect()
        const menuWidth = 180
        const menuHeight = 90
        const padding = 8

        let x = e.clientX - sidebarRect.left
        let y = e.clientY - sidebarRect.top

        if (x + menuWidth > sidebarRect.width) {
            x = sidebarRect.width - menuWidth - padding
        }
        if (y + menuHeight > sidebarRect.height) {
            y = sidebarRect.height - menuHeight - padding
        }

        menu.style.left = x + "px"
        menu.style.top = y + "px"
        menu.classList.remove("hidden")
        overlay.classList.remove("hidden")
    }

    function hideContextMenu() {
        menu.classList.add("hidden")
        overlay.classList.add("hidden")
        activeConversationId = null
    }

    window.showContextMenu = showContextMenu
    window.hideContextMenu = hideContextMenu

    overlay.addEventListener("click", hideContextMenu)

    document.addEventListener("click", (e) => {
        if (!menu.classList.contains("hidden") && !menu.contains(e.target)) {
            hideContextMenu()
        }
    })

    menu.querySelector("[data-action='rename']").addEventListener("click", () => {
        const id = activeConversationId
        hideContextMenu()
        renameConversation(id)
    })

    menu.querySelector("[data-action='delete']").addEventListener("click", () => {
        const id = activeConversationId
        hideContextMenu()
        deleteConversation(id)
    })

    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && !menu.classList.contains("hidden")) {
            e.stopPropagation()
            hideContextMenu()
        }
    })
}

function createNewChat() {
    const routes = getAppRoutes()
    window.location.href = routes.home
}

function initSearchModal() {
    const routes = getAppRoutes()
    const modal = document.getElementById("search-modal")
    const input = document.getElementById("search-modal-input")
    const resultsEl = document.getElementById("search-modal-results")
    const emptyEl = document.getElementById("search-modal-empty")
    if (!modal || !input) return

    let debounceTimer = null

    function open() {
        document.documentElement.classList.add("search-modal-open")
        document.body.classList.add("search-modal-open")
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
        document.documentElement.classList.remove("search-modal-open")
        document.body.classList.remove("search-modal-open")
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

    function renderSessionResult(s) {
        const a = document.createElement("a")
        a.href = s.url
        a.className = "flex flex-col gap-0.5 px-3 py-2.5 rounded-lg text-inherit no-underline transition-colors hover:bg-mm-hover"
        const title = document.createElement("span")
        title.className = "font-inter text-[14px] font-medium text-mm-text"
        title.textContent = s.title || "Untitled"
        const time = document.createElement("span")
        time.className = "font-inter text-[12px] text-mm-light"
        time.textContent = new Date(s.updated_at).toLocaleDateString()
        a.appendChild(title)
        a.appendChild(time)
        return a
    }

    function renderMemoryResult(m) {
        const a = document.createElement("a")
        a.href = routes.chatMemory
        a.className = "flex flex-col gap-0.5 px-3 py-2.5 rounded-lg text-inherit no-underline transition-colors hover:bg-mm-hover"
        const content = document.createElement("span")
        content.className = "font-inter text-[14px] font-medium text-mm-text truncate"
        content.textContent = m.content.length > 80 ? m.content.slice(0, 80) + "..." : m.content
        const meta = document.createElement("span")
        meta.className = "font-inter text-[12px] text-mm-light"
        meta.textContent = `Similarity: ${(m.similarity * 100).toFixed(0)}% \u00b7 ${m.topic || "Memory"}`
        a.appendChild(content)
        a.appendChild(meta)
        return a
    }

    function renderSectionHeader(text) {
        const header = document.createElement("div")
        header.className = "font-inter text-[11px] font-semibold text-mm-muted uppercase tracking-[0.5px] px-3 py-2 mt-1"
        header.textContent = text
        return header
    }

    input.addEventListener("input", () => {
        clearTimeout(debounceTimer)
        const q = input.value.trim()
        if (!q) {
            resultsEl.innerHTML = ""
            emptyEl.classList.add("hidden")
            return
        }
        debounceTimer = setTimeout(() => {
            const sessionsPromise = fetch(`${routes.chatSessionsApi}?q=${encodeURIComponent(q)}`)
                .then(r => r.json()).catch(() => ({ results: [] }))
            const semanticPromise = fetch(`${routes.chatSemanticSearchApi}?q=${encodeURIComponent(q)}&top_k=5`)
                .then(r => r.json()).catch(() => ({ results: [] }))

            Promise.all([sessionsPromise, semanticPromise]).then(([sessionData, memoryData]) => {
                resultsEl.innerHTML = ""
                const sessions = sessionData.results || []
                const memories = (memoryData.results || []).filter(m => m.similarity >= 0.30)
                if (sessions.length === 0 && memories.length === 0) {
                    emptyEl.classList.remove("hidden")
                    return
                }
                emptyEl.classList.add("hidden")
                if (sessions.length > 0) {
                    resultsEl.appendChild(renderSectionHeader("Conversations"))
                    sessions.forEach(s => resultsEl.appendChild(renderSessionResult(s)))
                }
                if (memories.length > 0) {
                    resultsEl.appendChild(renderSectionHeader("Semantic Matches"))
                    memories.forEach(m => resultsEl.appendChild(renderMemoryResult(m)))
                }
            })
        }, 300)
    })

    window.openSearchModal = open
    window.closeSearchModal = close
}

function initMobileNav() {
    const path = window.location.pathname
    const routes = getAppRoutes()
    const mobileLinks = document.querySelectorAll("[data-mobile-nav]")

    mobileLinks.forEach(link => {
        const key = link.dataset.mobileNav
        let isActive = false

        if (key === "chat") {
            const homeNoSlash = routes.home.endsWith("/") ? routes.home.slice(0, -1) : routes.home
            const convPrefix = routes.chatConversationDetailTemplate.replace("0/", "")
            isActive = path === routes.home || path === homeNoSlash || path.startsWith(convPrefix)
        } else if (key === "agent") {
            isActive = path.startsWith("/chat/agents/")
        }

        link.classList.toggle("is-active", isActive)
    })
}

function initConversationSidebarSearch() {
    const searchInput = document.getElementById("conv-sidebar-search")
    if (!searchInput) return

    searchInput.addEventListener("input", () => {
        const query = searchInput.value.trim().toLowerCase()
        const items = document.querySelectorAll(".conv-sidebar-item")
        items.forEach(item => {
            const title = item.querySelector(".conv-sidebar-title")
            if (!title) return
            const matches = !query || title.textContent.toLowerCase().includes(query)
            item.style.display = matches ? "" : "none"
        })
    })
}

function toggleConvSidebar() {
    const sidebar = document.querySelector("[data-conv-sidebar]")
    if (!sidebar) return
    const isHidden = sidebar.classList.contains("max-lg:hidden")
    if (isHidden) {
        sidebar.classList.remove("max-lg:hidden")
        sidebar.classList.add("fixed", "inset-0", "z-50", "w-full")
    } else {
        sidebar.classList.add("max-lg:hidden")
        sidebar.classList.remove("fixed", "inset-0", "z-50", "w-full")
    }
}

document.addEventListener("DOMContentLoaded", () => {
    initSidebarNav()
    initMobileNav()
    initSearchModal()
    initConversationSidebarSearch()
    initContextMenu()

    document.addEventListener("keydown", function(e) {
        if ((e.ctrlKey || e.metaKey) && e.key === "n") {
            e.preventDefault()
            createNewChat()
        }
        if ((e.ctrlKey || e.metaKey) && e.key === "k") {
            e.preventDefault()
            if (window.openSearchModal) window.openSearchModal()
        }
    })

    window.toggleConvSidebar = toggleConvSidebar
    window.renameConversation = renameConversation
    window.deleteConversation = deleteConversation
    window.createNewChat = createNewChat

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

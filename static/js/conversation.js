document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("conversation-form");
  const messages = document.getElementById("conversation-messages");
  const input = document.getElementById("conversation-message-input");
  const submitButton = document.getElementById("conversation-submit-button");
  const addButton = document.getElementById("conversation-add-button");
  if (!form || !messages || !input || !submitButton || !addButton) {
    return;
  }

  let isStreaming = false;
  let lastStreamedMessageId = null;
  let streamCooldown = false;
  let activeStreamAbort = null;
  const pendingAgentTurns = [];
  const currentUserId = form.dataset.currentUserId || "";
  const defaultAgentName = form.dataset.initialAgentName || "Assistant";
  const initialGenerationInProgress = form.dataset.generationInProgress === "1";
  const lockWaitUrl = form.dataset.lockWaitUrl || "";
  const streamSubscribeUrl = form.dataset.streamSubscribeUrl || "";
  const streamDebug =
    new URLSearchParams(window.location.search).get("stream_debug") === "1" ||
    window.localStorage.getItem("chat_stream_debug") === "1";

  const debugLog = (...args) => {
    if (streamDebug) {
      console.log("[chat-stream]", ...args);
    }
  };

  let pendingScrollFrame = null;
  const scrollToBottom = (smooth = false) => {
    if (pendingScrollFrame) return;
    pendingScrollFrame = requestAnimationFrame(() => {
      pendingScrollFrame = null;
      messages.scrollTo({ top: messages.scrollHeight, behavior: smooth ? "smooth" : "auto" });
    });
  };

  const removeEmptyState = () => {
    const emptyState = document.getElementById("empty-state");
    if (emptyState) {
      emptyState.remove();
    }
  };

  const createTypingDots = () => {
    const dots = document.createElement("span");
    dots.className = "conversation-typing-dots";
    dots.setAttribute("aria-hidden", "true");
    for (let index = 0; index < 3; index += 1) {
      dots.appendChild(document.createElement("span"));
    }
    return dots;
  };

  const copyText = async (text) => {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text);
      return;
    }
    const textArea = document.createElement("textarea");
    textArea.value = text;
    textArea.setAttribute("readonly", "");
    textArea.style.position = "absolute";
    textArea.style.left = "-9999px";
    document.body.appendChild(textArea);
    textArea.select();
    document.execCommand("copy");
    textArea.remove();
  };

  const decorateCodeBlocks = (root) => {
    const target = root || messages;
    target.querySelectorAll(".message-content-markdown pre").forEach((pre) => {
      if (pre.dataset.copyReady === "1") {
        return;
      }
      const code = pre.querySelector("code");
      if (!code) {
        return;
      }
      pre.dataset.copyReady = "1";

      const wrapper = document.createElement("div");
      wrapper.className = "chat-code-block";
      pre.parentNode.insertBefore(wrapper, pre);
      wrapper.appendChild(pre);

      const copyButton = document.createElement("button");
      copyButton.type = "button";
      copyButton.className = "chat-code-copy-button";
      copyButton.textContent = "Copy";
      copyButton.addEventListener("click", async () => {
        const original = copyButton.textContent;
        try {
          await copyText(code.textContent || "");
          copyButton.textContent = "Copied";
          copyButton.classList.add("is-copied");
        } catch (_) {
          copyButton.textContent = "Failed";
        } finally {
          window.setTimeout(() => {
            copyButton.textContent = original;
            copyButton.classList.remove("is-copied");
          }, 1200);
        }
      });
      wrapper.appendChild(copyButton);
    });
  };

  const extractVisibleTextFromHtml = (html) => {
    if (!html) {
      return "";
    }
    const tmp = document.createElement("div");
    tmp.innerHTML = html;
    return (tmp.textContent || "").replace(/\u00A0/g, " ").trim();
  };

  const hasVisibleAssistantContent = (content, html, node) => {
    if ((content || "").trim().length > 0) {
      return true;
    }
    if (extractVisibleTextFromHtml(html).length > 0) {
      return true;
    }
    return ((node && node.textContent) || "").trim().length > 0;
  };

  const currentUserName = form.dataset.currentUserName || "You";
  const currentUserInitial = (form.dataset.currentUserInitial || currentUserName.charAt(0) || "Y").toUpperCase();
  const currentUserAvatarUrl = form.dataset.currentUserAvatarUrl || "";

  const appendMessage = (role, content = "", options = {}) => {
    removeEmptyState();

    const container = document.getElementById("message-list") || messages;

    const row = document.createElement("div");
    row.className = `flex gap-3 chat-msg-row chat-message-appear ${role === "user" ? "flex-row-reverse" : ""}`;

    const senderName = options.senderName || (role === "user" ? currentUserName : (defaultAgentName || "Assistant"));
    const senderInitial = role === "user"
      ? currentUserInitial
      : (senderName.charAt(0) || "A").toUpperCase();

    const fallbackAvatarClass = role === "user"
      ? "flex-shrink-0 w-9 h-9 rounded-full flex items-center justify-center text-white font-semibold text-[13px] bg-gradient-to-br from-[#6C86C0] to-[#6C86C0] shadow-sm"
      : "flex-shrink-0 w-9 h-9 rounded-full flex items-center justify-center text-white font-semibold text-[13px] bg-gradient-to-br from-slate-600 to-slate-700 shadow-sm";

    let avatar;
    if (role === "user" && currentUserAvatarUrl) {
      avatar = document.createElement("img");
      avatar.src = currentUserAvatarUrl;
      avatar.alt = "";
      avatar.className = "flex-shrink-0 w-9 h-9 rounded-full object-cover shadow-sm";
      // If the avatar URL 404s (common with stale Google-hosted URLs or when
      // the user's profile_img path is served from a different origin), swap
      // in the initial-based fallback so we never render a broken-image icon.
      avatar.addEventListener("error", () => {
        const fallback = document.createElement("div");
        fallback.className = fallbackAvatarClass;
        fallback.textContent = senderInitial;
        avatar.replaceWith(fallback);
      });
    } else {
      avatar = document.createElement("div");
      avatar.className = fallbackAvatarClass;
      avatar.textContent = senderInitial;
    }

    const contentWrapper = document.createElement("div");
    contentWrapper.className = `flex-1 flex flex-col max-w-full sm:max-w-[85%] md:max-w-[75%] ${role === "user" ? "items-end" : ""}`;

    const meta = document.createElement("div");
    meta.className = "flex items-center gap-2 mb-1";
    const sender = document.createElement("div");
    sender.className = "font-inter font-semibold text-mm-text text-[13px] leading-5";
    sender.textContent = senderName;
    sender.dataset.senderLabel = "true";
    const time = document.createElement("div");
    time.className = "font-inter text-mm-light text-[11px] leading-4";
    time.textContent = new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
    meta.appendChild(sender);
    meta.appendChild(time);

    const bubble = document.createElement("div");
    bubble.className = role === "user"
      ? "bg-gradient-to-br from-[#6C86C0] to-[#6C86C0] text-white shadow-[0_2px_12px_rgba(108,134,192,0.2)] rounded-[18px] rounded-br-[4px] px-4 py-3 border border-white/20"
      : "bg-white shadow-sm text-slate-700 rounded-[18px] rounded-bl-[4px] px-4 py-3 border border-white/20";

    const contentNode = document.createElement(role === "assistant" ? "div" : "span");
    contentNode.className = role === "assistant"
      ? "message-content message-content-markdown font-inter text-[14px] leading-6"
      : "message-content font-inter text-[14px] leading-6 whitespace-pre-wrap";
    contentNode.textContent = content;
    bubble.appendChild(contentNode);

    let dotsNode = null;
    if (options.pending) {
      const thinkingWrap = document.createElement("div");
      thinkingWrap.className = "flex items-center gap-3";
      const dotsWrap = document.createElement("div");
      dotsWrap.className = "flex items-center gap-1";
      for (let i = 0; i < 3; i++) {
        const dot = document.createElement("div");
        dot.className = "h-2 w-2 animate-bounce rounded-full bg-mm-light";
        dot.style.animationDelay = `${-0.3 + i * 0.15}s`;
        dotsWrap.appendChild(dot);
      }
      const thinkText = document.createElement("span");
      thinkText.className = "text-sm text-mm-muted font-inter";
      thinkText.textContent = "is thinking...";
      thinkingWrap.appendChild(dotsWrap);
      thinkingWrap.appendChild(thinkText);
      bubble.appendChild(thinkingWrap);
      dotsNode = thinkingWrap;
    }

    contentWrapper.appendChild(meta);
    contentWrapper.appendChild(bubble);

    const actionsDiv = document.createElement("div");
    actionsDiv.className = "chat-message-actions flex gap-1 mt-1";

    const copyBtn = document.createElement("button");
    copyBtn.type = "button";
    copyBtn.className = "msg-action-copy p-1 rounded-md hover:bg-white/40 text-slate-400 hover:text-slate-600 transition-colors";
    copyBtn.title = "Copy message";
    copyBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"></path></svg>';
    actionsDiv.appendChild(copyBtn);

    if (role === "user") {
      const editBtn = document.createElement("button");
      editBtn.type = "button";
      editBtn.className = "msg-action-edit p-1 rounded-md hover:bg-white/40 text-slate-400 hover:text-slate-600 transition-colors";
      editBtn.title = "Edit text";
      editBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>';
      actionsDiv.appendChild(editBtn);

      const resendBtn = document.createElement("button");
      resendBtn.type = "button";
      resendBtn.className = "msg-action-resend p-1 rounded-md hover:bg-white/40 text-slate-400 hover:text-slate-600 transition-colors";
      resendBtn.title = "Resend message";
      resendBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"></polyline><path d="M20.49 15a9 9 0 11-2.12-9.36L23 10"></path></svg>';
      actionsDiv.appendChild(resendBtn);
    }

    contentWrapper.appendChild(actionsDiv);

    row.appendChild(avatar);
    row.appendChild(contentWrapper);
    container.appendChild(row);

    if (role === "assistant") {
      decorateCodeBlocks(contentNode);
    }
    scrollToBottom();

    return { bubble, contentNode, dotsNode };
  };

  const setStreamingState = (streaming) => {
    isStreaming = streaming;
    input.disabled = streaming;
    submitButton.disabled = streaming;
    addButton.disabled = streaming;
    if (streaming) {
      submitButton.classList.add("opacity-50", "cursor-not-allowed");
    } else {
      submitButton.classList.remove("opacity-50", "cursor-not-allowed");
    }
  };

  const renderLatex = (el) => {
    if (typeof renderMathInElement !== "function" || !el) return;
    const targets = el.classList && (el.classList.contains("math-inline") || el.classList.contains("math-block"))
      ? [el]
      : Array.from(el.querySelectorAll(".math-inline, .math-block"));
    targets.forEach((target) => {
      try {
        renderMathInElement(target, {
          delimiters: [
            { left: "$$", right: "$$", display: true },
            { left: "$", right: "$", display: false },
          ],
          throwOnError: false,
        });
      } catch (_) {}
    });
  };

  const updateAssistantBubble = (assistantUi, content, html = "") => {
    if (html) {
      assistantUi.contentNode.innerHTML = html;
      assistantUi.streamTextNode = null;
      decorateCodeBlocks(assistantUi.contentNode);
      renderLatex(assistantUi.contentNode);
    } else {
      assistantUi.contentNode.textContent = content;
      assistantUi.streamTextNode = null;
    }
    const hasContent = hasVisibleAssistantContent(content, html, assistantUi.contentNode);
    if (assistantUi.dotsNode) {
      if (hasContent) {
        assistantUi.dotsNode.remove();
        assistantUi.dotsNode = null;
      } else {
        assistantUi.dotsNode.hidden = false;
      }
    }
    scrollToBottom();
  };

  const appendStreamChunk = (assistantUi, chunk) => {
    if (!chunk) return;
    if (assistantUi.dotsNode) {
      assistantUi.dotsNode.remove();
      assistantUi.dotsNode = null;
    }
    if (!assistantUi.streamTextNode) {
      assistantUi.contentNode.textContent = "";
      const textNode = document.createTextNode("");
      assistantUi.contentNode.appendChild(textNode);
      assistantUi.streamTextNode = textNode;
    }
    assistantUi.streamTextNode.appendData(chunk);
    scrollToBottom();
  };

  const readStream = async (response, onPayload) => {
    const reader = response.body && response.body.getReader ? response.body.getReader() : null;
    if (!reader) {
      throw new Error("Streaming is not available for this response.");
    }

    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
      debugLog("chunk-received", { byteLength: value ? value.length : 0, done });

      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed) {
          continue;
        }
        try {
          onPayload(JSON.parse(trimmed));
        } catch (error) {
          debugLog("invalid-ndjson-line", { line: trimmed.slice(0, 200), error: String(error) });
        }
      }

      if (done) {
        break;
      }
    }

    const tail = buffer.trim();
    if (tail) {
      try {
        onPayload(JSON.parse(tail));
      } catch (error) {
        debugLog("invalid-ndjson-tail", { line: tail.slice(0, 200), error: String(error) });
      }
    }
  };

  const submitMessage = async (prefilledMessage = "") => {
    if (isStreaming) {
      return;
    }

    const content = (prefilledMessage || input.value).trim();
    if (!content) {
      return;
    }

    const csrfToken = form.querySelector('input[name="csrfmiddlewaretoken"]')?.value || "";
    const streamUrl = form.dataset.streamUrl;
    let assistantText = "";
    let assistantHtml = "";

    appendMessage("user", content);

    let initialAgentName = defaultAgentName;
    const expandedMatch = content.match(
      /@([A-Z][a-zA-Z]*(?:'[a-zA-Z]+)?(?:\s+[A-Z][a-zA-Z]*(?:'[a-zA-Z]+)?){0,4})(?:'s\s+[Aa]gent)?/
    );
    const compactMatch = content.match(/@([A-Za-z][\w']*)/);
    const mentionRaw = (expandedMatch && expandedMatch[1]) || (compactMatch && compactMatch[1]) || "";
    if (mentionRaw && cachedAgents) {
      const partial = mentionRaw.toLowerCase().replace(/['\s]/g, "");
      const matched = cachedAgents.find(a =>
        a.name.toLowerCase().replace(/['\s]/g, "").startsWith(partial)
      );
      if (matched) initialAgentName = matched.name;
    } else if (mentionRaw) {
      initialAgentName = mentionRaw.includes(" ") ? mentionRaw : mentionRaw + "'s Agent";
    }

    const assistantUi = appendMessage("assistant", "", { pending: true, senderName: initialAgentName });
    input.value = "";
    sessionStorage.removeItem(draftKey);
    setStreamingState(true);
    let currentStreamAgent = initialAgentName;
    addThinker(initialAgentName);
    debugLog("request-start", { streamUrl, promptLength: content.length });

    const abortController = new AbortController();
    const streamTimeoutId = setTimeout(() => abortController.abort(), 90000);
    activeStreamAbort = abortController;

    try {
      const response = await fetch(streamUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
          "X-CSRFToken": csrfToken,
          "X-Requested-With": "XMLHttpRequest",
        },
        body: new URLSearchParams({ message: content }),
        signal: abortController.signal,
      });

      if (!response.ok) {
        if (response.status === 409) {
          throw new Error("Previous response is still generating.");
        }
        throw new Error(`Request failed with status ${response.status}`);
      }
      debugLog("response-open", { status: response.status });

      await readStream(response, (payload) => {
        debugLog("payload", {
          type: payload.type,
          contentLength: (payload.content || "").length,
          hasHtml: Boolean(payload.html),
        });
        if (payload.auto_title && payload.session_id) {
          if (typeof handleAutoTitle === "function") {
            handleAutoTitle(payload.session_id, payload.auto_title);
          }
        }
        if (payload.type === "delta") {
          if (payload.agentName && payload.agentName !== currentStreamAgent) {
            removeThinker(currentStreamAgent);
            currentStreamAgent = payload.agentName;
            initialAgentName = payload.agentName;
            const senderLabel = assistantUi.bubble.closest(".chat-msg-row")?.querySelector("[data-sender-label]");
            if (senderLabel) senderLabel.textContent = payload.agentName;
            addThinker(payload.agentName);
          }
          const chunk = payload.content || "";
          assistantText += chunk;
          if (payload.html) {
            assistantHtml = payload.html;
            updateAssistantBubble(assistantUi, assistantText, assistantHtml);
          } else {
            appendStreamChunk(assistantUi, chunk);
          }
          return;
        }

        if (payload.type === "done") {
          assistantText = payload.content || assistantText;
          assistantHtml = payload.html || assistantHtml;
          updateAssistantBubble(assistantUi, assistantText, assistantHtml);
          removeThinker(currentStreamAgent);
          scrollToBottom();
          if (payload.message_id) {
            lastStreamedMessageId = payload.message_id;
          }
          if (payload.agentName) {
            const senderLabel = assistantUi.bubble.closest(".chat-msg-row")?.querySelector("[data-sender-label]");
            if (senderLabel) senderLabel.textContent = payload.agentName;
            const avatarEl = assistantUi.bubble.closest(".chat-msg-row")?.querySelector(".rounded-full, .rounded-\\[12px\\]");
            if (avatarEl) avatarEl.textContent = payload.agentName.charAt(0).toUpperCase();
          }
        }

        if (payload.type === "agent_turn") {
          const turnName = payload.agentName || "Agent";
          addThinker(turnName);
          pendingAgentTurns.push({ payload });
        }
      });
      if (!hasVisibleAssistantContent(assistantText, assistantHtml, assistantUi.contentNode)) {
        const fallbackMessage = "Sorry, generation finished without visible content.";
        debugLog("empty-visible-content-after-stream", {
          textLength: assistantText.length,
          htmlLength: assistantHtml.length,
        });
        updateAssistantBubble(assistantUi, fallbackMessage);
      }
    } catch (error) {
      debugLog("request-error", String(error));
      updateAssistantBubble(
        assistantUi,
        (error && error.message) || "Sorry, I couldn't reach the AI service just now."
      );
    } finally {
      clearTimeout(streamTimeoutId);
      if (activeStreamAbort === abortController) {
        activeStreamAbort = null;
      }
      debugLog("request-end");

      const revealAgentTurns = () => {
        if (pendingAgentTurns.length === 0) {
          clearThinkers();
          streamCooldown = true;
          setStreamingState(false);
          setTimeout(() => { streamCooldown = false; }, 3000);
          input.focus();
          return;
        }
        const { payload } = pendingAgentTurns.shift();
        const turnName = payload.agentName || "Agent";
        const turnUi = appendMessage("assistant", "", { senderName: turnName });
        updateAssistantBubble(turnUi, payload.content || "", payload.html || "");
        removeThinker(turnName);
        if (payload.message_id) lastStreamedMessageId = payload.message_id;
        scrollToBottom();
        if (pendingAgentTurns.length > 0) {
          setTimeout(revealAgentTurns, 800);
        } else {
          clearThinkers();
          streamCooldown = true;
          setStreamingState(false);
          setTimeout(() => { streamCooldown = false; }, 3000);
          input.focus();
        }
      };

      if (pendingAgentTurns.length > 0) {
        setTimeout(revealAgentTurns, 600);
      } else {
        hideTypingIndicator();
        streamCooldown = true;
        setStreamingState(false);
        setTimeout(() => { streamCooldown = false; }, 3000);
        input.focus();
      }
    }
  };

  const waitForUnlock = async () => {
    if (!lockWaitUrl) {
      return;
    }
    try {
      const response = await fetch(`${lockWaitUrl}?timeout=55`, {
        headers: { "X-Requested-With": "XMLHttpRequest" },
        cache: "no-store",
      });
      if (!response.ok) {
        window.setTimeout(waitForUnlock, 3000);
        return;
      }
      const payload = await response.json();
      if (!payload.generation_in_progress) {
        window.location.reload();
        return;
      }
      if (payload.timed_out) {
        window.setTimeout(waitForUnlock, 2000);
      }
    } catch (_) {
      window.setTimeout(waitForUnlock, 3000);
    }
  };

  const reconnectToLiveStream = async () => {
    if (!streamSubscribeUrl) {
      waitForUnlock();
      return;
    }
    setStreamingState(true);
    const assistantUi = appendMessage("assistant", "", { pending: true });
    let assistantText = "";
    let assistantHtml = "";
    let receivedAny = false;
    try {
      const response = await fetch(streamSubscribeUrl, {
        headers: { "X-Requested-With": "XMLHttpRequest" },
        cache: "no-store",
      });
      if (!response.ok) {
        throw new Error(`subscribe failed with status ${response.status}`);
      }
      await readStream(response, (payload) => {
        if (payload.type === "heartbeat") {
          return;
        }
        receivedAny = true;
        if (payload.type === "delta") {
          const chunk = payload.content || "";
          assistantText += chunk;
          if (payload.html) {
            assistantHtml = payload.html;
            updateAssistantBubble(assistantUi, assistantText, assistantHtml);
          } else {
            appendStreamChunk(assistantUi, chunk);
          }
          return;
        }
        if (payload.type === "done") {
          assistantText = payload.content || assistantText;
          assistantHtml = payload.html || assistantHtml;
          updateAssistantBubble(assistantUi, assistantText, assistantHtml);
        }
        if (payload.type === "error") {
          updateAssistantBubble(
            assistantUi,
            payload.error || "Sorry, I couldn't finish the response.",
          );
        }
      });
    } catch (error) {
      debugLog("reconnect-error", String(error));
    } finally {
      setStreamingState(false);
      if (!receivedAny) {
        waitForUnlock();
      } else {
        window.location.reload();
      }
    }
  };

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (stagedFile) {
      const userText = input.value.trim();
      const file = stagedFile;
      input.value = "";
      clearStagedFile();
      await handleFileUpload(file, userText);
    } else {
      await submitMessage();
    }
  });

  const draftSessionId = form.dataset.sessionId || "";
  const draftKey = `chat_draft_${draftSessionId}`;
  const hasPendingPrompt = (form.dataset.pendingPrompt || "").length > 0;
  const savedDraft = sessionStorage.getItem(draftKey);
  if (savedDraft && !hasPendingPrompt && !initialGenerationInProgress) {
    input.value = savedDraft;
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 120) + "px";
  }
  input.addEventListener("input", () => {
    sessionStorage.setItem(draftKey, input.value);
  });

  const headerTitleEl = document.getElementById("conv-header-title");
  if (headerTitleEl) {
    headerTitleEl.addEventListener("click", () => {
      const sid = parseInt(headerTitleEl.dataset.sessionId, 10);
      if (sid && typeof renameConversation === "function") {
        renameConversation(sid);
      }
    });
  }

  scrollToBottom();
  decorateCodeBlocks(messages);
  if (initialGenerationInProgress) {
    reconnectToLiveStream();
  } else {
    setStreamingState(false);
  }

  const pendingPrompt = form.dataset.pendingPrompt || "";
  if (pendingPrompt && !initialGenerationInProgress) {
    submitMessage(pendingPrompt);
  }

  const fileInput = document.getElementById("conversation-file-input");
  const uploadUrl = form.dataset.uploadUrl || "";
  const previewBar = document.getElementById("file-preview-bar");
  const previewThumb = document.getElementById("file-preview-thumb");
  const previewPdfIcon = document.getElementById("file-preview-pdf-icon");
  const previewName = document.getElementById("file-preview-name");
  const previewRemove = document.getElementById("file-preview-remove");
  let stagedFile = null;

  const allowedTypes = [
    "image/jpeg", "image/png", "image/tiff", "image/bmp", "image/webp",
    "application/pdf",
  ];

  const stageFile = (file) => {
    if (!file) return;
    if (!allowedTypes.includes(file.type)) {
      appendMessage("assistant", "Unsupported file type. Please upload JPEG, PNG, TIFF, BMP, WebP, or PDF.");
      return;
    }
    if (file.size > 10 * 1024 * 1024) {
      appendMessage("assistant", "File too large. Maximum size is 10 MB.");
      return;
    }
    stagedFile = file;
    if (previewName) previewName.textContent = file.name;
    // Explicit style.display toggling makes the thumb/icon mutually exclusive
    // regardless of the surrounding CSS framework state. Always show exactly
    // one: thumbnail for images, icon for PDFs/docs.
    const isPdf = file.type === "application/pdf";
    if (previewThumb) {
      if (isPdf) {
        previewThumb.style.display = "none";
        previewThumb.removeAttribute("src");
      } else {
        previewThumb.src = URL.createObjectURL(file);
        previewThumb.style.display = "";
      }
    }
    if (previewPdfIcon) {
      previewPdfIcon.style.display = isPdf ? "" : "none";
    }
    if (previewBar) previewBar.classList.remove("hidden");
    input.focus();
  };

  const clearStagedFile = () => {
    stagedFile = null;
    if (fileInput) fileInput.value = "";
    if (previewBar) previewBar.classList.add("hidden");
    if (previewThumb) {
      previewThumb.removeAttribute("src");
      previewThumb.style.display = "none";
    }
    if (previewPdfIcon) previewPdfIcon.style.display = "none";
  };

  if (previewRemove) {
    previewRemove.addEventListener("click", clearStagedFile);
  }

  const handleFileUpload = async (file, userMessage) => {
    if (isStreaming || !file || !uploadUrl) return;

    let assistantText = "";
    let assistantHtml = "";
    const displayText = userMessage
      ? `${userMessage}\n[Attached: ${file.name}]`
      : `[Uploaded: ${file.name}]`;

    appendMessage("user", displayText);
    const assistantUi = appendMessage("assistant", "", { pending: true });
    setStreamingState(true);
    debugLog("upload-start", { fileName: file.name, size: file.size });

    const csrfToken = form.querySelector('input[name="csrfmiddlewaretoken"]')?.value || "";
    const formData = new FormData();
    formData.append("file", file);
    if (userMessage) formData.append("message", userMessage);

    try {
      const response = await fetch(uploadUrl, {
        method: "POST",
        headers: {
          "X-CSRFToken": csrfToken,
          "X-Requested-With": "XMLHttpRequest",
        },
        body: formData,
      });

      if (!response.ok) {
        let errorMsg = `Upload failed (${response.status})`;
        try {
          const errData = await response.json();
          errorMsg = errData.error || errorMsg;
        } catch (_) {}
        throw new Error(errorMsg);
      }

      await readStream(response, (payload) => {
        if (payload.type === "delta") {
          assistantText += payload.content || "";
          assistantHtml = payload.html || assistantHtml;
          updateAssistantBubble(assistantUi, assistantText, assistantHtml);
        } else if (payload.type === "done") {
          assistantText = payload.content || assistantText;
          assistantHtml = payload.html || assistantHtml;
          updateAssistantBubble(assistantUi, assistantText, assistantHtml);
        }
      });

      if (!hasVisibleAssistantContent(assistantText, assistantHtml, assistantUi.contentNode)) {
        updateAssistantBubble(assistantUi, "Document processed, but no visible response was generated.");
      }
    } catch (error) {
      debugLog("upload-error", String(error));
      updateAssistantBubble(assistantUi, (error && error.message) || "Failed to process the uploaded document.");
    } finally {
      setStreamingState(false);
      input.focus();
    }
  };

  addButton.addEventListener("click", () => {
    if (!isStreaming && fileInput) fileInput.click();
  });

  if (fileInput) {
    fileInput.addEventListener("change", () => {
      if (fileInput.files && fileInput.files[0]) {
        stageFile(fileInput.files[0]);
      }
    });
  }

  const sessionId = form.dataset.sessionId || "";
  const typingUrl = form.dataset.typingUrl || "";
  const typingIndicator = document.getElementById("typing-indicator");
  const typingText = document.getElementById("typing-indicator-text");
  const typingAvatars = document.getElementById("typing-indicator-avatars");
  let typingTimeout = null;
  let typingDebounce = null;

  const activeThinkers = new Map();

  const AVATAR_GRADIENTS = [
    "from-[#6C86C0] to-[#8DA0FF]",
    "from-[#8E6FC0] to-[#B486E0]",
    "from-[#C06F8E] to-[#E086AF]",
    "from-[#6FC086] to-[#86E0AF]",
    "from-[#C0A76F] to-[#E0C086]",
  ];

  const thinkerGradient = (name) => {
    let hash = 0;
    for (let i = 0; i < name.length; i += 1) {
      hash = (hash * 31 + name.charCodeAt(i)) >>> 0;
    }
    return AVATAR_GRADIENTS[hash % AVATAR_GRADIENTS.length];
  };

  const renderThinkers = () => {
    if (!typingIndicator || !typingText) return;
    const names = Array.from(activeThinkers.keys());
    if (names.length === 0) {
      typingIndicator.classList.add("hidden");
      if (typingAvatars) typingAvatars.innerHTML = "";
      return;
    }

    if (typingAvatars) {
      typingAvatars.innerHTML = "";
      const visible = names.slice(0, 3);
      visible.forEach((name) => {
        const avatar = document.createElement("div");
        avatar.className = `w-9 h-9 rounded-full flex items-center justify-center text-white font-semibold text-[13px] bg-gradient-to-br ${thinkerGradient(name)} shadow-sm ring-2 ring-white`;
        avatar.textContent = name.charAt(0).toUpperCase();
        avatar.title = name;
        typingAvatars.appendChild(avatar);
      });
      if (names.length > 3) {
        const extra = document.createElement("div");
        extra.className = "w-9 h-9 rounded-full flex items-center justify-center text-white font-semibold text-[11px] bg-slate-500 shadow-sm ring-2 ring-white";
        extra.textContent = `+${names.length - 3}`;
        typingAvatars.appendChild(extra);
      }
    }

    if (names.length === 1) {
      typingText.textContent = `${names[0]} is thinking`;
    } else if (names.length === 2) {
      typingText.textContent = `${names[0]} and ${names[1]} are thinking`;
    } else if (names.length === 3) {
      typingText.textContent = `${names[0]}, ${names[1]} and ${names[2]} are thinking`;
    } else {
      typingText.textContent = `${names[0]}, ${names[1]} and ${names.length - 2} others are thinking`;
    }

    typingIndicator.classList.remove("hidden");
  };

  const addThinker = (name, options = {}) => {
    const displayName = (name || "").trim() || "Assistant";
    const persistent = options.persistent !== false;
    activeThinkers.set(displayName, { persistent, since: Date.now() });
    renderThinkers();
    clearTimeout(typingTimeout);
    if (!persistent) {
      typingTimeout = setTimeout(() => {
        activeThinkers.delete(displayName);
        renderThinkers();
      }, 3000);
    }
  };

  const removeThinker = (name) => {
    if (!name) return;
    const displayName = name.trim() || "Assistant";
    if (activeThinkers.delete(displayName)) {
      renderThinkers();
    }
  };

  const clearThinkers = () => {
    activeThinkers.clear();
    clearTimeout(typingTimeout);
    renderThinkers();
  };

  const showTypingIndicator = (name, persistent = false) => {
    addThinker(name, { persistent });
  };

  const hideTypingIndicator = () => {
    clearThinkers();
  };

  if (window.pusherClient && sessionId) {
    const channel = window.pusherClient.subscribe(`private-group-${sessionId}`);

    channel.bind("message:sent", (data) => {
      if (isStreaming || streamCooldown) return;
      const sName = data.agentName || (data.role === "user" ? "User" : "Assistant");
      const row = document.createElement("div");
      row.className = `flex gap-3 chat-msg-row ${data.role === "user" ? "flex-row-reverse" : ""}`;
      const avatar = document.createElement("div");
      avatar.className = "flex-shrink-0 w-10 h-10 rounded-[12px] flex items-center justify-center text-white font-semibold text-[14px] bg-gradient-to-br from-[#6C86C0] to-[#6C86C0] shadow-md";
      avatar.textContent = data.role === "user" ? "U" : sName.charAt(0);
      const contentWrapper = document.createElement("div");
      contentWrapper.className = `flex-1 flex flex-col ${data.role === "user" ? "items-end" : ""}`;
      const meta = document.createElement("div");
      meta.className = "flex items-center gap-2 mb-2";
      const senderEl = document.createElement("div");
      senderEl.className = "font-inter font-semibold text-slate-700/80 text-[14px] leading-5";
      senderEl.textContent = sName;
      meta.appendChild(senderEl);
      contentWrapper.appendChild(meta);
      const bubble = document.createElement("div");
      bubble.className = `${data.role === "user" ? "bg-gradient-to-br from-[#6C86C0]/90 to-[#6C86C0]/90 text-white shadow-[0_4px_20px_rgba(108, 134, 192,0.3)]" : "bg-white/60 backdrop-blur-md shadow-sm text-slate-700/90"} rounded-[16px] px-4 py-3 max-w-[600px] border border-white/30`;
      const contentNode = document.createElement("div");
      contentNode.className = "message-content message-content-markdown font-inter text-[14px] leading-5";
      if (data.html) {
        contentNode.innerHTML = data.html;
      } else {
        contentNode.textContent = data.content || "";
      }
      bubble.appendChild(contentNode);
      contentWrapper.appendChild(bubble);
      row.appendChild(avatar);
      row.appendChild(contentWrapper);
      const container = document.getElementById("message-list") || messages;
      container.appendChild(row);
      decorateCodeBlocks(contentNode);
      scrollToBottom();
      hideTypingIndicator();
    });

    channel.bind("user:typing", (data) => {
      if (String(data.userId) === currentUserId) return;
      addThinker(data.userName || "Someone", { persistent: false });
    });

    channel.bind("user:stop-typing", (data) => {
      if (String(data.userId) === currentUserId) return;
      removeThinker(data.userName || "Someone");
    });

    channel.bind("member:joined", (data) => {
      const container = document.getElementById("message-list") || messages;
      const systemMsg = document.createElement("div");
      systemMsg.className = "flex justify-center py-2";
      const badge = document.createElement("div");
      badge.className = "bg-mm-hover text-mm-muted font-inter text-[12px] font-medium px-4 py-1.5 rounded-full";
      badge.textContent = (data.userName || "Someone") + " joined the group";
      systemMsg.appendChild(badge);
      container.appendChild(systemMsg);
      scrollToBottom();
    });

    channel.bind("member:left", (data) => {
      const container = document.getElementById("message-list") || messages;
      const systemMsg = document.createElement("div");
      systemMsg.className = "flex justify-center py-2";
      const badge = document.createElement("div");
      badge.className = "bg-mm-hover text-mm-muted font-inter text-[12px] font-medium px-4 py-1.5 rounded-full";
      badge.textContent = (data.userName || "Someone") + " left the group";
      systemMsg.appendChild(badge);
      container.appendChild(systemMsg);
      scrollToBottom();
    });
  }

  if (typingUrl) {
    const stopTypingUrl = typingUrl.replace("/typing/", "/stop-typing/");
    let typingStopTimer = null;
    let isTypingActive = false;

    const sendTypingEvent = () => {
      const csrfToken = form.querySelector('input[name="csrfmiddlewaretoken"]')?.value || "";
      fetch(typingUrl, {
        method: "POST",
        headers: { "X-CSRFToken": csrfToken, "X-Requested-With": "XMLHttpRequest" },
      }).catch(() => {});
    };

    const sendStopTypingEvent = () => {
      isTypingActive = false;
      const csrfToken = form.querySelector('input[name="csrfmiddlewaretoken"]')?.value || "";
      fetch(stopTypingUrl, {
        method: "POST",
        headers: { "X-CSRFToken": csrfToken, "X-Requested-With": "XMLHttpRequest" },
      }).catch(() => {});
    };

    input.addEventListener("input", () => {
      clearTimeout(typingDebounce);
      clearTimeout(typingStopTimer);

      if (!isTypingActive) {
        isTypingActive = true;
        sendTypingEvent();
      }

      typingDebounce = setTimeout(sendTypingEvent, 2000);
      typingStopTimer = setTimeout(sendStopTypingEvent, 3000);
    });

    form.addEventListener("submit", () => {
      clearTimeout(typingDebounce);
      clearTimeout(typingStopTimer);
      if (isTypingActive) sendStopTypingEvent();
    });
  }

  let mentionDropdown = null;
  let cachedAgents = null;

  const fetchAgents = async () => {
    if (cachedAgents) return cachedAgents;
    try {
      const resp = await fetch("/chat/api/agents/?scope=all");
      const data = await resp.json();
      cachedAgents = data.agents || [];
      return cachedAgents;
    } catch (_) {
      return [];
    }
  };

  const closeMentionDropdown = () => {
    if (mentionDropdown) {
      mentionDropdown.remove();
      mentionDropdown = null;
    }
  };

  const buildAgentItem = (agent, idx) => {
    const item = document.createElement("button");
    item.type = "button";
    item.className = "w-full flex items-center gap-3 px-3 py-2.5 hover:bg-mm-hover transition-colors text-left";
    if (idx === 0) item.classList.add("bg-mm-hover");

    const avatar = document.createElement("div");
    avatar.className = "w-7 h-7 rounded-[8px] bg-gradient-to-br from-[#6C86C0] to-[#6C86C0] flex items-center justify-center text-white font-semibold text-[11px] flex-shrink-0 shadow-sm";
    avatar.textContent = agent.name.charAt(0).toUpperCase();

    const info = document.createElement("div");
    info.className = "flex-1 min-w-0";
    const nameEl = document.createElement("div");
    nameEl.className = "font-inter font-semibold text-mm-text text-[13px] truncate";
    nameEl.textContent = agent.name;
    const descEl = document.createElement("div");
    descEl.className = "font-inter text-mm-light text-[11px] truncate";
    descEl.textContent = agent.ownerName ? `by ${agent.ownerName}` : "";
    info.appendChild(nameEl);
    info.appendChild(descEl);

    item.appendChild(avatar);
    item.appendChild(info);
    item.addEventListener("click", () => { insertMention(agent.name); });
    return item;
  };

  const showMentionDropdown = async (query) => {
    const agents = await fetchAgents();
    const filtered = agents.filter(a =>
      a.name.toLowerCase().includes(query.toLowerCase()) ||
      (a.ownerName || "").toLowerCase().includes(query.toLowerCase())
    );
    if (filtered.length === 0 && query) {
      closeMentionDropdown();
      return;
    }

    closeMentionDropdown();
    mentionDropdown = document.createElement("div");
    mentionDropdown.className = "absolute bottom-full left-0 mb-2 w-72 bg-white border border-mm-border rounded-xl shadow-lg overflow-hidden z-50 flex flex-col";
    mentionDropdown.style.maxHeight = "320px";
    mentionDropdown.id = "mention-dropdown";

    const header = document.createElement("div");
    header.className = "px-3 py-2 font-inter font-semibold text-mm-muted text-[11px] uppercase tracking-[0.5px] border-b border-mm-border flex-shrink-0";
    header.textContent = "Mention an Agent";
    mentionDropdown.appendChild(header);

    const searchWrap = document.createElement("div");
    searchWrap.className = "px-3 py-2 border-b border-mm-border flex-shrink-0";
    const searchInput = document.createElement("input");
    searchInput.type = "text";
    searchInput.placeholder = "Search agents...";
    searchInput.className = "w-full bg-slate-50 border border-slate-200 rounded-lg px-3 py-1.5 font-inter text-[12px] outline-none focus:ring-1 focus:ring-mm-primary";
    searchInput.value = query || "";
    searchWrap.appendChild(searchInput);
    mentionDropdown.appendChild(searchWrap);

    const listContainer = document.createElement("div");
    listContainer.className = "overflow-y-auto flex-1";
    listContainer.style.maxHeight = "220px";

    const displayList = filtered.length > 0 ? filtered : agents;
    const ownAgents = displayList.filter(a => a.isOwn);
    const teamAgents = displayList.filter(a => !a.isOwn);

    ownAgents.forEach((agent, idx) => {
      listContainer.appendChild(buildAgentItem(agent, idx));
    });

    if (teamAgents.length > 0 && ownAgents.length > 0) {
      const divider = document.createElement("div");
      divider.className = "px-3 py-1.5 font-inter font-semibold text-mm-muted text-[10px] uppercase tracking-[0.5px] bg-slate-50/60";
      divider.textContent = "Team Agents";
      listContainer.appendChild(divider);
    }

    teamAgents.forEach((agent, idx) => {
      listContainer.appendChild(buildAgentItem(agent, ownAgents.length + idx));
    });

    mentionDropdown.appendChild(listContainer);

    searchInput.addEventListener("input", () => {
      const q = searchInput.value.toLowerCase();
      const refiltered = agents.filter(a =>
        a.name.toLowerCase().includes(q) ||
        (a.ownerName || "").toLowerCase().includes(q)
      );
      listContainer.innerHTML = "";
      const own = refiltered.filter(a => a.isOwn);
      const team = refiltered.filter(a => !a.isOwn);
      own.forEach((a, i) => listContainer.appendChild(buildAgentItem(a, i)));
      if (team.length > 0 && own.length > 0) {
        const d = document.createElement("div");
        d.className = "px-3 py-1.5 font-inter font-semibold text-mm-muted text-[10px] uppercase tracking-[0.5px] bg-slate-50/60";
        d.textContent = "Team Agents";
        listContainer.appendChild(d);
      }
      team.forEach((a, i) => listContainer.appendChild(buildAgentItem(a, own.length + i)));
    });

    const formRect = form.getBoundingClientRect();
    mentionDropdown.style.position = "fixed";
    mentionDropdown.style.bottom = (window.innerHeight - formRect.top + 8) + "px";
    mentionDropdown.style.left = formRect.left + "px";
    document.body.appendChild(mentionDropdown);
    searchInput.focus();
  };

  const getMentionHandle = (name) => {
    if (!name) return "";
    const cleaned = name.replace(/'s\s+Agent$/i, "").trim();
    return cleaned
      .split(/[\s'\-]+/)
      .filter(Boolean)
      .map(p => (p[0] === p[0].toLowerCase() ? p[0].toUpperCase() + p.slice(1) : p))
      .join("");
  };

  const insertMention = (agentName) => {
    const val = input.value;
    const cursorPos = input.selectionStart || val.length;
    const textBeforeCursor = val.substring(0, cursorPos);
    const atIdx = textBeforeCursor.lastIndexOf("@");
    if (atIdx >= 0) {
      const textAfterCursor = val.substring(cursorPos);
      const handle = getMentionHandle(agentName);
      const insertion = "@" + handle + " ";
      input.value = val.substring(0, atIdx) + insertion + textAfterCursor;
      const newCursorPos = atIdx + insertion.length;
      input.setSelectionRange(newCursorPos, newCursorPos);
    }
    closeMentionDropdown();
    input.focus();
  };

  input.addEventListener("input", () => {
    const val = input.value;
    const cursorPos = input.selectionStart || val.length;
    const textBeforeCursor = val.substring(0, cursorPos);
    const atMatch = textBeforeCursor.match(/@(\w*)$/);

    if (atMatch) {
      showMentionDropdown(atMatch[1]);
    } else {
      closeMentionDropdown();
    }
  });

  input.addEventListener("keydown", (e) => {
    if (mentionDropdown && e.key === "Escape") {
      e.preventDefault();
      closeMentionDropdown();
    }
    if (mentionDropdown && (e.key === "Tab" || e.key === "Enter")) {
      const firstItem = mentionDropdown.querySelector("button");
      if (firstItem) {
        e.preventDefault();
        firstItem.click();
      }
      return;
    }
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      form.dispatchEvent(new Event("submit", { cancelable: true }));
    }
  });

  document.addEventListener("click", (e) => {
    if (mentionDropdown && !mentionDropdown.contains(e.target) && e.target !== input) {
      closeMentionDropdown();
    }
  });

  const chatMain = messages.closest("main");
  if (chatMain) {
    let dragCounter = 0;
    chatMain.addEventListener("dragenter", (e) => {
      e.preventDefault();
      dragCounter++;
      chatMain.classList.add("ring-2", "ring-mm-primary", "ring-inset");
    });
    chatMain.addEventListener("dragleave", (e) => {
      e.preventDefault();
      dragCounter--;
      if (dragCounter <= 0) {
        dragCounter = 0;
        chatMain.classList.remove("ring-2", "ring-mm-primary", "ring-inset");
      }
    });
    chatMain.addEventListener("dragover", (e) => {
      e.preventDefault();
    });
    chatMain.addEventListener("drop", (e) => {
      e.preventDefault();
      dragCounter = 0;
      chatMain.classList.remove("ring-2", "ring-mm-primary", "ring-inset");
      const file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
      if (file) stageFile(file);
    });
  }

  messages.addEventListener("click", async (e) => {
    const copyBtn = e.target.closest(".msg-action-copy");
    if (copyBtn) {
      const msgRow = e.target.closest("[data-message-id]");
      if (!msgRow) return;
      const contentEl = msgRow.querySelector(".message-content");
      if (!contentEl) return;
      try {
        await copyText(contentEl.textContent.trim());
        const svg = copyBtn.querySelector("svg");
        const origColor = svg ? svg.getAttribute("class") : "";
        if (svg) svg.setAttribute("class", (origColor || "").replace("text-slate-400", "text-green-500"));
        setTimeout(() => { if (svg) svg.setAttribute("class", origColor || ""); }, 1200);
      } catch (_) {}
      return;
    }

    const editBtn = e.target.closest(".msg-action-edit");
    const resendBtn = e.target.closest(".msg-action-resend");
    if (!editBtn && !resendBtn) return;

    const msgRow = e.target.closest("[data-message-id]");
    if (!msgRow) return;
    const messageId = msgRow.dataset.messageId;
    const csrfToken = form.querySelector('input[name="csrfmiddlewaretoken"]')?.value || "";

    if (editBtn) {
      const contentEl = msgRow.querySelector(".message-content");
      if (!contentEl) return;
      if (contentEl.querySelector("textarea")) return;
      const currentText = contentEl.textContent.trim();
      const originalHtml = contentEl.innerHTML;

      const editArea = document.createElement("textarea");
      editArea.value = currentText;
      editArea.className = "w-full bg-white/90 text-slate-800 border border-slate-300 rounded-lg px-3 py-2 font-inter text-[14px] leading-6 resize-none outline-none focus:ring-1 focus:ring-mm-primary";
      editArea.rows = Math.min(Math.max(currentText.split("\n").length, 2), 6);

      const btnRow = document.createElement("div");
      btnRow.className = "flex justify-end gap-2 mt-2";
      const cancelBtn = document.createElement("button");
      cancelBtn.type = "button";
      cancelBtn.textContent = "Cancel";
      cancelBtn.className = "px-3 py-1 rounded-lg text-sm font-inter text-slate-500 hover:bg-slate-100 transition-colors";
      const saveEditBtn = document.createElement("button");
      saveEditBtn.type = "button";
      saveEditBtn.textContent = "Save";
      saveEditBtn.className = "px-3 py-1 rounded-lg text-sm font-inter font-semibold text-white bg-mm-primary hover:bg-mm-primary/90 transition-colors";
      btnRow.appendChild(cancelBtn);
      btnRow.appendChild(saveEditBtn);

      contentEl.innerHTML = "";
      contentEl.appendChild(editArea);
      contentEl.appendChild(btnRow);
      editArea.focus();
      editArea.setSelectionRange(editArea.value.length, editArea.value.length);

      const restoreOriginal = () => { contentEl.innerHTML = originalHtml; };

      cancelBtn.addEventListener("click", restoreOriginal);
      editArea.addEventListener("keydown", (ev) => {
        if (ev.key === "Escape") { restoreOriginal(); }
      });

      saveEditBtn.addEventListener("click", async () => {
        const newText = editArea.value.trim();
        if (!newText || newText === currentText) { restoreOriginal(); return; }
        saveEditBtn.disabled = true;
        saveEditBtn.textContent = "Saving...";
        try {
          const resp = await fetch(`/chat/c/${sessionId}/messages/${messageId}/edit/`, {
            method: "POST",
            headers: {
              "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
              "X-CSRFToken": csrfToken,
              "X-Requested-With": "XMLHttpRequest",
            },
            body: new URLSearchParams({ content: newText }),
          });
          if (resp.ok) {
            const data = await resp.json();
            contentEl.textContent = data.content || newText;
          } else {
            restoreOriginal();
          }
        } catch (_) {
          restoreOriginal();
        }
      });
    }

    if (resendBtn) {
      if (isStreaming) return;
      const siblings = Array.from(messages.querySelectorAll("[data-message-id]"));
      const msgIdx = siblings.indexOf(msgRow);
      for (let i = siblings.length - 1; i > msgIdx; i--) {
        siblings[i].remove();
      }
      const contentEl = msgRow.querySelector(".message-content");
      const msgText = contentEl ? contentEl.textContent.trim() : "";
      const assistantUi = appendMessage("assistant", "", { pending: true });
      setStreamingState(true);
      showTypingIndicator(defaultAgentName || "Assistant", true);

      let assistantText = "";
      let assistantHtml = "";
      try {
        const resp = await fetch(`/chat/c/${sessionId}/messages/${messageId}/resend/`, {
          method: "POST",
          headers: {
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "X-CSRFToken": csrfToken,
            "X-Requested-With": "XMLHttpRequest",
          },
          body: "",
        });
        if (!resp.ok) throw new Error(`Resend failed (${resp.status})`);
        await readStream(resp, (payload) => {
          if (payload.type === "delta") {
            const chunk = payload.content || "";
            assistantText += chunk;
            if (payload.html) {
              assistantHtml = payload.html;
              updateAssistantBubble(assistantUi, assistantText, assistantHtml);
            } else {
              appendStreamChunk(assistantUi, chunk);
            }
          } else if (payload.type === "done") {
            assistantText = payload.content || assistantText;
            assistantHtml = payload.html || assistantHtml;
            updateAssistantBubble(assistantUi, assistantText, assistantHtml);
            hideTypingIndicator();
            if (payload.message_id) lastStreamedMessageId = payload.message_id;
          } else if (payload.type === "agent_turn") {
            const turnUi = appendMessage("assistant", "", { pending: false, senderName: payload.agentName || "Agent" });
            const senderLabel = turnUi.bubble.closest(".chat-msg-row")?.querySelector("[data-sender-label]");
            if (senderLabel) senderLabel.textContent = payload.agentName || "Agent";
            updateAssistantBubble(turnUi, payload.content || "", payload.html || "");
            if (payload.message_id) lastStreamedMessageId = payload.message_id;
          }
        });
      } catch (err) {
        updateAssistantBubble(assistantUi, (err && err.message) || "Resend failed.");
      } finally {
        hideTypingIndicator();
        setStreamingState(false);
        input.focus();
      }
    }
  });

  const abortActiveStream = () => {
    if (activeStreamAbort) {
      try { activeStreamAbort.abort(); } catch (_) {}
      activeStreamAbort = null;
    }
  };

  window.addEventListener("pagehide", abortActiveStream);
  document.addEventListener("click", (event) => {
    const link = event.target.closest("a[href]");
    if (!link) return;
    if (link.target === "_blank" || event.ctrlKey || event.metaKey || event.shiftKey) return;
    const href = link.getAttribute("href") || "";
    if (!href || href.startsWith("#") || href.startsWith("javascript:")) return;
    abortActiveStream();
  }, true);
});

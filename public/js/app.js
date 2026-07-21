(function () {
    const messagesEl = document.getElementById('messages');
    const inputEl = document.getElementById('message-input');
    const sendBtn = document.getElementById('send-btn');
    const fileInput = document.getElementById('file-input');
    const filePreview = document.getElementById('file-preview');
    const fileName = document.getElementById('file-name');
    const fileRemove = document.getElementById('file-remove');
    const dropZone = document.getElementById('drop-zone');
    const chatList = document.getElementById('chat-list');
    const newChatBtn = document.getElementById('new-chat-btn');
    const progressOverlay = document.getElementById('progress-overlay');
    const progressBar = document.getElementById('progress-bar');
    const progressPhase = document.getElementById('progress-phase');
    const progressPercent = document.getElementById('progress-percent');
    const progressTimer = document.getElementById('progress-timer');
    const cancelBtn = document.getElementById('cancel-btn');
    const statusDot = document.querySelector('.status-dot');
    const statusText = document.querySelector('.status-text');
    const addVideoBtn = document.getElementById('add-video-btn');
    const cpuBar = document.getElementById('cpu-bar');
    const cpuVal = document.getElementById('cpu-val');
    const ramBar = document.getElementById('ram-bar');
    const ramVal = document.getElementById('ram-val');
    const gpuRow = document.getElementById('gpu-row');
    const gpuBar = document.getElementById('gpu-bar');
    const gpuVal = document.getElementById('gpu-val');
    const voicePartial = document.getElementById('voice-partial');
    const voiceIndicator = document.getElementById('voice-indicator');
    const voskLoading = document.getElementById('vosk-loading');

    let chats = JSON.parse(localStorage.getItem('transcriber_chats') || '{}');
    let currentChatId = null;
    let selectedFile = null;
    let uploadedFilePath = null;
    let sending = false;
    let activeEventSource = null;
    let activeJobId = null;
    let isRecording = false;
    let voiceRecorder = new VoiceRecorder();
    let voskReady = false;
    let spaceHeld = false;

    function saveChats() {
        localStorage.setItem('transcriber_chats', JSON.stringify(chats));
    }

    function generateId() {
        return Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
    }

    function formatElapsed(sec) {
        const m = Math.floor(sec / 60);
        const s = sec % 60;
        return m + ':' + String(s).padStart(2, '0');
    }

    function formatDuration(sec) {
        const h = Math.floor(sec / 3600);
        const m = Math.floor((sec % 3600) / 60);
        const s = sec % 60;
        if (h > 0) return h + 'ч ' + m + 'м ' + s + 'с';
        if (m > 0) return m + 'м ' + s + 'с';
        return s + 'с';
    }

    function checkHealth() {
        fetch('/api/health')
            .then(function (r) { return r.json(); })
            .then(function (data) {
                voskReady = !!data.vosk;
                voskLoading.style.display = data.vosk ? 'none' : 'block';
                if (data.mcp && data.deepseek && data.vosk) {
                    statusDot.className = 'status-dot ok';
                    statusText.textContent = 'Все системы готовы';
                } else if (data.mcp && data.deepseek) {
                    statusDot.className = 'status-dot';
                    statusText.textContent = 'MCP + DeepSeek готовы';
                } else {
                    statusDot.className = 'status-dot';
                    var issues = [];
                    if (!data.mcp) issues.push('MCP');
                    if (!data.deepseek) issues.push('DeepSeek');
                    statusText.textContent = issues.join(', ') + ' недоступен';
                }
            })
            .catch(function () {
                statusDot.className = 'status-dot';
                statusText.textContent = 'Сервер не в сети';
            });
    }

    function renderChatList() {
        chatList.innerHTML = '';
        var ids = Object.keys(chats).sort(function (a, b) {
            return (chats[b].updatedAt || 0) - (chats[a].updatedAt || 0);
        });
        ids.forEach(function (id) {
            var chat = chats[id];
            var div = document.createElement('div');
            div.className = 'chat-item' + (id === currentChatId ? ' active' : '');

            var text = document.createElement('span');
            text.className = 'chat-item-text';
            var firstMsg = chat.messages.find(function (m) { return m.role === 'user'; });
            text.textContent = firstMsg ? firstMsg.content.slice(0, 40) : 'Новый чат';

            var del = document.createElement('button');
            del.className = 'chat-item-delete';
            del.title = 'Удалить чат';
            del.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';
            del.addEventListener('click', function (e) {
                e.stopPropagation();
                deleteChat(id);
            });

            div.appendChild(text);
            div.appendChild(del);
            div.addEventListener('click', function () { switchChat(id); });
            chatList.appendChild(div);
        });
    }

    function deleteChat(id) {
        delete chats[id];
        saveChats();
        if (currentChatId === id) {
            var remaining = Object.keys(chats);
            currentChatId = remaining.length > 0 ? remaining[0] : null;
        }
        renderChatList();
        renderMessages();
    }

    function switchChat(id) {
        currentChatId = id;
        renderChatList();
        renderMessages();
    }

    function newChat() {
        var id = generateId();
        chats[id] = { messages: [], updatedAt: Date.now() };
        currentChatId = id;
        saveChats();
        renderChatList();
        renderMessages();
    }

    function renderMessages() {
        messagesEl.innerHTML = '';
        var chat = chats[currentChatId];
        if (!chat || chat.messages.length === 0) {
            messagesEl.innerHTML =
                '<div class="welcome">' +
                '<div class="welcome-icon">' +
                '<svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#6c5ce7" stroke-width="1.5">' +
                '<polygon points="23 7 16 12 23 17 23 7"/>' +
                '<rect x="1" y="5" width="15" height="14" rx="2" ry="2"/>' +
                '</svg>' +
                '</div>' +
                '<h1>Транскриптор</h1>' +
                '<p class="welcome-subtitle">AI-ассистент для транскрипции</p>' +
                '<div class="welcome-features">' +
                '<div class="welcome-feature">' +
                '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="23 7 16 12 23 17 23 7"/><rect x="1" y="5" width="15" height="14" rx="2" ry="2"/></svg>' +
                '<span>Транскрибация видео и аудио с таймкодами</span>' +
                '</div>' +
                '<div class="welcome-feature">' +
                '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>' +
                '<span>Скачивание результатов как Markdown</span>' +
                '</div>' +
                '<div class="welcome-feature">' +
                '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>' +
                '<span>Отслеживание прогресса в реальном времени</span>' +
                '</div>' +
                '<div class="welcome-feature">' +
                '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/></svg>' +
                '<span>Чат с AI о ваших транскрипциях</span>' +
                '</div>' +
                '<div class="welcome-feature">' +
                '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/></svg>' +
                '<span>Голосовой ввод: удерживай Пробел для записи</span>' +
                '</div>' +
                '</div>' +
                '<p class="welcome-hint">Перетащите файл, напишите сообщение или удерживайте Пробел</p>' +
                '</div>';
            return;
        }
        chat.messages.forEach(function (msg) {
            addMessageToDOM(msg.role, msg.content);
            if (msg.role === 'assistant' && msg.content && (msg.content.indexOf('| Время') !== -1 || msg.content.indexOf('| Time') !== -1)) {
                appendTranscriptionMeta(msg.content, null);
            }
        });
        scrollToBottom();
    }

    function parseMarkdown(text) {
        if (!text) return '';
        var html = text
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');

        html = html.replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code>$2</code></pre>');
        html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
        html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
        html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');

        var lines = html.split('\n');
        var inTable = false;
        var tableRows = [];
        var result = [];

        lines.forEach(function (line) {
            var trimmed = line.trim();
            if (trimmed.startsWith('|') && trimmed.endsWith('|')) {
                if (trimmed.replace(/[|\s\-:]/g, '') === '') return;
                if (!inTable) { inTable = true; tableRows = []; }
                var cells = trimmed.split('|').slice(1, -1).map(function (c) { return c.trim(); });
                tableRows.push(cells);
            } else {
                if (inTable) {
                    result.push(renderTable(tableRows));
                    inTable = false;
                    tableRows = [];
                }
                if (trimmed) result.push('<p>' + trimmed + '</p>');
            }
        });
        if (inTable) result.push(renderTable(tableRows));
        return result.join('');
    }

    function renderTable(rows) {
        if (rows.length === 0) return '';
        var html = '<table>';
        html += '<thead><tr>' + rows[0].map(function (c) { return '<th>' + c + '</th>'; }).join('') + '</tr></thead>';
        if (rows.length > 1) {
            html += '<tbody>' + rows.slice(1).map(function (r) {
                return '<tr>' + r.map(function (c) { return '<td>' + c + '</td>'; }).join('') + '</tr>';
            }).join('') + '</tbody>';
        }
        html += '</table>';
        return html;
    }

    function addMessageToDOM(role, content) {
        var div = document.createElement('div');
        div.className = 'message message-' + role;
        var contentDiv = document.createElement('div');
        contentDiv.className = 'message-content';
        if (role === 'assistant') {
            contentDiv.innerHTML = parseMarkdown(content);
        } else {
            contentDiv.textContent = content;
        }
        div.appendChild(contentDiv);
        messagesEl.appendChild(div);
    }

    function appendTranscriptionMeta(content, duration) {
        var lastMsg = messagesEl.querySelector('.message-assistant:last-child .message-content');
        if (!lastMsg) return;

        var meta = document.createElement('div');
        meta.className = 'transcription-meta';

        var dlBtn = document.createElement('a');
        dlBtn.className = 'md-download';
        dlBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg> Скачать .md';
        dlBtn.onclick = function () {
            var blob = new Blob([content], { type: 'text/markdown' });
            var url = URL.createObjectURL(blob);
            var a = document.createElement('a');
            a.href = url;
            a.download = 'транскрипция.md';
            a.click();
            URL.revokeObjectURL(url);
        };
        meta.appendChild(dlBtn);

        var sumBtn = document.createElement('button');
        sumBtn.className = 'md-download';
        sumBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg> Саммари';
        sumBtn.onclick = function () {
            sumBtn.disabled = true;
            sumBtn.textContent = 'Создание саммари...';
            var startTime = Date.now();
            fetch('/api/summarize', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text: content, language: 'en' })
            })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                var elapsed = Math.round((Date.now() - startTime) / 1000);
                if (data.error) {
                    addMessageToDOM('assistant', 'Ошибка саммари: ' + data.error);
                } else {
                    addMessageToDOM('assistant', '**Саммари:**\n\n' + data.summary);
                    appendSummaryMeta(data.summary, elapsed);
                }
                scrollToBottom();
                sumBtn.remove();
            })
            .catch(function (e) {
                addMessageToDOM('assistant', 'Ошибка саммари: ' + e.message);
                scrollToBottom();
                sumBtn.remove();
            });
        };
        meta.appendChild(sumBtn);

        if (duration) {
            var label = document.createElement('span');
            label.className = 'duration-label';
            label.textContent = 'Транскрипция заняла ' + duration;
            meta.appendChild(label);
        }

        lastMsg.appendChild(meta);
    }

    function appendSummaryMeta(summary, elapsed) {
        var lastMsg = messagesEl.querySelector('.message-assistant:last-child .message-content');
        if (!lastMsg) return;

        var meta = document.createElement('div');
        meta.className = 'transcription-meta';

        var dlBtn = document.createElement('a');
        dlBtn.className = 'md-download';
        dlBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg> Скачать .md';
        dlBtn.onclick = function () {
            var blob = new Blob([summary], { type: 'text/markdown' });
            var url = URL.createObjectURL(blob);
            var a = document.createElement('a');
            a.href = url;
            a.download = 'саммари.md';
            a.click();
            URL.revokeObjectURL(url);
        };
        meta.appendChild(dlBtn);

        if (elapsed !== undefined && elapsed !== null) {
            var label = document.createElement('span');
            label.className = 'duration-label';
            label.textContent = 'Саммари заняло ' + formatDuration(elapsed);
            meta.appendChild(label);
        }

        lastMsg.appendChild(meta);
    }

    function addThinkingIndicator() {
        var div = document.createElement('div');
        div.className = 'message message-assistant thinking-message';
        var contentDiv = document.createElement('div');
        contentDiv.className = 'message-content thinking-bubble';
        contentDiv.innerHTML = '<span class="thinking-dot"></span><span class="thinking-dot"></span><span class="thinking-dot"></span>';
        div.appendChild(contentDiv);
        messagesEl.appendChild(div);
        return div;
    }

    function scrollToBottom() {
        messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    async function uploadFile(file) {
        var formData = new FormData();
        formData.append('file', file);
        var resp = await fetch('/api/upload', { method: 'POST', body: formData });
        if (!resp.ok) {
            var err = await resp.json();
            throw new Error(err.error || 'Ошибка загрузки');
        }
        return await resp.json();
    }

    function showProgress(jobId) {
        progressOverlay.classList.add('active');
        progressBar.value = 0;
        progressPhase.textContent = 'Запуск...';
        progressPercent.textContent = '0%';
        progressTimer.textContent = '0:00';
        activeJobId = jobId;

        if (activeEventSource) activeEventSource.close();

        var evtSource = new EventSource('/api/stream/' + jobId);
        activeEventSource = evtSource;

        evtSource.onmessage = function (e) {
            var data = JSON.parse(e.data);
            var pct = Math.round((data.progress || 0) * 100);
            progressBar.value = pct;
            progressPercent.textContent = pct + '%';
            progressPhase.textContent = capitalize(data.phase || 'Обработка...');
            progressTimer.textContent = formatElapsed(data.elapsed || 0);

            if (data.status === 'done') {
                evtSource.close();
                activeEventSource = null;
                activeJobId = null;
                progressBar.value = 100;
                progressPercent.textContent = '100%';
                progressPhase.textContent = 'Готово!';

                if (data.message) {
                    addMessageToDOM('assistant', data.message);
                    appendTranscriptionMeta(data.message, data.duration);

                    var chat = chats[currentChatId];
                    if (chat) {
                        chat.messages.push({ role: 'assistant', content: data.message });
                        chat.updatedAt = Date.now();
                        saveChats();
                        renderChatList();
                    }
                }
                scrollToBottom();
                setTimeout(function () { progressOverlay.classList.remove('active'); }, 1200);
                sending = false;
                sendBtn.disabled = false;
            } else if (data.status === 'error' || data.status === 'cancelled') {
                evtSource.close();
                activeEventSource = null;
                activeJobId = null;
                var msg = data.status === 'cancelled' ? 'Транскрипция отменена.' : (data.message || data.error || 'Неизвестная ошибка');
                addMessageToDOM('assistant', msg);
                var chat2 = chats[currentChatId];
                if (chat2) {
                    chat2.messages.push({ role: 'assistant', content: msg });
                    chat2.updatedAt = Date.now();
                    saveChats();
                    renderChatList();
                }
                scrollToBottom();
                progressOverlay.classList.remove('active');
                sending = false;
                sendBtn.disabled = false;
            }
        };

        evtSource.onerror = function () {
            evtSource.close();
            activeEventSource = null;
            activeJobId = null;
            progressOverlay.classList.remove('active');
            sending = false;
            sendBtn.disabled = false;
        };
    }

    function cancelTranscription() {
        if (!activeJobId) return;
        fetch('/api/cancel/' + activeJobId, { method: 'POST' }).catch(function () {});
    }

    function capitalize(s) {
        return s.charAt(0).toUpperCase() + s.slice(1);
    }

    function clearFile() {
        selectedFile = null;
        uploadedFilePath = null;
        filePreview.style.display = 'none';
        fileName.textContent = '';
        fileInput.value = '';
    }

    function handleFile(file) {
        if (!file) return;
        if (file.size > 500 * 1024 * 1024) {
            alert('Файл слишком большой. Максимум 500 МБ.');
            return;
        }
        selectedFile = file;
        fileName.textContent = file.name;
        filePreview.style.display = 'block';
        inputEl.placeholder = 'Нажмите Enter или кнопку Отправить для транскрипции...';
        inputEl.focus();
    }

    async function sendMessage(text) {
        if (!text) text = inputEl.value.trim();
        if (!text && !selectedFile) return;
        if (sending) return;
        sending = true;
        sendBtn.disabled = true;

        if (!currentChatId) newChat();

        var displayMessage = text;
        if (selectedFile && text) {
            displayMessage = text;
        } else if (selectedFile && !text) {
            displayMessage = 'Транскрибировать файл: ' + selectedFile.name;
        }

        chats[currentChatId].messages.push({ role: 'user', content: displayMessage });
        chats[currentChatId].updatedAt = Date.now();
        saveChats();
        renderChatList();

        addMessageToDOM('user', displayMessage);
        inputEl.value = '';
        inputEl.style.height = 'auto';
        scrollToBottom();

        var filePath = uploadedFilePath;

        if (selectedFile && !uploadedFilePath) {
            try {
                var result = await uploadFile(selectedFile);
                filePath = result.path;
            } catch (e) {
                addMessageToDOM('assistant', 'Ошибка загрузки: ' + e.message);
                sending = false;
                sendBtn.disabled = false;
                return;
            }
        }
        clearFile();

        var thinkingEl = null;
        if (!filePath) {
            thinkingEl = addThinkingIndicator();
            scrollToBottom();
        }

        try {
            var resp = await fetch('/api/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    message: displayMessage,
                    conversation_id: currentChatId,
                    file_path: filePath || undefined
                })
            });
            var data = await resp.json();

            if (thinkingEl) thinkingEl.remove();

            if (data.error) {
                addMessageToDOM('assistant', 'Ошибка: ' + data.error);
                sending = false;
                sendBtn.disabled = false;
            } else if (data.job_id) {
                showProgress(data.job_id);
            } else {
                addMessageToDOM('assistant', data.message);
                chats[currentChatId].messages.push({ role: 'assistant', content: data.message });
                chats[currentChatId].updatedAt = Date.now();
                saveChats();
                renderChatList();
                scrollToBottom();
                sending = false;
                sendBtn.disabled = false;
            }
        } catch (e) {
            if (thinkingEl) thinkingEl.remove();
            addMessageToDOM('assistant', 'Ошибка соединения: ' + e.message);
            sending = false;
            sendBtn.disabled = false;
        }
    }

    inputEl.addEventListener('input', function () {
        this.style.height = 'auto';
        this.style.height = Math.min(this.scrollHeight, 150) + 'px';
    });

    inputEl.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    sendBtn.addEventListener('click', function () { sendMessage(); });
    cancelBtn.addEventListener('click', cancelTranscription);
    newChatBtn.addEventListener('click', newChat);

    fileRemove.addEventListener('click', function () {
        clearFile();
        inputEl.placeholder = 'Загрузите файл или напишите сообщение...';
    });

    fileInput.addEventListener('change', function () {
        if (this.files.length > 0) handleFile(this.files[0]);
    });

    addVideoBtn.addEventListener('click', function (e) {
        e.stopPropagation();
        fileInput.click();
    });

    dropZone.addEventListener('dragover', function (e) {
        e.preventDefault();
        this.classList.add('drag-over');
    });
    dropZone.addEventListener('dragleave', function () {
        this.classList.remove('drag-over');
    });
    dropZone.addEventListener('drop', function (e) {
        e.preventDefault();
        this.classList.remove('drag-over');
        if (e.dataTransfer.files.length > 0) handleFile(e.dataTransfer.files[0]);
    });

    document.addEventListener('paste', function (e) {
        var items = e.clipboardData.items;
        for (var i = 0; i < items.length; i++) {
            if (items[i].kind === 'file') {
                handleFile(items[i].getAsFile());
                break;
            }
        }
    });

    checkHealth();
    setInterval(checkHealth, 5000);

    function updateStats() {
        fetch('/api/stats')
            .then(function (r) { return r.json(); })
            .then(function (data) {
                cpuBar.style.width = data.cpu + '%';
                cpuVal.textContent = data.cpu + '%';
                ramBar.style.width = data.ram_percent + '%';
                ramVal.textContent = data.ram_used + ' / ' + data.ram_total + ' GB';
                if (data.gpu_total) {
                    gpuRow.style.display = '';
                    var gpuPct = Math.round((data.gpu_used / data.gpu_total) * 100);
                    gpuBar.style.width = gpuPct + '%';
                    gpuVal.textContent = data.gpu_used + ' / ' + data.gpu_total + ' GB';
                }
            })
            .catch(function () {});
    }
    updateStats();
    setInterval(updateStats, 3000);

    if (Object.keys(chats).length > 0) {
        var latest = Object.keys(chats).sort(function (a, b) {
            return (chats[b].updatedAt || 0) - (chats[a].updatedAt || 0);
        })[0];
        switchChat(latest);
    } else {
        renderChatList();
        renderMessages();
    }

    function startRecording() {
        if (sending || isRecording) return;
        isRecording = true;
        voiceIndicator.classList.add('active');
        voicePartial.textContent = '';
        voicePartial.style.display = 'block';

        voiceRecorder.onPartial = function (text) {
            voicePartial.textContent = text;
        };

        voiceRecorder.onError = function (err) {
            stopRecording();
            addMessageToDOM('assistant', 'Ошибка голосового ввода: ' + err.message);
            scrollToBottom();
        };

        voiceRecorder.start().catch(function (err) {
            isRecording = false;
            voiceIndicator.classList.remove('active');
            voicePartial.style.display = 'none';
            addMessageToDOM('assistant', 'Ошибка голосового ввода: ' + err.message);
            scrollToBottom();
        });
    }

    function stopRecording() {
        if (!isRecording) return;
        isRecording = false;
        voiceIndicator.classList.remove('active');

        voiceRecorder.stop().then(function (text) {
            voicePartial.style.display = 'none';
            voicePartial.textContent = '';
            if (text && text.trim()) {
                sendMessage(text.trim());
            }
        }).catch(function () {
            voicePartial.style.display = 'none';
            voicePartial.textContent = '';
        });
    }

    document.addEventListener('keydown', function (e) {
        if (e.code !== 'Space' || e.repeat) return;

        var active = document.activeElement;
        var inputFocused = active === inputEl || active.tagName === 'TEXTAREA' || active.tagName === 'INPUT';

        if (inputFocused) return;

        e.preventDefault();
        if (!spaceHeld) {
            spaceHeld = true;
            startRecording();
        }
    });

    document.addEventListener('keyup', function (e) {
        if (e.code !== 'Space') return;
        if (spaceHeld) {
            spaceHeld = false;
            stopRecording();
        }
    });
})();

# Результаты тестирования профилей

## Тест 1: Bug Fix

### Входная задача (баг-репорт)
```
При запуске `ruff check .` выдаёт ошибку E402:
"Module level import not at top of file — server.py:73:1"
import atexit находится после signal.signal() вызовов.
```

### Результат работы профиля Bug Fix

## Bug: import atexit не в начале файла (E402)

### Симптом
`ruff check .` выдаёт E402 на строке 73 server.py. Модуль `atexit` импортируется после вызовов `signal.signal()`, хотя должен быть в начале файла.

### Корневая причина
В `server.py:73` импорт `import atexit` расположен после строк 71-72 с `signal.signal()`. Это произошло потому что `atexit` использовался сразу после регистрации signal handlers, и автор расположил его рядом с кодом использования.

### Фикс
Переместить `import atexit` наверх файла (после остальных stdlib импортов, до `import signal`). Также переместить `atexit.register(cleanup)` вниз к остальной инициализации.

### Проверка
- [ ] ruff check: E402 исчезнет
- [ ] mypy: без изменений (atexit — stdlib)
- [ ] Edge cases: cleanup по-прежнему зарегистрируется при импорте модуля

### Затронутые файлы
- `server.py:73` — перенос import в верх файла
- `server.py:75` — перенос atexit.register() к cleanup

---

## Тест 2: Research

### Входная задача
```
"Как у нас работает транскрипция от загрузки файла до результата?"
```

### Результат работы профиля Research

## Исследование: Транскрипция от загрузки до результата

### Найденные файлы
| Файл | Роль | Ключевые строки |
|------|------|-----------------|
| `public/js/app.js` | Frontend — загрузка и SSE | L372-381: uploadFile(), L383-456: showProgress() |
| `server.py` | Main server — API + orchestration | L355-380: upload(), L454-567: chat(), L212-300: run_transcription_stream() |
| `mcp_server.py` | MCP worker — Whisper модель | L37-44: get_model(), L47-131: run_transcription() |

### Поток данных

```
1. Browser: file drop → uploadFile() → POST /api/upload
   └─ server.py:upload() → сохраняет в uploads/, возвращает {file_id, path}

2. Browser: sendMessage() → POST /api/chat {file_path, message}
   └─ server.py:chat() → создаёт job_id, запускает thread
   
3. Thread: run_transcription_stream()
   ├─ → POST MCP_URL/call {file_path} → mcp_server.py:call_tool()
   │   └─ mcp_server создаёт job, запускает thread → run_transcription()
   │       ├─ get_model() — lazy load Whisper (первый вызов)
   │       ├─ model.transcribe() — сегменты с таймкодами
   │       └─ результат → jobs[job_id]["result"]
   │
   ├─ Polling: GET MCP_URL/job/{mcp_job_id} — проверка статуса
   │
   └─ DeepSeek: formatting через _deepseek() → красивый markdown

4. Browser: SSE /api/stream/{job_id} → получает progress + result
   └─ showProgress() → отрисовка в UI
```

### Связи и зависимости
- `server.py` зависит от `mcp_server.py` через HTTP (localhost:3001)
- `mcp_server.py` зависит от `faster-whisper` (Whisper CTranslate2)
- Frontend зависит от `server.py` через REST API + SSE
- DeepSeek API используется для форматирования результата транскрипции
- Vosk используется для голосового ввода (отдельный сервер, порт 2700)

### Выводы
Транскрипция — трёхуровневая система: Browser → Main Server → MCP Worker. Основная логика:
1. Загрузка файла на main server
2. Main server делегирует MCP worker через HTTP
3. MCP worker загружает Whisper модель (лениво), транскрибирует
4. Main server поллит MCP worker через SSE, стримит прогресс в browser
5. DeepSeek форматирует результат в красивый markdown

---

## Тест 3: Code Review

### Входная задача
```
Проведи code review файла server.py
```

### Результат работы профиля Code Review

## Code Review: server.py

### Lint Results
```
E402  Module level import not at top of file (server.py:73)
RUF005  Consider iterable unpacking (server.py:262, 498)
F841  Local variable `elapsed` is assigned to but never used (server.py:283)
SIM105  Use contextlib.suppress instead of try-except-pass (server.py:439)
SIM102  Use a single if statement (server.py:447)
```

### Critical (нужно исправить до merge)
| # | Файл:строка | Проблема | Рекомендация |
|---|-------------|----------|--------------|
| 1 | `server.py:85` | DEEPSEEK_API_KEY может быть пустым строковым значением | Проверять `if not DEEPSEEK_API_KEY` вместо `if DEEPSEEK_API_KEY and DEEPSEEK_API_KEY != "your_deepseek_api_key_here"` |

### Major (стоит исправить)
| # | Файл:строка | Проблема | Рекомендация |
|---|-------------|----------|--------------|
| 1 | `server.py:73` | E402: import atexit не в начале файла | Переместить import наверх |
| 2 | `server.py:283` | F841: неиспользуемая переменная `elapsed` | Удалить или использовать |
| 3 | `server.py:262,498` | RUF005: конкатенация списков | Использовать `[*iter1, *iter2]` |
| 4 | `server.py:439` | SIM105: try-except-pass | Использовать `contextlib.suppress(Exception)` |

### Minor (желательно)
| # | Файл:строка | Проблема | Рекомендация |
|---|-------------|----------|--------------|
| 1 | `server.py:447` | SIM102: вложенные if | Объединить в один `if` с `and` |
| 2 | `server.py:97` | conversations缺乏 типизации | Добавить `dict[str, list[dict]]` |

### Style (по желанию)
| # | Файл:строка | Проблема | Рекомендация |
|---|-------------|----------|--------------|
| 1 | `server.py:98` | stream_results缺乏 типизации | Добавить type hints |

### Итого
- Critical: 1
- Major: 4
- Minor: 2
- Style: 2
- Вердикт: fix-then-merge

---

## Итерация профилей после первого теста

### Что пришлось доработать

1. **Bug Fix profile**: Добавил проверку invariant'ов проекта — без этого профиль мог бы предложить фикс, ломающий two-server architecture

2. **Research profile**: Уточнил что ответ должен содержать конкретные файлы:строки, а не абстрактные описания. Первый вариант давал слишком общий ответ

3. **Code Review profile**: Добавил чек-лист из 12 пунктов — без него профиль пропускал проверку edge cases и thread safety

### Сравнение v1 → v2

| Аспект | v1 (до доработки) | v2 (после) |
|--------|-------------------|------------|
| Bug Fix | Мог предложить рефакторинг заодно | Только minimal fix |
| Research | Общие описания без файлов | Конкретные file:line ссылки |
| Code Review | Пропускал SIM-предупреждения | Полный чек-лист 12 пунктов |
| Все профили | Могли нарушить invariant'ы | Явные invariant'ы в каждом |

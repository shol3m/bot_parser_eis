# Безопасность

## Найденные уязвимости

| # | Severity | Проблема | Файл | Статус |
|---|----------|----------|------|--------|
| 1 | 🔴 CRITICAL | Удаление чужих подписок без проверки владельца | `bot/bot.py:2578, 2691` | ❌ не исправлено |
| 2 | 🔴 CRITICAL | IDOR: `data_{chat_id}.json` открыты на GitHub Pages | `webapp/`, `bot/bot.py:3083` | ❌ не исправлено |
| 3 | 🟠 HIGH | GitHub token может попасть в логи при ошибке | `bot/bot.py:89` | ❌ не исправлено |
| 4 | 🟡 MEDIUM | XSS: `esc()` не экранирует кавычки, уязвимость в атрибутах | `webapp/index.html:760` | ❌ не исправлено |

---

## Детали

### 1. Удаление чужих подписок (CRITICAL)
Callbacks `wt:del:{id}` и `ppwt:del:{id}` вызывают `delete_watch(id)` без проверки что подписка принадлежит текущему пользователю. Любой авторизованный пользователь может удалить чужую подписку, зная её ID.

**Fix:**
```python
w = get_watch(watch_id)
if not w or w["chat_id"] != update.effective_chat.id:
    return
delete_watch(watch_id)
```

### 2. IDOR на GitHub Pages (CRITICAL)
`data_{chat_id}.json`, `priceplan_{chat_id}.json`, `subs_{chat_id}.json` лежат в публичном репозитории на GitHub Pages. Перебор chat_id даёт доступ к фильтрам и результатам поиска других пользователей.

**Fix:** Файлы пушатся через GitHub API напрямую (не коммитами), но нужно убедиться что их нет в репо:
```
# .gitignore должен содержать:
webapp/data_*.json
webapp/priceplan_*.json
webapp/subs_*.json
webapp/config.json
```

### 3. GitHub token в логах (HIGH)
`_github_push_file()` при ошибке логирует полный объект исключения, который может содержать заголовок Authorization с токеном.

**Fix:** логировать только `e.code` и `repo_path`.

### 4. XSS в esc() (MEDIUM)
```js
// Текущий код — не экранирует кавычки:
function esc(s) {
  return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// Fix:
function esc(s) {
  return String(s||'').replace(/[&<>"']/g, c =>
    ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
```

---

## Что защищено

- `.gitignore` исключает `config/bot_config.json`, `.env`, `data/state.db` ✅
- SQL-запросы параметризованы, SQL-инъекции нет ✅
- Telegram авторизация через `allowed_users` + `pending_users` workflow ✅
- Все секреты через `.env` / `bot_config.json`, не в коде ✅

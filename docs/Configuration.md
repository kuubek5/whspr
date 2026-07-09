# Configuration

Усі налаштування зберігаються в `config.json` (створюється при першому
збереженні з вікна; шаблон — `config.example.json`). Редагуй через
**Налаштування** у вікні або вручну.

## Параметри

| Ключ | Тип | Дефолт | Опис |
|---|---|---|---|
| `hotkey` | str | `"f9"` | клавіша/комбо диктовки (hold-to-talk). Напр. `"ctrl+space"`, `"alt+vk81"` |
| `lang_hotkey` | str | `"f10"` | клавіша перемикання мови (натиснути) |
| `language` | str | `"uk"` | мова за замовчуванням: `uk` або `en` |
| `model_uk` | str | `"stock"` | модель для української: `stock` або `uk-ft` (див. [Ukrainian Accuracy](Ukrainian-Accuracy.md)) |
| `beam_size` | int | `5` | ширина beam-search. Більше = точніше, повільніше (1–10) |
| `rms_threshold` | float | `0.003` | поріг тиші. Нижче — запис вважається порожнім і відкидається |
| `overlay` | bool | `true` | показувати пігулку-індикатор на екрані |
| `dictionary` | str | `""` | терміни через кому → Whisper `hotwords` |
| `replacements` | obj | (кілька) | голосові команди `фраза → текст` |
| `llm` | str | `"off"` | постобробка: `off` / `groq` / `ollama` |
| `groq_api_key` | str | `""` | ключ Groq (якщо `llm: groq`) |
| `groq_model` | str | `llama-3.3-70b-versatile` | модель Groq |
| `ollama_model` | str | `qwen2.5:7b` | модель Ollama |
| `autostart` | bool | `false` | копіювати ярлик у Startup |

## Формат хоткею

Рядок із токенів через `+`:
- модифікатори: `ctrl`, `alt`, `shift`, `cmd`
- функціональні/спец: `f9`, `space`, `scroll_lock`, `pause`, `tab`…
- літери/цифри: по фізичному коду, напр. `vk81` (= клавіша Q), `vk68` (= D)

Приклади: `"f9"`, `"ctrl+space"`, `"alt+shift+vk68"` (Alt+Shift+D).
Найпростіше — не редагувати вручну, а натиснути «Натисніть клавіші» у вікні.

## Формат голосових команд

`config.json` → `replacements` — об'єкт `{"що сказати": "що вставити"}`:
```json
"replacements": {
  "новий рядок": "\n",
  "новий абзац": "\n\n",
  "крапка з комою": ";"
}
```
Збіг — регістронезалежний, разом із сусідньою пунктуацією.

## Приклад повного config.json

Див. [`config.example.json`](https://github.com/kuubek5/whspr/blob/master/config.example.json)
у репозиторії.

> `config.json`, `history.db`, `whspr.log` **не потрапляють у git** (`.gitignore`)
> — вони особисті.

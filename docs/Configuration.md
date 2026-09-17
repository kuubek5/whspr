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
| `model_uk` | str | `"stock"` | активна модель: `stock`, `uk-ft`, `large-v3`, `distil-large-v3`, `medium`, `small`, `base`, `tiny`. Керується з UI (Налаштування → Модель розпізнавання), не редагуйте вручну — активувати можна лише завантажену модель (див. [Ukrainian Accuracy](Ukrainian-Accuracy.md)) |
| `beam_size` | int | `5` | ширина beam-search. Більше = точніше, повільніше (1–10) |
| `rms_threshold` | float | `0.003` | поріг тиші. Нижче — запис вважається порожнім і відкидається |
| `target_rms` | float | `0.06` | тихий запис підсилюється до цього рівня перед розпізнаванням (слабкі мікрофони) |
| `max_gain` | float | `12.0` | стеля підсилення, щоб шум не роздувався в галюцинації |
| `mute_others` | bool | `true` | глушити звук інших програм під час запису; після відпускання клавіші повертається |
| `spoken_punctuation` | bool | `true` | «кома»/«крапка»/«знак питання» → `,` `.` `?` |
| `normalize_numbers` | bool | `true` | числівники словами → цифри: «триста п'ятдесят два» → `352` |
| `voice_commands` | bool | `true` | голосові команди редагують попередню диктовку («великими літерами», «видали останнє», «переклади англійською») |
| `hands_free` | bool | `false` | тап клавіші вмикає запис, авто-стоп по тиші (замість утримання) |
| `silence_stop_s` | float | `1.5` | скільки тиші завершує запис у hands-free |
| `max_utterance_s` | int | `60` | стеля тривалости hands-free запису |
| `auto_lang` | bool | `false` | Whisper сам визначає мову (використовує stock-модель, не uk-ft) |
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

Див. [`config.example.json`](https://github.com/kuubek5/kuubwave/blob/master/config.example.json)
у репозиторії.

> `config.json`, `history.db`, `kuubwave.log` **не потрапляють у git** (`.gitignore`)
> — вони особисті.

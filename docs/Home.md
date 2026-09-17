# KuubWave Wiki

**KuubWave** — локальний клон [Wispr Flow](https://wisprflow.ai) для Windows.
Push-to-talk диктовка українською та англійською: тримаєш клавішу, говориш,
відпускаєш — текст вставляється в активне вікно. Усе локально, на NVIDIA GPU,
**без хмари, без підписки, офлайн**.

## Зміст

- **[Installation](Installation.md)** — встановлення з нуля, вимоги, залежності
- **[Usage](Usage.md)** — щоденне користування, хоткеї, UI, голосові команди
- **[Configuration](Configuration.md)** — усі налаштування та `config.json`
- **[Ukrainian Accuracy](Ukrainian-Accuracy.md)** — моделі, русифікація, як покращити
- **[Architecture](Architecture.md)** — як влаштовано всередині, пайплайн
- **[Troubleshooting](Troubleshooting.md)** — типові проблеми й рішення
- **[Roadmap](Roadmap.md)** — плани розвитку

## Швидкий старт

```powershell
git clone https://github.com/kuubek5/kuubwave.git
cd kuubwave
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python make_shortcut.py
.venv\Scripts\python flow.py
```

Тримай **F9** → говори → відпусти. Текст вставиться. **F10** — зміна мови.

## Чим відрізняється від Wispr Flow

| | Wispr Flow | KuubWave |
|---|---|---|
| Обробка | хмара (сервери) | **локально, на твоєму GPU** |
| Офлайн | ні | **так** (після 1-го завантаження моделі) |
| Ціна | $12–15/міс | **безкоштовно** |
| Приватність | аудіо + скріншоти в хмару | **нічого не покидає ПК** |
| Українська | так | так, + вибір fine-tuned моделі |

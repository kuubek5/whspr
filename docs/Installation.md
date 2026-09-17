# Installation

## Вимоги

| Компонент | Мінімум | Рекомендовано |
|---|---|---|
| ОС | Windows 10 x64 | Windows 11 x64 |
| Python | 3.12 | 3.12 |
| GPU | будь-який (CPU-fallback) | NVIDIA GTX 900+ / RTX, ≥4 ГБ VRAM |
| Драйвер NVIDIA | ≥525 | останній |
| RAM | 8 ГБ | 16 ГБ+ |
| Диск | ~4 ГБ вільного | SSD |
| Pagefile | **увімкнений** | авто-керований |

> **Windows ARM (Snapdragon) не підтримується** — CTranslate2 лише x64.
> macOS/Linux не підтримуються — код Windows-only.

## Крок за кроком

### 1. Клон репозиторію
```powershell
git clone https://github.com/kuubek5/kuubwave.git
cd kuubwave
```

### 2. Віртуальне середовище
```powershell
python -m venv .venv
```

### 3. Залежності
```powershell
.venv\Scripts\pip install -r requirements.txt
```
Це поставить faster-whisper, customtkinter, pynput, sounddevice тощо **плюс**
CUDA-бібліотеки (`nvidia-cublas-cu12`, `nvidia-cudnn-cu12`) з pip-коліс —
**окремий CUDA Toolkit встановлювати не треба**. Розмір: ~2 ГБ (CUDA важкі).

> cuDNN закріплений на `9.1.0.70`: новіші 9.x на деяких Ampere-картах
> запускають багатохвилинну компіляцію кернелів на кожен старт.

### 4. Ярлик запуску
```powershell
.venv\Scripts\python make_shortcut.py
```
Створює `KuubWave.lnk` (запуск через `pythonw` — без чорного консольного вікна).
Скопіюй його куди зручно (робочий стіл, Start Menu).

### 5. Перший запуск
```powershell
.venv\Scripts\python flow.py
```
Модель (~1,6 ГБ) завантажиться з HuggingFace — **потрібен інтернет один раз**.
Далі все офлайн. Вікно з'явиться одразу, модель прогріється у фоні (~4 с).

## Перевірка встановлення

```powershell
.venv\Scripts\python test_pipeline.py
```
Має вивести `CUDA PIPELINE OK` і час транскрипції ~1 с. Якщо падає —
див. [Troubleshooting](Troubleshooting.md).

## Автозапуск із Windows

Увімкни в **Налаштування → Запускати з Windows** (копіює ярлик у Startup-папку),
або вручну поклади `KuubWave.lnk` у `shell:startup`.

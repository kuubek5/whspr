# app_gui.py — main window (customtkinter), Wispr-style:
# left sidebar nav + content pages (Dashboard / History / Dictionary / Settings).
# Fully decoupled from flow.py via a `ctx` object of callbacks/values.

import time
import customtkinter as ctk

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

ACCENT = "#e5484d"
ACCENT_HOVER = "#c93b40"
OK = "#46a758"
MUTED = "#8a8a9a"
CARD = "#26262f"
BG = "#191920"

STATUS_UK = {
    "loading": ("Завантаження моделі…", "#6a6ad0"),
    "idle": ("Готово", OK),
    "recording": ("Запис…", ACCENT),
    "processing": ("Розпізнаю…", "#f0b429"),
}


class WhsprApp:
    """Main application window. `ctx` provides all data + actions:
    ctx.config, ctx.save_config(cfg), ctx.history_last(n), ctx.history_delete(id),
    ctx.history_clear(), ctx.history_stats(), ctx.status()->str, ctx.lang()->str,
    ctx.toggle_lang(), ctx.set_autostart(bool), ctx.LANGUAGES, ctx.UK_MODELS,
    ctx.HOTKEYS, ctx.quit().
    """

    def __init__(self, root: ctk.CTk, ctx):
        self.root = root
        self.ctx = ctx
        self.pages = {}
        self.nav_buttons = {}
        self._build()
        self.root.after(1000, self._tick)

    # ---------- window ----------
    def _build(self):
        r = self.root
        r.title("whspr")
        r.geometry("860x580")
        r.minsize(760, 520)
        r.configure(fg_color=BG)
        try:
            r.iconbitmap("whspr.ico")
        except Exception:
            pass
        # close (X) hides to tray instead of quitting
        r.protocol("WM_DELETE_WINDOW", self.hide)
        r.grid_columnconfigure(1, weight=1)
        r.grid_rowconfigure(0, weight=1)

        self._build_sidebar()
        self._build_pages()
        self.select("dashboard")

    def _build_sidebar(self):
        bar = ctk.CTkFrame(self.root, width=200, corner_radius=0, fg_color="#14141a")
        bar.grid(row=0, column=0, sticky="nsw")
        bar.grid_propagate(False)

        ctk.CTkLabel(bar, text="  whspr", font=ctk.CTkFont(size=26, weight="bold"),
                     text_color="#ffffff").pack(anchor="w", padx=18, pady=(22, 2))
        ctk.CTkLabel(bar, text="  голосова диктовка", font=ctk.CTkFont(size=12),
                     text_color=MUTED).pack(anchor="w", padx=18, pady=(0, 18))

        for key, label in (("dashboard", "  🎙   Головна"),
                           ("history", "  🕐   Історія"),
                           ("dictionary", "  📖   Словник"),
                           ("settings", "  ⚙    Налаштування")):
            b = ctk.CTkButton(
                bar, text=label, anchor="w", height=44, corner_radius=8,
                fg_color="transparent", hover_color=CARD, text_color="#d8d8e0",
                font=ctk.CTkFont(size=15), command=lambda k=key: self.select(k),
            )
            b.pack(fill="x", padx=10, pady=3)
            self.nav_buttons[key] = b

        # bottom: live status dot + hotkey hint
        bottom = ctk.CTkFrame(bar, fg_color="transparent")
        bottom.pack(side="bottom", fill="x", padx=16, pady=16)
        self.side_status = ctk.CTkLabel(bottom, text="●  …", font=ctk.CTkFont(size=13),
                                        text_color=MUTED, anchor="w")
        self.side_status.pack(anchor="w")

    def _build_pages(self):
        holder = ctk.CTkFrame(self.root, fg_color=BG)
        holder.grid(row=0, column=1, sticky="nsew", padx=0, pady=0)
        holder.grid_rowconfigure(0, weight=1)
        holder.grid_columnconfigure(0, weight=1)
        for key, builder in (("dashboard", self._page_dashboard),
                            ("history", self._page_history),
                            ("dictionary", self._page_dictionary),
                            ("settings", self._page_settings)):
            frame = ctk.CTkFrame(holder, fg_color=BG)
            frame.grid(row=0, column=0, sticky="nsew")
            builder(frame)
            self.pages[key] = frame

    def select(self, key: str):
        for k, b in self.nav_buttons.items():
            b.configure(fg_color=CARD if k == key else "transparent")
        self.pages[key].tkraise()
        if key == "history":
            self._reload_history()
        elif key == "dashboard":
            self._refresh_stats()

    # ---------- dashboard ----------
    def _page_dashboard(self, f):
        ctk.CTkLabel(f, text="Головна", font=ctk.CTkFont(size=28, weight="bold"),
                     text_color="#fff").pack(anchor="w", padx=28, pady=(24, 4))

        # big status card
        card = ctk.CTkFrame(f, fg_color=CARD, corner_radius=16)
        card.pack(fill="x", padx=28, pady=(8, 16))
        self.dash_dot = ctk.CTkLabel(card, text="●", font=ctk.CTkFont(size=40),
                                     text_color=MUTED)
        self.dash_dot.grid(row=0, column=0, rowspan=2, padx=(24, 16), pady=20)
        self.dash_status = ctk.CTkLabel(card, text="…", font=ctk.CTkFont(size=22, weight="bold"),
                                        text_color="#fff", anchor="w")
        self.dash_status.grid(row=0, column=1, sticky="w", pady=(20, 0))
        self.dash_hint = ctk.CTkLabel(card, text="", font=ctk.CTkFont(size=13),
                                      text_color=MUTED, anchor="w")
        self.dash_hint.grid(row=1, column=1, sticky="w", pady=(0, 20))
        card.grid_columnconfigure(1, weight=1)
        self.lang_btn = ctk.CTkButton(card, text="🌐 UK", width=90, height=40,
                                      corner_radius=10, fg_color=ACCENT,
                                      hover_color=ACCENT_HOVER, command=self._toggle_lang)
        self.lang_btn.grid(row=0, column=2, rowspan=2, padx=24)

        # stat tiles
        stats = ctk.CTkFrame(f, fg_color="transparent")
        stats.pack(fill="x", padx=28)
        self.tiles = {}
        for i, (key, title) in enumerate((("words_today", "Слів сьогодні"),
                                         ("dictations_today", "Диктовок сьогодні"),
                                         ("words", "Слів усього"),
                                         ("wpm", "Слів/хв"))):
            t = ctk.CTkFrame(stats, fg_color=CARD, corner_radius=14)
            t.grid(row=0, column=i, sticky="nsew", padx=6, pady=4)
            stats.grid_columnconfigure(i, weight=1)
            val = ctk.CTkLabel(t, text="0", font=ctk.CTkFont(size=30, weight="bold"),
                               text_color="#fff")
            val.pack(pady=(18, 2))
            ctk.CTkLabel(t, text=title, font=ctk.CTkFont(size=12),
                         text_color=MUTED).pack(pady=(0, 16))
            self.tiles[key] = val

        ctk.CTkLabel(f, text="Останні диктовки", font=ctk.CTkFont(size=16, weight="bold"),
                     text_color="#fff").pack(anchor="w", padx=28, pady=(18, 4))
        self.recent = ctk.CTkScrollableFrame(f, fg_color=CARD, corner_radius=14)
        self.recent.pack(fill="both", expand=True, padx=28, pady=(0, 24))

    def _refresh_stats(self):
        s = self.ctx.history_stats()
        self.tiles["words_today"].configure(text=str(s["words_today"]))
        self.tiles["dictations_today"].configure(text=str(s["dictations_today"]))
        self.tiles["words"].configure(text=str(s["words"]))
        self.tiles["wpm"].configure(text=f"{s['wpm']:.0f}")
        for w in self.recent.winfo_children():
            w.destroy()
        rows = self.ctx.history_last(8)
        if not rows:
            ctk.CTkLabel(self.recent, text="Ще нічого не надиктовано. Тримай хоткей і говори.",
                         text_color=MUTED).pack(anchor="w", padx=12, pady=12)
        for _id, ts, lang, dur, text in rows:
            row = ctk.CTkFrame(self.recent, fg_color="transparent")
            row.pack(fill="x", padx=8, pady=2)
            ctk.CTkLabel(row, text=ts[11:16], font=ctk.CTkFont(size=12),
                         text_color=MUTED, width=44).pack(side="left")
            ctk.CTkLabel(row, text=text.replace("\n", " ⏎ "), anchor="w",
                         font=ctk.CTkFont(size=13), text_color="#e0e0e8",
                         justify="left", wraplength=460).pack(side="left", fill="x", expand=True)

    # ---------- history ----------
    def _page_history(self, f):
        head = ctk.CTkFrame(f, fg_color="transparent")
        head.pack(fill="x", padx=28, pady=(24, 8))
        ctk.CTkLabel(head, text="Історія", font=ctk.CTkFont(size=28, weight="bold"),
                     text_color="#fff").pack(side="left")
        ctk.CTkButton(head, text="Очистити все", width=120, height=34, corner_radius=8,
                      fg_color="transparent", border_width=1, border_color=MUTED,
                      text_color=MUTED, hover_color=CARD,
                      command=self._clear_history).pack(side="right")
        self.hist_list = ctk.CTkScrollableFrame(f, fg_color=BG)
        self.hist_list.pack(fill="both", expand=True, padx=22, pady=(0, 20))

    def _reload_history(self):
        for w in self.hist_list.winfo_children():
            w.destroy()
        rows = self.ctx.history_last(200)
        if not rows:
            ctk.CTkLabel(self.hist_list, text="Порожньо.", text_color=MUTED).pack(pady=20)
            return
        for _id, ts, lang, dur, text in rows:
            card = ctk.CTkFrame(self.hist_list, fg_color=CARD, corner_radius=10)
            card.pack(fill="x", padx=6, pady=4)
            top = ctk.CTkFrame(card, fg_color="transparent")
            top.pack(fill="x", padx=12, pady=(8, 0))
            ctk.CTkLabel(top, text=f"{ts}   ·   {lang}   ·   {dur:.1f}s",
                         font=ctk.CTkFont(size=11), text_color=MUTED).pack(side="left")
            ctk.CTkButton(top, text="Копіювати", width=80, height=26, corner_radius=6,
                          fg_color="transparent", hover_color="#333",
                          text_color="#bbb", font=ctk.CTkFont(size=11),
                          command=lambda t=text: self._copy(t)).pack(side="right")
            ctk.CTkButton(top, text="✕", width=28, height=26, corner_radius=6,
                          fg_color="transparent", hover_color="#402",
                          text_color=MUTED, command=lambda i=_id: self._del_history(i)
                          ).pack(side="right", padx=4)
            ctk.CTkLabel(card, text=text.replace("\n", " ⏎ "), anchor="w", justify="left",
                         font=ctk.CTkFont(size=14), text_color="#e8e8f0",
                         wraplength=560).pack(anchor="w", fill="x", padx=12, pady=(2, 10))

    def _copy(self, text: str):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)

    def _del_history(self, row_id: int):
        self.ctx.history_delete(row_id)
        self._reload_history()

    def _clear_history(self):
        self.ctx.history_clear()
        self._reload_history()

    # ---------- dictionary ----------
    def _page_dictionary(self, f):
        ctk.CTkLabel(f, text="Словник", font=ctk.CTkFont(size=28, weight="bold"),
                     text_color="#fff").pack(anchor="w", padx=28, pady=(24, 4))
        ctk.CTkLabel(f, text="Терміни, імена, бренди — через кому. Підвищують точність "
                     "розпізнавання (передаються моделі як hotwords).",
                     font=ctk.CTkFont(size=13), text_color=MUTED, justify="left",
                     wraplength=560).pack(anchor="w", padx=28, pady=(0, 10))
        self.dict_box = ctk.CTkTextbox(f, height=140, corner_radius=10, fg_color=CARD,
                                       font=ctk.CTkFont(size=14))
        self.dict_box.pack(fill="x", padx=28)
        self.dict_box.insert("1.0", self.ctx.config.get("dictionary", ""))

        ctk.CTkLabel(f, text="Голосові команди", font=ctk.CTkFont(size=16, weight="bold"),
                     text_color="#fff").pack(anchor="w", padx=28, pady=(20, 2))
        ctk.CTkLabel(f, text="Що казати → що вставляти. Формат: фраза = текст (по рядку). "
                     "\\n = новий рядок.", font=ctk.CTkFont(size=13), text_color=MUTED,
                     justify="left").pack(anchor="w", padx=28, pady=(0, 8))
        self.cmd_box = ctk.CTkTextbox(f, height=120, corner_radius=10, fg_color=CARD,
                                      font=ctk.CTkFont(size=13))
        self.cmd_box.pack(fill="x", padx=28)
        reps = self.ctx.config.get("replacements", {})
        self.cmd_box.insert("1.0", "\n".join(
            f"{k} = {v.replace(chr(10), '\\n')}" for k, v in reps.items()))

        bar = ctk.CTkFrame(f, fg_color="transparent")
        bar.pack(fill="x", padx=28, pady=16)
        self.dict_saved = ctk.CTkLabel(bar, text="", text_color=OK, font=ctk.CTkFont(size=13))
        self.dict_saved.pack(side="left")
        ctk.CTkButton(bar, text="Зберегти", width=120, height=38, corner_radius=10,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      command=self._save_dictionary).pack(side="right")

    def _save_dictionary(self):
        reps = {}
        for line in self.cmd_box.get("1.0", "end").splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                if k.strip():
                    reps[k.strip()] = v.strip().replace("\\n", "\n")
        self.ctx.config["dictionary"] = self.dict_box.get("1.0", "end").strip()
        self.ctx.config["replacements"] = reps
        self.ctx.save_config(self.ctx.config)
        self._flash(self.dict_saved, "Збережено ✓")

    # ---------- settings ----------
    def _page_settings(self, f):
        ctk.CTkLabel(f, text="Налаштування", font=ctk.CTkFont(size=28, weight="bold"),
                     text_color="#fff").pack(anchor="w", padx=28, pady=(24, 8))
        body = ctk.CTkScrollableFrame(f, fg_color=BG)
        body.pack(fill="both", expand=True, padx=22, pady=(0, 12))
        c = self.ctx.config

        def row_widget(label, widget):
            r = ctk.CTkFrame(body, fg_color=CARD, corner_radius=10)
            r.pack(fill="x", padx=6, pady=4)
            ctk.CTkLabel(r, text=label, font=ctk.CTkFont(size=14),
                         text_color="#e0e0e8", anchor="w").pack(side="left", padx=14, pady=12)
            widget(r)
            return r

        # dictation hotkey: capture any key/combo
        self.s_hotkey = c.get("hotkey", "f9")

        def hotkey_row(r):
            self.hotkey_btn = ctk.CTkButton(
                r, text=self.ctx.hotkey_label(self.s_hotkey), width=200, height=32,
                corner_radius=8, fg_color="#33333f", hover_color=ACCENT,
                command=lambda: self._capture("dictation"))
            self.hotkey_btn.pack(side="right", padx=14)
        row_widget("Клавіша диктовки (тримати)", hotkey_row)

        self.s_lang_hotkey = c.get("lang_hotkey", "f10")

        def lang_hk_row(r):
            self.lang_hk_btn = ctk.CTkButton(
                r, text=self.ctx.hotkey_label(self.s_lang_hotkey), width=200, height=32,
                corner_radius=8, fg_color="#33333f", hover_color=ACCENT,
                command=lambda: self._capture("lang"))
            self.lang_hk_btn.pack(side="right", padx=14)
        row_widget("Клавіша зміни мови (натиснути)", lang_hk_row)

        self.s_lang = ctk.StringVar(value=c.get("language", "uk"))
        row_widget("Мова за замовчуванням", lambda r: ctk.CTkOptionMenu(
            r, variable=self.s_lang, values=list(self.ctx.LANGUAGES), width=160,
            fg_color="#33333f", button_color="#33333f").pack(side="right", padx=14))

        self.s_model = ctk.StringVar(value=c.get("model_uk", "stock"))
        row_widget("Модель для української", lambda r: ctk.CTkOptionMenu(
            r, variable=self.s_model, values=list(self.ctx.UK_MODELS), width=160,
            fg_color="#33333f", button_color="#33333f").pack(side="right", padx=14))

        self.s_llm = ctk.StringVar(value=c.get("llm", "off"))
        row_widget("LLM-постобробка", lambda r: ctk.CTkOptionMenu(
            r, variable=self.s_llm, values=["off", "groq", "ollama"], width=160,
            fg_color="#33333f", button_color="#33333f").pack(side="right", padx=14))

        self.s_groq = ctk.StringVar(value=c.get("groq_api_key", ""))
        row_widget("Groq API key", lambda r: ctk.CTkEntry(
            r, textvariable=self.s_groq, width=200, show="•").pack(side="right", padx=14))

        self.s_beam = ctk.StringVar(value=str(c.get("beam_size", 5)))
        row_widget("Beam size (якість↑ швидкість↓)", lambda r: ctk.CTkOptionMenu(
            r, variable=self.s_beam, values=[str(i) for i in range(1, 11)], width=160,
            fg_color="#33333f", button_color="#33333f").pack(side="right", padx=14))

        self.s_rms = ctk.StringVar(value=str(c.get("rms_threshold", 0.003)))
        row_widget("Поріг тиші (RMS)", lambda r: ctk.CTkEntry(
            r, textvariable=self.s_rms, width=160).pack(side="right", padx=14))

        self.s_overlay = ctk.BooleanVar(value=c.get("overlay", True))
        row_widget("Індикатор на екрані", lambda r: ctk.CTkSwitch(
            r, text="", variable=self.s_overlay, progress_color=ACCENT).pack(side="right", padx=14))

        self.s_autostart = ctk.BooleanVar(value=c.get("autostart", False))
        row_widget("Запускати з Windows", lambda r: ctk.CTkSwitch(
            r, text="", variable=self.s_autostart, progress_color=ACCENT).pack(side="right", padx=14))

        bar = ctk.CTkFrame(f, fg_color="transparent")
        bar.pack(fill="x", padx=28, pady=(0, 18))
        self.set_saved = ctk.CTkLabel(bar, text="", text_color=OK, font=ctk.CTkFont(size=13))
        self.set_saved.pack(side="left")
        ctk.CTkLabel(bar, text="Зміна клавіші диктовки — після перезапуску.",
                     text_color=MUTED, font=ctk.CTkFont(size=12)).pack(side="left", padx=14)
        ctk.CTkButton(bar, text="Зберегти", width=120, height=38, corner_radius=10,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      command=self._save_settings).pack(side="right")

    def _capture(self, which: str):
        btn = self.hotkey_btn if which == "dictation" else self.lang_hk_btn
        btn.configure(text="Натисніть клавіші…", fg_color=ACCENT)

        def done(spec):
            def apply():
                if which == "dictation":
                    self.s_hotkey = spec
                else:
                    self.s_lang_hotkey = spec
                btn.configure(text=self.ctx.hotkey_label(spec), fg_color="#33333f")
            self.root.after(0, apply)

        self.ctx.capture_hotkey(done)

    def _save_settings(self):
        c = self.ctx.config
        try:
            rms = float(self.s_rms.get().replace(",", "."))
        except ValueError:
            rms = 0.003
        # don't switch to a model that isn't downloaded — the next dictation
        # would otherwise block on a synchronous multi-GB pull under the model
        # lock. Keep the current model and warn instead.
        sel_model = self.s_model.get()
        repo = self.ctx.UK_MODELS.get(sel_model)
        if repo and not self.ctx.model_installed(repo):
            sel_model = c.get("model_uk", "stock")
            self.s_model.set(sel_model)
            self._flash(self.set_saved, "Модель не завантажена")
        c.update({
            "hotkey": self.s_hotkey,
            "lang_hotkey": self.s_lang_hotkey,
            "language": self.s_lang.get(),
            "model_uk": sel_model,
            "llm": self.s_llm.get(),
            "groq_api_key": self.s_groq.get().strip(),
            "beam_size": int(self.s_beam.get()),
            "rms_threshold": rms,
            "overlay": bool(self.s_overlay.get()),
            "autostart": bool(self.s_autostart.get()),
        })
        self.ctx.save_config(c)
        self.ctx.set_autostart(c["autostart"])
        self._flash(self.set_saved, "Збережено ✓")

    # ---------- live status ----------
    def _tick(self):
        st = self.ctx.status()
        text, color = STATUS_UK.get(st, (st, MUTED))
        lang = self.ctx.lang().upper()
        self.side_status.configure(text=f"●  {text}", text_color=color)
        if self.root.state() != "withdrawn":
            self.dash_dot.configure(text_color=color)
            self.dash_status.configure(text=text)
            self.dash_hint.configure(
                text=f"Тримай {self.ctx.hotkey_label(self.ctx.config.get('hotkey', 'f9'))} "
                     f"і говори  ·  {self.ctx.hotkey_label(self.ctx.config.get('lang_hotkey', 'f10'))} "
                     f"— зміна мови  ·  зараз {lang}")
            self.lang_btn.configure(text=f"🌐 {lang}")
        self.root.after(700, self._tick)

    def _toggle_lang(self):
        self.ctx.toggle_lang()
        self.lang_btn.configure(text=f"🌐 {self.ctx.lang().upper()}")

    def _flash(self, label, text):
        label.configure(text=text)
        self.root.after(1600, lambda: label.configure(text=""))

    # ---------- show/hide ----------
    def show(self):
        self.root.after(0, self._show)

    def _show(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        self.select("dashboard")

    def hide(self):
        self.root.withdraw()

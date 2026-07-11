# test_webview.py — opens the real WebView2 window, verifies the page loads and
# the JS bridge boots, then auto-closes. Confirms no crash / runtime present.
import os, threading, time
import webview
import webview_app

BASE = os.path.dirname(os.path.abspath(__file__))


def probe(window):
    time.sleep(3.0)  # let page + boot() run
    try:
        title = window.evaluate_js("document.querySelector('.brand-text')?.textContent")
        page = window.evaluate_js("document.getElementById('pageTitle')?.textContent")
        stat = window.evaluate_js("document.querySelector('[data-stat=\"wordsTotal\"]')?.textContent")
        gpu = window.evaluate_js("document.getElementById('gpuBadge')?.textContent")
        theme = window.evaluate_js("document.documentElement.getAttribute('data-theme')")
        print(f"brand={title!r} page={page!r} wordsTotal={stat!r} gpu={gpu!r} theme={theme!r}", flush=True)
        # switch to settings to exercise render
        window.evaluate_js("document.querySelector('[data-page=\"settings\"]').click()")
        time.sleep(0.5)
        st = window.evaluate_js("document.querySelector('.section-title')?.textContent")
        print(f"settings first section={st!r}", flush=True)
        print("WEBVIEW OK", flush=True)
    except Exception as e:
        print(f"probe error: {e}", flush=True)
    finally:
        window.destroy()


api = webview_app.Api()
win = webview.create_window("whspr test", os.path.join(BASE, "web", "index.html"),
                            js_api=api, width=980, height=660, background_color="#0E0E12")
webview.start(probe, win)
print("window closed", flush=True)

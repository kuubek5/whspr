// serve.mjs — zero-dependency static server with poll-based live reload for the
// KuubWave design prototype. Serves C_soft_studio_full.html at "/", injects a
// tiny reload snippet into every .html response, and exposes /__mtime so the
// page can poll for edits and refresh itself. Run via .claude/launch.json.
import { createServer } from "node:http";
import { readFile, stat } from "node:fs/promises";
import { extname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = fileURLToPath(new URL(".", import.meta.url));
const PORT = 5179;
const ENTRY = "C_soft_studio_full.html";

const TYPES = {
  ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8", ".png": "image/png", ".jpg": "image/jpeg",
  ".svg": "image/svg+xml", ".ico": "image/x-icon", ".woff2": "font/woff2",
  ".json": "application/json; charset=utf-8",
};

// files whose mtime the page watches; newest wins
const WATCH = [ENTRY, "C_component_variants.html", "C_hero_variants.html", "C_onboarding.html", "C_logo_variants.html", "C_history_variants.html", "C_tray_variants.html", "serve.mjs"];
async function latest() {
  let m = 0;
  for (const f of WATCH) {
    try { m = Math.max(m, (await stat(join(ROOT, f))).mtimeMs); } catch {}
  }
  return Math.floor(m);
}

const RELOAD = `<script>
(function(){var last=null;
 async function tick(){try{var r=await fetch('/__mtime',{cache:'no-store'});var t=await r.text();
   if(last!==null&&t!==last){location.reload();return;}last=t;}catch(e){}
   setTimeout(tick,700);}
 tick();})();
</script>`;

createServer(async (req, res) => {
  const url = decodeURIComponent((req.url || "/").split("?")[0]);
  if (url === "/__mtime") {
    res.writeHead(200, { "content-type": "text/plain", "cache-control": "no-store" });
    res.end(String(await latest()));
    return;
  }
  const rel = url === "/" ? ENTRY : normalize(url).replace(/^(\.\.[/\\])+/, "").replace(/^[/\\]+/, "");
  const path = join(ROOT, rel);
  try {
    const buf = await readFile(path);
    const type = TYPES[extname(path).toLowerCase()] || "application/octet-stream";
    if (type.startsWith("text/html")) {
      const html = buf.toString("utf8").replace("</body>", RELOAD + "</body>");
      res.writeHead(200, { "content-type": type, "cache-control": "no-store" });
      res.end(html);
    } else {
      res.writeHead(200, { "content-type": type });
      res.end(buf);
    }
  } catch {
    res.writeHead(404, { "content-type": "text/plain; charset=utf-8" });
    res.end("404 — " + rel);
  }
}).listen(PORT, () => console.log("KuubWave prototype live at http://localhost:" + PORT + "/  (auto-reload on save)"));

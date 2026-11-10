import os
import re
import json
import time
import asyncio
import io
import random
import urllib.parse
import urllib.request
import base64
import socket
import selectors
import threading
from datetime import datetime
from urllib.parse import urlparse, urljoin

try:
    from pyvirtualdisplay import Display
    from playwright.async_api import async_playwright
except ImportError:
    print("Please install requirements: pip install playwright pyvirtualdisplay pillow")
    exit(1)

# ==================== CONFIG ====================
START_URL = os.environ.get("START_URL", "https://linkpays.in/vVVSq")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "") # e.g. "samir9156/LPbypass"
PROXY_FILE = "proxy.txt"
DB_FILE = "db.json"

GATEWAY_HOSTS = {"linkpays.in"}
CHAIN_HOSTS = {
    "roadtaxcalculatorr.my", "rank1st.in", "pipefitter.in",
    "startuplearners.com", "vplink.in", "evspec.in"
}
TRACK_RE = re.compile(
    r"doubleclick|googlesyndication|google-analytics|googletagmanager|"
    r"adtrafficquality|safeframe|sodar|quantserve|rubicon|bluekai|"
    r"1rx\.io|tribalfusion|adtdp|criteo|taboola|outbrain|temu\.com|"
    r"recaptcha|challenges\.cloudflare|adnxs|adsystem|adservice|"
    r"pagead|adserver|adcolony|unityads|vungle|applovin|mopub|inmobi|"
    r"chartboost|ironsrc|fyber|smaato|chpadblock|oxylabs", re.I
)
BANDWIDTH_SAVE_RE = re.compile(r"\.(mp4|webm|mp3|wav|ogg|woff|woff2|ttf|otf|eot)(\?.*)?$", re.I)

def log(*a): print(f"[{datetime.now().strftime('%H:%M:%S')}]", *a, flush=True)
def get_host(u):
    try: return urlparse(u).hostname.replace("www.", "") if urlparse(u).hostname else ""
    except: return ""
def base_url(u): return u.split("#")[0]

# ==================== LOCAL AUTH PROXY (Fixes Chromium Bug) ====================
class LocalAuthProxy:
    def __init__(self, host, port, username, password):
        self.host = host
        self.port = port
        self.auth_header = "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()
        self.sel = selectors.DefaultSelector()
        self.running = False
        self.server_sock = None

    def start(self):
        self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_sock.bind(("127.0.0.1", 0)) # OS assigns free port
        self.server_sock.listen(100)
        self.server_sock.setblocking(False)
        self.port = self.server_sock.getsockname()[1]
        self.sel.register(self.server_sock, selectors.EVENT_READ, self._accept)
        self.running = True
        threading.Thread(target=self._run, daemon=True).start()
        return self.port

    def stop(self):
        self.running = False
        if self.server_sock:
            try: self.server_sock.close()
            except: pass

    def _run(self):
        while self.running:
            try:
                events = self.sel.select(timeout=0.5)
                for key, mask in events:
                    callback = key.data
                    callback(key.fileobj)
            except Exception:
                pass

    def _accept(self, sock):
        conn, addr = sock.accept()
        conn.setblocking(False)
        self.sel.register(conn, selectors.EVENT_READ, self._read)

    def _read(self, conn):
        try:
            data = conn.recv(65536)
            if not data:
                self._close(conn); return
            
            header_end = data.find(b"\r\n\r\n")
            if header_end != -1:
                head = data[:header_end].decode('utf-8', errors='ignore')
                body = data[header_end:]
                
                if "Proxy-Authorization" not in head:
                    lines = head.split("\r\n")
                    new_headers = lines[0] + "\r\n"
                    for line in lines[1:]:
                        if line.lower().startswith("host:") or line.lower().startswith("proxy-connection:"):
                            new_headers += line + "\r\n"
                    
                    new_headers += f"Proxy-Authorization: {self.auth_header}\r\n"
                    new_headers += "Proxy-Connection: close\r\n"
                    new_headers += "\r\n"
                    data = new_headers.encode('utf-8') + body

            upstream = socket.create_connection((self.host, self.port), timeout=15)
            upstream.sendall(data)
            
            while True:
                resp = upstream.recv(65536)
                if not resp: break
                conn.sendall(resp)
            
            self._close(conn)
            upstream.close()
        except Exception:
            self._close(conn)

    def _close(self, conn):
        try:
            self.sel.unregister(conn)
            conn.close()
        except:
            pass

# ==================== GITHUB DB ====================
def gh_api(method, path, data=None):
    if not GITHUB_TOKEN or not GITHUB_REPO: return None
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"
    req = urllib.request.Request(url, method=method)
    req.add_header("Authorization", f"token {GITHUB_TOKEN}")
    req.add_header("Accept", "application/vnd.github.v3+json")
    req.add_header("User-Agent", "Railway-Script")
    if data:
        req.add_header("Content-Type", "application/json")
        req.data = json.dumps(data).encode()
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 404: return None
        log("GitHub API Error:", e.read().decode())
        return None

def load_db():
    if not GITHUB_TOKEN or not GITHUB_REPO:
        if os.path.exists(DB_FILE):
            with open(DB_FILE, "r") as f: return json.load(f)
        return {"used_ips": [], "used_user_agents": [], "completed_tasks": []}
    
    res = gh_api("GET", "db.json")
    if res and "content" in res:
        content = base64.b64decode(res["content"]).decode("utf-8")
        return json.loads(content)
    return {"used_ips": [], "used_user_agents": [], "completed_tasks": []}

def save_db(db):
    if not GITHUB_TOKEN or not GITHUB_REPO:
        with open(DB_FILE, "w") as f: json.dump(db, f, indent=2)
        return
    
    content_b64 = base64.b64encode(json.dumps(db, indent=2).encode()).decode()
    res = gh_api("GET", "db.json")
    sha = res["sha"] if res and "sha" in res else None
    
    data = {"message": "Auto-update DB after task", "content": content_b64}
    if sha: data["sha"] = sha
    
    gh_api("PUT", "db.json", data)
    log("  ✅ DB updated on GitHub")

# ==================== STEALTH JS ====================
STEALTH_JS = """
    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
    window.chrome = window.chrome || { runtime: {}, loadTimes: function(){}, csi: function(){} };
    Object.defineProperty(navigator, 'languages', {get: () => ['en-IN','en']});
    Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
    Object.defineProperty(navigator, 'deviceMemory', {get: () => 8});
    Object.defineProperty(navigator, 'hardwareConcurrency', {get: () => 8});
    
    const getParameter = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(parameter) {
        if (parameter === 37445) return 'Intel Inc.';
        if (parameter === 37446) return 'Intel Iris OpenGL Engine';
        return getParameter.apply(this, [parameter]);
    };
    
    const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) => (
        parameters.name === 'notifications' ?
            Promise.resolve({ state: Notification.permission }) :
            originalQuery(parameters)
    );

    const stripDbg = c => typeof c === 'string' ? c.replace(/\\bdebugger\\b/g, '') : c;
    const origEval = window.eval;
    window.eval = function(c) {
        if (typeof c === 'string' && /chp_?ad|chp_ads_block|chp_branding/i.test(c)) return undefined;
        return origEval.call(this, stripDbg(c));
    };
    const origFn = window.Function;
    window.Function = function(...a) { return origFn.apply(this, a.map(x => stripDbg(x))); };
    window.Function.prototype = origFn.prototype;

    const SPEEDUP = 20;
    const _st = window.setTimeout;
    window.setTimeout = function(fn, d, ...a) {
        return _st.call(this, fn, d > 500 ? Math.max(50, d / SPEEDUP) : d, ...a);
    };
    const _si = window.setInterval;
    window.setInterval = function(fn, d, ...a) {
        return _si.call(this, fn, d > 500 ? Math.max(50, d / SPEEDUP) : d, ...a);
    };
"""

# ==================== LINKPAYS LOGIC ====================
def is_gateway_host(h): return bool(h) and (h == "linkpays.in" or h.endswith(".linkpays.in"))
def is_intermediate_hop(u): return bool(re.search(r'[?&](verify|link|code|goto|go|r|ref)=', u, re.I)) if u else False
def is_known_shortener(u):
    if not u: return False
    h = get_host(u)
    return h in CHAIN_HOSTS or h.endswith(".linkpays.in")
def is_valid_dest(u, current_url=None):
    if not u or not u.startswith("http"): return False
    if is_intermediate_hop(u): return False
    if is_known_shortener(u): return False
    if TRACK_RE.search(u): return False
    if current_url and base_url(u) == base_url(current_url): return False
    return True

async def is_vis(loc):
    try:
        if not await loc.is_visible(): return False
        bb = await loc.bounding_box() or {}
        return bb.get("width", 0) > 4 and bb.get("height", 0) > 4
    except: return False
async def is_en(loc):
    try: return await loc.is_enabled()
    except: return False
async def itext(loc):
    try: return (await loc.inner_text() or "").strip()
    except: return ""

async def safe_click(loc, page=None, force=True):
    try: await loc.scroll_into_view_if_needed(timeout=2000)
    except: pass
    if page is not None:
        try:
            bb = await loc.bounding_box()
            if bb:
                cx, cy = bb["x"] + bb["width"]/2, bb["y"] + bb["height"]/2
                await page.mouse.move(cx, cy)
                await asyncio.sleep(0.08)
                await page.mouse.click(cx, cy)
                return True
        except: pass
    try: await loc.click(timeout=2500, no_wait_after=True, force=force); return True
    except: pass
    try: await loc.evaluate("el => el.click()"); return True
    except: return False

SEL = "button, input[type=submit], input[type=button], a, [role=button]"
_failed_x = set()
_last_url_x = [""]

async def close_all_x(page):
    if page.url != _last_url_x[0]:
        _failed_x.clear()
        _last_url_x[0] = page.url
    did = False
    try:
        removed = await page.evaluate(r"""() => {
            const X = /^[×✕✖xX✗✘]$/;
            const C = /(close|dismiss|btn-x|x-btn|modal-close|popup-close|overlay-close|ad-close|interstitial-close|exit)/i;
            const isX = (el) => {
                if (!el || el.nodeType !== 1) return false;
                if (X.test((el.innerText || el.textContent || '').trim())) return true;
                if (C.test((el.className || '') + '') || C.test(el.id || '')) return true;
                const aria = (el.getAttribute?.('aria-label') || '').toLowerCase();
                const title = (el.getAttribute?.('title') || '').toLowerCase();
                if (/(close|dismiss|exit|remove)/.test(aria + ' ' + title)) return true;
                const tag = el.tagName.toLowerCase();
                if (['svg','path','use','g','polyline','line'].includes(tag)) {
                    let n = el.parentElement;
                    for (let i = 0; i < 5 && n && n !== document.body; i++) {
                        const cc = ((n.className || '') + ' ' + (n.id || '') + ' ' +
                                    (n.getAttribute?.('aria-label') || '') + ' ' +
                                    (n.getAttribute?.('title') || '')).toLowerCase();
                        if (/(close|dismiss|exit|remove|x-btn|btn-x|popup-close|modal-close)/.test(cc)) return true;
                        n = n.parentElement;
                    }
                }
                return false;
            };
            let count = 0; const seen = new Set();
            document.querySelectorAll('body *').forEach(el => {
                if (!isX(el)) return;
                const r = el.getBoundingClientRect();
                if (r.width < 4 || r.width > 100 || r.height < 4 || r.height > 100) return;
                if (r.top < 0 || r.left < 0) return;
                const s = getComputedStyle(el);
                if (s.display === 'none' || s.visibility === 'hidden') return;
                const a = el.closest('a');
                if (a) { const h = a.getAttribute('href') || ''; if (h && !h.startsWith('#') && !h.startsWith('javascript:')) return; }
                let p = el.parentElement;
                for (let i = 0; i < 8 && p && p !== document.body; i++) {
                    const pr = p.getBoundingClientRect();
                    const ps = getComputedStyle(p);
                    if ((ps.position === 'fixed' || ps.position === 'absolute') &&
                        pr.width > 100 && pr.width < 900 && pr.height > 80 && pr.height < 900) {
                        const edge = Math.min(Math.abs(r.left - pr.left), Math.abs(r.left + r.width - pr.right),
                                              Math.abs(r.top - pr.top), Math.abs(r.top + r.height - pr.bottom));
                        if (edge < 100 && !seen.has(p)) {
                            const b = p.querySelectorAll('button, input[type=submit], textarea').length;
                            if (b <= 3) { try { p.remove(); count++; seen.add(p); } catch {} }
                        }
                        break;
                    }
                    p = p.parentElement;
                }
            });
            return count;
        }""")
        if removed > 0: did = True
    except: pass
    try:
        hits = await page.evaluate(r"""() => {
            const X = /^[×✕✖xX✗✘]$/;
            const C = /(close|dismiss|btn-x|x-btn|modal-close|popup-close|overlay-close|ad-close|interstitial-close|exit)/i;
            const isX = (el) => {
                if (!el || el.nodeType !== 1) return false;
                if (X.test((el.innerText || el.textContent || '').trim())) return true;
                if (C.test((el.className || '') + '') || C.test(el.id || '')) return true;
                const aria = (el.getAttribute?.('aria-label') || '').toLowerCase();
                const title = (el.getAttribute?.('title') || '').toLowerCase();
                if (/(close|dismiss|exit|remove)/.test(aria + ' ' + title)) return true;
                const tag = el.tagName.toLowerCase();
                if (['svg','path','use','g','polyline','line'].includes(tag)) {
                    let n = el.parentElement;
                    for (let i = 0; i < 5 && n && n !== document.body; i++) {
                        const cc = ((n.className || '') + ' ' + (n.id || '') + ' ' +
                                    (n.getAttribute?.('aria-label') || '') + ' ' +
                                    (n.getAttribute?.('title') || '')).toLowerCase();
                        if (/(close|dismiss|exit|remove|x-btn|btn-x|popup-close|modal-close)/.test(cc)) return true;
                        n = n.parentElement;
                    }
                }
                return false;
            };
            const out = [];
            document.querySelectorAll('body *').forEach(el => {
                if (!isX(el)) return;
                const r = el.getBoundingClientRect();
                if (r.width < 4 || r.width > 100 || r.height < 4 || r.height > 100) return;
                if (r.top < 0 || r.left < 0) return;
                const s = getComputedStyle(el);
                if (s.display === 'none' || s.visibility === 'hidden') return;
                const a = el.closest('a');
                if (a) { const h = a.getAttribute('href') || ''; if (h && !h.startsWith('#') && !h.startsWith('javascript:')) return; }
                out.push({x: Math.round(r.x + r.width/2), y: Math.round(r.y + r.height/2), tag: el.tagName});
            });
            return out.slice(0, 5);
        }""")
        for h in hits:
            key = f"{h['x']}_{h['y']}"
            if key in _failed_x: continue
            _failed_x.add(key)
            try:
                await page.mouse.move(h["x"], h["y"])
                await asyncio.sleep(0.06)
                await page.mouse.click(h["x"], h["y"])
                did = True
            except: pass
            break
    except: pass
    return did

async def kill_chpadblock(page):
    try:
        n = await page.evaluate("""() => {
            let n = 0;
            const k = (el) => { try { el.remove(); n++; } catch {} };
            document.querySelectorAll('[class*="chp_ads_block" i], [id*="chp_ads_block" i], [class*="chp_branding" i]').forEach(k);
            if (document.body) { document.body.style.overflow = ''; document.body.classList.remove('modal-open','no-scroll'); }
            return n;
        }""")
        return n > 0
    except: return False

async def find_cookie(page):
    for loc in await page.locator(SEL).all():
        if not await is_vis(loc): continue
        if re.match(r"^(got\s*it!?|accept(\s*all)?|i\s*agree)$", await itext(loc), re.I):
            return loc
    return None

async def find_not_robot(page):
    for loc in await page.locator(SEL).all():
        if not await is_vis(loc): continue
        t = await itext(loc)
        if len(t) > 60: continue
        if not re.search(r"not\s*(?:a\s*)?robot|i['’]?m\s*not\s*robot", t, re.I): continue
        try:
            fake = await loc.evaluate(r"""el => {
                let n = el;
                for (let i = 0; i < 8 && n && n !== document.body; i++) {
                    if (n.tagName === 'IFRAME') return 'iframe';
                    const cls = ((n.className || '') + ' ' + (n.id || '')).toLowerCase();
                    if (/\b(ad|ads|advert|sponsor|promo|banner|interstitial|popup|overlay)\b/.test(cls)) return 'ad-class';
                    const s = getComputedStyle(n);
                    const r = n.getBoundingClientRect();
                    if ((s.position === 'fixed' || s.position === 'absolute') &&
                        r.width > 100 && r.width < 800 && r.height > 80 && r.height < 800 &&
                        (s.boxShadow !== 'none' || parseFloat(s.borderRadius) > 0)) return 'fixed-popup';
                    n = n.parentElement;
                }
                return null;
            }""")
            if fake: continue
        except: pass
        return loc
    return None

async def find_continue_nn(page):
    a_p, btn, a_href = None, None, None
    for loc in await page.locator(SEL).all():
        if not await is_vis(loc): continue
        t = await itext(loc)
        if not re.search(r"continue\s*\d+\s*/\s*\d+", t, re.I): continue
        try: tag = await loc.evaluate("el => el.tagName")
        except: tag = ""
        if tag == "A":
            href = await loc.get_attribute("href") or ""
            if href and not href.startswith("javascript:") and not TRACK_RE.search(href):
                if a_p is None: a_p, a_href = loc, href
        elif btn is None: btn = loc
    return (a_p or btn, a_href)

async def find_generic(page):
    pat = re.compile(r"^(continue(\s*to\s*(content|link))?|verify|get\s*link|proceed|submit|next|go\s*to\s*link|click\s*to\s*verify|back\s*for\s*link)$", re.I)
    for loc in await page.locator(SEL).all():
        if not await is_vis(loc): continue
        t = await itext(loc)
        if not t or len(t) > 90: continue
        if pat.match(t): return loc
    return None

async def wait_url_change(page, prev, timeout_s=25):
    prev_b = base_url(prev)
    end = time.time() + timeout_s
    while time.time() < end:
        if base_url(page.url) != prev_b: return True
        await asyncio.sleep(0.3)
    return False

async def try_turnstile(page):
    try:
        fl = page.frame_locator('iframe[src*="challenges.cloudflare.com"]')
        cb = fl.locator('input[type="checkbox"]')
        if await cb.count() > 0 and await cb.first.is_visible(timeout=800):
            await cb.first.click(timeout=1500); return True
    except: pass
    return False

async def fast_forward_meta(page):
    try:
        content = await page.evaluate("""() => {
            const m = document.querySelector('meta[http-equiv="refresh" i]');
            return m ? m.getAttribute('content') : null;
        }""")
    except: content = None
    if not content: return False
    m = re.match(r"^\s*(\d+)\s*;\s*url\s*=\s*['\"]?([^'\"]+)", content, re.I)
    if not m or int(m.group(1)) < 2: return False
    try: target = urljoin(page.url, m.group(2))
    except: return False
    if not is_valid_dest(target, current_url=page.url): return False
    try:
        await page.goto(target, wait_until="domcontentloaded", timeout=15000)
        return True
    except: return False

async def find_dest(page, cur_host):
    for loc in await page.locator("script:not([src])").all():
        try: src = await loc.inner_text(timeout=200)
        except: continue
        for m in re.finditer(r"""location\.(?:href|replace|assign)\s*(?:=|\()\s*['"]([^'"]{8,})['"]""", src or ""):
            u = m.group(1)
            if u.startswith("http") and is_valid_dest(u, current_url=page.url): return u
        for m in re.finditer(r"""window\.(?:open|location)\s*(?:=|\()\s*['"]([^'"]{8,})['"]""", src or ""):
            u = m.group(1)
            if u.startswith("http") and is_valid_dest(u, current_url=page.url): return u
    for a in await page.locator('a[href]').all():
        if not await is_vis(a): continue
        if not re.search(r"get\s*link|download|click\s*here|final|visit\s*link", await itext(a), re.I): continue
        href = await a.get_attribute("href") or ""
        try: full = urljoin(page.url, href)
        except: full = href
        if is_valid_dest(full, current_url=page.url): return full
    return None

async def gateway_page_state(page):
    try: text = await page.evaluate("() => (document.body?.innerText || '').slice(0, 3000)")
    except: text = ""
    if re.search(r"redirecting", text, re.I): return "return"
    if re.search(r"verification\s+complete", text, re.I): return "fresh"
    if re.search(r"continue\s+to\s+content", text, re.I): return "fresh"
    btn = await find_generic(page)
    if btn: return "fresh"
    return "unknown"

async def handle_gateway_fresh(page, code):
    start = time.time(); ts = False
    while time.time() - start < 60:
        await close_all_x(page); await kill_chpadblock(page)
        loc = await find_generic(page)
        if loc and await is_en(loc):
            await safe_click(loc, page=page, force=True)
            if await wait_url_change(page, page.url, 20): return "navigated"
        if not ts and time.time() - start > 5:
            ts = True; await try_turnstile(page)
        await asyncio.sleep(0.5)
    return "timeout"

async def handle_gateway_return(page, code, state):
    start = time.time(); last_dest_attempt = 0
    while time.time() - start < 60:
        cur_h = get_host(page.url)
        if not is_gateway_host(cur_h): return "navigated"
        pstate = await gateway_page_state(page)
        if pstate == "fresh":
            state[f"code:{code}"] = {
                "chainStartedAt": int(time.time()*1000),
                "lastHost": cur_h, "lastUrl": page.url, "rechained": True,
            }
            save_db(state)
            return "fresh-reset"
        if time.time() - start > 15 and time.time() - last_dest_attempt > 10:
            last_dest_attempt = time.time()
            dest = await find_dest(page, cur_h)
            if dest and is_valid_dest(dest, current_url=page.url):
                try: await page.goto(dest, wait_until="domcontentloaded", timeout=25000)
                except: continue
                await asyncio.sleep(2)
                final_h = get_host(page.url)
                if not is_gateway_host(final_h): return "navigated"
                return "bounced"
        await asyncio.sleep(1)
    return "timeout"

async def handle_chain_page(page, max_wait=300):
    await asyncio.sleep(1.5)
    if await fast_forward_meta(page): return "navigated"
    start = time.time(); init_url = page.url
    nr_last = ""; nr_count = 0
    last_click = 0; last_img = time.time(); stall_at = time.time()

    while time.time() - start < max_wait:
        if base_url(page.url) != base_url(init_url): return "navigated"
        if page.url != nr_last: nr_count = 0; nr_last = page.url

        if await close_all_x(page): await asyncio.sleep(0.3); continue
        if await kill_chpadblock(page): await asyncio.sleep(0.2); continue

        cookie = await find_cookie(page)
        if cookie: await safe_click(cookie, page=page); await asyncio.sleep(0.4); continue

        loc, href = await find_continue_nn(page)
        if loc and await is_en(loc):
            if href and href.startswith("http") and not is_intermediate_hop(href) and is_valid_dest(href, current_url=page.url):
                try: await page.goto(href, wait_until="domcontentloaded", timeout=30000); return "navigated"
                except: pass
            if time.time() - last_click > 1.5:
                await safe_click(loc, page=page)
                last_click = time.time()
                if await wait_url_change(page, init_url, 20): return "navigated"
                continue

        loc = await find_generic(page)
        if loc and await is_en(loc) and time.time() - last_click > 2:
            await safe_click(loc, page=page)
            last_click = time.time()
            if await wait_url_change(page, init_url, 20): return "navigated"
            continue

        nr = await find_not_robot(page)
        if nr and nr_count < 1 and time.time() - last_click > 2:
            await safe_click(nr, page=page)
            nr_count += 1; last_click = time.time()
            await asyncio.sleep(2); continue

        if time.time() - last_img > 25 and not nr:
            try:
                img = await page.evaluate("""() => {
                    for (const img of document.querySelectorAll('img')) {
                        const r = img.getBoundingClientRect();
                        if (r.width < 150 || r.height < 100) continue;
                        if (getComputedStyle(img).display === 'none') continue;
                        const a = img.closest('a');
                        if ((a && (a.getAttribute('target') === '_blank' || a.href)) || img.onclick) {
                            return {x: r.x + r.width/2, y: r.y + r.height/2};
                        }
                    }
                    return null;
                }""")
                if img:
                    await page.mouse.click(img["x"], img["y"])
                    last_img = time.time()
                    await asyncio.sleep(2); continue
            except: pass

        await asyncio.sleep(0.5)
    return "timeout"

# ==================== MAIN LOGIC ====================
async def run():
    db = load_db()
    
    # ==================== PRE-CHECK ====================
    if START_URL in db.get("completed_tasks", []):
        log(f"🛑 ALERT: {START_URL} is already marked as COMPLETED in db.json.")
        log("Exiting to save resources and prevent duplicate clicks.")
        return

    # Proxy setup
    proxy_url = None
    if os.path.exists(PROXY_FILE):
        with open(PROXY_FILE, "r") as f:
            lines = [l.strip() for l in f if l.strip() and not l.startswith("#")]
            if lines: proxy_url = random.choice(lines)
            
    # UA setup
    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Mobile/15E148 Safari/604.1"
    ]
    ua = random.choice(USER_AGENTS)
    
    display = Display(visible=0, size=(1920, 1080))
    display.start()
    
    log(f"Starting Task: {START_URL}")
    
    local_proxy = None
    launch_opts = {
        "headless": False,
        "args": ["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"]
    }

    if proxy_url:
        parsed = urlparse(proxy_url)
        log(f"Proxy detected: {parsed.hostname}:{parsed.port}")
        local_proxy = LocalAuthProxy(parsed.hostname, parsed.port, parsed.username, parsed.password)
        local_port = local_proxy.start()
        launch_opts["proxy"] = {"server": f"http://127.0.0.1:{local_port}"}
        log(f"  ✅ local proxy listening on 127.0.0.1:{local_port}")
    else:
        log("No proxy detected, using Railway default IP")

    async with async_playwright() as p:
        browser = await p.chromium.launch(**launch_opts)
        ctx = await browser.new_context(user_agent=ua, viewport={"width": 1920, "height": 1080}, locale="en-IN")
        
        async def block_route(route):
            if TRACK_RE.search(route.request.url) or BANDWIDTH_SAVE_RE.search(route.request.url):
                await route.abort()
            else:
                await route.continue_()
        await ctx.route("**/*", block_route)
        
        page = await ctx.new_page()
        await page.add_init_script(STEALTH_JS)
        
        try:
            cdp = await ctx.new_cdp_session(page)
            await cdp.send("Debugger.enable")
            await cdp.send("Debugger.setSkipAllPauses", {"skip": True})
        except: pass

        log(f"Opening {START_URL}")
        try:
            await page.goto(START_URL, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            log("Navigation failed:", e)
            await browser.close()
            display.stop()
            return

        # State Management for Flow
        state = {}
        dest_url = None
        gateway_visits = {}
        bounce_count = 0
        last_base = ""
        stuck = 0
        t0 = time.time()

        while time.time() - t0 < 900: # Max 15 mins
            cur_u = page.url; cur_b = base_url(cur_u); cur_h = get_host(cur_u)
            
            is_inter = is_intermediate_hop(cur_u)
            is_shortener = is_known_shortener(cur_u)

            if (cur_h and not is_gateway_host(cur_h) and not is_inter and not is_shortener and not TRACK_RE.search(cur_u)):
                dest_url = cur_u
                log(f"✅ DESTINATION: {cur_u}")
                break

            if cur_b == last_base: stuck += 1
            else: stuck = 0; last_base = cur_b
            if stuck > 180:
                log("STUCK, aborting"); break

            try:
                c = await ctx.new_cdp_session(page)
                await c.send("Debugger.enable")
                await c.send("Debugger.setSkipAllPauses", {"skip": True})
                await c.detach()
            except: pass

            code_m = re.match(r"^/([A-Za-z0-9_-]{2,})/?$", urlparse(cur_u).path)
            code = code_m.group(1) if code_m and is_gateway_host(cur_h) else None

            if is_gateway_host(cur_h) and code:
                pstate = await gateway_page_state(page)
                ent = state.get(f"code:{code}", {})
                is_ret_state = (ent.get("chainStartedAt") and (time.time()*1000 - ent["chainStartedAt"] < 30*60*1000) and ent.get("lastHost"))
                
                gateway_visits[code] = gateway_visits.get(code, 0) + 1
                if gateway_visits[code] > 6:
                    log("Gateway loop detected, aborting"); break

                if pstate == "fresh":
                    state[f"code:{code}"] = {
                        "chainStartedAt": int(time.time()*1000),
                        "lastHost": cur_h, "lastUrl": cur_u,
                    }
                    save_db(state)
                    await handle_gateway_fresh(page, code)
                elif pstate == "return" or (pstate == "unknown" and is_ret_state):
                    result = await handle_gateway_return(page, code, state)
                    if result == "bounced":
                        bounce_count += 1
                        if bounce_count >= 2: break
                        await asyncio.sleep(5)
                else:
                    if is_ret_state:
                        result = await handle_gateway_return(page, code, state)
                        if result == "bounced":
                            bounce_count += 1
                            if bounce_count >= 2: break
                    else:
                        state[f"code:{code}"] = {
                            "chainStartedAt": int(time.time()*1000),
                            "lastHost": cur_h, "lastUrl": cur_u,
                        }
                        save_db(state)
                        await handle_gateway_fresh(page, code)
            else:
                # Chain host or unknown hop
                await handle_chain_page(page)

            if base_url(page.url) != base_url(cur_u):
                nh = get_host(page.url)
                if nh and not is_gateway_host(nh) and not is_intermediate_hop(page.url) and not is_known_shortener(page.url):
                    dest_url = page.url
                    log(f"✅ DESTINATION: {page.url}")
                    break

            await asyncio.sleep(0.8)

        # ==================== POST-CHECK ====================
        if dest_url:
            if START_URL not in db["completed_tasks"]: db["completed_tasks"].append(START_URL)
            if dest_url not in db["completed_tasks"]: db["completed_tasks"].append(dest_url)
            db["used_user_agents"].append(ua)
            if proxy_url: db["used_ips"].append(proxy_url)
            save_db(db)
            log("✅ Task completed and saved to DB. Next run will skip this URL.")
        else:
            log("❌ Flow failed or stuck.")

        await browser.close()
    
    if local_proxy: local_proxy.stop()
    display.stop()

if __name__ == "__main__":
    asyncio.run(run())

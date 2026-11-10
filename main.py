import os, re, json, time, asyncio, random, urllib.parse, urllib.request, base64, socket, selectors, threading
from datetime import datetime
from urllib.parse import urlparse, urljoin
from pyvirtualdisplay import Display
from playwright.async_api import async_playwright

# ==================== CONFIG ====================
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "") # e.g. samir9156/LPbypass
RAILWAY_TOKEN = os.environ.get("RAILWAY_TOKEN", "")
RAILWAY_SERVICE_ID = os.environ.get("RAILWAY_SERVICE_ID", "")
RAILWAY_ENVIRONMENT_ID = os.environ.get("RAILWAY_ENVIRONMENT_ID", "")

PROXY_FILE = "proxy.txt"
DB_FILE = "db.json"
URLS_FILE = "urls.txt"

GATEWAY_HOSTS = {"linkpays.in"}
CHAIN_HOSTS = {"roadtaxcalculatorr.my", "rank1st.in", "pipefitter.in", "startuplearners.com", "vplink.in", "evspec.in"}
TRACK_RE = re.compile(r"doubleclick|googlesyndication|google-analytics|googletagmanager|adtrafficquality|safeframe|sodar|quantserve|rubicon|bluekai|1rx\.io|tribalfusion|adtdp|criteo|taboola|outbrain|temu\.com|recaptcha|challenges\.cloudflare|adnxs|adsystem|adservice|pagead|adserver|adcolony|unityads|vungle|applovin|mopub|inmobi|chartboost|ironsrc|fyber|smaato|chpadblock", re.I)
BANDWIDTH_SAVE_RE = re.compile(r"\.(mp4|webm|mp3|wav|ogg|woff|woff2|ttf|otf|eot)(\?.*)?$", re.I)

REGIONS = ["us-east4-eqdc4a", "us-west2"] # Virginia, California

def log(*a): print(f"[{datetime.now().strftime('%H:%M:%S')}]", *a, flush=True)
def get_host(u):
    try: return urlparse(u).hostname.replace("www.", "") if urlparse(u).hostname else ""
    except: return ""
def base_url(u): return u.split("#")[0]

# ==================== GITHUB DB & API ====================
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
        return None

def load_gh_file(path):
    res = gh_api("GET", path)
    if res and "content" in res:
        return base64.b64decode(res["content"]).decode("utf-8")
    return ""

def save_gh_file(path, content):
    if not GITHUB_TOKEN or not GITHUB_REPO: return
    content_b64 = base64.b64encode(content.encode()).decode()
    res = gh_api("GET", path)
    sha = res["sha"] if res and "sha" in res else None
    data = {"message": f"Auto-update {path}", "content": content_b64}
    if sha: data["sha"] = sha
    gh_api("PUT", path, data)

def load_db():
    content = load_gh_file("db.json")
    if content: return json.loads(content)
    return {"used_ips": [], "used_user_agents": [], "completed_tasks": [], "current_region": "us-east4-eqdc4a"}

def save_db(db): save_gh_file("db.json", json.dumps(db, indent=2))

def get_next_url():
    content = load_gh_file("urls.txt")
    urls = [line.strip() for line in content.splitlines() if line.strip()]
    db = load_db()
    completed = set(db.get("completed_tasks", []))
    available = [u for u in urls if u not in completed]
    if not available: return None
    return random.choice(available)

# ==================== RAILWAY REDEPLOY API ====================
def trigger_railway_redeploy():
    if not RAILWAY_TOKEN or not RAILWAY_SERVICE_ID or not RAILWAY_ENVIRONMENT_ID:
        log("⚠️ Railway API keys missing. Cannot auto-redeploy.")
        return False
        
    db = load_db()
    current_region = db.get("current_region", REGIONS[0])
    next_region = REGIONS[1] if current_region == REGIONS[0] else REGIONS[0]
    db["current_region"] = next_region
    save_db(db)

    log(f"🚀 Triggering Railway redeploy to region: {next_region}")
    
    url = "https://backboard.railway.app/graphql/v2"
    query = """
    mutation {
      serviceInstanceUpdate(
        serviceId: "%s"
        environmentId: "%s"
        input: { region: "%s" }
      )
    }
    """ % (RAILWAY_SERVICE_ID, RAILWAY_ENVIRONMENT_ID, next_region)

    req = urllib.request.Request(url, method="POST")
    req.add_header("Authorization", f"Bearer {RAILWAY_TOKEN}")
    req.add_header("Content-Type", "application/json")
    req.data = json.dumps({"query": query}).encode()
    
    try:
        with urllib.request.urlopen(req) as resp:
            res = json.loads(resp.read().decode())
            if "errors" in res:
                log(f"Railway API Error: {res['errors']}")
            else:
                log("✅ Railway redeploy triggered successfully.")
    except Exception as e:
        log(f"Failed to trigger Railway API: {e}")

# ==================== LOCAL AUTH PROXY ====================
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
        self.server_sock.bind(("127.0.0.1", 0))
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
            except Exception: pass

    def _accept(self, sock):
        conn, addr = sock.accept()
        conn.setblocking(False)
        self.sel.register(conn, selectors.EVENT_READ, self._read)

    def _read(self, conn):
        try:
            data = conn.recv(65536)
            if not data: self._close(conn); return
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
                    new_headers += f"Proxy-Authorization: {self.auth_header}\r\nProxy-Connection: close\r\n\r\n"
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
        try: self.sel.unregister(conn); conn.close()
        except: pass

# ==================== STEALTH JS ====================
STEALTH_JS = """
    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
    window.chrome = window.chrome || { runtime: {}, loadTimes: function(){}, csi: function(){} };
    Object.defineProperty(navigator, 'languages', {get: () => ['en-IN','en']});
    Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
    Object.defineProperty(navigator, 'deviceMemory', {get: () => 8});
    const getParameter = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(parameter) {
        if (parameter === 37445) return 'Intel Inc.';
        if (parameter === 37446) return 'Intel Iris OpenGL Engine';
        return getParameter.apply(this, [parameter]);
    };
    const stripDbg = c => typeof c === 'string' ? c.replace(/\\bdebugger\\b/g, '') : c;
    const origEval = window.eval;
    window.eval = function(c) {
        if (typeof c === 'string' && /chp_?ad|chp_ads_block|chp_branding/i.test(c)) return undefined;
        return origEval.call(this, stripDbg(c));
    };
    const origFn = window.Function;
    window.Function = function(...a) { return origFn.apply(this, a.map(x => stripDbg(x))); };
    const SPEEDUP = 20;
    const _st = window.setTimeout;
    window.setTimeout = function(fn, d, ...a) { return _st.call(this, fn, d > 500 ? Math.max(50, d / SPEEDUP) : d, ...a); };
    const _si = window.setInterval;
    window.setInterval = function(fn, d, ...a) { return _si.call(this, fn, d > 500 ? Math.max(50, d / SPEEDUP) : d, ...a); };
"""

# ==================== LINKPAYS LOGIC (Summarized for brevity) ====================
# [Include is_gateway_host, is_intermediate_hop, is_known_shortener, is_valid_dest, safe_click, close_all_x, kill_chpadblock, find_not_robot, find_continue_nn, find_generic, wait_url_change, try_turnstile, fast_forward_meta, find_dest, gateway_page_state, handle_gateway_fresh, handle_gateway_return, handle_chain_page EXACTLY from previous version]

async def run():
    target_url = get_next_url()
    if not target_url:
        log("🎉 All URLs from urls.txt have been completed! Exiting without redeploying.")
        return
        
    log(f"🎯 Selected Random Target: {target_url}")

    proxy_url = None
    if os.path.exists(PROXY_FILE):
        with open(PROXY_FILE, "r") as f:
            lines = [l.strip() for l in f if l.strip() and not l.startswith("#")]
            if lines: proxy_url = random.choice(lines)
            
    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36"
    ]
    ua = random.choice(USER_AGENTS)
    
    display = Display(visible=0, size=(1920, 1080))
    display.start()
    
    local_proxy = None
    launch_opts = {
        "headless": False,
        "args": ["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"]
    }

    if proxy_url:
        parsed = urlparse(proxy_url)
        local_proxy = LocalAuthProxy(parsed.hostname, parsed.port, parsed.username, parsed.password)
        local_port = local_proxy.start()
        launch_opts["proxy"] = {"server": f"http://127.0.0.1:{local_port}"}

    async with async_playwright() as p:
        browser = await p.chromium.launch(**launch_opts)
        ctx = await browser.new_context(user_agent=ua, viewport={"width": 1920, "height": 1080}, locale="en-IN")
        
        async def block_route(route):
            if TRACK_RE.search(route.request.url) or BANDWIDTH_SAVE_RE.search(route.request.url): await route.abort()
            else: await route.continue_()
        await ctx.route("**/*", block_route)
        
        page = await ctx.new_page()
        await page.add_init_script(STEALTH_JS)
        
        try: await page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
        except: 
            await browser.close(); display.stop()
            if local_proxy: local_proxy.stop()
            return

        # [Flow loop logic - Same as previous version, just change START_URL to target_url in state keys]
        # ... (Assume the whole flow completes and returns dest_url)
        dest_url = page.url # Placeholder for actual logic
        
        if dest_url and get_host(dest_url) not in GATEWAY_HOSTS:
            db = load_db()
            if target_url not in db["completed_tasks"]: db["completed_tasks"].append(target_url)
            if dest_url not in db["completed_tasks"]: db["completed_tasks"].append(dest_url)
            db["used_user_agents"].append(ua)
            if proxy_url: db["used_ips"].append(proxy_url)
            save_db(db)
            log(f"✅ Task completed: {dest_url}")
            
        await browser.close()
    
    if local_proxy: local_proxy.stop()
    display.stop()
    
    # 🚀 Naya IP lene ke liye Railway API trigger karo
    trigger_railway_redeploy()

if __name__ == "__main__":
    asyncio.run(run())

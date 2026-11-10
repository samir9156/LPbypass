import os, re, json, time, asyncio, io, random, urllib.parse, urllib.request, base64
from datetime import datetime
from urllib.parse import urlparse, urljoin
from pyvirtualdisplay import Display
from playwright.async_api import async_playwright

# ==================== CONFIG ====================
START_URL = os.environ.get("START_URL", "https://linkpays.in/vVVSq")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "")
PROXY_FILE = "proxy.txt"
DB_FILE = "db.json"

GATEWAY_HOSTS = {"linkpays.in"}
CHAIN_HOSTS = {"roadtaxcalculatorr.my", "rank1st.in", "pipefitter.in", "startuplearners.com", "vplink.in", "evspec.in"}
TRACK_RE = re.compile(r"doubleclick|googlesyndication|google-analytics|googletagmanager|adtrafficquality|safeframe|sodar|quantserve|rubicon|bluekai|1rx\.io|tribalfusion|adtdp|criteo|taboola|outbrain|temu\.com|recaptcha|challenges\.cloudflare|adnxs|adsystem|adservice|pagead|adserver|adcolony|unityads|vungle|applovin|mopub|inmobi|chartboost|ironsrc|fyber|smaato|chpadblock", re.I)
BANDWIDTH_SAVE_RE = re.compile(r"\.(mp4|webm|mp3|wav|ogg|woff|woff2|ttf|otf|eot)(\?.*)?$", re.I)

def log(*a): print(f"[{datetime.now().strftime('%H:%M:%S')}]", *a, flush=True)
def get_host(u):
    try: return urlparse(u).hostname.replace("www.", "") if urlparse(u).hostname else ""
    except: return ""
def base_url(u): return u.split("#")[0]

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
"""

# ==================== MAIN LOGIC ====================
async def run():
    db = load_db()
    
    # Get Proxy
    proxy_url = None
    if os.path.exists(PROXY_FILE):
        with open(PROXY_FILE, "r") as f:
            lines = [l.strip() for l in f if l.strip() and not l.startswith("#")]
            if lines: proxy_url = random.choice(lines)
            
    # Get UA
    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36"
    ]
    ua = random.choice(USER_AGENTS)
    
    display = Display(visible=0, size=(1920, 1080))
    display.start()
    
    log(f"Starting Task: {START_URL}")
    log(f"Proxy: {'Custom from proxy.txt' if proxy_url else 'Railway Default IP'}")
    
    async with async_playwright() as p:
        launch_opts = {
            "headless": False,
            "args": ["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"]
        }
        if proxy_url:
            parsed = urlparse(proxy_url)
            launch_opts["proxy"] = {
                "server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port}",
                "username": parsed.username,
                "password": parsed.password
            }
            
        browser = await p.chromium.launch(**launch_opts)
        ctx = await browser.new_context(user_agent=ua, viewport={"width": 1920, "height": 1080}, locale="en-IN")
        
        # Route blocking for bandwidth
        async def block_route(route):
            if TRACK_RE.search(route.request.url) or BANDWIDTH_SAVE_RE.search(route.request.url):
                await route.abort()
            else:
                await route.continue_()
        await ctx.route("**/*", block_route)
        
        page = await ctx.new_page()
        await page.add_init_script(STEALTH_JS)
        
        log(f"Navigating to {START_URL}")
        try:
            await page.goto(START_URL, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            log("Navigation failed:", e)
            await browser.close()
            display.stop()
            return
            
        # Wait logic for chain...
        # [Insert your LinkPays flow logic here - simplified for brevity]
        # Example: Wait for redirects, click buttons, etc.
        
        await asyncio.sleep(5) # Placeholder for actual flow
        
        final_url = page.url
        log(f"Destination: {final_url}")
        
        if final_url and get_host(final_url) not in GATEWAY_HOSTS and get_host(final_url) not in CHAIN_HOSTS:
            db["completed_tasks"].append(final_url)
            db["used_user_agents"].append(ua)
            if proxy_url: db["used_ips"].append(proxy_url)
            save_db(db)
            log("✅ Task completed and saved to DB.")
            
        await browser.close()
    
    display.stop()

if __name__ == "__main__":
    asyncio.run(run())

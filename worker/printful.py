"""Printful Mockup Generator (API v2) client: styles, create-task, poll, download.

Mockup generation is free and creates no order. It never touches the order, product-sync or file-library endpoints.
The token comes from the PRINTFUL_API_TOKEN environment variable (a repository secret on Actions) and is never logged.

Rate limits: HTTP 429 is retried with the server's Retry-After (else exponential back-off), 5xx the same, up to 6 tries.
Errors raised here never contain the token or request headers."""
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.printful.com"
MAX_IMAGE_BYTES = 12 * 1024 * 1024
POLL_SECONDS = 4
POLL_TIMEOUT = 300


class PrintfulError(RuntimeError):
    def __init__(self, msg: str, status: int | None = None, body: str = ""):
        super().__init__(msg)
        self.status = status
        self.body = body


def _token() -> str:
    t = os.environ.get("PRINTFUL_API_TOKEN", "").strip()
    if not t:
        raise PrintfulError("PRINTFUL_API_TOKEN is not set for the render worker")
    return t


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):  # never forward the token (or follow a download) to another URL
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)
_ALLOWED = re.compile(r"^/v2/(mockup-tasks(\?id=\d+)?|catalog-products/\d+/mockup-styles\?limit=\d+&offset=\d+)$")


def request(method: str, path: str, body: dict | None = None, *, sleep=time.sleep) -> dict:
    if not _ALLOWED.match(path):  # mockup generation only: no orders, files or sync, even by a later edit
        raise PrintfulError("path not allowed for the render worker")
    data = json.dumps(body).encode() if body is not None else None
    last = ""
    for attempt in range(6):
        req = urllib.request.Request(API + path, data=data, method=method)
        req.add_header("Authorization", "Bearer " + _token())
        req.add_header("Content-Type", "application/json")
        req.add_header("User-Agent", "novam-stores-render/2")
        try:
            with _OPENER.open(req, timeout=60) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            text = e.read().decode("utf-8", "replace")[:600]
            if e.code == 429 or e.code >= 500:
                wait = e.headers.get("Retry-After")
                delay = min(120, int(wait)) if wait and wait.isdigit() else min(90, 8 * 2**attempt)
                last = f"HTTP {e.code}"
                sleep(delay)
                continue
            raise PrintfulError(f"{method} {path.split('?')[0]} -> HTTP {e.code}: {text}", e.code, text) from None
        except (urllib.error.URLError, TimeoutError) as e:
            last = type(e).__name__
            sleep(min(60, 5 * 2**attempt))
    raise PrintfulError(f"{method} {path.split('?')[0]} failed after retries ({last})")


def style_rows(product_id: int) -> list[dict]:
    """All placement rows of a product's mockup styles (paged by the API)."""
    rows: list[dict] = []
    offset = 0
    while True:
        r = request("GET", f"/v2/catalog-products/{int(product_id)}/mockup-styles?limit=100&offset={offset}")
        page = r.get("data", [])
        rows.extend(page)
        if len(page) < 100:
            return rows
        offset += 100


def find_style(rows: list[dict], placement: str, area: tuple[float, float], category: str, view: str) -> int | None:
    """Style id for (category, view) on the row of this placement whose print area matches `area` (inches)."""
    for row in rows:
        if row.get("placement") != placement:
            continue
        if abs(float(row.get("print_area_width", 0)) - area[0]) > 0.02 or abs(float(row.get("print_area_height", 0)) - area[1]) > 0.02:
            continue
        for s in row.get("mockup_styles", []):
            if s.get("category_name") == category and s.get("view_name") == view:
                return int(s["id"])
    return None


def create_task(product_id: int, variant_id: int, placement: str, technique: str, layer: dict, logo_url: str, style_ids: list[int]) -> int:
    body = {
        "format": "jpg",
        "products": [
            {
                "source": "catalog",
                "mockup_style_ids": style_ids,
                "catalog_product_id": int(product_id),
                "catalog_variant_ids": [int(variant_id)],
                "placements": [{"placement": placement, "technique": technique, "layers": [{"type": "file", "url": logo_url, "position": layer}]}],
            }
        ],
    }
    r = request("POST", "/v2/mockup-tasks", body)
    return int(r["data"][0]["id"])


def wait_task(task_id: int, *, sleep=time.sleep, timeout: int = POLL_TIMEOUT) -> dict:
    deadline = time.monotonic() + timeout
    while True:
        t = request("GET", f"/v2/mockup-tasks?id={int(task_id)}")["data"][0]
        if t.get("status") == "completed":
            return t
        if t.get("status") == "failed":
            raise PrintfulError("mockup task failed: " + json.dumps(t.get("failure_reasons"))[:400])
        if time.monotonic() >= deadline:
            raise PrintfulError("mockup task timed out")
        sleep(POLL_SECONDS)


def mockups_by_style(task: dict, placement: str) -> dict[int, str]:
    out: dict[int, str] = {}
    for vm in task.get("catalog_variant_mockups", []):
        for m in vm.get("mockups", []):
            sid = int(m["style_id"])
            if m.get("placement") == placement or sid not in out:
                out[sid] = m["mockup_url"]
    return out


_HOST = re.compile(r"(^|\.)(printful\.com|amazonaws\.com)$")


def download(url: str) -> bytes:
    u = urllib.parse.urlsplit(url)
    if u.scheme != "https" or not u.hostname or not _HOST.search(u.hostname) or u.username or u.password:
        raise PrintfulError("unexpected mockup URL host")
    with _OPENER.open(urllib.request.Request(url, headers={"User-Agent": "novam-stores-render/2"}), timeout=60) as r:
        data = r.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise PrintfulError("mockup image too large")
    return data

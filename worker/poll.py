"""Production worker loop for one GitHub Actions run.

    python worker/poll.py claim  <work_dir>    # asks every API in RENDER_API_BASES for queued jobs, writes <work_dir>/job-N.json
    python worker/poll.py render <work_dir>    # renders each claimed job, uploads the images, reports completion

Env: RENDER_API_BASES (comma list of store origins), RENDER_WORKER_SECRET (shared HMAC secret; a repo secret).
Nothing here holds brand data: the API hands out jobs with a lease token and the image URLs to fetch."""
import json
import os
import pathlib
import sys
import traceback
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from render_job import render_recipe  # noqa: E402
from signing import sign  # noqa: E402

SECRET = os.environ.get("RENDER_WORKER_SECRET", "")
BASES = [b.strip().rstrip("/") for b in os.environ.get("RENDER_API_BASES", "").split(",") if b.strip()]
WORKER = os.environ.get("GITHUB_RUN_ID", "local")
MAX_JOBS = int(os.environ.get("RENDER_MAX_JOBS", "1"))


def call(base: str, path: str, body: bytes, headers: dict | None = None) -> dict:
    headers = dict(headers or {})
    req = urllib.request.Request(base + path, data=body, method="POST")
    req.add_header("User-Agent", "novam-stores-render/1")
    req.add_header("X-Render-Signature", sign(SECRET, body))
    req.add_header("Content-Type", headers.pop("Content-Type", "application/json"))
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{path} -> HTTP {e.code} {e.read()[:200]!r}") from None


def claim(work: pathlib.Path) -> int:
    work.mkdir(parents=True, exist_ok=True)
    n = 0
    if not SECRET:
        print("RENDER_WORKER_SECRET not set; nothing to do")
        return 0
    for base in BASES:
        try:
            r = call(base, "/api/internal/render/claim", json.dumps({"max": MAX_JOBS - n, "worker": f"gha-{WORKER}"}).encode())
        except Exception as e:  # noqa: BLE001
            print(f"claim failed for {base}: {e}")
            continue
        for job in r.get("jobs", []):
            (work / f"job-{n}.json").write_text(json.dumps({"base": base, **job}))
            n += 1
        if n >= MAX_JOBS:
            break
    print(f"claimed {n} job(s)")
    return n


def render(work: pathlib.Path) -> None:
    for f in sorted(work.glob("job-*.json")):
        job = json.loads(f.read_text())
        base, jid, lease = job["base"], job["id"], job["leaseToken"]
        try:
            recipe = {k: v for k, v in job["recipe"].items() if k not in ("logoPath", "labelPath")}  # local paths are for samples only
            results = render_recipe(recipe, work / f.stem, base)
            for r in results:
                call(
                    base,
                    "/api/internal/render/upload",
                    r["webp"],
                    {"Content-Type": "image/webp", "X-Render-Job": jid, "X-Render-Lease": lease, "X-Render-Color": urllib.parse.quote(r["color"], safe=""), "X-Render-Shot": r["shot"], "X-Render-Seconds": str(r["seconds"])},
                )
            call(base, "/api/internal/render/complete", json.dumps({"jobId": jid, "lease": lease, "ok": True, "count": len(results)}).encode())
            print("done", jid, len(results), "images")
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            try:
                call(base, "/api/internal/render/complete", json.dumps({"jobId": jid, "lease": lease, "ok": False, "error": str(e)[:400]}).encode())
            except Exception as e2:  # noqa: BLE001
                print("could not report failure:", e2)


if __name__ == "__main__":
    cmd, w = sys.argv[1], pathlib.Path(sys.argv[2])
    if cmd == "claim":
        n = claim(w)
        out = os.environ.get("GITHUB_OUTPUT")
        if out:
            with open(out, "a") as fh:
                fh.write(f"count={n}\n")
    elif cmd == "render":
        render(w)

"""CDP reconnaissance — dump ALL XHR/fetch requests from all Chrome pages"""
import asyncio
import json
import aiohttp
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

CDP_HOST = "127.0.0.1"
CDP_PORT = 9222
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "cdp_dump"

# Only track content-types that are likely API responses
API_CONTENT_TYPES = {"application/json", "text/json", "application/vnd.api+json"}


def check_cdp_port() -> bool:
    try:
        urllib.request.urlopen(f"http://{CDP_HOST}:{CDP_PORT}/json", timeout=2)
        return True
    except Exception:
        return False


async def find_target(target_filter=None):
    """Find the best CDP target. Prefer dianxiaomi page, then any non-chrome page."""
    async with aiohttp.ClientSession() as session:
        async with session.get(f"http://{CDP_HOST}:{CDP_PORT}/json") as resp:
            targets = await resp.json()

    print(f"[*] {len(targets)} targets found:")
    for t in targets:
        print(f"    [{t.get('type'):16s}] {t.get('title', '')[:50]}")

    # Priority 1: dianxiaomi page
    for t in targets:
        if "dianxiaomi" in t.get("url", "").lower():
            print(f"\n[*] Using dianxiaomi page: {t.get('title')}")
            return t["webSocketDebuggerUrl"]

    # Priority 2: any non-chrome page
    for t in targets:
        url = t.get("url", "")
        if t.get("type") == "page" and not url.startswith("chrome://") and not url.startswith("devtools://"):
            print(f"\n[*] Using page: {t.get('title')}")
            return t["webSocketDebuggerUrl"]

    # Priority 3: any page
    for t in targets:
        if t.get("type") == "page":
            print(f"\n[*] Using fallback page: {t.get('title')}")
            return t["webSocketDebuggerUrl"]

    raise Exception("No debuggable page found")


async def listen():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    log_file = OUTPUT_DIR / "all_requests.jsonl"
    print(f"[*] Logging ALL requests to: {log_file}")

    ws_url = await find_target()

    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(ws_url) as ws:

            await ws.send_json({"id": 1, "method": "Network.enable"})
            resp = await ws.receive_json()
            print(f"[*] Network.enable: {resp.get('result', 'OK')}")

            print("\n" + "=" * 60)
            print("  DUMPING ALL NETWORK REQUESTS")
            print("  Go collect a product in dianxiaomi now!")
            print("=" * 60 + "\n")

            msg_id = 2
            pending = {}
            request_count = 0

            async for msg in ws:
                if msg.type != aiohttp.WSMsgType.TEXT:
                    continue

                data = json.loads(msg.data)
                method = data.get("method", "")

                if method == "Network.requestWillBeSent":
                    req = data.get("params", {}).get("request", {})
                    req_id = data["params"]["requestId"]
                    url = req.get("url", "")
                    rtype = data["params"].get("type", "")
                    http_method = req.get("method", "")

                    # Track XHR, Fetch, and unknown (could be extension)
                    if rtype in ("XHR", "Fetch", "") or "api" in url.lower() or "dianxiaomi" in url.lower():
                        pending[req_id] = {"url": url, "method": http_method, "type": rtype}
                        request_count += 1
                        print(f"[#{request_count}] {http_method} [{rtype}] {url[:200]}")

                        post_data = data["params"].get("request", {}).get("postData", "")
                        if post_data:
                            print(f"      POST data: {post_data[:500]}")

                elif method == "Network.responseReceived":
                    req_id = data["params"]["requestId"]
                    if req_id not in pending:
                        continue

                    info = pending[req_id]
                    resp_info = data["params"]["response"]
                    status = resp_info.get("status")
                    ct = resp_info.get("mimeType", "")

                    if not ct or any(t in ct.lower() for t in API_CONTENT_TYPES) or "dianxiaomi" in info["url"].lower():
                        try:
                            await ws.send_json({
                                "id": msg_id,
                                "method": "Network.getResponseBody",
                                "params": {"requestId": req_id},
                            })
                            body_resp = await ws.receive_json()
                            msg_id += 1

                            body = body_resp.get("result", {}).get("body", "")
                            print(f"      <- HTTP {status} | {len(body)} bytes | {ct}")

                            entry = {
                                "timestamp": datetime.now().isoformat(),
                                "url": info["url"],
                                "method": info["method"],
                                "type": info["type"],
                                "status": status,
                                "content_type": ct,
                            }
                            try:
                                entry["body"] = json.loads(body)
                            except Exception:
                                entry["body_raw"] = body[:5000]

                            with open(log_file, "a", encoding="utf-8") as f:
                                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

                        except Exception:
                            pass  # response body not available (redirects, etc.)

                    del pending[req_id]


def main():
    print("=" * 60)
    print("  CDP Recon - Full Request Dump")
    print("=" * 60)

    if not check_cdp_port():
        print("[!] Chrome CDP port not open on 127.0.0.1:9222")
        print("[!] Please run start_cdp_chrome.bat first")
        sys.exit(1)

    print(f"[*] Output dir: {OUTPUT_DIR}")
    asyncio.run(listen())


if __name__ == "__main__":
    main()

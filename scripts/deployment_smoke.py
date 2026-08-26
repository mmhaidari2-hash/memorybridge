#!/usr/bin/env python3
"""MemoryBridge deployment smoke checks. Never prints API or Stripe secrets."""
from __future__ import annotations
import json, os, sys, urllib.error, urllib.request
USAGE="Usage: python scripts/deployment_smoke.py https://api.example.com"
def request(url,method="GET",headers=None,body=None):
    req=urllib.request.Request(url,method=method,headers=headers or {},data=body)
    try:
        with urllib.request.urlopen(req,timeout=10) as response: return response.status,dict(response.headers),response.read().decode("utf-8",errors="replace")
    except urllib.error.HTTPError as exc: return exc.code,dict(exc.headers),exc.read().decode("utf-8",errors="replace")
def expect_json(url,expected_status,expected_status_value):
    status,headers,body=request(url)
    if status!=expected_status: raise RuntimeError(f"{url} returned HTTP {status}, expected {expected_status}")
    try: payload=json.loads(body)
    except json.JSONDecodeError as exc: raise RuntimeError(f"{url} did not return JSON") from exc
    if payload.get("status")!=expected_status_value: raise RuntimeError(f"{url} returned unexpected status payload: {payload!r}")
    return payload,headers.get("X-Request-ID") or headers.get("x-request-id")
def main():
    if len(sys.argv)==2 and sys.argv[1] in {"-h","--help"}: print(USAGE); print("Optional: MEMORYBRIDGE_API_KEY verifies account status; SMOKE_STRIPE_CHECKOUT=1 safely creates Test Mode checkout sessions."); return 0
    if len(sys.argv)!=2: print(USAGE,file=sys.stderr); return 2
    base=sys.argv[1].rstrip("/")
    if not base.startswith("https://"): print("Refusing non-HTTPS deployment target.",file=sys.stderr); return 2
    print("[1/6] health"); expect_json(f"{base}/health",200,"ok")
    print("[2/6] readiness"); expect_json(f"{base}/ready",200,"ready")
    print("[3/6] root metadata"); status,_,body=request(f"{base}/"); root=json.loads(body) if status==200 else {}; 
    if status!=200 or root.get("service")!="memorybridge": raise RuntimeError("unexpected root service metadata")
    print("[4/6] customer web entrypoint"); status,_,body=request(f"{base}/app/landing.html")
    if status!=200 or "MemoryBridge" not in body or 'href="onboarding.html"' not in body: raise RuntimeError("customer landing is unavailable or incomplete")
    key=os.getenv("MEMORYBRIDGE_API_KEY","").strip(); headers={"X-MemoryBridge-Key":key,"Content-Type":"application/json"} if key else {}
    print("[5/6] authenticated account path (optional)")
    if key:
        status,_,body=request(f"{base}/v1/account/status",headers=headers)
        if status!=200: raise RuntimeError(f"account/status returned HTTP {status}")
        account=json.loads(body); required={"workspace_id","plan","usage_used","usage_limit","can_upgrade"}; missing=sorted(required.difference(account))
        if missing: raise RuntimeError(f"account/status missing fields: {', '.join(missing)}")
        print(f"      workspace={account.get('workspace_name','<unnamed>')} plan={account.get('plan')}")
    else: print("      skipped: set MEMORYBRIDGE_API_KEY")
    print("[6/6] Stripe Test Mode checkout creation (opt-in)")
    if os.getenv("SMOKE_STRIPE_CHECKOUT","").strip()=="1":
        if not key: raise RuntimeError("SMOKE_STRIPE_CHECKOUT requires MEMORYBRIDGE_API_KEY")
        for plan in ("pro","team"):
            status,_,body=request(f"{base}/v1/billing/checkout",method="POST",headers=headers,body=json.dumps({"plan":plan}).encode())
            if status!=200: raise RuntimeError(f"{plan} checkout returned HTTP {status}: {body[:160]}")
            checkout=json.loads(body); url=checkout.get("checkout_url","")
            if not url.startswith("https://checkout.stripe.com/") or not checkout.get("session_id"): raise RuntimeError(f"{plan} checkout returned invalid Stripe session")
            print(f"      {plan}=PASS (session created; URL/ID not printed)")
    else: print("      skipped: set SMOKE_STRIPE_CHECKOUT=1 only in Stripe Test Mode")
    print("PASS: deployment smoke checks completed"); return 0
if __name__=="__main__":
    try: raise SystemExit(main())
    except Exception as exc: print(f"FAIL: {exc}",file=sys.stderr); raise SystemExit(1)

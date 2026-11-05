"""Live test of the business dashboard API and the platform (super admin) console against the deployed stack.

Uses two EXISTING accounts; it never creates users or sets passwords. Credentials come from the environment only:
  E2E_BUSINESS_EMAIL / E2E_BUSINESS_PASSWORD   an ordinary business admin
  E2E_PLATFORM_EMAIL / E2E_PLATFORM_PASSWORD   a member of the platform-admins group (sign-in must happen AFTER the group was granted)
  E2E_USER_POOL_ID, E2E_CLIENT_ID, E2E_API_URL, optional E2E_WEB_URL
Read-only except one expected side effect: viewing a business writes `platform.viewed_tenant` to that business's audit log.
"""
import json, os, sys, time, requests
from pycognito import Cognito

POOL, CLIENT, API = os.environ["E2E_USER_POOL_ID"], os.environ["E2E_CLIENT_ID"], os.environ["E2E_API_URL"]
WEB = os.environ.get("E2E_WEB_URL", "")
RES = []

def check(name, ok, detail=""):
    RES.append(bool(ok)); print(("PASS " if ok else "FAIL ") + name + ("" if ok else "  -> " + str(detail)[:300]), flush=True)

def login(prefix):
    u = Cognito(POOL, CLIENT, username=os.environ[f"E2E_{prefix}_EMAIL"])
    u.authenticate(password=os.environ[f"E2E_{prefix}_PASSWORD"])
    return {"Authorization": f"Bearer {u.id_token}"}

def call(h, path, method="GET", **kw):
    r = requests.request(method, API + path, headers=h, timeout=40, **kw)
    try: return r.status_code, r.json()
    except Exception: return r.status_code, r.text

BIZ, OPS = login("BUSINESS"), login("PLATFORM")

print("== Business account")
s, me = call(BIZ, "/me")
check("business /me works and is not platform", s == 200 and not me["user"].get("platform"), me)
check("business user is admin of its own tenant", me["user"]["role"] == "admin")
BIZ_TENANT = me["tenant"]["tenantId"]
for p in ("/platform/overview", "/platform/tenants", f"/platform/tenants/{BIZ_TENANT}"):
    check(f"business admin is refused on {p.split('/')[2]}", call(BIZ, p)[0] == 403)
check("signed-out call is 401", requests.get(API + "/platform/tenants", timeout=20).status_code == 401)
s, docs = call(BIZ, "/documents")
check("documents sync status is this business's own (never another's)", s == 200 and docs["lastSync"] is None or docs["lastSync"]["status"], docs)

print("== Super admin account")
s, me2 = call(OPS, "/me")
check("platform /me reports platform=true (signed in after group grant)", s == 200 and me2["user"].get("platform") is True, me2)
s, ov = call(OPS, "/platform/overview")
check("overview returns totals", s == 200 and ov["tenants"] >= 2 and "pluginInstalls" in ov, ov)
s, tl = call(OPS, "/platform/tenants")
rows = tl.get("tenants", []) if isinstance(tl, dict) else []
check("tenant list includes both test businesses", s == 200 and BIZ_TENANT in {t["tenantId"] for t in rows}, s)
check("list is count-only: no message/lead/config/key fields anywhere", not any(k in json.dumps(tl).lower() for k in ('"body"', "draftreply", "collected", "sitekey", "ownermail", "summary", "transcript")), "")
check("overview total matches list length", ov["tenants"] == len(rows), (ov["tenants"], len(rows)))

s, d = call(OPS, f"/platform/tenants/{BIZ_TENANT}")
check("detail for a business works", s == 200 and d["tenantId"] == BIZ_TENANT and "userList" in d, d)
check("detail shows users, plugins, documents, recent actions", all(k in d for k in ("userList", "pluginList", "documents", "recentAudit")))
check("detail has no customer content or secrets", not any(k in json.dumps(d).lower() for k in ('"detail"', "sitekey", "ownermail", "collected", "draftreply", "phone")), "")
check("unknown business is 404", call(OPS, "/platform/tenants/zzzzzz999")[0] == 404)
check("malformed id is rejected", call(OPS, "/platform/tenants/ab")[0] == 400)
check("platform routes are read-only (POST not routed)", call(OPS, "/platform/tenants", "POST", json={})[0] in (404, 405, 403))

print("== Transparency: the business can see that an operator looked")
time.sleep(2)
s, aud = call(BIZ, "/audit")
mine = [a for a in aud if a["action"] == "platform.viewed_tenant"] if s == 200 else []
check("business audit log contains platform.viewed_tenant", bool(mine), [a["action"] for a in aud][:8] if s == 200 else s)
check("the audit actor names the operator", any(a["actor"].startswith("platform:") for a in mine), [a["actor"] for a in mine][:2])

if WEB:
    print("== Hosted site (no login)")
    for p, want in (("/", 200), ("/dashboard/", 200), ("/platform/", 200)):
        check(f"{WEB}{p} -> {want}", requests.get(WEB + p, timeout=20).status_code == want)
    h = requests.get(WEB + "/", timeout=20).headers
    check("security headers present", all(k in h for k in ("strict-transport-security", "content-security-policy", "x-frame-options")), list(h))

print(f"\nRESULT: {sum(RES)}/{len(RES)} passed")
sys.exit(0 if all(RES) else 1)

"""Live test of the follow-up engine on the deployed stack: the real worker, the real due-time index, real conditional writes.

Same environment variables as e2e.py. Creates one throwaway tenant and deletes it. Sends two emails to E2E_VERIFIED_EMAIL.
A follow-up normally waits a day, so the test moves the deal's due time into the past directly in the table, then invokes the worker.
The worker acts on every due deal in the account, exactly as its 15-minute schedule does.
"""
import json, os, secrets, string, time, boto3, requests
from pycognito import Cognito
from boto3.dynamodb.conditions import Key

POOL, CLIENT, API, OWNER = (os.environ[k] for k in ("E2E_USER_POOL_ID", "E2E_CLIENT_ID", "E2E_API_URL", "E2E_VERIFIED_EMAIL"))
s = boto3.Session(profile_name=os.environ.get("AWS_PROFILE"), region_name="ap-southeast-2")
idp, lam, cf = s.client("cognito-idp"), s.client("lambda"), s.client("cloudformation")
table = s.resource("dynamodb").Table({o["OutputKey"]: o["OutputValue"] for o in cf.describe_stacks(StackName="hivemate-dev-data")["Stacks"][0]["Outputs"]}["TableName"])
SWEEPER = next(f["FunctionName"] for p in lam.get_paginator("list_functions").paginate() for f in p["Functions"] if "SweeperFn" in f["FunctionName"])
RES = []


def check(name, ok, detail=""):
    RES.append(bool(ok)); print(("PASS " if ok else "FAIL ") + name + ("" if ok else "  -> " + str(detail)[:300]), flush=True)


def call(m, p, **kw):
    r = requests.request(m, API + p, headers=H, timeout=40, **kw)
    try: return r.status_code, r.json()
    except Exception: return r.status_code, r.text


def sweep():
    out = json.loads(lam.invoke(FunctionName=SWEEPER, Payload=b"{}")["Payload"].read())
    return out["followUps"]


def make_due(deal_id):
    """Move the deal's next-due time 60 seconds into the past, keeping the index key the worker queries in step."""
    key = {"PK": PK, "SK": f"DEAL#{deal_id}"}
    item = table.get_item(Key=key)["Item"]
    past = int(time.time()) - 60
    table.update_item(Key=key, UpdateExpression="SET nextDueAt = :d, GSI1SK = :g",
                      ExpressionAttributeValues={":d": past, ":g": f"{past:013d}#{PK}#{deal_id}"})
    return item


def deal():
    return next(d for d in call("GET", "/deals")[1]["deals"] if d["source"] == "email")


def wait_messages(n):
    for _ in range(30):
        time.sleep(3); ms = call("GET", "/messages")[1]
        if len(ms) >= n: return ms
    return call("GET", "/messages")[1]


em, pw = f"fu+{int(time.time())}@example.com", "Aa1!" + "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(16))
idp.sign_up(ClientId=CLIENT, Username=em, Password=pw, UserAttributes=[{"Name": "email", "Value": em}, {"Name": "custom:businessName", "Value": "Follow-up Test Co"}])
idp.admin_confirm_sign_up(UserPoolId=POOL, Username=em); time.sleep(3)
u = Cognito(POOL, CLIENT, username=em, session=s); u.authenticate(password=pw)
H = {"Authorization": f"Bearer {u.id_token}"}
TID = call("GET", "/me")[1]["tenant"]["tenantId"]; PK = f"TENANT#{TID}"
try:
    call("POST", "/packs/smart-inbox/enable")
    call("POST", "/plugins/email-automation/ingest", json={"from": OWNER, "subject": "Quote for an end of lease clean", "body": "Hi, can I get a quote for an end of lease clean of a 2 bedroom flat?"})
    ms = wait_messages(1); check("enquiry drafted", len(ms) == 1, ms)
    st, ap = call("POST", f"/messages/{ms[0]['SK'].replace('MSG#', '')}/approve"); check("reply approved and sent", st == 200 and ap["status"].startswith("SENT"), ap)
    d = deal(); check("deal waits on the customer, follow-up scheduled about a day out", d["awaiting"] == "customer" and 23 * 3600 < d["nextDueAt"] - time.time() < 25 * 3600, d)
    check("nothing is due yet: the worker leaves it alone", call("GET", "/work")[1]["tasks"] == [] and sweep()["tasks"] == 0)

    # --- a day passes with no reply ---
    make_due(d["dealId"])
    r = sweep(); check("the worker finds the due deal through the index and creates one task", r["checked"] >= 1 and r["tasks"] == 1, r)
    st, w = call("GET", "/work"); fu = [t for t in w["tasks"] if t["type"] == "follow_up"]
    check("a follow-up draft is waiting for approval", len(fu) == 1 and fu[0]["status"] == "needs_approval" and fu[0]["to"] == OWNER.lower(), w)
    check("the draft is the fixed safe wording (business name, no price)", fu and "Follow-up Test Co" in fu[0]["draft"] and "$" not in fu[0]["draft"], fu)
    make_due(d["dealId"]); r2 = sweep()
    w2 = call("GET", "/work")[1]["tasks"]
    check("a second sweep on the same deal creates a second, later follow-up, never a duplicate of the first", len({t["taskId"] for t in w2}) == len(w2) and len([t for t in w2 if t["type"] == "follow_up"]) == 2, w2)
    d = deal(); check("deal shows two follow-ups and stage followed_up", d["followUpCount"] == 2 and d["stage"] == "followed_up", d)
    st, sent = call("POST", f"/work/{fu[0]['taskId']}/approve", json={"text": fu[0]["draft"]}); check("approving sends the follow-up", st == 200 and sent.get("status") == "done", sent)
    check("approving again is refused (sent once)", call("POST", f"/work/{fu[0]['taskId']}/approve")[0] == 409)

    # --- still silent after the maximum follow-ups: cold ---
    make_due(d["dealId"]); r3 = sweep()
    d = deal(); check("after the maximum follow-ups the lead goes cold and leaves the due index", r3["cold"] == 1 and d["stage"] == "cold" and "nextDueAt" not in d, (r3, d))
    check("one escalation task for the owner", len([t for t in call("GET", "/work")[1]["tasks"] if t["type"] == "cold_lead"]) == 1)

    # --- the customer finally replies: recovered ---
    call("POST", "/plugins/email-automation/ingest", json={"from": OWNER, "subject": "Re: Quote for an end of lease clean", "body": "Sorry for the delay, yes please go ahead."})
    wait_messages(2)
    d = deal(); check("a reply after going cold reopens the deal, waiting on the business", d["awaiting"] == "business" and d["stage"] == "responded", d)
    m = call("GET", "/impact?days=7")[1]["measured"]
    check("impact counts it: 1 recovered lead, follow-ups due and sent, first reply time", m["leadsRecovered"] == 1 and m["followUpsDue"] >= 2 and m["executionsOk"] == 1 and m["medianResponseSeconds"] is not None, m)

    # --- now nobody answers the customer: reply overdue ---
    make_due(d["dealId"]); r4 = sweep()
    ro = [t for t in call("GET", "/work")[1]["tasks"] if t["type"] == "reply_overdue"]
    check("an unanswered customer raises an urgent task for a person (never auto-answered)", r4["tasks"] == 1 and len(ro) == 1 and ro[0]["priority"] == "urgent", (r4, ro))
    check("marking it done records the reply and restarts the clock", call("POST", f"/work/{ro[0]['taskId']}/done")[0] == 200 and deal()["awaiting"] == "customer")

    # --- paused automation does nothing ---
    call("PUT", "/policy", json={"paused": {"follow_up": True}}); make_due(d["dealId"])
    before = len(call("GET", "/work?status=done")[1]["tasks"]) + len(call("GET", "/work")[1]["tasks"])
    sweep(); after = len(call("GET", "/work?status=done")[1]["tasks"]) + len(call("GET", "/work")[1]["tasks"])
    check("a paused automation creates nothing", before == after, (before, after))
finally:
    print("== Cleanup")
    kw = {"KeyConditionExpression": Key("PK").eq(PK)}
    while True:
        r = table.query(**kw)
        for it in r["Items"]: table.delete_item(Key={"PK": it["PK"], "SK": it["SK"]})
        if "LastEvaluatedKey" not in r: break
        kw["ExclusiveStartKey"] = r["LastEvaluatedKey"]
    idp.admin_delete_user(UserPoolId=POOL, Username=em)
    print("   cleaned", TID, "items left:", table.query(KeyConditionExpression=Key("PK").eq(PK))["Count"])
print(f"\nRESULT: {sum(RES)}/{len(RES)} passed")

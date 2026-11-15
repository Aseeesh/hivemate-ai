"""Live check of the Hivemate 2.0 routes (packs, policy, deals, inbox, impact, ask, customers, connections, isolation).

Same environment variables as e2e.py. Creates two throwaway tenants and deletes them. Sends one email to E2E_VERIFIED_EMAIL.
Does not cover live Microsoft 365 / Xero sign-in (needs registered apps) or the follow-up sweep firing (needs a day to pass)."""
import os, secrets, string, time, boto3, requests
from pycognito import Cognito
from boto3.dynamodb.conditions import Key
POOL, CLIENT, API, OWNER = (os.environ[k] for k in ("E2E_USER_POOL_ID", "E2E_CLIENT_ID", "E2E_API_URL", "E2E_VERIFIED_EMAIL"))
s = boto3.Session(profile_name=os.environ.get("AWS_PROFILE"), region_name="ap-southeast-2"); idp = s.client("cognito-idp")
RES = []
def check(name, ok, detail=""):
    RES.append(bool(ok)); print(("PASS " if ok else "FAIL ") + name + ("" if ok else "  -> " + str(detail)[:300]), flush=True)
def tenant(label):
    em = f"v2+{label}{int(time.time())}@example.com"; pw = "Aa1!" + "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(16))
    idp.sign_up(ClientId=CLIENT, Username=em, Password=pw, UserAttributes=[{"Name": "email", "Value": em}, {"Name": "custom:businessName", "Value": f"V2 Test {label}"}])
    idp.admin_confirm_sign_up(UserPoolId=POOL, Username=em); time.sleep(3)
    u = Cognito(POOL, CLIENT, username=em, session=s); u.authenticate(password=pw)
    return {"email": em, "H": {"Authorization": f"Bearer {u.id_token}"}}
def call(t, m, p, **kw):
    r = requests.request(m, API + p, headers=t["H"], timeout=40, **kw)
    try: return r.status_code, r.json()
    except Exception: return r.status_code, r.text
A, B = tenant("a"), tenant("b")
TA = call(A, "GET", "/me")[1]["tenant"]["tenantId"]; TB = call(B, "GET", "/me")[1]["tenant"]["tenantId"]
try:
    st, packs = call(A, "GET", "/packs"); check("packs list", st == 200 and len(packs) == 6, packs)
    check("enable Customer Support pack installs the assistant", call(A, "POST", "/packs/customer-support/enable")[0] == 200)
    check("enable Smart Inbox pack installs email automation", call(A, "POST", "/packs/smart-inbox/enable")[1].get("enabled") is True)
    st, pol = call(A, "GET", "/policy"); check("policy defaults to approve", st == 200 and pol["modes"]["follow_up"] == "approve", pol)
    check("refunds can never be automated (400)", call(A, "PUT", "/policy", json={"modes": {"refund": "automate"}})[0] == 400)
    check("policy saves cadence", call(A, "PUT", "/policy", json={"cadence": {"followUpAfterHours": 48}})[1]["cadence"]["followUpAfterHours"] == 48)
    # chat -> deal (regression of the agent hook on the live Lambda)
    st, r = call(A, "POST", "/chat", json={"message": "Hi, my name is Jordan Reid and I need a carpet clean. My phone is 021 555 0199."})
    check("chat still answers", st == 200 and r.get("reply"), r)
    time.sleep(1); st, d = call(A, "GET", "/deals")
    chat_deal = next((x for x in d.get("deals", []) if x["source"] == "chat"), None)
    check("chat with contact details became a deal awaiting the customer", bool(chat_deal) and chat_deal["awaiting"] == "customer", d)
    # email -> draft -> deal (regression of the email worker hook)
    st, ing = call(A, "POST", "/plugins/email-automation/ingest", json={"from": OWNER, "subject": "Quote for a 3 bed house", "body": "Hi, how much is a standard clean for a 3 bedroom house?"})
    check("email ingest accepted", st == 202, ing)
    msg = None
    for _ in range(25):
        time.sleep(3); ms = call(A, "GET", "/messages")[1]
        if ms: msg = ms[0]; break
    check("email worker drafted a reply", bool(msg), "no MSG after 75s")
    st, d = call(A, "GET", "/deals"); em_deal = next((x for x in d["deals"] if x["source"] == "email"), None)
    check("email became a deal awaiting the business", bool(em_deal) and em_deal["awaiting"] == "business" and em_deal["email"] == OWNER.lower(), d)
    st, ib = call(A, "GET", "/inbox"); kinds = {i["kind"] for i in ib["items"]}
    check("unified inbox shows chat and email together", kinds == {"conversation", "email"}, ib)
    check("inbox filter: unanswered", all(i["unanswered"] for i in call(A, "GET", "/inbox?status=unanswered")[1]["items"]))
    if msg and msg["status"] == "PENDING_APPROVAL":
        st, ap = call(A, "POST", f"/messages/{msg['SK'].replace('MSG#', '')}/approve")
        check("approving the draft sends it", st == 200 and ap["status"].startswith("SENT"), ap)
    time.sleep(1); d = call(A, "GET", "/deals")[1]; em_deal = next(x for x in d["deals"] if x["source"] == "email")
    check("after the reply the deal waits on the customer with a follow-up scheduled", em_deal["awaiting"] == "customer" and em_deal.get("nextDueAt", 0) > time.time(), em_deal)
    st, im = call(A, "GET", "/impact?days=7"); m = im["measured"]
    check("impact is measured from events", st == 200 and m["enquiries"] == 2 and m["medianResponseSeconds"] is not None and im["estimated"]["minutesSaved"] > 0, im)
    check("stage change to quote_sent", call(A, "POST", f"/deals/{em_deal['dealId']}/stage", json={"stage": "quote_sent"})[0] == 200)
    check("invalid stage rejected", call(A, "POST", f"/deals/{em_deal['dealId']}/stage", json={"stage": "cold"})[0] == 400)
    st, w = call(A, "GET", "/work"); check("work queue reachable and empty (nothing is due yet)", st == 200 and w["tasks"] == [], w)
    st, cu = call(A, "GET", "/customers"); check("customer 360 list has both customers", st == 200 and len(cu["customers"]) == 2, cu)
    key = next(c["key"] for c in cu["customers"] if c["email"])
    st, cd = call(A, "GET", "/customers/" + requests.utils.quote(key, safe="")); check("customer detail joins the email", st == 200 and len(cd["emails"]) == 1, cd)
    st, an = call(A, "POST", "/ask", json={"question": "How many enquiries did we get this week?"}); check("ask answers with calculation and sources", st == 200 and an["supported"] and an["answer"].startswith("2 ") and an["sources"], an)
    check("ask refuses to guess", call(A, "POST", "/ask", json={"question": "Will we be profitable next year?"})[1]["supported"] is False)
    st, cn = call(A, "GET", "/connections"); check("connections list both providers, not configured yet", st == 200 and {c["provider"] for c in cn} == {"microsoft365", "xero"} and not any(c["available"] for c in cn), cn)
    st, sa = call(A, "POST", "/connections/xero/start"); check("starting an unconfigured connection is a clear 409", st == 409 and "not set up" in sa["error"], sa)
    check("team list", call(A, "GET", "/team")[1]["members"] == [A["email"]])
    check("extract rejects another tenant's file", call(A, "POST", "/extract", json={"key": f"tenants/{TB}/extract/x.pdf"})[0] == 400)
    # isolation
    db_ = call(B, "GET", "/deals")[1]; check("tenant B sees none of A's deals", db_["deals"] == [], db_)
    check("tenant B cannot change A's deal", call(B, "POST", f"/deals/{em_deal['dealId']}/stage", json={"stage": "won"})[0] == 404)
    check("tenant B sees none of A's customers or inbox", call(B, "GET", "/customers")[1]["customers"] == [] and call(B, "GET", "/inbox")[1]["items"] == [])
    check("A's deal unchanged by B", next(x for x in call(A, "GET", "/deals")[1]["deals"] if x["dealId"] == em_deal["dealId"])["stage"] == "quote_sent")
finally:
    print("== Cleanup")
    cf = s.client("cloudformation"); outs = {o["OutputKey"]: o["OutputValue"] for o in cf.describe_stacks(StackName="hivemate-dev-data")["Stacks"][0]["Outputs"]}
    table = s.resource("dynamodb").Table(outs["TableName"])
    for t, tid in ((A, TA), (B, TB)):
        kw = {"KeyConditionExpression": Key("PK").eq(f"TENANT#{tid}")}
        while True:
            r = table.query(**kw)
            for it in r["Items"]: table.delete_item(Key={"PK": it["PK"], "SK": it["SK"]})
            if "LastEvaluatedKey" not in r: break
            kw["ExclusiveStartKey"] = r["LastEvaluatedKey"]
        idp.admin_delete_user(UserPoolId=POOL, Username=t["email"])
        left = table.query(KeyConditionExpression=Key("PK").eq(f"TENANT#{tid}"))["Count"]
        print("   cleaned", tid, "items left:", left)
print(f"\nRESULT: {sum(RES)}/{len(RES)} passed")

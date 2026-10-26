"""Write the invented fixture files. Deterministic: same seed, same files.

Every name, product and ticket here is made up for this demo.
"""
import json
import random
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
SEED = 20260101

PRODUCTS = [
    (1, "Tidewater Sync", "File sync between laptops and phones"),
    (2, "Marrow Billing", "Invoices, taxes and card payments"),
    (3, "Lantern Reports", "Dashboards and scheduled reports"),
    (4, "Cobalt Gateway", "API gateway with webhooks and keys"),
    (5, "Fennel Mobile", "Companion mobile app"),
]

# (product_id, feature, symptom 1, symptom 2, symptom 3)
FEATURES = [
    (1, "sign in", "I cannot sign in on my laptop after the update", "the login page says my session expired again and again", "sign in fails with an unknown error on the second device"),
    (1, "password reset", "the password reset email is not arriving", "I asked for a password reset three times and no message came", "the reset link in the email says it has expired"),
    (1, "sync stall", "sync stalls at 99 percent on a large folder", "the folder sync stalls at 99 percent and never finishes", "sync stalls at 99 percent after I rename a folder"),
    (1, "sync conflict", "two copies of the same file appear with conflict in the name", "a conflict copy was made when both laptops were offline", "my edits were replaced by an older version after a sync conflict"),
    (1, "selective sync", "selective sync still downloads folders I unchecked", "the unchecked folder keeps coming back on my disk", "I cannot choose which folders stay on my phone"),
    (1, "file restore", "I deleted a folder and need to restore it from history", "the restore button is greyed out for old versions", "restoring a file gives me an empty file"),
    (1, "shared link", "the shared link opens a blank page for my guest", "my guest sees access denied on the shared link", "the link expiry date cannot be changed"),
    (1, "storage quota", "the app says my storage is full but I used half", "the quota bar does not update after I delete files", "I was charged for extra storage I did not add"),
    (2, "invoice tax", "the invoice shows the wrong tax rate for my region", "wrong tax rate appears on every new invoice", "tax is added twice on invoices with a discount"),
    (2, "duplicate charge", "a customer was charged twice for one invoice", "I see a duplicate charge on the card statement", "the duplicate charge needs a refund but the button fails"),
    (2, "refund", "the refund shows pending for ten days", "a partial refund was sent for the full amount", "the refund email never reached the customer"),
    (2, "invoice export", "export csv gives an empty file for last month", "the invoice export csv is missing the tax column", "exporting invoices to csv times out on large accounts"),
    (2, "payment method", "the card was declined but the bank says it worked", "I cannot add a new payment method in the portal", "bank transfer details are missing from the invoice"),
    (2, "dunning email", "reminder emails go out after the invoice was paid", "the overdue reminder uses the wrong company name", "I want to turn off reminder emails for one customer"),
    (2, "currency", "the invoice total uses the wrong currency symbol", "exchange rates look a day old on foreign invoices", "I cannot switch an existing customer to euros"),
    (2, "credit note", "the credit note number skips a value", "a credit note cannot be linked to the original invoice", "the credit note pdf is blank"),
    (3, "dashboard speed", "the dashboard loads slowly on Monday mornings", "the main dashboard takes a minute to show charts", "dashboard loads slowly when I add a date filter"),
    (3, "scheduled report", "the scheduled report did not arrive this week", "the weekly report arrives twice with different numbers", "I cannot change the send time of a scheduled report"),
    (3, "chart filter", "the region filter does not change the chart", "filters reset when I open another tab", "the chart legend hides some series"),
    (3, "data source", "the data source connection keeps timing out", "new rows from the source do not show up in reports", "the data source password was rotated and reports broke"),
    (3, "report export", "export to pdf cuts off the right side of the table", "the exported report has no logo", "export csv from a report gives garbled characters"),
    (3, "user access", "a teammate can see reports they should not see", "I cannot give read only access to one dashboard", "the access list does not show new users"),
    (3, "alert rule", "the alert rule fires even when the value is normal", "I get no alert when the metric drops to zero", "alert emails arrive an hour late"),
    (3, "dark mode", "dark mode makes the chart text hard to read", "dark mode resets to light after each login", "the print view ignores dark mode"),
    (4, "webhook timeout", "the webhook returns a 504 timeout for every event", "our server sees the webhook returns a 504 after thirty seconds", "webhook returns a 504 only on large payloads"),
    (4, "rate limit", "we get rate limit errors 429 during the nightly job", "the 429 response has no retry after header", "the rate limit looks lower than our plan says"),
    (4, "api key", "a new api key is rejected as invalid", "I cannot rotate an api key without downtime", "the api key list does not show last used time"),
    (4, "webhook retry", "failed webhooks are not retried", "the same webhook is delivered five times", "I cannot replay a webhook from the dashboard"),
    (4, "request logs", "request logs are missing for the last hour", "the log search does not find a known request id", "log export stops at ten thousand rows"),
    (4, "cors", "the browser blocks calls with a cors error", "the cors setting does not accept my wildcard", "preflight requests fail for one route"),
    (4, "tls certificate", "our custom domain shows a certificate warning", "the certificate renewal failed and the site is down", "I cannot upload a certificate chain"),
    (4, "route config", "a route change did not take effect", "the route test says ok but live traffic fails", "I cannot import routes from a file"),
    (5, "push notification", "push notifications are missing on my phone", "push notifications arrive hours late", "I turned off push notifications but they still come"),
    (5, "offline mode", "offline mode loses my last edits", "the app shows offline even with good wifi", "offline files are not available after a restart"),
    (5, "biometric login", "face unlock stopped working after the update", "the fingerprint prompt appears and then closes", "I cannot turn on biometric login"),
    (5, "photo upload", "photo upload stops halfway on mobile data", "uploaded photos appear rotated", "the upload queue is stuck on one photo"),
    (5, "battery", "the app drains the battery in the background", "battery use is high during sync", "the phone gets warm while the app is open"),
    (5, "app crash", "the app crashes when I open settings", "the app closes right after the splash screen", "the app crashes on a tablet in landscape"),
    (5, "widget", "the home screen widget shows old data", "I cannot add the widget on my tablet", "the widget tap opens the wrong screen"),
    (5, "language", "some screens are still in English", "the date format ignores my phone region", "I cannot change the app language without a restart"),
]

CUSTOMERS = [
    "Brightloom Cafe", "Quillstone Labs", "Harborview Dental", "Mossgate Studio", "Ember and Oak",
    "Palmer Row Books", "Sunbridge Logistics", "Tallpine Outfitters", "Velvet Anchor Press", "Copperfield Bikes",
    "Driftwood Analytics", "Oakline Clinic", "Marlow Street Bakery", "Northfold Farms", "Pebble and Plum",
    "Redwren Design", "Silverbank Tutors", "Thistle Hill Hotel", "Umber Works", "Violet Hour Spa",
    "Willow Lane Pharmacy", "Yarrow Tech Repair", "Zephyr Print Shop", "Amberfield Realty", "Blue Heron Tours",
]

OPENERS = ["Hi team,", "Hello,", "Good morning,", "Hi,", "Quick question,", "We need help,"]
ASKS = [
    "Can you look into this today?",
    "Please tell us what to try next.",
    "This is blocking our team.",
    "It started this week.",
    "It happens for everyone in our office.",
    "We have not changed any settings.",
    "A fix would help a lot.",
]
PRIORITIES = ["low", "medium", "high"]
STATUSES = ["open", "pending", "closed"]


def articles():
    rows = []
    for i, (pid, feature, s1, s2, s3) in enumerate(FEATURES, start=1):
        pname = next(p[1] for p in PRODUCTS if p[0] == pid)
        rows.append({
            "id": i,
            "product_id": pid,
            "title": f"How to fix {feature} problems in {pname}",
            "body": (
                f"This article covers {feature} in {pname}. "
                f"Customers often write that {s1}. "
                f"Check the account status first, then follow the steps in the settings page for {feature}."
            ),
            "revision": 1,
        })
    return rows


def tickets(rng, start_id, count):
    rows = []
    for n in range(count):
        a_index = rng.randrange(len(FEATURES))
        pid, feature, *symptoms = FEATURES[a_index]
        symptom = rng.choice(symptoms)
        extra = rng.choice(symptoms)
        rows.append({
            "id": start_id + n,
            "customer_id": rng.randrange(1, len(CUSTOMERS) + 1),
            "article_id": a_index + 1,
            "product_id": pid,
            "subject": f"{feature.capitalize()}: {symptom}"[:90],
            "body": f"{rng.choice(OPENERS)} {symptom}. Also, {extra}. {rng.choice(ASKS)}",
            "priority": rng.choice(PRIORITIES),
            "status": rng.choice(STATUSES),
        })
    return rows


def write_jsonl(path, rows):
    path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), encoding="utf-8")


def main():
    FIXTURES.mkdir(exist_ok=True)
    rng = random.Random(SEED)
    (FIXTURES / "products.json").write_text(json.dumps(
        [{"id": i, "name": n, "summary": s} for i, n, s in PRODUCTS], indent=1) + "\n")
    (FIXTURES / "customers.json").write_text(json.dumps(
        [{"id": i, "name": n,
          "product_id": 1 + (i - 1) % len(PRODUCTS)} for i, n in enumerate(CUSTOMERS, start=1)], indent=1) + "\n")
    write_jsonl(FIXTURES / "articles.jsonl", articles())
    write_jsonl(FIXTURES / "tickets.jsonl", tickets(rng, 1, 500))
    # Extra tickets: ids 1001-1010 for step 4, ids 2001-2030 for step 5.
    write_jsonl(FIXTURES / "tickets_late.jsonl", tickets(rng, 1001, 10))
    write_jsonl(FIXTURES / "tickets_crash.jsonl", tickets(rng, 2001, 30))
    print("fixtures written")


if __name__ == "__main__":
    main()

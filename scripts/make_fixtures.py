"""Write the invented fixture files. Deterministic: same seed, same files.

Every name, product and ticket here is made up for this demo.

Two groups of files come out of this script:

1. The original demo fixtures (products, customers, articles, three ticket files). They use one
   random generator, seeded with SEED, in a fixed call order. Do not reorder those calls: the
   recorded outputs in demo-state/ depend on these exact files.
2. The retrieval-evaluation fixtures (incident_graph.json, eval_questions.json, eval_qrels.json,
   incoming_tickets.json). They use their own generators (SEED_INCIDENT_GRAPH) and never touch the
   first group. How relevance labels are made is described next to EVAL_QUESTIONS below.
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


# ---------------------------------------------------------------------------------------------
# Retrieval evaluation fixtures
#
# Where the labels come from (this is the whole labelling rule, nothing else is used):
#
# * Every core ticket (tickets.jsonl) was generated from one feature, and records it as article_id.
#   That field exists independently of any search and is never passed to a retrieval strategy.
# * An INCIDENT below is an invented root cause that explains symptoms in several features, often
#   in several products (for example one identity-service outage that shows up as sign-in
#   failures, rejected API keys and broken biometric login). Incidents are defined here, once,
#   before any search runs. A feature belongs to at most one incident.
# * Each evaluation question has an intent chosen by whoever wrote the question:
#     "feature":  the person wants tickets about the same problem. Relevant tickets are the
#                 tickets whose article_id is that feature. Relevant article: that feature's article.
#     "incident": the person wants every ticket caused by the same outage. Relevant tickets are the
#                 tickets of ALL features of the incident. Relevant articles: those features' articles.
# * eval_qrels.json is computed from those rules by qrels() below. Nobody edits it by hand.
#
# The question texts were written by hand by the author of this script and were not compared with
# search results. The labels were NOT reviewed by a second person or by a domain expert. They are
# labels by construction on invented data, not human relevance judgements.
#
# The graph the retrieval can use (see INCIDENT_LINKS rule below) records "a triage engineer linked
# ticket a to ticket b because they come from the same outage". Because the incident definition is
# also the source of the "incident" labels, a perfect link set would let a graph recover those
# labels. The links are therefore deliberately partial and partly wrong (rule below), and the
# evaluation reports how much of that a ranker actually gets from them.
# ---------------------------------------------------------------------------------------------
SEED_INCIDENT_GRAPH = 20260202

# (id, name, root cause, feature names)
INCIDENTS = [
    (1, "Identity service outage", "The shared sign-in token service rejected valid tokens",
     ["sign in", "api key", "biometric login"]),
    (2, "Email provider degradation", "The outbound email provider delayed or dropped messages",
     ["password reset", "dunning email", "alert rule"]),
    (3, "Storage backend migration", "Uploads and quota accounting were disturbed by a storage backend migration",
     ["sync stall", "storage quota", "photo upload"]),
    (4, "Rates and tax feed outage", "The tax and exchange rate feed returned stale or partial data",
     ["invoice tax", "currency", "invoice export"]),
]
TRIAGED_SHARE = 0.5        # share of an incident's tickets that a triage engineer looked at
LINKS_PER_TRIAGED = 2      # same-incident links a triaged ticket gets, to tickets of a different feature
MISFILED_SHARE = 0.1       # share of triaged tickets that also get one wrong link to a non-incident ticket

# (id, text, intent, feature name for "feature" intent or incident id for "incident" intent)
EVAL_QUESTIONS = [
    ("f01", "reset password link never reaches my inbox", "feature", "password reset"),
    ("f02", "folder upload frozen near the end", "feature", "sync stall"),
    ("f03", "tax amount on invoices is incorrect", "feature", "invoice tax"),
    ("f04", "customer billed two times for the same invoice", "feature", "duplicate charge"),
    ("f05", "refund is stuck and has not arrived", "feature", "refund"),
    ("f06", "csv download of invoices comes out blank", "feature", "invoice export"),
    ("f07", "dashboard is very slow to open", "feature", "dashboard speed"),
    ("f08", "weekly report email did not come", "feature", "scheduled report"),
    ("f09", "callbacks to our endpoint time out with a 504", "feature", "webhook timeout"),
    ("f10", "too many requests error during batch jobs", "feature", "rate limit"),
    ("f11", "api credential rejected as invalid", "feature", "api key"),
    ("f12", "events are not redelivered after a failure", "feature", "webhook retry"),
    ("f13", "certificate expired on our custom domain", "feature", "tls certificate"),
    ("f14", "push alerts do not show up on my phone", "feature", "push notification"),
    ("f15", "app forgets my changes when there is no connection", "feature", "offline mode"),
    ("f16", "face recognition login stopped working", "feature", "biometric login"),
    ("f17", "battery drains fast because of the app", "feature", "battery"),
    ("f18", "app closes immediately when opening settings", "feature", "app crash"),
    ("f19", "two versions of a file created after being offline", "feature", "sync conflict"),
    ("f20", "currency symbol on invoice is wrong", "feature", "currency"),
    ("f21", "cannot log in on a second computer", "feature", "sign in"),
    ("f22", "reminder emails sent after payment", "feature", "dunning email"),
    ("f23", "storage full warning but plenty of space left", "feature", "storage quota"),
    ("f24", "photos stop uploading on cellular", "feature", "photo upload"),
    ("i01", "users cannot authenticate since this morning", "incident", 1),
    ("i02", "login keeps failing and sessions expire", "incident", 1),
    ("i03", "credentials rejected across our apps", "incident", 1),
    ("i04", "transactional emails are not being delivered", "incident", 2),
    ("i05", "email sent late or never arrives", "incident", 2),
    ("i06", "notification emails delayed by an hour", "incident", 2),
    ("i07", "uploads and syncing hang at the end", "incident", 3),
    ("i08", "storage usage numbers look wrong and transfers stall", "incident", 3),
    ("i09", "files stop uploading halfway", "incident", 3),
    ("i10", "invoices show wrong amounts", "incident", 4),
    ("i11", "incorrect tax and currency values on invoices", "incident", 4),
    ("i12", "invoice numbers and columns are off", "incident", 4),
]

# Workflow demo: new tickets that arrive while the support workflow runs. Invented. Ids 3001 and up.
# customer_id is known from the account. Nothing else about the ticket is known when it arrives:
# the product is taken from the customer's account and the article is chosen later by triage.
INCOMING_TICKETS = [
    {"id": 3001, "customer_id": 6, "subject": "Login fails on all our devices",
     "body": "Hello, since this morning nobody in our office can log in and the session expires right away. "
             "We have not changed any settings.", "priority": "medium", "status": "open"},
    {"id": 3002, "customer_id": 12, "subject": "Report layout question",
     "body": "Hi, the scheduled report arrives with a different column order than last month. "
             "Can you tell us how to fix the order?", "priority": "low", "status": "open"},
]


def feature_article_ids():
    return {feature: i for i, (_, feature, *_rest) in enumerate(FEATURES, start=1)}


def incident_features():
    """Incident id -> list of article ids, resolved from feature names."""
    by_name = feature_article_ids()
    return {iid: [by_name[f] for f in names] for iid, _name, _cause, names in INCIDENTS}


def qrels(ticket_rows):
    """Question id -> relevant ticket ids and article ids, from the rules above."""
    by_name = feature_article_ids()
    inc_features = incident_features()
    out = {}
    for qid, _text, intent, target in EVAL_QUESTIONS:
        articles = [by_name[target]] if intent == "feature" else sorted(inc_features[target])
        tickets = sorted(t["id"] for t in ticket_rows if t["article_id"] in articles)
        out[qid] = {"intent": intent, "target": target, "tickets": tickets, "articles": articles}
    return out


def incident_graph(ticket_rows):
    """The recorded incident links: which tickets a triage engineer attached to an incident, and the
    ticket-to-ticket links they drew. Deterministic for SEED_INCIDENT_GRAPH."""
    rng = random.Random(SEED_INCIDENT_GRAPH)
    inc_features = incident_features()
    all_features = set(range(1, len(FEATURES) + 1))
    by_feature = {}
    for t in ticket_rows:
        by_feature.setdefault(t["article_id"], []).append(t["id"])
    members, links = [], []
    seen = set()
    for iid, _name, _cause, _features in INCIDENTS:
        feats = inc_features[iid]
        outside = sorted(i for f in all_features - set(feats) for i in by_feature.get(f, []))
        incident_tickets = sorted((f, i) for f in feats for i in by_feature.get(f, []))
        for feature, ticket in incident_tickets:
            if rng.random() >= TRIAGED_SHARE:
                continue
            members.append({"ticket": ticket, "incident": iid})
            other_feature_tickets = [i for f, i in incident_tickets if f != feature]
            for other in rng.sample(other_feature_tickets, min(LINKS_PER_TRIAGED, len(other_feature_tickets))):
                key = frozenset((ticket, other))
                if key not in seen:
                    seen.add(key)
                    links.append({"a": ticket, "b": other, "incident": iid, "kind": "same_incident"})
            if rng.random() < MISFILED_SHARE:
                other = rng.choice(outside)
                key = frozenset((ticket, other))
                if key not in seen:
                    seen.add(key)
                    links.append({"a": ticket, "b": other, "incident": iid, "kind": "misfiled"})
    return {
        "rule": ("Triaged tickets are a seeded random half of each incident's tickets. A triaged ticket is linked "
                 "to 2 tickets of a different feature of the same incident. One in ten triaged tickets also gets "
                 "one wrong link to a ticket outside the incident (kind misfiled). Seed " + str(SEED_INCIDENT_GRAPH) + "."),
        "incidents": [{"id": i, "name": n, "root_cause": c, "features": inc_features[i]} for i, n, c, _ in INCIDENTS],
        "members": members,
        "links": links,
    }


def write_eval_fixtures(ticket_rows):
    (FIXTURES / "eval_questions.json").write_text(json.dumps({
        "note": ("Question texts were written by hand before any search ran and were not changed after seeing "
                 "results. Labels are in eval_qrels.json and come from scripts/make_fixtures.py, not from a person."),
        "questions": [{"id": q, "text": text, "intent": intent} for q, text, intent, _ in EVAL_QUESTIONS],
    }, indent=1) + "\n")
    (FIXTURES / "eval_qrels.json").write_text(json.dumps(qrels(ticket_rows), indent=1, sort_keys=True) + "\n")
    (FIXTURES / "incident_graph.json").write_text(json.dumps(incident_graph(ticket_rows), indent=1) + "\n")
    (FIXTURES / "incoming_tickets.json").write_text(json.dumps(INCOMING_TICKETS, indent=1) + "\n")


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
    core = tickets(rng, 1, 500)
    write_jsonl(FIXTURES / "tickets.jsonl", core)
    # Extra tickets: ids 1001-1010 for step 4, ids 2001-2030 for step 5.
    write_jsonl(FIXTURES / "tickets_late.jsonl", tickets(rng, 1001, 10))
    write_jsonl(FIXTURES / "tickets_crash.jsonl", tickets(rng, 2001, 30))
    write_eval_fixtures(core)
    print("fixtures written")


if __name__ == "__main__":
    main()

"""The store schema: Customer, Ticket, Article, Product and the links between them."""
from okto_grafx import connect

DIMENSION = 384

DDL = [
    f"CREATE VECTOR SPACE minilm {{dimension: {DIMENSION}, metric: 'cosine'}}",
    "CREATE NODE TABLE Product(id INT64, name STRING, summary STRING, PRIMARY KEY(id))",
    "CREATE NODE TABLE Customer(id INT64, name STRING, PRIMARY KEY(id))",
    "CREATE NODE TABLE Article(id INT64, title STRING, body STRING, revision INT64, PRIMARY KEY(id))",
    "CREATE NODE TABLE Ticket(id INT64, subject STRING, body STRING, priority STRING, status STRING, "
    "embedding VECTOR(minilm), PRIMARY KEY(id))",
    "CREATE REL TABLE Opened(FROM Customer TO Ticket)",
    "CREATE REL TABLE Mentions(FROM Ticket TO Article)",
    "CREATE REL TABLE About(FROM Ticket TO Product)",
    "CREATE REL TABLE Covers(FROM Article TO Product)",
    "CREATE REL TABLE Uses(FROM Customer TO Product)",
    "CREATE REL TABLE Related(FROM Ticket TO Ticket)",
]

NODE_TABLES = ("Product", "Customer", "Article", "Ticket")
REL_TABLES = ("Opened", "Mentions", "About", "Covers", "Uses", "Related")
HISTORY_TABLES = NODE_TABLES + REL_TABLES


def create_store(path):
    """Create the store, turn on identity indexes, commit history and system history."""
    with connect(path) as db:
        with db.begin("write") as txn:
            for statement in DDL:
                txn.execute(statement)
        assert txn.report is not None and txn.report.durable
        db.ensure_identity_indexes()
        db.enable_commit_history()
        db.enable_system_history(HISTORY_TABLES)
        return db.verify("all")

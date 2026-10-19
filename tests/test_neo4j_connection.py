"""Verify connectivity to the local ExoTrace Neo4j database."""

from getpass import getpass

from neo4j import GraphDatabase
from neo4j.exceptions import Neo4jError

NEO4J_URI = "neo4j://127.0.0.1:7687"
NEO4J_USERNAME = "neo4j"
NEO4J_DATABASE = "exotrace"


def main() -> None:
    """Connect to Neo4j and verify the selected database."""
    password = getpass("Enter your Neo4j password: ")

    try:
        with GraphDatabase.driver(
            NEO4J_URI,
            auth=(NEO4J_USERNAME, password),
        ) as driver:
            driver.verify_connectivity()

            with driver.session(database=NEO4J_DATABASE) as session:
                record = session.run(
                    "RETURN 1 AS ok"
                ).single()

                if record is None or record["ok"] != 1:
                    raise RuntimeError(
                        "Neo4j returned an unexpected health-check result."
                    )

                print("Neo4j connection successful.")
                print(f"Database: {NEO4J_DATABASE}")
                print(f"Health check: {record['ok']}")

    except Neo4jError as exc:
        print(f"Neo4j connection failed: {exc}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
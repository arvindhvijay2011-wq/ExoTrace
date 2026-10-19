import json
from pathlib import Path

corpus_path = Path("data/processed/vector_corpus.jsonl")
targets = ("pl_orbeccen", "eccentricity")
matches = 0

print("=== Source-derived documents in the corpus ===")

with corpus_path.open("r", encoding="utf-8") as corpus:
    for line_number, line in enumerate(corpus, start=1):
        document = json.loads(line)
        serialized = json.dumps(document, ensure_ascii=False).casefold()

        if "pl_orbeccen" not in serialized:
            continue

        matches += 1
        print(f"\nCorpus line: {line_number}")
        print(json.dumps(document, indent=2, ensure_ascii=False))

        if matches >= 3:
            break

print(f"\nMatching documents displayed: {matches}")

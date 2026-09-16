# -*- coding: utf-8 -*-
from pathlib import Path
import json, csv, collections

root = Path(__file__).resolve().parent

def load_jsonl(p):
    with open(p, "r", encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]

queries = load_jsonl(root / "queries.jsonl")
corpus = load_jsonl(root / "corpus.jsonl")
doc_ids = {d["id"] for d in corpus}

with open(root / "qrels.tsv", "r", encoding="utf-8") as f:
    qrels = list(csv.DictReader(f, delimiter="\t"))

assert len(queries) == 50
assert len(corpus) == 500
assert len({q["id"] for q in queries}) == 50
assert len(doc_ids) == 500
assert len(qrels) == 50
assert all(q["gold_doc_id"] in doc_ids for q in queries)

kind_counts = collections.Counter(d["kind"] for d in corpus)
type_counts = collections.Counter(q["query_type"] for q in queries)

print("Dataset OK")
print("Queries:", len(queries))
print("Corpus :", len(corpus))
print("Kinds  :", dict(kind_counts))
print("Types  :", dict(type_counts))

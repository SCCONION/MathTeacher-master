# -*- coding: utf-8 -*-
"""
基于 MathTutor 项目真实 RAG 实现的中文检索评测
================================================

重要：
1. 本脚本不是另写一套 BGE / FAISS / BM25。
2. 它直接导入项目 src/backend/agents/nodes/tools/tools.py 中的：
      _embed_texts
      _tokenize
      _STORES
      rag_tool
   并导入项目当前配置：
      EMBED_DIM
      EMBED_INPUT_TYPE_DOC / QUERY
      TOP_K
      MIN_SCORE
3. “Project Hybrid RRF + CRAG” 指标直接调用项目生产 rag_tool.invoke() 得到，
   因而会走你当前项目里的：
      BGE dense Top-10
      + BM25 sparse Top-10
      + RRF(K=60)
      + TOP_K
      + MIN_SCORE 余弦过滤

数据集：
    data/eval/math_rag_eval_zh_500/
        queries.jsonl
        corpus.jsonl
        qrels.tsv

从项目根目录运行：
    python scripts/eval_rag_project.py

输出：
    data/eval/math_rag_eval_zh_500/results_project.json
    data/eval/math_rag_eval_zh_500/results_project.csv
    data/eval/math_rag_eval_zh_500/failures_project.jsonl
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

import faiss
import numpy as np
from rank_bm25 import BM25Okapi


# ─────────────────────────────────────────────────────────────────────────────
# 让脚本能从 MathTutor 项目根目录直接运行
# ─────────────────────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


# ─────────────────────────────────────────────────────────────────────────────
# 直接复用项目真实 RAG 代码与参数
# ─────────────────────────────────────────────────────────────────────────────

from backend.agents.nodes.tools import (  # noqa: E402
    EMBED_DIM,
    EMBED_INPUT_TYPE_DOC,
    EMBED_INPUT_TYPE_QUERY,
    MIN_SCORE,
    TOP_K,
)

from backend.agents.nodes.tools.tools import (  # noqa: E402
    _STORES,
    _embed_texts,
    _tokenize,
    clear_store,
    rag_tool,
)


RRF_K = 60  # 与 tools.py / rag_tool 当前实现一致
DENSE_CANDIDATES = 10
SPARSE_CANDIDATES = 10


# ─────────────────────────────────────────────────────────────────────────────
# 数据读取
# ─────────────────────────────────────────────────────────────────────────────

def load_jsonl(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def load_qrels(path: Path) -> Dict[str, str]:
    """本评测集每个 Query 恰好一个 gold document。"""
    gold: Dict[str, str] = {}
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            if int(row["relevance"]) > 0:
                gold[row["query_id"]] = row["document_id"]
    return gold


# ─────────────────────────────────────────────────────────────────────────────
# 用“已经切好的评测 chunk”构建和 ingest_pdf 后相同结构的项目 _STORES
# ─────────────────────────────────────────────────────────────────────────────

def build_project_store(
    corpus: list[dict],
    thread_id: str,
) -> Tuple[dict, float]:
    """
    构造与 tools.py::ingest_pdf() 最终写入 _STORES 相同的数据结构。

    区别只有一个：
      生产环境：PDF -> RecursiveCharacterTextSplitter -> chunks
      评测环境：corpus.jsonl 每条本身就是一个 chunk

    后面的 BGE / FAISS / BM25 / RRF / CRAG 全部仍由项目当前实现/参数决定。
    """
    clear_store(thread_id)

    texts = [d["text"] for d in corpus]
    doc_ids = [d["id"] for d in corpus]

    t0 = time.perf_counter()

    # 与项目 ingest_pdf 一致：项目自己的 tokenizer
    tokenized_chunks = [_tokenize(t) for t in texts]
    bm25 = BM25Okapi(tokenized_chunks)

    # 与项目 ingest_pdf 一致：项目自己的 BGE embedding helper
    doc_vecs = np.asarray(
        _embed_texts(texts, EMBED_INPUT_TYPE_DOC),
        dtype=np.float32,
    )

    if doc_vecs.ndim != 2 or doc_vecs.shape[1] != EMBED_DIM:
        raise RuntimeError(
            f"Embedding 维度异常：得到 {doc_vecs.shape}，"
            f"项目配置 EMBED_DIM={EMBED_DIM}"
        )

    # 与项目一致：IndexFlatIP
    index = faiss.IndexFlatIP(EMBED_DIM)
    index.add(doc_vecs)

    # rag_tool 会把 metadata.page 打印出来。
    # 这里故意把 page 设置成 doc_id，便于从 rag_tool 的真实输出恢复排名。
    metadata = [
        {
            "page": did,
            "doc_id": did,
            "eval_topic": corpus[i].get("topic"),
            "eval_kind": corpus[i].get("kind"),
        }
        for i, did in enumerate(doc_ids)
    ]

    _STORES[thread_id] = {
        "index": index,
        "chunks": texts,
        "metadata": metadata,
        "filenames": ["math_rag_eval_zh_500"],
        "bm25": bm25,
        "tokenized_chunks": tokenized_chunks,
        "doc_vecs": doc_vecs,
    }

    elapsed = time.perf_counter() - t0
    return _STORES[thread_id], elapsed


# ─────────────────────────────────────────────────────────────────────────────
# 三个 baseline：完全使用项目当前 embedding / tokenizer / FAISS / BM25
# ─────────────────────────────────────────────────────────────────────────────

def dense_only(store: dict, query: str) -> List[int]:
    q_vec = np.asarray(
        _embed_texts([query], EMBED_INPUT_TYPE_QUERY),
        dtype=np.float32,
    )
    _, indices = store["index"].search(q_vec, TOP_K)
    return [int(i) for i in indices[0] if int(i) >= 0]


def bm25_only(store: dict, query: str) -> List[int]:
    """
    注意：这里和生产 rag_tool 一样，不人为过滤 BM25 score == 0 的候选。
    """
    scores = store["bm25"].get_scores(_tokenize(query))
    indices = np.argsort(scores)[::-1][:TOP_K]
    return [int(i) for i in indices]


def hybrid_rrf_without_crag(store: dict, query: str) -> List[int]:
    """
    与项目 rag_tool 的 Dense + Sparse + RRF 完全同参数，
    只是停在 CRAG 相似度过滤之前，用于做消融 baseline。
    """
    q_vec = np.asarray(
        _embed_texts([query], EMBED_INPUT_TYPE_QUERY),
        dtype=np.float32,
    )

    _, dense_indices = store["index"].search(q_vec, DENSE_CANDIDATES)
    dense_idx = dense_indices[0]

    sparse_scores = store["bm25"].get_scores(_tokenize(query))
    sparse_idx = np.argsort(sparse_scores)[::-1][:SPARSE_CANDIDATES]

    rrf: Dict[int, float] = {}

    for rank, idx in enumerate(dense_idx):
        idx = int(idx)
        if 0 <= idx < len(store["chunks"]):
            rrf[idx] = rrf.get(idx, 0.0) + 1.0 / (RRF_K + rank + 1)

    for rank, idx in enumerate(sparse_idx):
        idx = int(idx)
        if 0 <= idx < len(store["chunks"]):
            rrf[idx] = rrf.get(idx, 0.0) + 1.0 / (RRF_K + rank + 1)

    return sorted(rrf, key=rrf.get, reverse=True)[:TOP_K]


# ─────────────────────────────────────────────────────────────────────────────
# 生产路径：直接调用你项目自己的 rag_tool
# ─────────────────────────────────────────────────────────────────────────────

_PAGE_DOC_ID_RE = re.compile(r"\[Page\s+(d\d+)\s+\|\s+relevance=")


def project_rag_tool_ranked_doc_ids(query: str, thread_id: str) -> List[str]:
    """
    真正调用 backend.agents.nodes.tools.tools.rag_tool。

    评测 store 的 metadata.page 被设置成 d001 / d002 ...，
    所以可以从项目 rag_tool 的输出中按原顺序解析出 doc_id。
    """
    output = rag_tool.invoke(
        {
            "query": query,
            "thread_id": thread_id,
        }
    )
    return _PAGE_DOC_ID_RE.findall(output)


# ─────────────────────────────────────────────────────────────────────────────
# 指标
# ─────────────────────────────────────────────────────────────────────────────

def score_one(ranked_doc_ids: List[str], gold_doc_id: str) -> dict:
    rank = None
    for i, did in enumerate(ranked_doc_ids[:TOP_K], start=1):
        if did == gold_doc_id:
            rank = i
            break

    return {
        "recall_at_1": 1.0 if rank == 1 else 0.0,
        "recall_at_5": 1.0 if rank is not None and rank <= 5 else 0.0,
        "mrr_at_5": 0.0 if rank is None else 1.0 / rank,
        "gold_rank": rank,
    }


def mean(values: list[float]) -> float:
    return float(sum(values) / len(values)) if values else 0.0


def aggregate(rows: list[dict]) -> dict:
    return {
        "queries": len(rows),
        "Recall@1": mean([r["recall_at_1"] for r in rows]),
        "Recall@5": mean([r["recall_at_5"] for r in rows]),
        "MRR@5": mean([r["mrr_at_5"] for r in rows]),
        "avg_latency_ms": mean([r["latency_ms"] for r in rows]),
        "avg_returned": mean([float(r["returned_count"]) for r in rows]),
    }


def evaluate_method(
    method_name: str,
    queries: list[dict],
    gold_map: Dict[str, str],
    run_query,
) -> Tuple[dict, list[dict]]:
    rows = []

    for i, q in enumerate(queries, start=1):
        t0 = time.perf_counter()
        ranked_doc_ids = run_query(q["query"])
        latency_ms = (time.perf_counter() - t0) * 1000

        s = score_one(ranked_doc_ids, gold_map[q["id"]])

        rows.append(
            {
                "method": method_name,
                "query_id": q["id"],
                "query": q["query"],
                "topic": q["topic"],
                "query_type": q["query_type"],
                "gold_doc_id": gold_map[q["id"]],
                "ranked_doc_ids": ranked_doc_ids,
                "returned_count": len(ranked_doc_ids),
                "latency_ms": latency_ms,
                **s,
            }
        )

        print(
            f"\r[{method_name}] {i:>2}/{len(queries)}",
            end="",
            flush=True,
        )

    print()
    return aggregate(rows), rows


# ─────────────────────────────────────────────────────────────────────────────
# 输出与分组统计
# ─────────────────────────────────────────────────────────────────────────────

def grouped_metrics(rows: list[dict], key: str) -> dict:
    groups = defaultdict(list)
    for row in rows:
        groups[row[key]].append(row)
    return {name: aggregate(items) for name, items in sorted(groups.items())}


def print_summary(summary: dict) -> None:
    print("\n" + "=" * 92)
    print(
        f"{'方法':<34}"
        f"{'R@1':>10}"
        f"{'R@5':>10}"
        f"{'MRR@5':>10}"
        f"{'Avg返回':>12}"
        f"{'Avg耗时ms':>14}"
    )
    print("-" * 92)

    for name, m in summary.items():
        print(
            f"{name:<34}"
            f"{m['Recall@1']*100:>9.1f}%"
            f"{m['Recall@5']*100:>9.1f}%"
            f"{m['MRR@5']:>10.3f}"
            f"{m['avg_returned']:>12.2f}"
            f"{m['avg_latency_ms']:>14.2f}"
        )
    print("=" * 92)


def write_csv(path: Path, all_rows: list[dict]) -> None:
    fieldnames = [
        "method",
        "query_id",
        "topic",
        "query_type",
        "query",
        "gold_doc_id",
        "gold_rank",
        "recall_at_1",
        "recall_at_5",
        "mrr_at_5",
        "returned_count",
        "latency_ms",
        "ranked_doc_ids",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in all_rows:
            out = dict(row)
            out["ranked_doc_ids"] = ",".join(row["ranked_doc_ids"])
            writer.writerow({k: out.get(k) for k in fieldnames})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=ROOT / "data" / "eval" / "math_rag_eval_zh_500",
    )
    parser.add_argument(
        "--thread-id",
        default="__mathtutor_rag_eval__",
    )
    args = parser.parse_args()

    data_dir = args.data_dir.resolve()
    queries_path = data_dir / "queries.jsonl"
    corpus_path = data_dir / "corpus.jsonl"
    qrels_path = data_dir / "qrels.tsv"

    for p in [queries_path, corpus_path, qrels_path]:
        if not p.exists():
            raise FileNotFoundError(f"找不到评测文件：{p}")

    queries = load_jsonl(queries_path)
    corpus = load_jsonl(corpus_path)
    gold_map = load_qrels(qrels_path)

    if len(queries) != 50 or len(corpus) != 500:
        print(
            f"[提示] 当前数据规模：queries={len(queries)}, corpus={len(corpus)}。"
            "脚本仍会运行。"
        )

    print("=" * 78)
    print("MathTutor 项目真实 RAG 评测")
    print("=" * 78)
    print(f"项目根目录 : {ROOT}")
    print(f"评测数据   : {data_dir}")
    print(f"Queries    : {len(queries)}")
    print(f"Corpus     : {len(corpus)}")
    print(f"EMBED_DIM  : {EMBED_DIM}")
    print(f"TOP_K      : {TOP_K}")
    print(f"MIN_SCORE  : {MIN_SCORE}")
    print(f"RRF_K      : {RRF_K}")
    print()
    print(
        "注意：Project Hybrid RRF + CRAG 会直接调用项目的 rag_tool.invoke()，"
        "不是独立重写版本。"
    )

    print("\n[1/2] 按项目 ingest 后的结构构建 500-chunk 临时 Store...")
    store, build_seconds = build_project_store(corpus, args.thread_id)
    print(
        f"完成：FAISS ntotal={store['index'].ntotal}, "
        f"索引/Embedding 构建耗时={build_seconds:.2f}s"
    )

    doc_ids = [d["id"] for d in corpus]

    methods = {
        "BM25-only (项目当前)": lambda text: [
            doc_ids[i] for i in bm25_only(store, text)
        ],
        "FAISS-only (项目BGE)": lambda text: [
            doc_ids[i] for i in dense_only(store, text)
        ],
        "Hybrid RRF (去掉CRAG消融)": lambda text: [
            doc_ids[i] for i in hybrid_rrf_without_crag(store, text)
        ],
        "Project Hybrid RRF + CRAG": lambda text: (
            project_rag_tool_ranked_doc_ids(text, args.thread_id)
        ),
    }

    print("\n[2/2] 开始评测...")
    summary = {}
    per_method = {}
    all_rows = []

    for name, fn in methods.items():
        metrics, rows = evaluate_method(
            name,
            queries,
            gold_map,
            fn,
        )
        summary[name] = metrics
        per_method[name] = {
            "overall": metrics,
            "by_query_type": grouped_metrics(rows, "query_type"),
            "by_topic": grouped_metrics(rows, "topic"),
        }
        all_rows.extend(rows)

    print_summary(summary)

    # 将失败样本单独保存，方便你面试前做 error analysis
    production_name = "Project Hybrid RRF + CRAG"
    failures = [
        r for r in all_rows
        if r["method"] == production_name and r["recall_at_5"] == 0.0
    ]

    result_obj = {
        "evaluation": {
            "dataset": "自建中文数学 RAG 检索评测集",
            "query_count": len(queries),
            "corpus_count": len(corpus),
            "one_gold_per_query": True,
            "note": "本数据集每个 Query 仅 1 个 gold，因此 Recall@K 数值等同于 Hit@K。",
        },
        "project_config": {
            "EMBED_DIM": EMBED_DIM,
            "TOP_K": TOP_K,
            "MIN_SCORE": MIN_SCORE,
            "RRF_K": RRF_K,
            "dense_candidates": DENSE_CANDIDATES,
            "sparse_candidates": SPARSE_CANDIDATES,
        },
        "index_build_seconds": build_seconds,
        "summary": summary,
        "details": per_method,
        "production_failures": len(failures),
    }

    results_json = data_dir / "results_project.json"
    results_csv = data_dir / "results_project.csv"
    failures_jsonl = data_dir / "failures_project.jsonl"

    results_json.write_text(
        json.dumps(result_obj, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_csv(results_csv, all_rows)

    with failures_jsonl.open("w", encoding="utf-8") as f:
        for row in failures:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    clear_store(args.thread_id)

    print("\n结果文件：")
    print(f"  {results_json}")
    print(f"  {results_csv}")
    print(f"  {failures_jsonl}")
    print()
    print(
        "简历中不要提前写提升数字。先看 results_project.json 的真实结果，"
        "再决定是否写“Recall@1/Recall@5 提升 X.X 个百分点”。"
    )


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""
MathTutor Solver / Verifier / RAG 正确率评测（基于项目真实节点）
================================================================

这不是另写一个“模拟 Solver”。

本脚本直接复用项目：
    workflow.solver_agent
    workflow.verifier_agent
    ToolNode(SOLVER_TOOLS)
    _route_solver_or_tools
    make_initial_state

因此：
- Solver 的 Prompt / DeepSeek 模型 / tool binding 均来自项目
- Verifier 的 Prompt 与结构化输出来自项目
- Solver -> Tool -> Solver 的 ReAct 路径来自项目工具
- Verifier 错误反馈后最多重试 3 次，与生产 graph.py 相同

为避免 Redis 长期记忆、Safety、Explainer、满意度 HITL 干扰“解题正确率”，
这里构造一个专用 Eval 子图，只保留：
    Solver <-> Tool -> Verifier -> [Retry / END]

也就是说，它专门回答：
    1) Solver 第一次做题正确率是多少？
    2) 经过项目 Verifier 反馈 + 最多 3 次重试后，最终正确率是多少？
    3) 打开项目 RAG 后，上述两个指标是否变化？

默认会跑两个模式：
    no_rag : Solver / Solver+Verifier
    rag    : Solver+RAG / Solver+Verifier+RAG

运行前：
    1. 项目 .env / Streamlit secrets 中要有 DEEPSEEK_API_KEY
    2. 若跑 rag 模式，需要：
       data/math_rag_eval_zh_500/corpus.jsonl
       （就是你前面已经放进项目的 500 文档检索集）

建议先小跑：
    python scripts/eval_solver_accuracy.py --limit 10 --modes no_rag

再全量：
    python scripts/eval_solver_accuracy.py --limit 100 --modes no_rag rag

输出：
    data/math_solver_eval_100/results_solver_accuracy.json
    data/math_solver_eval_100/results_solver_accuracy.csv
    data/math_solver_eval_100/failures_solver_accuracy.jsonl
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import faiss
import numpy as np
import sympy as sp
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode
from rank_bm25 import BM25Okapi


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for p in (ROOT, SRC):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


# ─────────────────────────────────────────────────────────────────────────────
# 项目真实代码
# ─────────────────────────────────────────────────────────────────────────────

from backend.agents.graph import (  # noqa: E402
    SOLVER_TOOLS,
    _route_solver_or_tools,
    workflow,
)
from backend.agents.state import AgentState, make_initial_state  # noqa: E402
from backend.agents.nodes.tools import (  # noqa: E402
    EMBED_DIM,
    EMBED_INPUT_TYPE_DOC,
)
from backend.agents.nodes.tools.tools import (  # noqa: E402
    _STORES,
    _embed_texts,
    _tokenize,
    clear_store,
)


# ─────────────────────────────────────────────────────────────────────────────
# Eval 子图：真实 Solver + ToolNode + Verifier，重试策略与生产一致
# ─────────────────────────────────────────────────────────────────────────────

def _route_after_verifier_for_eval(state: AgentState) -> str:
    """
    对应生产 graph.py::_route_after_verifier 的 solve 路径：

    correct      -> 生产去 safety，这里 END
    needs_human  -> 生产去 HITL，这里 END 并记录
    incorrect / partially_correct:
        solve_iterations >= 3 -> 生产 HITL，这里 END
        否则                 -> solver_agent retry

    因此“最多 3 次 Solver 尝试”与项目生产策略一致。
    """
    verifier = state.get("verifier_output") or {}
    status = verifier.get("status") or "incorrect"

    if status == "correct":
        return "END"
    if status == "needs_human":
        return "END"

    if state.get("solve_iterations", 0) >= 3:
        return "END"
    return "solver_agent"


def build_eval_graph():
    graph = StateGraph(AgentState)

    graph.add_node("solver_agent", workflow.solver_agent)
    graph.add_node("tool_node", ToolNode(SOLVER_TOOLS))
    graph.add_node("verifier_agent", workflow.verifier_agent)

    graph.set_entry_point("solver_agent")

    graph.add_conditional_edges(
        "solver_agent",
        _route_solver_or_tools,
        {
            "tool_node": "tool_node",
            "verifier_agent": "verifier_agent",
        },
    )
    graph.add_edge("tool_node", "solver_agent")

    graph.add_conditional_edges(
        "verifier_agent",
        _route_after_verifier_for_eval,
        {
            "solver_agent": "solver_agent",
            "END": END,
        },
    )

    return graph.compile()


# ─────────────────────────────────────────────────────────────────────────────
# RAG：复用项目真实 tokenizer / BGE / FAISS / BM25 数据结构
# ─────────────────────────────────────────────────────────────────────────────

def load_jsonl(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def build_rag_store_template(corpus: list[dict]) -> dict:
    texts = [d["text"] for d in corpus]

    print("[RAG] 使用项目 _tokenize 构建 BM25 ...")
    tokenized = [_tokenize(t) for t in texts]
    bm25 = BM25Okapi(tokenized)

    print("[RAG] 使用项目 _embed_texts / BGE 构建 500 文档向量 ...")
    doc_vecs = np.asarray(
        _embed_texts(texts, EMBED_INPUT_TYPE_DOC),
        dtype=np.float32,
    )
    if doc_vecs.ndim != 2 or doc_vecs.shape[1] != EMBED_DIM:
        raise RuntimeError(
            f"Embedding shape={doc_vecs.shape}, expected dim={EMBED_DIM}"
        )

    index = faiss.IndexFlatIP(EMBED_DIM)
    index.add(doc_vecs)

    metadata = [
        {
            "page": d["id"],
            "doc_id": d["id"],
            "eval_topic": d.get("topic"),
            "eval_kind": d.get("kind"),
        }
        for d in corpus
    ]

    return {
        "index": index,
        "chunks": texts,
        "metadata": metadata,
        "filenames": ["math_rag_eval_zh_500"],
        "bm25": bm25,
        "tokenized_chunks": tokenized,
        "doc_vecs": doc_vecs,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 确定性判分：不让 LLM Judge 给自己打分
# ─────────────────────────────────────────────────────────────────────────────

FRAC_RE = re.compile(r"\\[dtc]?frac\s*\{([^{}]+)\}\s*\{([^{}]+)\}")
FINAL_MARKERS = (
    "最终答案：",
    "最终答案:",
    "∴ 最终答案：",
    "∴ 最终答案:",
    "Final Answer:",
    "FINAL ANSWER:",
    "答案：",
    "答案:",
)

VALUE_PATTERN = r"[-+]?\d+(?:\.\d+)?(?:\s*/\s*[-+]?\d+(?:\.\d+)?)?"

# x>0 / n≤5 这类条件里的数字不是答案，提取前先剔除
CONDITION_RE = re.compile(r"[A-Za-z]\s*(?:>=|<=|>|<|≥|≤)\s*[-+]?\d+(?:\.\d+)?")

# \frac25 这种省略花括号的写法
FRAC_SHORT_RE = re.compile(r"\\[dtc]?frac\s*(\d)\s*(\d)")

BOXED_TOKEN = "\\boxed"


def _boxed_contents(s: str) -> list[str]:
    """返回所有 \\boxed{...} 的内部内容（按出现顺序，支持嵌套花括号）。

    boxed 是模型标注最终答案最强的信号，所以答案数值优先只在
    这些内容里取，而不是在整个句子（含 x^2 指数、条件数字）里取。
    """
    out: list[str] = []
    i = 0
    while True:
        j = s.find(BOXED_TOKEN, i)
        if j == -1:
            break

        k = j + len(BOXED_TOKEN)
        while k < len(s) and s[k] == " ":
            k += 1
        if k >= len(s) or s[k] != "{":
            i = k if k > j else j + len(BOXED_TOKEN)
            continue

        depth = 0
        m = k
        while m < len(s):
            if s[m] == "{":
                depth += 1
            elif s[m] == "}":
                depth -= 1
                if depth == 0:
                    break
            m += 1
        if depth != 0:            # 花括号不配平，放弃后续解析
            break

        out.append(s[k + 1:m])
        i = m + 1
    return out


def _is_simple_number(expr: str) -> bool:
    """分子/分母是纯数字时不需要括号，保证 1/2 能被 VALUE_PATTERN 直接匹配。"""
    return re.fullmatch(r"\s*[-+]?\d+(?:\.\d+)?\s*", expr) is not None


def _frac_repl(m: re.Match) -> str:
    num, den = m.group(1), m.group(2)
    if _is_simple_number(num) and _is_simple_number(den):
        return f"{num.strip()}/{den.strip()}"
    return f"({num})/({den})"


def _latex_to_plain(s: str) -> str:
    s = s or ""
    # \frac/\dfrac/\tfrac/\cfrac{a}{b} -> a/b 或 (a)/(b)
    for _ in range(4):
        new = FRAC_RE.sub(_frac_repl, s)
        if new == s:
            break
        s = new

    # \frac25 -> 2/5
    s = FRAC_SHORT_RE.sub(r"\1/\2", s)

    # 数字指数不是答案（x^2 的 2 会被误会成数值），先去掉
    s = re.sub(r"\^\s*\{?\s*[-+]?\d+(?:\.\d+)?\s*\}?", "", s)

    s = (
        s.replace("$", "")
         .replace("\\(", "")
         .replace("\\)", "")
         .replace("\\[", "")
         .replace("\\]", "")
         .replace("−", "-")
         .replace("–", "-")
         .replace("，", ",")
         .replace("；", ";")
         .replace("。", ".")
         .replace("＝", "=")
    )
    # 条件式里的数字（如 x>0 的 0）不是答案，先剔除
    s = CONDITION_RE.sub(" ", s)
    # 百分数归一为小数，便于与分数形式 gold 比较
    s = PERCENT_RE.sub(_percent_repl, s)
    # x_1 / x1 / x₂ 等下标会污染“解集”数值提取，先消掉变量下标
    s = re.sub(r"([A-Za-z])_\{?\d+\}?", r"\1", s)
    # 注意排除 LaTeX 命令名：\dfrac25 里的 c25 不能被当成下标吃掉
    s = re.sub(r"(?<![\\A-Za-z])([A-Za-z])\d+", r"\1", s)
    s = s.translate(str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789"))
    return s


def _final_segment(final_answer: str, solution: str) -> str:
    """返回原始答案片段（不作 LaTeX 清洗）。

    保留 \\boxed{...} 原样，交给 _extract_scalar / _extract_set 判断，
    因为 boxed 是模型标注最终答案最强的信号。
    """
    text = (final_answer or "").strip()
    if text:
        return text

    text = solution or ""
    best = text
    for marker in FINAL_MARKERS:
        if marker in text:
            best = text.split(marker)[-1]
    return best.strip()


def _to_rational(token: str):
    token = token.strip().replace(" ", "")
    try:
        return sp.Rational(token)
    except Exception:
        try:
            x = sp.sympify(token)
            if x.is_real is not False:
                return sp.nsimplify(x)
        except Exception:
            return None
    return None


# 锚点分组，按优先级从高到低尝试。
# “为 / 是”优先于 “=”，因为 “∫₀¹eˣdx = e-1，其中系数之和为 0”
# 这种句子里 “=” 只是推导中间式；而 “最小值为 6（在 x=3 时取得）”
# 若让 “=” 优先会错误地抠到 x=3。
# 不含 “等于 / 得”：“第 14 项等于 31”（问项数 14）会被它们误导。
SCALAR_ANCHORS = (("为", "是"), ("=",))
# “因为...”里的“为”不是答案锚点
ANCHOR_BAD_PREFIX = {"为": "因"}

# 百分数需归一到小数：3.2% 与 4/125 是同一个答案
PERCENT_RE = re.compile(r"([-+]?\d+(?:\.\d+)?)\s*\\?%")


def _percent_repl(m: re.Match) -> str:
    try:
        val = float(m.group(1)) / 100.0
    except Exception:
        return m.group(0)
    return f"({sp.Rational(val).limit_denominator(1000000)})"


def _value_after_last_anchor(segment: str, anchors: tuple[str, ...]):
    """在锚点之后取数值，取“最后一个能解析出数值”的锚点位置。

    逐位置评估，而不是只取锚点的最大下标：像
    “最小值为 6，其中 e 是自然常数” 里，“是”比“为”靠后但后面没数值，
    应当继续用“为”后面的 6。
    """
    best = None
    for anchor in anchors:
        start = 0
        while True:
            i = segment.find(anchor, start)
            if i == -1:
                break
            start = i + 1

            bad = ANCHOR_BAD_PREFIX.get(anchor)
            if bad is not None and i > 0 and segment[i - 1] == bad:
                continue

            vals = re.findall(VALUE_PATTERN, segment[i + 1:])
            if not vals:
                continue
            val = _to_rational(vals[0])
            if val is None:
                continue

            if best is None or i > best[0]:
                best = (i, val)

    return None if best is None else best[1]


def _extract_scalar(segment: str):
    # 1) \boxed{...} 内部就是模型给出的最终答案，只在这里取值
    for inner in reversed(_boxed_contents(segment)):
        vals = re.findall(VALUE_PATTERN, _latex_to_plain(inner))
        if vals:
            return _to_rational(vals[0])

    plain = _latex_to_plain(segment)

    # 2) 按优先级依次尝试锚点（“为”优先于“=”）
    for anchors in SCALAR_ANCHORS:
        anchored = _value_after_last_anchor(plain, anchors)
        if anchored is not None:
            return anchored

    # 3) 兜底：片段中的第一个数值
    vals = re.findall(VALUE_PATTERN, plain)
    if not vals:
        return None
    return _to_rational(vals[0])


def _set_from_plain(segment: str):
    # 优先提取 x=... / x=... 的 RHS
    assigns = re.findall(
        rf"(?:^|[,;、或和\s])(?:x|X)\s*=\s*({VALUE_PATTERN})",
        segment
    )
    if assigns:
        vals = [_to_rational(x) for x in assigns]
        return {v for v in vals if v is not None}

    # {2, 3} / (-1,4) 等
    brace = re.search(r"[\{\(\[]([^{}\(\)\[\]]+)[\}\)\]]", segment)
    if brace:
        vals = [_to_rational(x) for x in re.findall(VALUE_PATTERN, brace.group(1))]
        out = {v for v in vals if v is not None}
        if out:
            return out

    # 兜底：最终答案片段中的所有数值
    vals = [_to_rational(x) for x in re.findall(VALUE_PATTERN, segment)]
    return {v for v in vals if v is not None}


def _extract_set(segment: str):
    # \boxed{...} 内部优先
    for inner in reversed(_boxed_contents(segment)):
        got = _set_from_plain(_latex_to_plain(inner))
        if got:
            return got
    return _set_from_plain(_latex_to_plain(segment))


def grade_output(question: dict, solver_output: dict | None) -> dict:
    solver_output = solver_output or {}
    final_answer = solver_output.get("final_answer") or ""
    solution = solver_output.get("solution") or ""
    segment = _final_segment(final_answer, solution)

    if question["answer_type"] == "scalar":
        pred = _extract_scalar(segment)
        gold = sp.Rational(question["gold"])
        ok = pred is not None and sp.simplify(pred - gold) == 0
        pred_display = None if pred is None else str(pred)

    elif question["answer_type"] == "set":
        pred = _extract_set(segment)
        gold = {sp.Rational(x) for x in question["gold"]}
        ok = pred == gold
        pred_display = sorted([str(x) for x in pred], key=str)

    else:
        raise ValueError(f"Unsupported answer_type={question['answer_type']}")

    return {
        "correct": bool(ok),
        "pred": pred_display,
        "answer_segment": _latex_to_plain(segment)[:500],
    }


# ─────────────────────────────────────────────────────────────────────────────
# 单题运行
# ─────────────────────────────────────────────────────────────────────────────

def initial_state_for(question: dict, thread_id: str) -> AgentState:
    state = make_initial_state(
        student_id="eval_student",
        thread_id=thread_id,
        raw_text=question["question"],
    )

    # Eval 专门测 Solver/Verifier，不重复测 Parser/Router。
    # 这些字段正是 solver_agent 当前真实读取的字段。
    state["input_mode"] = "text"
    state["parsed_data"] = {
        "problem_text": question["question"],
        "topic": question["topic"],
        "variables": [],
        "constraints": [],
        "needs_clarification": False,
    }
    state["solution_plan"] = {
        "intent_type": "solve",
        "difficulty": question.get("difficulty", "medium"),
        "solver_strategy": question.get(
            "solver_strategy", "choose the most direct method"
        ),
    }
    state["ltm_context"] = {}
    return state


def run_one(
    app,
    question: dict,
    mode: str,
    rag_store_template: dict | None,
) -> dict:
    thread_id = f"__solver_eval__{mode}__{question['id']}"

    if mode == "rag":
        if rag_store_template is None:
            raise RuntimeError("rag mode requested but RAG store is unavailable")
        _STORES[thread_id] = rag_store_template
    else:
        clear_store(thread_id)

    state = initial_state_for(question, thread_id)

    attempts = []
    verifier_events = []
    t0 = time.perf_counter()
    error = None

    try:
        for event in app.stream(state, stream_mode="updates"):
            if not isinstance(event, dict):
                continue

            solver_patch = event.get("solver_agent")
            if isinstance(solver_patch, dict) and solver_patch.get("solver_output"):
                output = solver_patch["solver_output"]
                g = grade_output(question, output)
                attempts.append({
                    "attempt": len(attempts) + 1,
                    "solver_output": output,
                    "grader": g,
                    "verifier": None,
                })

            verifier_patch = event.get("verifier_agent")
            if isinstance(verifier_patch, dict) and verifier_patch.get("verifier_output"):
                vo = verifier_patch["verifier_output"]
                verifier_events.append(vo)
                if attempts:
                    attempts[-1]["verifier"] = vo

    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"

    elapsed_ms = (time.perf_counter() - t0) * 1000

    first = attempts[0] if attempts else None
    final = attempts[-1] if attempts else None

    first_correct = bool(first and first["grader"]["correct"])
    final_correct = bool(final and final["grader"]["correct"])

    final_verifier = (final or {}).get("verifier") or {}
    verifier_status = final_verifier.get("status")

    # Verifier agreement：每一个有 verifier 结果的尝试，Verifier “correct”
    # 是否和确定性 gold grader 一致。
    agreements = []
    false_accept = 0
    false_reject = 0
    for a in attempts:
        vo = a.get("verifier") or {}
        if not vo:
            continue
        verifier_says_correct = vo.get("status") == "correct"
        gold_says_correct = bool(a["grader"]["correct"])
        agreements.append(verifier_says_correct == gold_says_correct)
        if verifier_says_correct and not gold_says_correct:
            false_accept += 1
        if (not verifier_says_correct) and gold_says_correct:
            false_reject += 1

    rag_used = any(
        bool((a.get("solver_output") or {}).get("rag_context_used"))
        for a in attempts
    )
    calc_used = any(
        bool((a.get("solver_output") or {}).get("calculator_used"))
        for a in attempts
    )
    web_used = any(
        bool((a.get("solver_output") or {}).get("web_search_used"))
        for a in attempts
    )

    clear_store(thread_id)

    return {
        "mode": mode,
        "question_id": question["id"],
        "topic": question["topic"],
        "concept": question["concept"],
        "difficulty": question["difficulty"],
        "question": question["question"],
        "answer_type": question["answer_type"],
        "gold": question["gold"],
        "attempts": len(attempts),
        "first_pass_correct": first_correct,
        "final_correct": final_correct,
        "recovered": (not first_correct) and final_correct,
        "regressed": first_correct and (not final_correct),
        "final_verifier_status": verifier_status,
        "verifier_agreement_events": sum(agreements),
        "verifier_total_events": len(agreements),
        "verifier_false_accept_events": false_accept,
        "verifier_false_reject_events": false_reject,
        "rag_used": rag_used,
        "calculator_used": calc_used,
        "web_used": web_used,
        "latency_ms": elapsed_ms,
        "error": error,
        "first_pred": None if not first else first["grader"]["pred"],
        "final_pred": None if not final else final["grader"]["pred"],
        "first_answer_segment": "" if not first else first["grader"]["answer_segment"],
        "final_answer_segment": "" if not final else final["grader"]["answer_segment"],
        "attempt_trace": attempts,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 汇总
# ─────────────────────────────────────────────────────────────────────────────

def mean(xs):
    return float(sum(xs) / len(xs)) if xs else 0.0


def aggregate(rows: list[dict]) -> dict:
    valid = [r for r in rows if not r["error"] and r["attempts"] > 0]
    first_wrong = [r for r in valid if not r["first_pass_correct"]]

    agree = sum(r["verifier_agreement_events"] for r in valid)
    total_v = sum(r["verifier_total_events"] for r in valid)

    return {
        "questions_total": len(rows),
        "questions_valid": len(valid),
        "errors": len(rows) - len(valid),
        "first_pass_accuracy": mean([1.0 if r["first_pass_correct"] else 0.0 for r in valid]),
        "final_accuracy": mean([1.0 if r["final_correct"] else 0.0 for r in valid]),
        "recovery_rate_among_first_pass_wrong": (
            mean([1.0 if r["recovered"] else 0.0 for r in first_wrong])
            if first_wrong else 0.0
        ),
        "regression_rate": mean([1.0 if r["regressed"] else 0.0 for r in valid]),
        "avg_solver_attempts": mean([float(r["attempts"]) for r in valid]),
        "avg_latency_ms": mean([r["latency_ms"] for r in valid]),
        "rag_used_rate": mean([1.0 if r["rag_used"] else 0.0 for r in valid]),
        "calculator_used_rate": mean([1.0 if r["calculator_used"] else 0.0 for r in valid]),
        "web_used_rate": mean([1.0 if r["web_used"] else 0.0 for r in valid]),
        "verifier_agreement": (agree / total_v) if total_v else 0.0,
        "verifier_events": total_v,
        "verifier_false_accept_events": sum(r["verifier_false_accept_events"] for r in valid),
        "verifier_false_reject_events": sum(r["verifier_false_reject_events"] for r in valid),
    }


def grouped(rows: list[dict], key: str) -> dict:
    groups = defaultdict(list)
    for r in rows:
        groups[r[key]].append(r)
    return {k: aggregate(v) for k, v in sorted(groups.items())}


def print_table(summaries: dict) -> None:
    print("\n" + "=" * 112)
    print(
        f"{'模式':<12}"
        f"{'First Acc':>12}"
        f"{'Final Acc':>12}"
        f"{'恢复率':>12}"
        f"{'平均尝试':>12}"
        f"{'Verifier一致':>14}"
        f"{'平均耗时(s)':>14}"
    )
    print("-" * 112)

    for mode, m in summaries.items():
        print(
            f"{mode:<12}"
            f"{m['first_pass_accuracy']*100:>11.1f}%"
            f"{m['final_accuracy']*100:>11.1f}%"
            f"{m['recovery_rate_among_first_pass_wrong']*100:>11.1f}%"
            f"{m['avg_solver_attempts']:>12.2f}"
            f"{m['verifier_agreement']*100:>13.1f}%"
            f"{m['avg_latency_ms']/1000:>14.2f}"
        )
    print("=" * 112)


def write_csv(path: Path, rows: list[dict]) -> None:
    fields = [
        "mode", "question_id", "topic", "concept", "difficulty", "question",
        "answer_type", "gold", "attempts",
        "first_pass_correct", "final_correct", "recovered", "regressed",
        "final_verifier_status",
        "verifier_agreement_events", "verifier_total_events",
        "verifier_false_accept_events", "verifier_false_reject_events",
        "rag_used", "calculator_used", "web_used",
        "latency_ms", "error",
        "first_pred", "final_pred",
        "first_answer_segment", "final_answer_segment",
    ]

    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for row in rows:
            out = dict(row)
            if isinstance(out.get("gold"), list):
                out["gold"] = json.dumps(out["gold"], ensure_ascii=False)
            if isinstance(out.get("first_pred"), list):
                out["first_pred"] = json.dumps(out["first_pred"], ensure_ascii=False)
            if isinstance(out.get("final_pred"), list):
                out["final_pred"] = json.dumps(out["final_pred"], ensure_ascii=False)
            w.writerow({k: out.get(k) for k in fields})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=ROOT / "data" / "math_solver_eval_100",
    )
    parser.add_argument(
        "--rag-corpus",
        type=Path,
        default=ROOT / "data" / "math_rag_eval_zh_500" / "corpus.jsonl",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
    )
    parser.add_argument(
        "--modes",
        nargs="+",
        choices=["no_rag", "rag"],
        default=["no_rag", "rag"],
    )
    parser.add_argument(
        "--start",
        type=int,
        default=0,
        help="从第几个题开始，便于断点分批跑。例如 --start 50 --limit 50",
    )
    args = parser.parse_args()

    questions_path = args.data_dir / "questions.jsonl"
    if not questions_path.exists():
        raise FileNotFoundError(f"找不到题集：{questions_path}")

    all_questions = load_jsonl(questions_path)
    questions = all_questions[args.start: args.start + args.limit]

    print("=" * 80)
    print("MathTutor Solver Accuracy Evaluation")
    print("=" * 80)
    print(f"Project root : {ROOT}")
    print(f"Questions    : {len(questions)} / {len(all_questions)}")
    print(f"Slice        : start={args.start}, limit={args.limit}")
    print(f"Modes        : {args.modes}")
    print()
    print("判分方式：SymPy + 确定性规则；不使用 LLM Judge。")
    print("First-pass：第 1 次 Solver 输出。")
    print("Final：经过项目 Verifier 反馈、最多 3 次 Solver 尝试后的最终输出。")
    print()

    rag_store = None
    if "rag" in args.modes:
        if not args.rag_corpus.exists():
            raise FileNotFoundError(
                "你选择了 rag 模式，但找不到 500 文档 corpus：\n"
                f"{args.rag_corpus}\n"
                "请先把 math_rag_eval_zh_500 放到 data/ 下，"
                "或者只跑 --modes no_rag。"
            )
        corpus = load_jsonl(args.rag_corpus)
        t0 = time.perf_counter()
        rag_store = build_rag_store_template(corpus)
        print(
            f"[RAG] 500 文档索引构建完成，耗时 "
            f"{time.perf_counter()-t0:.2f}s\n"
        )

    app = build_eval_graph()

    rows = []
    summaries = {}

    for mode in args.modes:
        mode_rows = []
        print(f"\n--- mode={mode} ---")
        for i, q in enumerate(questions, start=1):
            print(
                f"[{mode}] {i:>3}/{len(questions)} "
                f"{q['id']} {q['topic']} | {q['concept']}",
                flush=True,
            )
            row = run_one(app, q, mode, rag_store)
            mode_rows.append(row)
            rows.append(row)

            if row["error"]:
                print(f"    ERROR: {row['error']}")
            else:
                print(
                    f"    first={'✓' if row['first_pass_correct'] else '✗'} "
                    f"final={'✓' if row['final_correct'] else '✗'} "
                    f"attempts={row['attempts']} "
                    f"verifier={row['final_verifier_status']} "
                    f"pred={row['final_pred']}"
                )

        summaries[mode] = aggregate(mode_rows)

    print_table(summaries)

    result = {
        "evaluation": {
            "dataset": "MathTutor Solver Accuracy Evaluation 100 (Synthetic v1)",
            "questions_in_file": len(all_questions),
            "questions_evaluated": len(questions),
            "slice_start": args.start,
            "modes": args.modes,
            "grading": "deterministic rules + SymPy; no LLM judge",
            "graph_scope": "project solver_agent + ToolNode(SOLVER_TOOLS) + verifier_agent",
            "retry_policy": "same as production solve path; max 3 solver attempts",
        },
        "summary": summaries,
        "by_topic": {
            mode: grouped([r for r in rows if r["mode"] == mode], "topic")
            for mode in args.modes
        },
        "by_difficulty": {
            mode: grouped([r for r in rows if r["mode"] == mode], "difficulty")
            for mode in args.modes
        },
    }

    out_json = args.data_dir / "results_solver_accuracy.json"
    out_csv = args.data_dir / "results_solver_accuracy.csv"
    out_fail = args.data_dir / "failures_solver_accuracy.jsonl"

    out_json.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_csv(out_csv, rows)

    with out_fail.open("w", encoding="utf-8") as f:
        for r in rows:
            if r["error"] or not r["final_correct"]:
                compact = dict(r)
                # trace 可能很大；失败文件保留即可做 error analysis
                f.write(json.dumps(compact, ensure_ascii=False, default=str) + "\n")

    print("\n结果：")
    print(out_json)
    print(out_csv)
    print(out_fail)

    print("\n建议简历只使用全量 100 题真实跑完后的数字。")
    print("如果 no_rag 的 Final Acc > First Acc，才可量化说明 Verifier+Retry 的恢复收益。")
    print("如果 rag 的指标进一步提高，才可说明 RAG 对最终解题正确率有正向贡献。")


if __name__ == "__main__":
    main()

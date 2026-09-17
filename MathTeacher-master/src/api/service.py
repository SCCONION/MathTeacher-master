from typing import Any

from langgraph.errors import GraphInterrupt
from langgraph.types import Command

from backend.agents.graph import chatbot
from backend.agents.state import make_initial_state


def graph_config(thread_id: str) -> dict:
    return {
        "configurable": {
            "thread_id": thread_id,
        },
        "metadata": {
            "thread_id": thread_id,
        },
    }


def ensure_thread_owner(student_id: str, thread_id: str) -> None:
    """
    你的 create_thread() 生成：
        <student_id>:<timestamp>

    因此这里可以做最基本的 ownership 检查。
    """
    if not thread_id.startswith(f"{student_id}:"):
        raise ValueError("thread_id does not belong to this student")


def extract_hitl(snapshot) -> tuple[bool, dict | None]:
    """
    基本复用你 Streamlit app.py 中
    _extract_hitl_from_snap() 的逻辑。
    """

    next_nodes = list(snapshot.next or [])

    if "hitl_node" not in next_nodes:
        return False, None

    for task in snapshot.tasks or []:
        for interrupt_value in getattr(task, "interrupts", []):
            value = getattr(interrupt_value, "value", {}) or {}

            if isinstance(value, dict):
                return True, value

    values = snapshot.values or {}

    stored = values.get("hitl_interrupt")

    if isinstance(stored, dict):
        return True, stored

    hitl_type = values.get("hitl_type") or "clarification"
    reason = values.get("hitl_reason") or "请提供所需信息。"

    prompt = reason
    message = reason

    if hitl_type == "satisfaction":
        message = "这次的讲解对你有帮助吗？"
        prompt = "这次的讲解你听懂了吗？如果没有，请告诉我们哪里不清楚，我们会重新讲解。"
    elif hitl_type == "verification":
        prompt = "请确认这个解答是否正确。"
    elif hitl_type == "bad_input":
        prompt = "请重新输入题目内容。"
    elif hitl_type == "clarification":
        prompt = reason

    return True, {
        "hitl_type": hitl_type,
        "prompt": prompt,
        "message": message,
    }


def build_response(thread_id: str) -> dict[str, Any]:
    snapshot = chatbot.get_state(
        config=graph_config(thread_id)
    )

    values = snapshot.values or {}

    pending, hitl_payload = extract_hitl(snapshot)

    solution_plan = values.get("solution_plan") or {}
    parsed_data = values.get("parsed_data") or {}

    return {
        "thread_id": thread_id,
        "status": "awaiting_human" if pending else "completed",
        "answer": values.get("final_response"),
        "intent": solution_plan.get("intent_type"),
        "topic": parsed_data.get("topic"),
        "hitl": hitl_payload if pending else None,
        "activity": values.get("agent_payload_log") or [],
    }


def run_text_chat(
    student_id: str,
    thread_id: str,
    message: str,
) -> dict:

    ensure_thread_owner(student_id, thread_id)

    state = make_initial_state(
        student_id=student_id,
        thread_id=thread_id,
        raw_text=message,
    )

    try:
        for _ in chatbot.stream(
            state,
            config=graph_config(thread_id),
            stream_mode="updates",
        ):
            pass

    except GraphInterrupt:
        # HITL 正常暂停，不算服务器错误
        pass

    return build_response(thread_id)


def run_file_chat(
    student_id: str,
    thread_id: str,
    *,
    image_path: str | None = None,
    audio_path: str | None = None,
) -> dict:

    ensure_thread_owner(student_id, thread_id)

    state = make_initial_state(
        student_id=student_id,
        thread_id=thread_id,
        image_path=image_path,
        audio_path=audio_path,
    )

    try:
        for _ in chatbot.stream(
            state,
            config=graph_config(thread_id),
            stream_mode="updates",
        ):
            pass

    except GraphInterrupt:
        pass

    return build_response(thread_id)


def resume_chat(
    student_id: str,
    thread_id: str,
    response: dict,
) -> dict:

    ensure_thread_owner(student_id, thread_id)

    try:
        for _ in chatbot.stream(
            Command(resume=response),
            config=graph_config(thread_id),
            stream_mode="updates",
        ):
            pass

    except GraphInterrupt:
        pass

    return build_response(thread_id)


def _stream_nodes(
    initial_state,
    config: dict,
    thread_id: str,
    resume: dict | None = None,
):
    """
    Shared generator that streams the graph node-by-node.

    Yields two event shapes:
        {"type": "thinking", "node": ..., "summary": ..., "fields": {...}}
        {"type": "node",     "node": ...}
    and finally:
        {"type": "done", ...full ChatResponse...}

    "thinking" events are derived from the incremental `agent_payload_log`
    each agent appends (its structured decision summary), so the UI can
    stream the model's reasoning/thinking content live.
    """
    seen = 0
    if resume is not None:
        # HITL 恢复时，checkpoint 中已保存了暂停前的日志，从已有长度继续，
        # 避免把之前已经流式输出过的 thinking 事件重复推给前端。
        try:
            snapshot = chatbot.get_state(config)
            seen = len((snapshot.values or {}).get("agent_payload_log") or [])
        except Exception:
            seen = 0

    try:
        if resume is not None:
            stream = chatbot.stream(
                Command(resume=resume),
                config=config,
                stream_mode="updates",
            )
        else:
            stream = chatbot.stream(
                initial_state,
                config=config,
                stream_mode="updates",
            )

        for chunk in stream:
            for node, update in chunk.items():
                # LangGraph 在 hitl_node 调用 interrupt() 时会产出一个
                # {"__interrupt__": (Interrupt(...),)} 的 chunk，其 value 是
                # tuple 而非节点更新 dict —— 跳过它，HITL 负载由 done 事件携带。
                if node == "__interrupt__" or not isinstance(update, dict):
                    continue

                log = update.get("agent_payload_log") or []

                if len(log) > seen:
                    for entry in log[seen:]:
                        yield {
                            "type": "thinking",
                            "node": node,
                            "summary": entry.get("summary", ""),
                            "fields": entry.get("fields", {}),
                        }
                    seen = len(log)
                else:
                    yield {"type": "node", "node": node}

    except GraphInterrupt:
        # HITL 正常暂停：`done` 事件会带上 hitl 负载
        pass

    yield {"type": "done", **build_response(thread_id)}


def run_text_chat_stream(
    student_id: str,
    thread_id: str,
    message: str,
):
    """流式版本的 run_text_chat：逐节点产出思考过程与最终结果。"""
    ensure_thread_owner(student_id, thread_id)

    state = make_initial_state(
        student_id=student_id,
        thread_id=thread_id,
        raw_text=message,
    )

    yield from _stream_nodes(
        state,
        graph_config(thread_id),
        thread_id,
    )


def run_resume_chat_stream(
    student_id: str,
    thread_id: str,
    response: dict,
):
    """流式版本的 resume_chat：HITL 反馈后继续流式产出。"""
    ensure_thread_owner(student_id, thread_id)

    yield from _stream_nodes(
        None,
        graph_config(thread_id),
        thread_id,
        resume=response,
    )
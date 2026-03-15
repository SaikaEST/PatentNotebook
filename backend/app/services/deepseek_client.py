import httpx

from app.core.config import settings
from app.models.entities import DocumentChunk


class DeepSeekError(RuntimeError):
    pass


def _build_context(
    question: str,
    chunks: list[DocumentChunk],
    source_lookup: dict[str, dict[str, str | None]],
) -> str:
    blocks: list[str] = []
    total_chars = 0
    max_chars = max(2000, int(settings.deepseek_max_context_chars))

    for index, chunk in enumerate(chunks, start=1):
        source_id = str(chunk.source_id)
        source_meta = source_lookup.get(source_id, {})
        source_name = source_meta.get("source_name") or source_id
        page_label = f"第 {chunk.page_no} 页" if chunk.page_no is not None else "页码未知"
        text = (chunk.text or "").strip()
        if not text:
            continue
        block = (
            f"[{index}] 文档: {source_name}\n"
            f"source_id: {source_id}\n"
            f"chunk_id: {chunk.id}\n"
            f"位置: {page_label}\n"
            f"内容:\n{text}\n"
        )
        if total_chars + len(block) > max_chars and blocks:
            break
        blocks.append(block)
        total_chars += len(block)

    if not blocks:
        raise DeepSeekError("No usable chunk content for prompt")

    return (
        "你是专利审查助手。请仅依据给定证据回答，使用中文输出。\n"
        "要求：\n"
        "1. 只使用提供的材料，不要编造事实。\n"
        "2. 如果证据不足，明确指出不足点。\n"
        "3. 回答要直接、结构清晰。\n"
        "4. 在句末使用方括号引用证据编号，例如 [1][2]。\n\n"
        f"用户问题：{question}\n\n"
        "可用证据如下：\n\n" + "\n".join(blocks)
    )


def generate_answer(
    question: str,
    chunks: list[DocumentChunk],
    source_lookup: dict[str, dict[str, str | None]],
) -> str:
    api_key = settings.deepseek_api_key.strip()
    if not api_key:
        raise DeepSeekError("DeepSeek API key is not configured")

    prompt = _build_context(question, chunks, source_lookup)
    base_url = settings.deepseek_api_base.rstrip("/")
    url = f"{base_url}/chat/completions"

    payload = {
        "model": settings.deepseek_model,
        "messages": [
            {"role": "system", "content": "你是严谨的专利审查助手。"},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "temperature": 0.2,
    }

    try:
        with httpx.Client(timeout=settings.deepseek_timeout_sec) as client:
            response = client.post(
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise DeepSeekError(f"DeepSeek request failed: {exc}") from exc

    try:
        data = response.json()
        content = data["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise DeepSeekError("DeepSeek response format invalid") from exc

    answer = str(content or "").strip()
    if not answer:
        raise DeepSeekError("DeepSeek returned empty answer")
    return answer

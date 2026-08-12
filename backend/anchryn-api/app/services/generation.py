"""Answering a question from retrieved passages, and only from those.

A thin httpx client over Hugging Face's OpenAI-compatible chat endpoint rather
than InferenceClient, because the TLS context has to be constructed explicitly:
behind a TLS-inspecting proxy the corporate root is trusted by the OS but absent
from certifi, and Python 3.13's default strict validation rejects roots missing
an Authority Key Identifier.

The refusal is enforced here, in code, before any model call. Asking a model to
decline and trusting it to comply is exactly the failure this project exists to
avoid — and skipping the call also costs nothing in quota.
"""

import logging
import re
import ssl
from dataclasses import dataclass
from pathlib import Path

import httpx

from app.config import get_settings
from app.services.retrieval import RetrievedChunk

logger = logging.getLogger(__name__)

REFUSAL = (
    "The documents provided do not cover this. I can only answer from what has "
    "been uploaded, so I would rather say nothing than guess."
)

SYSTEM_PROMPT = """You answer questions using ONLY the numbered passages supplied by the user.

Rules, in order of importance:
1. Never use knowledge from outside the passages. If the passages do not contain
   the answer, reply with exactly: NOT_IN_DOCUMENTS
2. Cite the passage you used with a bracketed number, like [2], immediately after
   the claim it supports. Every factual sentence needs a citation.
3. Do not speculate, and do not fill gaps with what is generally true.
4. Answer in plain English. No preamble, no restating the question.

Formatting, so the answer is easy to scan:
- Lead with the direct answer in one short sentence.
- If the answer has several steps or several distinct facts, follow with a
  bulleted list, one "- " per line. If it is a single fact, do not pad it into
  a list — one sentence is a complete answer.
- Put **bold** around the few terms that matter most: a setting name, a limit, a
  deadline. Two or three at most.
- Use `backticks` for literal values, header names, status codes and field names.
- Keep the whole answer under 120 words.
"""


class GenerationError(Exception):
    """Calling the model failed. The message is written for the user."""


class GenerationRateLimitError(GenerationError):
    """Quota or rate limit. Worth retrying later; nothing is wrong with the request."""


@dataclass(frozen=True)
class Answer:
    text: str
    #: chunk_ids of the passages the model actually cited.
    cited_chunk_ids: list[int]
    grounded: bool
    model: str


def build_ssl_context() -> ssl.SSLContext | bool:
    """The TLS context for outbound calls, or True for library defaults."""
    settings = get_settings()

    if not settings.ca_bundle and settings.tls_strict:
        return True

    cafile = None
    if settings.ca_bundle:
        path = Path(settings.ca_bundle).expanduser()
        if not path.is_file():
            raise GenerationError(f"CA bundle not found at {path}")
        cafile = str(path)

    context = ssl.create_default_context(cafile=cafile)
    if not settings.tls_strict:
        # Clears only the RFC-5280 extension strictness. Certificates are still
        # verified against the bundle — this is not "trust anything".
        context.verify_flags &= ~ssl.VERIFY_X509_STRICT
    return context


def answer_from_chunks(question: str, chunks: list[RetrievedChunk], grounded: bool) -> Answer:
    """Answer strictly from ``chunks``.

    When retrieval found nothing close enough, refuses without calling the model.
    """
    settings = get_settings()

    if not grounded or not chunks:
        return Answer(text=REFUSAL, cited_chunk_ids=[], grounded=False, model=settings.hf_model)

    if not settings.hf_configured:
        raise GenerationError(
            "No Hugging Face token configured. Set HF_TOKEN and restart the backend."
        )

    prompt = _build_prompt(question, chunks)
    raw = _call_model(prompt)

    if "NOT_IN_DOCUMENTS" in raw:
        # The passages cleared the similarity threshold but did not actually
        # answer the question. Retrieval being close is not the same as correct.
        return Answer(text=REFUSAL, cited_chunk_ids=[], grounded=False, model=settings.hf_model)

    cited = _extract_citations(raw, chunks)
    return Answer(text=raw.strip(), cited_chunk_ids=cited, grounded=True, model=settings.hf_model)


def _build_prompt(question: str, chunks: list[RetrievedChunk]) -> str:
    passages = "\n\n".join(
        f"[{index}] (from {chunk.filename}, page {chunk.page_number})\n{chunk.text}"
        for index, chunk in enumerate(chunks, start=1)
    )
    return f"Passages:\n\n{passages}\n\nQuestion: {question}"


def _extract_citations(text: str, chunks: list[RetrievedChunk]) -> list[int]:
    """Map the [n] markers in the answer back to chunk ids.

    Out-of-range markers are dropped rather than trusted — a model citing [7]
    when it was given four passages has invented the reference.
    """
    seen: list[int] = []
    for match in re.finditer(r"\[(\d+)\]", text):
        index = int(match.group(1))
        if 1 <= index <= len(chunks):
            chunk_id = chunks[index - 1].chunk_id
            if chunk_id not in seen:
                seen.append(chunk_id)
        else:
            logger.warning("Model cited [%d] but was given %d passages", index, len(chunks))
    return seen


def _call_model(prompt: str) -> str:
    settings = get_settings()

    payload = {
        "model": settings.hf_model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        # Low temperature: this is extraction from supplied text, not writing.
        "temperature": 0.2,
        "max_tokens": 600,
    }

    try:
        with httpx.Client(verify=build_ssl_context(), timeout=settings.hf_timeout_seconds) as client:
            response = client.post(
                f"{settings.hf_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {settings.hf_token}"},
                json=payload,
            )
    except httpx.ConnectError as exc:
        raise GenerationError(
            "Could not reach the Hugging Face API. If you are behind a TLS-inspecting "
            f"proxy, set CA_BUNDLE and TLS_STRICT=false. ({exc})"
        ) from exc
    except httpx.TimeoutException as exc:
        raise GenerationError("The model took too long to respond.") from exc

    _raise_for_status(response)

    try:
        return response.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, ValueError) as exc:
        raise GenerationError("The model returned a response in an unexpected shape.") from exc


def _raise_for_status(response: httpx.Response) -> None:
    if response.status_code == 200:
        return

    detail = response.text[:300]

    if response.status_code == 401:
        raise GenerationError("Hugging Face rejected the token. Check HF_TOKEN.")
    if response.status_code == 403:
        # Distinct from 401 and the more likely mistake: a fine-grained token
        # created without the Inference Providers permission.
        raise GenerationError(
            "The Hugging Face token is valid but not permitted to call Inference Providers. "
            "Create a Read token, or enable that permission on the fine-grained one."
        )
    if response.status_code in (402, 429):
        raise GenerationRateLimitError(
            "Hugging Face inference quota reached. Wait and try again, or add credits."
        )
    if response.status_code == 404:
        raise GenerationError(
            f"Model '{get_settings().hf_model}' is not available. Set HF_MODEL to one that is."
        )

    logger.error("Hugging Face returned %d: %s", response.status_code, detail)
    raise GenerationError(f"Hugging Face returned HTTP {response.status_code}.")

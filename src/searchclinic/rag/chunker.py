"""문서 전처리와 청킹 — 긴 문서를 검색 가능한 조각으로.

## 왜 필요한가

지금 지식베이스는 문서 하나가 짧아서 통째로 검색해도 됐다. 그런데 실무 문서는
그렇지 않다 — nori 공식 문서, 사내 검색 운영 위키, 장애 회고록은 수천 자다.
그런 문서를 통째로 넣으면 두 가지가 동시에 나빠진다:

    검색  — 문서 하나에 여러 주제가 섞여 어떤 질의에도 어중간하게 걸린다
    생성  — 관련 없는 문단까지 컨텍스트에 실려 토큰을 먹고 주의를 흩는다

## 문자 수로 자르지 않는다

가장 흔한 방식은 N자마다 자르는 것인데, 그러면 문장 한복판이 끊긴다. 끊긴
조각은 그 자체로 뜻이 통하지 않아 검색에도 근거에도 못 쓴다.

이 모듈은 **경계를 존중하는 순서**로 자른다:

    1순위  마크다운 섹션 헤더(`## `) — 저자가 이미 나눠 놓은 경계다
    2순위  빈 줄로 구분된 문단
    3순위  한국어 문장 끝(`다.` `요.` `.` `!` `?`)
    마지막  그래도 넘치면 문자 수 (여기까지 오면 어쩔 수 없다)

## 겹침(overlap)을 두는 이유

경계에서 자르면 앞뒤 문맥이 끊긴다. "그래서 사전 등록이 선행되어야 한다"는
문장이 새 청크의 첫 줄이면, `그래서`가 무엇을 받는지 알 수 없다. 앞 청크의
꼬리를 조금 겹쳐 두면 조각 하나만 읽어도 말이 된다.

겹침은 공짜가 아니다 — 색인이 커지고 같은 문장이 여러 번 검색된다. 그래서
비율을 파라미터로 두고 **검색 품질로 정한다**(`clinic rag-eval --chunking`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# 실무 문서를 상정한 기본값. 이 값들은 실측으로 정한다 — docs/EVALUATION.md
DEFAULT_MAX_CHARS = 400
DEFAULT_OVERLAP = 80

# 한국어 문장 끝. 종결어미 뒤의 마침표를 우선 보고, 없으면 일반 문장부호를 본다.
_SENTENCE_END = re.compile(r"(?<=[다요임함])\.\s|(?<=[.!?])\s")
_SECTION = re.compile(r"^#{1,6}\s+", re.MULTILINE)


@dataclass(frozen=True)
class Chunk:
    """문서 조각. 출처를 잃지 않는 것이 핵심이다."""

    doc_id: str
    chunk_id: str
    text: str
    index: int  # 문서 안에서 몇 번째인가
    heading: str = ""  # 이 조각이 속한 섹션 제목

    @property
    def display(self) -> str:
        """검색 결과에 보여줄 형태 — 제목을 앞에 붙여 맥락을 준다."""
        return f"{self.heading}\n{self.text}" if self.heading else self.text


def normalize(text: str) -> str:
    """문서 전처리 — 검색에 방해가 되는 것만 걷어낸다.

    과하게 씻으면 안 된다. 코드 블록의 `user_dictionary_rules` 같은 식별자는
    이 도메인에서 **가장 중요한 검색어**이므로 기호를 지우면 안 된다. 여기서
    하는 것은 공백 정규화와 제로폭 문자 제거까지다.
    """
    text = text.replace("​", "").replace("﻿", "")
    # 줄 끝 공백과 3줄 이상 연속 개행만 정리한다 (문단 경계는 보존).
    text = re.sub(r"[ \t]+(\n)", r"\1", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _split_sentences(text: str) -> list[str]:
    parts = _SENTENCE_END.split(text)
    return [p.strip() for p in parts if p and p.strip()]


def _pack(units: list[str], max_chars: int, joiner: str) -> list[str]:
    """조각들을 상한 안에서 이어 붙인다 — 너무 잘게 쪼개지지 않게."""
    packed: list[str] = []
    current = ""
    for unit in units:
        if not current:
            current = unit
        elif len(current) + len(joiner) + len(unit) <= max_chars:
            current = current + joiner + unit
        else:
            packed.append(current)
            current = unit
    if current:
        packed.append(current)
    return packed


def _hard_split(text: str, max_chars: int) -> list[str]:
    """마지막 수단. 여기까지 왔다면 경계 없이 긴 덩어리라는 뜻이다."""
    return [text[i : i + max_chars] for i in range(0, len(text), max_chars)] or [text]


def _with_overlap(pieces: list[str], overlap: int) -> list[str]:
    """앞 조각의 꼬리를 다음 조각 앞에 붙인다.

    문장 경계에서 꼬리를 떼어 낸다 — 글자 수로 자르면 겹침 자체가
    말이 안 되는 조각이 되어 오히려 검색을 흐린다.
    """
    if overlap <= 0 or len(pieces) < 2:
        return pieces
    out = [pieces[0]]
    for prev, piece in zip(pieces, pieces[1:]):
        tail = prev[-overlap:]
        sentences = _split_sentences(tail)
        tail_text = sentences[-1] if sentences else tail
        out.append(f"{tail_text} {piece}".strip())
    return out


def split_text(
    text: str, max_chars: int = DEFAULT_MAX_CHARS, overlap: int = DEFAULT_OVERLAP
) -> list[str]:
    """경계를 존중하는 순서로 자른다. 상한을 넘지 않는 조각들을 돌려준다."""
    text = normalize(text)
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    # 1순위: 문단. 문단이 이미 상한 안이면 그대로 묶는다.
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    pieces: list[str] = []
    for para in _pack(paragraphs, max_chars, "\n\n"):
        if len(para) <= max_chars:
            pieces.append(para)
            continue
        # 2순위: 문장
        sentences = _split_sentences(para)
        for packed in _pack(sentences, max_chars, " "):
            # 3순위: 문자 수 (문장 하나가 상한을 넘는 경우)
            pieces.extend([packed] if len(packed) <= max_chars else _hard_split(packed, max_chars))

    return _with_overlap(pieces, overlap)


def chunk_document(
    doc_id: str,
    text: str,
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap: int = DEFAULT_OVERLAP,
) -> list[Chunk]:
    """문서 하나를 청크 목록으로. 섹션 헤더가 있으면 그것을 1순위 경계로 쓴다."""
    text = normalize(text)
    if not text:
        return []

    sections: list[tuple[str, str]] = []
    if _SECTION.search(text):
        current_heading = ""
        buffer: list[str] = []
        for line in text.split("\n"):
            if _SECTION.match(line):
                if buffer:
                    sections.append((current_heading, "\n".join(buffer).strip()))
                    buffer = []
                current_heading = _SECTION.sub("", line).strip()
            else:
                buffer.append(line)
        if buffer:
            sections.append((current_heading, "\n".join(buffer).strip()))
    else:
        sections = [("", text)]

    chunks: list[Chunk] = []
    for heading, body in sections:
        if not body:
            continue
        for piece in split_text(body, max_chars=max_chars, overlap=overlap):
            idx = len(chunks)
            chunks.append(
                Chunk(
                    doc_id=doc_id,
                    chunk_id=f"{doc_id}#{idx}",
                    text=piece,
                    index=idx,
                    heading=heading,
                )
            )

    # **빈 목록은 절대 돌려주지 않는다.** 섹션 분해가 헤더만 남기고 본문을
    # 비우는 경우가 있는데(제목 줄에 본문이 붙어 있는 문서), 그대로 두면
    # 문서가 조용히 색인에서 사라진다 — 검색이 안 되는데 이유를 알 수 없는
    # 최악의 실패다. 실측으로 겪었고, 회귀 테스트가 이 줄을 지킨다.
    if not chunks:
        for idx, piece in enumerate(split_text(text, max_chars=max_chars, overlap=overlap)):
            chunks.append(
                Chunk(doc_id=doc_id, chunk_id=f"{doc_id}#{idx}", text=piece, index=idx)
            )
    return chunks


def chunk_knowledge(
    docs, max_chars: int = DEFAULT_MAX_CHARS, overlap: int = DEFAULT_OVERLAP
) -> list[Chunk]:
    """지식베이스 전체를 청크로. 제목은 헤더로 실어 맥락을 보존한다."""
    out: list[Chunk] = []
    for doc in docs:
        pieces = chunk_document(doc.doc_id, doc.body, max_chars=max_chars, overlap=overlap)
        for piece in pieces:
            out.append(
                Chunk(
                    doc_id=piece.doc_id,
                    chunk_id=piece.chunk_id,
                    text=piece.text,
                    index=piece.index,
                    heading=piece.heading or doc.title,
                )
            )
    return out

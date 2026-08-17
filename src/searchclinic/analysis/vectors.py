"""임베딩 기반 토큰 유사도 — 자모 거리가 못 넘는 경계를 위한 두 번째 자.

자모 편집 거리는 **형태**만 본다. 그래서 두 곳에서 막힌다:

    블루투스 ↔ bluetooth   유사도 0.00  (문자 체계가 다르면 자모가 겹치지 않는다)
    핸드폰   ↔ 휴대폰      유사도 0.63  (임계값 0.65 아래 — 형태가 다른 같은 뜻)

임베딩은 이 둘을 의미로 잇는다. 그러나 **모든 것을 잇지는 않는다** — 그
경계가 어디인지가 이 모듈을 넣은 진짜 이유다. `아답터`가 사전 등록을
선행해야 한다는 것은 유사도 문제가 아니라 **절차 문제**라서, 벡터를
아무리 잘 뽑아도 나오지 않는다.

## 백엔드가 둘인 이유

의사 엔진이 scripted/claude로 갈리는 것과 같은 구조다.

- `SentenceTransformerBackend` — 실제 모델. 임의의 단어를 벡터로 만든다.
  무겁고(수백 MB) 설치가 필요하다.
- `CachedVectors` — 그 모델로 미리 뽑아 저장소에 커밋해 둔 벡터.
  모델 없이도 **같은 수치가 재현**되고, CI가 오프라인으로 돈다.

캐시는 손으로 만든 값이 아니라 `clinic build-vectors`가 실제 모델로
생성한 것이다. 재현 절차가 저장소 안에 있어야 숫자를 믿을 수 있다.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Protocol, runtime_checkable

# 이 값 이상이면 "의미가 같다"고 본다. 자모 임계값(0.65)과 달리 벡터
# 유사도는 분포가 다르므로 따로 실측해 정한다 (docs/EVALUATION.md).
VECTOR_THRESHOLD = 0.60

DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / "vectors.json"


@runtime_checkable
class EmbeddingBackend(Protocol):
    """텍스트 목록을 벡터 목록으로. 두 백엔드가 이 하나를 구현한다."""

    def embed(self, texts: list[str]) -> list[list[float]]: ...


def cosine(a: list[float], b: list[float]) -> float:
    """코사인 유사도. 정규화되지 않은 벡터도 받도록 분모를 직접 계산한다."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


class CachedVectors:
    """미리 뽑아 저장소에 커밋한 벡터. 모델 없이 같은 수치를 재현한다.

    모르는 단어는 **조용히 0을 주지 않고 없다고 답한다.** 캐시에 없는
    단어를 0.0으로 처리하면 "의미가 멀다"와 "모른다"가 구분되지 않고,
    그 구분이 사라지면 측정 결과를 해석할 수 없다.
    """

    def __init__(self, vectors: dict[str, list[float]], model: str = "") -> None:
        self._vectors = vectors
        self.model = model

    @classmethod
    def load(cls, path: Path | str = CACHE_PATH) -> "CachedVectors":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(payload["vectors"], payload.get("model", ""))

    @classmethod
    def build(cls, backend: EmbeddingBackend, tokens: list[str], model: str = "") -> "CachedVectors":
        uniq = sorted(set(tokens))
        vecs = backend.embed(uniq)
        return cls({t: v for t, v in zip(uniq, vecs)}, model)

    def save(self, path: Path | str = CACHE_PATH, decimals: int = 5) -> None:
        """소수점을 잘라 저장한다 — 5자리면 코사인 유사도가 소수 4자리까지 같다."""
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "model": self.model,
            "dim": len(next(iter(self._vectors.values()))) if self._vectors else 0,
            "vectors": {
                t: [round(x, decimals) for x in v] for t, v in sorted(self._vectors.items())
            },
        }
        Path(path).write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
        )

    def __contains__(self, token: str) -> bool:
        return token in self._vectors

    def __len__(self) -> int:
        return len(self._vectors)

    def get(self, token: str) -> list[float] | None:
        return self._vectors.get(token)

    def similarity(self, a: str, b: str) -> float | None:
        """둘 다 아는 단어일 때만 유사도. 하나라도 모르면 None."""
        va, vb = self.get(a), self.get(b)
        if va is None or vb is None:
            return None
        return cosine(va, vb)

    def most_similar(self, term: str, candidates: list[str], k: int = 8) -> list[tuple[str, float]]:
        scored = [
            (tok, sim)
            for tok in candidates
            if tok != term and (sim := self.similarity(term, tok)) is not None
        ]
        scored.sort(key=lambda x: (-x[1], x[0]))
        return scored[: max(1, k)]


class SentenceTransformerBackend:
    """실제 임베딩 모델. 캐시를 생성할 때만 필요하다 (선택 의존성)."""

    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        # torch를 먼저 직접 확인한다. sentence-transformers만 깔리고 torch가
        # 없으면 라이브러리 안쪽에서 `NameError: name 'torch' is not defined`
        # 같은 날것의 오류가 튀어나오는데, 그 메시지로는 무엇을 해야 할지
        # 알 수 없다 (실측으로 확인된 실패).
        try:
            import torch  # noqa: F401  # 존재 확인이 목적이라 쓰지 않는다
        except Exception as e:  # pragma: no cover - 설치 환경에 따라 갈림
            raise RuntimeError(
                f"PyTorch를 불러올 수 없습니다 ({type(e).__name__}: {e}).\n"
                "  일반 환경:  pip install torch\n"
                "  인텔 맥:    pip install 'torch<=2.2.2'  "
                "(PyTorch가 macOS x86_64 빌드를 2.2.2에서 중단했습니다)\n"
                "설치가 계속 막히면 다른 기계에서 캐시를 만들어 커밋해도 됩니다 — "
                "캐시만 있으면 --engine vector는 torch 없이 돕니다."
            ) from e

        try:
            from sentence_transformers import SentenceTransformer
        except Exception as e:  # pragma: no cover - 설치 환경에 따라 갈림
            raise RuntimeError(
                f"sentence-transformers를 불러올 수 없습니다 ({type(e).__name__}: {e}).\n"
                '  pip install -e ".[vector]"'
            ) from e

        self.model_name = model_name
        try:
            self._model = SentenceTransformer(model_name)
        except Exception as e:  # pragma: no cover - 네트워크·디스크에 따라 갈림
            raise RuntimeError(
                f"모델 '{model_name}'을 준비하지 못했습니다 ({type(e).__name__}: {e}).\n"
                "처음 실행이면 HuggingFace에서 내려받습니다 — 네트워크가 막혀 있으면 "
                "다른 기계에서 캐시를 만들어 커밋하세요."
            ) from e

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [list(map(float, v)) for v in self._model.encode(texts, show_progress_bar=False)]


def load_vectors_if_available(path: Path | str = CACHE_PATH) -> CachedVectors | None:
    """캐시가 있으면 싣고, 없으면 None.

    없을 때 예외를 던지지 않는 이유: 벡터 없이 도는 것이 이 프로젝트의
    기본 상태이고, 벡터는 **더한 자**이지 필수품이 아니다. 다만 벡터
    의사를 명시적으로 부른 경우에는 CLI가 캐시 부재를 알려야 한다.
    """
    p = Path(path)
    if not p.exists():
        return None
    return CachedVectors.load(p)

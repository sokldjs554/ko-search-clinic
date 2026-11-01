"""Strict public input contract; final labels live only in the evaluator."""
import json
import subprocess
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from searchclinic.research.models import PolicyObservation
from searchclinic.research.splits import digest

ROOT = Path(__file__).resolve().parents[4]
PROTOCOL_PATH = 'artifacts/research/phase2/protocol.json'
PROTOCOL_COMMIT = '921ce4b381a4848ee6f897bf297a0233589644eb'


def load_protocol():
    current = json.loads((ROOT / PROTOCOL_PATH).read_text(encoding='utf-8'))
    frozen = json.loads(subprocess.check_output(
        ['git', 'show', f'{PROTOCOL_COMMIT}:{PROTOCOL_PATH}'], cwd=ROOT, text=True))
    if current != frozen:
        raise ValueError('Phase 2 protocol differs from pre-outcome freeze')
    return current


def source_provenance():
    files = {p.relative_to(ROOT).as_posix(): p.read_text(encoding='utf-8')
             for p in sorted((ROOT / 'src').rglob('*.py'))}
    def git(*args):
        return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()
    return {'source_sha': git('rev-parse', 'HEAD'), 'source_hash': digest(files),
            'source_dirty': bool(git('status','--porcelain','--','src','tests')),
            'protocol_commit': PROTOCOL_COMMIT, 'protocol_hash': digest(load_protocol())}


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)


class PublicDocument(Strict):
    doc_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    tokens: list[str]


class SimilarToken(Strict):
    token: str = Field(min_length=1)
    similarity: float = Field(ge=0, le=1)


class Context(Strict):
    query_id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    observation: PolicyObservation
    query_tokens: list[str]
    search_total: int = Field(ge=0, le=10)
    grep_total: int = Field(ge=0)
    similar: list[SimilarToken] = Field(max_length=10)
    documents: list[PublicDocument] = Field(max_length=10)
    max_candidates: int = Field(default=3, ge=3, le=3)

    @model_validator(mode='after')
    def matching_observation(self):
        if (self.query != self.observation.query or self.query_id != self.observation.query_id
                or self.search_total != self.observation.result_count):
            raise ValueError('observation/target mismatch')
        if len({d.doc_id for d in self.documents}) != len(self.documents):
            raise ValueError('duplicate evidence document')
        return self

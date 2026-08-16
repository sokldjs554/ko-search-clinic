"""이식성 계약 — 리눅스에서만 돌려보면 못 잡는 것들.

실측 실패: 한국어 Windows에서 `pytest`가 깨졌다.

    UnicodeDecodeError: 'cp949' codec can't decode byte 0xe2

파이썬의 `open()`·`Path.read_text()`는 encoding을 생략하면 **OS locale 기본값**을
쓴다. 리눅스는 UTF-8이라 아무 일도 없지만, 한국어 Windows는 cp949라 한글이나
`✅` 같은 문자가 든 파일을 읽는 순간 터진다. CI가 리눅스에서만 돌면 이 부류의
버그는 사용자 PC에서 처음 발견된다 — 실제로 그렇게 발견됐다.

그래서 "고쳤다"로 끝내지 않고 **소스 전체에 대한 계약**으로 못 박는다.
"""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIRS = ("src", "tests")

# 텍스트 파일을 여는 호출들. urlopen·read_bytes처럼 인코딩 개념이 없는 것은
# 애초에 이름이 다르므로 목록에 넣지 않는 것으로 걸러진다.
_TEXT_OPENERS = {"open", "read_text", "write_text"}


def _python_files() -> list[Path]:
    return sorted(
        p
        for d in SOURCE_DIRS
        for p in (ROOT / d).rglob("*.py")
        if "__pycache__" not in p.parts
    )


def _called_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _is_binary_mode(node: ast.Call) -> bool:
    """open(path, "rb") 처럼 바이너리로 열면 encoding을 줄 수 없다(주면 오류)."""
    args = list(node.args[1:2]) + [
        kw.value for kw in node.keywords if kw.arg == "mode"
    ]
    return any(
        isinstance(a, ast.Constant) and isinstance(a.value, str) and "b" in a.value
        for a in args
    )


def find_unencoded_opens(source: str, label: str = "<source>") -> list[str]:
    """encoding 없이 텍스트 파일을 여는 호출을 찾는다.

    AST로 **실제 호출만** 본다. 정규식으로 훑으면 주석과 docstring의
    산문("`open()`은 ...")까지 걸려 경고가 무의미해진다 — 실제로 이 파일이
    자기 docstring에 걸렸다.
    """
    offenders: list[str] = []
    for node in ast.walk(ast.parse(source, filename=label)):
        if not isinstance(node, ast.Call):
            continue
        name = _called_name(node)
        if name not in _TEXT_OPENERS or _is_binary_mode(node):
            continue
        if any(kw.arg == "encoding" for kw in node.keywords):
            continue
        offenders.append(f"{label}:{node.lineno}: {name}(...) — encoding 없음")
    return offenders


def test_the_checker_actually_catches_violations():
    """검사기 자체의 검증 — 아무것도 못 잡는 린트는 통과해도 쓸모가 없다."""
    assert find_unencoded_opens('open("a.txt")')
    assert find_unencoded_opens('Path("a.txt").read_text()')
    assert find_unencoded_opens('p.write_text(md)')

    # 걸리면 안 되는 것들
    assert not find_unencoded_opens('open("a.txt", encoding="utf-8")')
    assert not find_unencoded_opens('open("a.bin", "rb")')
    assert not find_unencoded_opens('open("a.bin", mode="wb")')
    assert not find_unencoded_opens('urllib.request.urlopen(req)')
    assert not find_unencoded_opens('Path("a.bin").read_bytes()')
    assert not find_unencoded_opens('"open() 없이 쓰면 안 된다"  # 산문은 무시')


def test_every_file_open_declares_encoding():
    """소스 전체: 텍스트 파일을 여는 모든 호출은 encoding을 명시해야 한다."""
    offenders = [
        line
        for path in _python_files()
        for line in find_unencoded_opens(
            path.read_text(encoding="utf-8"), str(path.relative_to(ROOT))
        )
    ]
    assert not offenders, (
        "encoding 없이 텍스트 파일을 엽니다 — 한국어 Windows(cp949)에서 깨집니다:\n  "
        + "\n  ".join(offenders)
    )


def test_cli_forces_utf8_stdout():
    """CLI는 표준 출력을 UTF-8로 고정한다.

    `clinic heal > report.md`처럼 출력을 리다이렉트하면 파이썬이 locale
    기본값으로 인코딩하는데, 리포트에는 `✅`·`→`가 들어 있어 cp949에서
    UnicodeEncodeError가 난다.
    """
    from searchclinic.cli import _force_utf8_output

    seen = []

    class FakeStream:
        def reconfigure(self, **kw):
            seen.append(kw)

    import searchclinic.cli as cli

    orig = (cli.sys.stdout, cli.sys.stderr)
    cli.sys.stdout, cli.sys.stderr = FakeStream(), FakeStream()
    try:
        _force_utf8_output()
    finally:
        cli.sys.stdout, cli.sys.stderr = orig

    assert seen == [{"encoding": "utf-8"}, {"encoding": "utf-8"}]


def test_force_utf8_survives_streams_that_cannot_reconfigure():
    """재설정할 수 없는 스트림(파이프 종료, 캡처된 스트림)에서도 죽지 않는다."""
    from searchclinic.cli import _force_utf8_output

    class Broken:
        def reconfigure(self, **kw):
            raise ValueError("closed")

    class NoReconfigure:
        pass

    import searchclinic.cli as cli

    orig = (cli.sys.stdout, cli.sys.stderr)
    cli.sys.stdout, cli.sys.stderr = Broken(), NoReconfigure()
    try:
        _force_utf8_output()  # 예외가 새어 나오면 실패
    finally:
        cli.sys.stdout, cli.sys.stderr = orig


@pytest.mark.parametrize("rel", ["docker/docker-compose.yml", "docker/Dockerfile"])
def test_docker_files_have_no_crlf(rel: str):
    """Dockerfile에 CRLF가 섞이면 RUN 명령 끝에 \\r이 붙어 컨테이너 안에서 깨진다.

    Windows용 Git은 기본값(core.autocrlf=true)으로 체크아웃 때 LF를 CRLF로
    바꾼다. `.gitattributes`의 `eol=lf`가 그것을 막는데, 그 설정이 실제로
    적용되고 있는지는 이렇게 파일을 직접 열어봐야 알 수 있다.
    """
    raw = (ROOT / rel).read_bytes()
    assert b"\r\n" not in raw, (
        f"{rel}에 CRLF 줄바꿈이 있습니다. .gitattributes가 적용되지 않은 "
        f"체크아웃입니다 — 아래로 정규화하세요:\n"
        f"  git add --renormalize .\n"
        f"  git checkout -- ."
    )


def test_gitattributes_pins_line_endings():
    """.gitattributes가 있어야 위 검사가 Windows에서 의미를 갖는다."""
    text = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert "eol=lf" in text

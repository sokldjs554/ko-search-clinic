# 벡터 캐시

`vectors.json`은 `clinic build-vectors`가 실제 임베딩 모델로 생성한
색인 어휘·평가셋 질의의 벡터다. 손으로 만든 값이 아니다.

이 파일이 커밋돼 있으면 `--engine vector`가 **모델 없이도 같은 수치를
재현**한다. 없으면 벡터 의사는 자모 규칙만 쓰는 상태로 떨어지고,
CLI가 그 사실을 알려준다.

재생성:

    pip install -e ".[vector]"
    clinic build-vectors

모델을 바꾸면 수치가 달라지므로, 캐시 파일에 사용한 모델 이름이
함께 저장된다.

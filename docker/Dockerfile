# analysis-nori는 Elasticsearch 기본 배포에 포함되지 않는 플러그인이라
# 이미지에 미리 구워 둔다. 컨테이너가 뜰 때마다 설치하면 네트워크에
# 의존하게 되고, 검증이 인터넷 상태에 좌우된다.
FROM docker.elastic.co/elasticsearch/elasticsearch:8.15.0

RUN bin/elasticsearch-plugin install --batch analysis-nori

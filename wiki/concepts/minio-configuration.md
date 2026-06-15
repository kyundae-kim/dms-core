---
title: MinIO configuration
created: 2026-06-15
updated: 2026-06-15
type: concept
tags: [minio, object-storage, storage, configuration]
sources: [raw/articles/docmesh-py-core-config-v0-1-1.md]
confidence: medium
---

# MinIO configuration

`docmesh-py-core`는 MinIO 연결에 대해 endpoint, access key, secret key를 필수 축으로 두고, HTTPS 사용 여부와 region, bucket, retry/timeout 정책을 별도 환경변수로 관리한다. 이는 문서 바이트 저장소를 서비스 코드와 분리된 인프라 설정으로 유지하려는 모델이다.

## 핵심 환경변수
- `MINIO_ENDPOINT`
- `MINIO_ACCESS_KEY`
- `MINIO_SECRET_KEY`
- `MINIO_SECURE`
- `MINIO_REGION`
- `MINIO_BUCKET`
- `MINIO_REQUEST_TIMEOUT_SECONDS`
- `MINIO_MAX_RETRIES`

## 운영 규칙
- endpoint는 `host:port` 형식을 권장한다.
- secret key는 로그/예외/디버그 출력에 포함하지 않는다.
- health check는 bucket 존재 확인 또는 서버 응답 확인으로 구현할 수 있다.

## 문서 서비스 관점
문서 본문 파일을 Object Storage에 저장하는 서비스에서는 MinIO 연결 규칙이 업로드/다운로드/삭제 API의 실제 가용성을 좌우한다. SDK는 이 연결 정보를 환경변수로만 주입받도록 설계되어 있으므로, 배포 환경별 bucket/endpoint 교체도 코드 수정 없이 처리 가능하다.

## 관련 페이지
- [[configuration-loading-and-validation]]
- [[service-health-checking]]
- [[docmesh-py-core]]
- [[postgres-configuration]]

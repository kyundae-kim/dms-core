---
title: MinIO configuration
created: 2026-06-15
updated: 2026-07-21
type: concept
tags: [minio, object-storage, storage, configuration]
sources: [raw/articles/docmesh-py-core-config-v0-1-1.md, raw/articles/docmesh-py-core-configuration-v0-4-0.md]
confidence: medium
---

# MinIO configuration

`docmesh-py-core`는 MinIO 연결에 대해 endpoint, access key, secret key를 필수 축으로 두고, HTTPS 사용 여부·인증서 검증·region·bucket·retry/timeout 정책을 별도 환경변수로 관리한다. v0.5.0 Configuration Guide는 `MINIO_BUCKET`을 application이 `require_minio_bucket()`으로 선택적으로 요구하는 값으로 정의하고, production에서는 `MINIO_SECURE`와 `MINIO_CERT_CHECK`가 모두 true여야 한다고 명시한다.^[raw/articles/docmesh-py-core-configuration-v0-4-0.md]

## 핵심 환경변수
- `MINIO_ENDPOINT`
- `MINIO_ACCESS_KEY`
- `MINIO_SECRET_KEY`
- `MINIO_SECURE`
- `MINIO_CERT_CHECK`
- `MINIO_REGION`
- `MINIO_BUCKET`
- `MINIO_REQUEST_TIMEOUT_SECONDS`
- `MINIO_MAX_RETRIES`

## 운영 규칙
- endpoint는 `host:port` 형식을 권장한다.
- secret key는 로그/예외/디버그 출력에 포함하지 않는다.
- 현재 기본 health check는 `list_buckets()`다.
- 운영 환경에서는 `MINIO_SECURE=false` 또는 `MINIO_CERT_CHECK=false`를 허용하지 않으며, endpoint placeholder도 설정 진단에서 거부한다.^[raw/articles/docmesh-py-core-configuration-v0-4-0.md]

## 문서 서비스 관점
문서 본문 파일을 Object Storage에 저장하는 서비스에서는 MinIO 연결 규칙이 업로드/다운로드/삭제 API의 실제 가용성을 좌우한다. SDK는 이 연결 정보를 환경변수로만 주입받도록 설계되어 있으므로, 배포 환경별 bucket/endpoint 교체도 코드 수정 없이 처리 가능하다. runtime default로 보존되는 값은 소비자가 별도 resource/retry 정책에 활용할 수 있으나, SDK 생성자에 직접 전달되는 값과 같은 방식으로 해석해서는 안 된다.^[raw/articles/docmesh-py-core-config-v0-1-1.md]

## 관련 페이지
- [[configuration-loading-and-validation]]
- [[service-health-checking]]
- [[docmesh-py-core]]
- [[postgres-configuration]]
- [[service-runtime-assembly]]

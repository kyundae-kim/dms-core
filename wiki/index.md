# Wiki Index

> Content catalog. Every wiki page listed under its type with a one-line summary.
> Read this first to find relevant pages for any query.
> Last updated: 2026-06-15 | Total pages: 17

## Entities
<!-- Alphabetical within section -->

- [[dms-sdk]] - MinIO 원문 저장과 PostgreSQL 메타데이터 관리를 SDK 계약으로 제공하는 DMS 패키지.
- [[docmesh-py-core]] - 여러 인프라 서비스 통합, 설정 로딩, 헬스체크, 인증 보조를 제공하는 Python SDK 코어 패키지.

## Concepts

- [[configuration-loading-and-validation]] - 환경변수 기반 설정 로딩, 검증, 운영 분리 원칙.
- [[document-lifecycle-and-consistency]] - 업로드/삭제 시 object storage와 metadata store 사이의 일관성 정책.
- [[document-metadata-model]] - 문서 메타데이터 최소 필드, 상태 모델, 인덱스/삭제 시사점.
- [[fastapi-lifespan-integration]] - FastAPI lifespan에서 SDK 초기화와 정리를 수행하는 통합 패턴.
- [[keycloak-auth-service]] - Keycloak 토큰 발급과 JWT 검증을 담당하는 인증 통합 계층.
- [[minio-configuration]] - MinIO endpoint, credential, retry/timeout 규칙과 저장소 운영 관점.
- [[nats-connection-builder]] - NATS 연결을 비동기적으로 생성/점검하는 builder 모델.
- [[postgres-configuration]] - PostgreSQL DSN 우선 모델과 metadata 저장소 연결 규칙.
- [[sdk-consumption-patterns]] - 소비 프로젝트에서 권장되는 SDK 부트스트랩/lifecycle 패턴.
- [[sdk-exception-model]] - 설정/검증/스토리지/일관성/헬스체크 오류를 구분하는 SDK 예외 계층 초안.
- [[sdk-factory-assembly]] - `create_sdk(env)`를 통해 설정과 저장소 구현체를 조립하는 팩토리 패턴.
- [[sdk-public-interface]] - 문서 업로드/조회/삭제/헬스체크를 노출하는 최소 SDK 계약.
- [[service-factory-registry]] - 서비스 이름별 클라이언트 생성 규칙을 캡슐화한 팩토리.
- [[service-health-checking]] - 개별/집계형 의존성 헬스체크 규약과 운영 시사점.
- [[storage-backend-selection]] - 환경변수 존재 여부 기반의 PostgreSQL/SQLite 저장소 선택 패턴.

## Comparisons

## Queries

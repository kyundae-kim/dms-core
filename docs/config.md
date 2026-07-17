# 설정 정의서

## 설정 방식

SDK는 `create_sdk_from_environment(env)` 환경 기반 조립과 `create_sdk_from_components(...)` 명시적 구성요소 조립을 지원합니다. 환경 설정은 `diagnose_environment(env)`로 외부 서비스 연결 없이 사전 진단할 수 있습니다.

## 문서 정보 저장소

`DMS_METADATA_BACKEND`는 `postgresql` 또는 `sqlite`를 지정할 수 있습니다.

- PostgreSQL: `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`
- SQLite: `SQLITE_PATH`

명시적 선택이 없으면 PostgreSQL 설정을 우선하고, 그다음 SQLite 설정을 사용합니다. 두 설정이 함께 있고 `DMS_CONFIGURATION_STRICT=true`이면 모호한 설정으로 거부합니다.

## 문서 본문 저장소

MinIO 조립에는 다음 값이 필요합니다.

- `MINIO_ENDPOINT`
- `MINIO_ACCESS_KEY`
- `MINIO_SECRET_KEY`
- `MINIO_BUCKET`

실제 값과 비밀정보를 문서나 로그에 출력하지 마십시오.

## 시작 상태 확인

`DOCMESH_HEALTHCHECK_ENABLED`는 기본적으로 활성화됩니다. `0`, `false`, `no`, `off` 중 하나로 설정하면 시작 시 상태 확인을 비활성화합니다. 운영 환경에서는 실제 서비스 값을 설정한 뒤 상태 확인을 활성화하는 것을 권장합니다.

## 메타데이터 정책

factory의 `metadata_max_serialized_bytes`와 `metadata_max_depth`로 기본 부가 정보 제한을 조정할 수 있습니다. 업무 스키마가 필요하면 `metadata_validator`를 주입합니다. 자세한 계약은 `docs/api.md`를 참고하십시오.

# Document Management Service

사용자 문서를 Object Storage(MinIO)에 저장/조회/삭제 하고 문서 연관 metadata를 RDB(Postgres)에 저장/관리하는 서비스

## Integration tests

실제 PostgreSQL + MinIO integration test는 외부에 이미 준비된 서비스를 사용합니다.
테스트가 docker compose를 생성하거나 실행하지 않습니다.

필수 환경변수:
- `POSTGRES_DSN`
- `MINIO_ENDPOINT`
- `MINIO_ACCESS_KEY`
- `MINIO_SECRET_KEY`
- `MINIO_BUCKET`

실행:

`uv run pytest test_dms/test_integration_adapters.py -q`

기존 환경변수를 그대로 재사용하며, 별도의 `DMS_TEST_*` 변수는 사용하지 않습니다.
환경변수가 없으면 integration test는 skip 됩니다.

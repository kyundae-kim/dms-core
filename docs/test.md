# 테스트 정의

## 메타데이터 및 복구 공개 계약

- `test_sdk_metadata.py`는 공개 메타데이터 projection에서 `storage_key`가 제외되고 입력 부가 정보가 복사되는지 검증한다.
- 구조화 validator의 schema-version 오류와 field-level issue 보존, 기존 `metadata_validator` callable 호환성을 검증한다.
- `test_sdk_reconciliation.py`는 dry-run 결과의 계획 export, 실행 직전 재점검에 따른 stale 계획 거부, 정상 계획 적용을 검증한다.
- 모든 복구 시도의 구조화 감사 이벤트와 callback 실패의 best-effort 격리를 검증한다.

집중 실행: `uv run pytest -q test_dms/test_sdk_metadata.py test_dms/test_sdk_reconciliation.py`
전체 실행: `uv run pytest -q`

# Wiki Log

> Chronological record of all wiki actions. Append-only.
> Format: `## [YYYY-MM-DD] action | subject`
> Actions: ingest, update, query, lint, create, archive, delete
> When this file exceeds 500 entries, rotate: rename to log-YYYY.md, start fresh.

## [2026-06-15] create | Wiki initialized
- Domain: 사용자 문서를 Object Storage(MinIO)에 저장/조회/삭제하고 문서 연관 metadata를 PostgreSQL에 저장/관리하며 서비스와 SDK를 함께 배포하는 시스템
- Structure created with SCHEMA.md, index.md, log.md

## [2026-06-15] ingest | docmesh-py-core API
- Source: https://github.com/kyundae-kim/docmesh-py-core/blob/v0.1.1/docs/api.md
- Created: raw/articles/docmesh-py-core-api-v0-1-1.md
- Created: entities/docmesh-py-core.md
- Created: concepts/keycloak-auth-service.md
- Created: concepts/nats-connection-builder.md
- Created: concepts/service-factory-registry.md
- Created: concepts/service-health-checking.md
- Updated: index.md

## [2026-06-15] ingest | docmesh-py-core config
- Source: https://github.com/kyundae-kim/docmesh-py-core/blob/v0.1.1/docs/config.md
- Created: raw/articles/docmesh-py-core-config-v0-1-1.md
- Created: concepts/configuration-loading-and-validation.md
- Created: concepts/postgres-configuration.md
- Created: concepts/minio-configuration.md
- Updated: entities/docmesh-py-core.md
- Updated: concepts/keycloak-auth-service.md
- Updated: concepts/service-health-checking.md
- Updated: index.md

## [2026-06-15] ingest | docmesh-py-core sdk
- Source: https://github.com/kyundae-kim/docmesh-py-core/blob/v0.1.1/docs/sdk.md
- Created: raw/articles/docmesh-py-core-sdk-v0-1-1.md
- Created: concepts/sdk-consumption-patterns.md
- Created: concepts/storage-backend-selection.md
- Created: concepts/fastapi-lifespan-integration.md
- Updated: entities/docmesh-py-core.md
- Updated: concepts/service-factory-registry.md
- Updated: concepts/nats-connection-builder.md
- Updated: concepts/configuration-loading-and-validation.md
- Updated: index.md

## [2026-06-15] ingest | dms SRS
- Source: file:///workspaces/dms-core/docs/SRS.md
- Created: raw/articles/dms-srs-2026-06-15.md
- Created: entities/dms-sdk.md
- Created: concepts/document-metadata-model.md
- Created: concepts/document-lifecycle-and-consistency.md
- Created: concepts/sdk-public-interface.md
- Updated: concepts/sdk-consumption-patterns.md
- Updated: concepts/service-health-checking.md
- Updated: concepts/storage-backend-selection.md
- Updated: index.md

## [2026-06-15] ingest | dms SDK interface
- Source: file:///workspaces/dms-core/docs/SDK_INTERFACE.md
- Created: raw/articles/dms-sdk-interface-2026-06-15.md
- Created: concepts/sdk-exception-model.md
- Created: concepts/sdk-factory-assembly.md
- Updated: concepts/sdk-public-interface.md
- Updated: concepts/document-metadata-model.md
- Updated: index.md

## [2026-06-16] ingest | dms SDK interface
- Source: file:///workspaces/dms-core/docs/SDK_INTERFACE.md
- Updated: raw/articles/dms-sdk-interface-2026-06-15.md
- Updated: entities/dms-sdk.md
- Updated: concepts/sdk-public-interface.md
- Updated: concepts/sdk-factory-assembly.md
- Updated: concepts/document-metadata-model.md
- Updated: concepts/document-lifecycle-and-consistency.md
- Updated: concepts/service-health-checking.md
- Updated: index.md

## [2026-06-16] query | requirements vs implementation
- Query: 요구사항에 대해서 찾고 현재 개발된 내용과 비교
- Created: queries/requirements-vs-implementation-2026-06-16.md
- Updated: index.md

## [2026-06-16] update | sdk public api alignment
- Updated: concepts/sdk-public-interface.md
- Updated: queries/requirements-vs-implementation-2026-06-16.md
- Implemented: `dms.sdk.DocumentMetadata` export
- Implemented: `create_sdk(env)` public entrypoint with `create_sdk_from_environment(env)` compatibility alias

## [2026-06-16] update | sdk auth helper alignment
- Updated: concepts/sdk-public-interface.md
- Updated: concepts/sdk-exception-model.md
- Updated: queries/requirements-vs-implementation-2026-06-16.md
- Updated: README.md
- Updated: docs/SDK_INTERFACE.md
- Implemented: optional `DMS_AUTH_ENABLED=true` Keycloak wiring for `fetch_access_token(...)` and `get_authenticated_user(...)`
- Implemented: `AuthenticationError` mapping for token acquisition and validation failures

## [2026-06-16] update | sdk logging diagnostics alignment
- Updated: concepts/sdk-public-interface.md
- Updated: queries/requirements-vs-implementation-2026-06-16.md
- Updated: README.md
- Updated: docs/SDK_INTERFACE.md
- Implemented: optional `logger` injection for SDK factory and implementation
- Implemented: structured diagnostic log fields (`dms_event`, `dms_document_id`, `dms_storage_key`, `dms_duration_ms`, `dms_error_type`)

## [2026-06-16] update | sdk streaming download alignment
- Updated: concepts/sdk-public-interface.md
- Updated: queries/requirements-vs-implementation-2026-06-16.md
- Updated: README.md
- Updated: docs/SDK_INTERFACE.md
- Implemented: `get_document_content_stream(document_id, *, chunk_size=65536)` on the SDK surface
- Implemented: MinIO stream download path and chunked stream tests

## [2026-06-16] update | requirements vs implementation refresh
- Updated: queries/requirements-vs-implementation-2026-06-16.md
- Verified: `uv run pytest -q` -> `40 passed, 1 warning in 1.04s`
- Refined gaps: partial-failure state persistence, runtime dependency declaration, secret redaction verification

## [2026-06-16] update | delete partial-failure status alignment
- Updated: dms/sdk/implementation.py
- Updated: test_dms/test_sdk_behavior.py
- Updated: README.md
- Updated: docs/SDK_INTERFACE.md
- Updated: concepts/document-lifecycle-and-consistency.md
- Updated: concepts/document-metadata-model.md
- Updated: concepts/sdk-public-interface.md
- Updated: queries/requirements-vs-implementation-2026-06-16.md
- Implemented: delete 시작 시 metadata `deleting` persistence
- Implemented: object delete failure 시 metadata `failed` persistence
- Verified: `uv run pytest test_dms/test_sdk_behavior.py -q` -> `28 passed, 1 warning in 0.77s`
- Verified: `uv run pytest -q` -> `43 passed, 1 warning in 1.04s`

## [2026-06-18] ingest | dms SRS
- Source: file:///workspaces/dms-core/docs/SRS.md
- Updated: raw/articles/dms-srs-2026-06-15.md
- Updated: entities/dms-sdk.md
- Updated: concepts/sdk-public-interface.md
- Updated: concepts/document-metadata-model.md
- Updated: concepts/document-lifecycle-and-consistency.md
- Updated: concepts/sdk-consumption-patterns.md
- Updated: queries/requirements-vs-implementation-2026-06-16.md
- Updated: index.md

## [2026-06-18] ingest | dms SDK interface
- Source: file:///workspaces/dms-core/docs/SDK_INTERFACE.md
- Updated: raw/articles/dms-sdk-interface-2026-06-15.md
- Updated: entities/dms-sdk.md
- Updated: concepts/sdk-public-interface.md
- Updated: concepts/sdk-exception-model.md
- Updated: concepts/sdk-factory-assembly.md
- Updated: concepts/document-metadata-model.md
- Updated: concepts/document-lifecycle-and-consistency.md
- Updated: queries/requirements-vs-implementation-2026-06-16.md

## [2026-06-18] lint | 8 issues found
- Broken links: 0
- Orphans: 1 (`queries/requirements-vs-implementation-2026-06-16.md`)
- Index missing pages: 0
- Frontmatter issues: 0
- Tag taxonomy issues: 4 (`configuration` used but not declared in SCHEMA.md taxonomy)
- Source drift: 3 (`raw/articles/docmesh-py-core-api-v0-1-1.md`, `raw/articles/docmesh-py-core-config-v0-1-1.md`, `raw/articles/docmesh-py-core-sdk-v0-1-1.md`)
- Page size issues: 0
- Log rotation needed: no

## [2026-07-03] ingest | docmesh-py-core API
- Source: https://github.com/kyundae-kim/docmesh-py-core/blob/v0.1.4/docs/api.md
- Updated: raw/articles/docmesh-py-core-api-v0-1-1.md
- Updated: entities/docmesh-py-core.md
- Updated: concepts/keycloak-auth-service.md
- Updated: concepts/nats-connection-builder.md
- Updated: concepts/service-factory-registry.md
- Updated: concepts/service-health-checking.md
- Updated: index.md

## [2026-07-03] ingest | docmesh-py-core config
- Source: https://github.com/kyundae-kim/docmesh-py-core/blob/v0.1.4/docs/config.md
- Updated: raw/articles/docmesh-py-core-config-v0-1-1.md
- Updated: entities/docmesh-py-core.md
- Updated: concepts/configuration-loading-and-validation.md
- Updated: concepts/minio-configuration.md
- Updated: concepts/postgres-configuration.md
- Updated: concepts/keycloak-auth-service.md
- Updated: concepts/service-health-checking.md

## [2026-07-03] ingest | docmesh-py-core examples
- Source: https://github.com/kyundae-kim/docmesh-py-core/blob/v0.1.4/docs/examples.md
- Created: raw/articles/docmesh-py-core-examples-v0-1-4.md
- Updated: entities/docmesh-py-core.md
- Updated: concepts/sdk-consumption-patterns.md
- Updated: concepts/fastapi-lifespan-integration.md
- Updated: concepts/nats-connection-builder.md
- Updated: concepts/service-health-checking.md
- Updated: concepts/configuration-loading-and-validation.md

## [2026-07-15] ingest | docmesh-py-core API
- Source: https://github.com/kyundae-kim/docmesh-py-core/blob/v0.2.0/docs/api.md
- Updated: raw/articles/docmesh-py-core-api-v0-1-1.md
- Created: concepts/service-runtime-assembly.md
- Updated: entities/docmesh-py-core.md
- Updated: concepts/keycloak-auth-service.md
- Updated: concepts/nats-connection-builder.md
- Updated: concepts/service-factory-registry.md
- Updated: concepts/service-health-checking.md
- Updated: index.md

## [2026-07-15] ingest | docmesh-py-core config
- Source: https://github.com/kyundae-kim/docmesh-py-core/blob/v0.2.0/docs/config.md
- Updated: raw/articles/docmesh-py-core-config-v0-1-1.md
- Updated: entities/docmesh-py-core.md
- Updated: concepts/configuration-loading-and-validation.md
- Updated: concepts/minio-configuration.md
- Updated: concepts/postgres-configuration.md
- Updated: concepts/service-health-checking.md

## [2026-07-15] ingest | docmesh-py-core examples
- Source: https://github.com/kyundae-kim/docmesh-py-core/blob/v0.2.0/docs/examples.md
- Updated: raw/articles/docmesh-py-core-examples-v0-1-4.md
- Updated: concepts/sdk-consumption-patterns.md
- Updated: concepts/fastapi-lifespan-integration.md
- Updated: concepts/nats-connection-builder.md

## [2026-07-15] ingest | docmesh-py-core environment template
- Source: https://github.com/kyundae-kim/docmesh-py-core/blob/v0.2.0/.env.example
- Created: raw/articles/docmesh-py-core-env-example.md
- Updated: concepts/configuration-loading-and-validation.md

## [2026-07-15] lint | 2 issues found
- Orphan: queries/requirements-vs-implementation-2026-06-16.md
- Tag taxonomy: `configuration` is used but not declared in SCHEMA.md

## [2026-07-15] query | docmesh-py-core v0.2.0 코드 수정 사항
- Updated: queries/requirements-vs-implementation-2026-06-16.md
- Verified: `uv run pytest -q` (`36 passed`)
- Finding: direct env 전달로 전역 환경 overlay 제거가 최우선이며, upstream factory 연동 회귀 테스트 보강이 필요함

## [2026-07-15] update | docmesh-py-core factory 회귀 테스트 보강
- Updated: dms/sdk/factory.py
- Updated: test_dms/test_infrastructure_adapters.py
- Updated: queries/requirements-vs-implementation-2026-06-16.md
- Verified: `uv run pytest -q` (`37 passed`)
- Closed: startup health failure 시 생성된 client rollback cleanup 및 close 위임 검증

## [2026-07-15] update | SQLAlchemy runtime dependency 명시
- Updated: pyproject.toml
- Updated: uv.lock
- Updated: queries/requirements-vs-implementation-2026-06-16.md
- Verified: `uv sync --locked`, `uv tree --depth 1`, `uv run pytest -q` (`37 passed`)
- Closed: runtime 코드의 SQLAlchemy 직접 사용과 패키지 dependency 선언 간 불일치

## [2026-07-15] update | ServiceBundle 기반 factory 조립
- Updated: dms/sdk/factory.py
- Updated: test_dms/test_infrastructure_adapters.py
- Updated: test_dms/test_sdk_behavior.py
- Updated: concepts/sdk-factory-assembly.md
- Updated: queries/requirements-vs-implementation-2026-06-16.md
- Verified: `uv run pytest -q` (`38 passed`), compileall, diff check
- Closed: 개별 py-core helper 기반 lifecycle 중복

## [2026-07-17] ingest | docmesh-py-core API
- Source: https://github.com/kyundae-kim/docmesh-py-core/blob/v0.3.0/docs/api.md
- Updated: raw/articles/docmesh-py-core-api-v0-1-1.md
- Created: concepts/runtime-planning-and-environment-diagnosis.md
- Updated: entities/docmesh-py-core.md
- Updated: concepts/service-runtime-assembly.md
- Updated: concepts/service-health-checking.md
- Updated: concepts/keycloak-auth-service.md
- Updated: concepts/postgres-configuration.md
- Updated: index.md
- Key changes: typed runtime planning and environment diagnosis, structured error taxonomy, Keycloak password-grant default, and PostgreSQL DSN deprecation.

## [2026-07-17] ingest | docmesh-py-core config
- Source: https://github.com/kyundae-kim/docmesh-py-core/blob/v0.3.0/docs/config.md
- Updated: raw/articles/docmesh-py-core-config-v0-1-1.md
- Updated: concepts/configuration-loading-and-validation.md
- Updated: concepts/runtime-planning-and-environment-diagnosis.md
- Updated: concepts/keycloak-auth-service.md
- Updated: concepts/postgres-configuration.md
- Key changes: permissive boolean literals, plan-based preflight diagnosis with production placeholder detection, password-grant startup healthcheck constraint, and PostgreSQL DSN removal path.

## [2026-07-17] ingest | docmesh-py-core examples
- Source: https://github.com/kyundae-kim/docmesh-py-core/blob/v0.3.0/docs/examples.md
- Updated: raw/articles/docmesh-py-core-examples-v0-1-4.md
- Updated: concepts/sdk-consumption-patterns.md
- Updated: concepts/fastapi-lifespan-integration.md
- Updated: concepts/nats-connection-builder.md
- Updated: concepts/service-runtime-assembly.md
- Key changes: typed async runtime recipes, PostgreSQL field-based configuration examples, direct-client cleanup recipes, and expanded public API examples.

## [2026-07-19] ingest | docmesh-py-core API Reference v0.4.0
- Source: https://github.com/kyundae-kim/docmesh-py-core/wiki/API-Reference-v0.4.0
- Created: raw/articles/docmesh-py-core-api-reference-v0-4-0.md
- Created: concepts/public-api-contract.md
- Updated: entities/docmesh-py-core.md
- Updated: concepts/service-runtime-assembly.md
- Updated: concepts/runtime-planning-and-environment-diagnosis.md
- Updated: concepts/service-health-checking.md
- Updated: concepts/keycloak-auth-service.md
- Updated: concepts/sdk-consumption-patterns.md
- Updated: index.md
- Key changes: package-root `__all__` public boundary, RuntimePlan-first bootstrap guidance, lifecycle close aggregation, and Keycloak provisioning contract.

## [2026-07-19] ingest | docmesh-py-core Configuration v0.4.0
- Source: https://github.com/kyundae-kim/docmesh-py-core/wiki/Configuration-v0.4.0
- Created: raw/articles/docmesh-py-core-configuration-v0-4-0.md
- Updated: concepts/configuration-loading-and-validation.md
- Updated: concepts/minio-configuration.md
- Updated: concepts/postgres-configuration.md
- Updated: concepts/keycloak-auth-service.md
- Updated: concepts/runtime-planning-and-environment-diagnosis.md
- Updated: entities/docmesh-py-core.md
- Key changes: environment-only config construction, production-mode/placeholder validation, PostgreSQL DSN removal, and Keycloak provisioning admin-auth exclusivity.

## [2026-07-19] ingest | docmesh-py-core Examples v0.4.0
- Source: https://github.com/kyundae-kim/docmesh-py-core/wiki/Examples-v0.4.0
- Created: raw/articles/docmesh-py-core-examples-v0-4-0.md
- Updated: concepts/sdk-consumption-patterns.md
- Updated: concepts/nats-connection-builder.md
- Updated: concepts/service-runtime-assembly.md
- Updated: concepts/service-health-checking.md
- Updated: entities/docmesh-py-core.md
- Key changes: RuntimePlan bootstrap with preflight, NATS connect/drain, direct cleanup, aggregate close failure handling, and runtime preset examples.

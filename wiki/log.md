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

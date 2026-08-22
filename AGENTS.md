
### Environment
- `uv` is already installed and available in the execution environment.  
- Prefer `uv` for all Python package and dependency operations.

### Docker compose
- minio: .devcontainer/docker-compose.minio.yml
- postgres: .devcontainer/docker-compose.postgres.yml

### Documents
- 제품 요구사항 정의서: docs/prd.md.
- 소프트웨어 요구사항 정의: docs/srs.md.

### What to avoid
- lazy import.
- optional dependency.
- sqlalchemy core style.
- access uv.lock.
- kwargs override.
- regression testing for document.
- build python package.

# Wiki Schema

## Domain
문서 파일을 Object Storage(MinIO)에 저장/조회/삭제하고, 문서 연관 메타데이터를 PostgreSQL에 저장/관리하며, 최종적으로 서비스와 SDK를 함께 배포하는 시스템에 대한 지식 베이스.

## Conventions
- File names: lowercase, hyphens, no spaces (e.g., `document-upload-flow.md`)
- Every wiki page starts with YAML frontmatter
- Use `[[wikilinks]]` to link between pages (minimum 2 outbound links per page)
- When updating a page, always bump the `updated` date
- Every new page must be added to `index.md` under the correct section
- Every action must be appended to `log.md`
- On pages synthesizing 3+ sources, append provenance markers like `^[raw/articles/source-file.md]` to paragraphs whose claims come from a specific source
- Use Korean for narrative text unless the source material is best preserved in English

## Frontmatter
```yaml
---
title: Page Title
created: YYYY-MM-DD
updated: YYYY-MM-DD
type: entity | concept | comparison | query | summary
tags: [from taxonomy below]
sources: [raw/articles/source-name.md]
confidence: high | medium | low
contested: true
contradictions: [other-page-slug]
---
```

## Raw Frontmatter
```yaml
---
source_url: https://example.com/article
ingested: YYYY-MM-DD
sha256: <hex digest of the raw content below the frontmatter>
---
```

## Tag Taxonomy
- Core domain: document, storage, metadata, service, sdk
- Infrastructure: minio, postgres, object-storage, database, deployment
- API/workflows: upload, download, delete, lifecycle, versioning
- Architecture: architecture, consistency, schema, eventing, integration
- Quality attributes: security, auth, performance, observability, reliability, testing
- Delivery: packaging, release, client-library, migration, operations

Rule: every tag on a page must appear in this taxonomy. If a new tag is needed, add it here first.

## Page Thresholds
- Create a page when an entity/concept appears in 2+ sources OR is central to one source
- Add to existing page when a source mentions something already covered
- DON'T create a page for passing mentions, incidental implementation details, or items outside this service/SDK scope
- Split a page when it exceeds ~200 lines
- Archive a page when its content is fully superseded — move to `_archive/`, remove from index

## Entity Pages
One page per notable entity. Include:
- What it is and its role in the system
- Key interfaces, constraints, and dates/versions when relevant
- Relationships to other entities via [[wikilinks]]
- Source references

## Concept Pages
One page per architectural or product concept. Include:
- Definition
- Why it matters in this service/SDK
- Trade-offs, failure modes, and open questions
- Related concepts via [[wikilinks]]

## Comparison Pages
Include:
- What is being compared and why
- Comparison dimensions (table preferred)
- Decision or synthesis
- Sources

## Update Policy
When new information conflicts with existing content:
1. Check dates — newer sources generally supersede older ones
2. If genuinely contradictory, note both positions with dates and sources
3. Mark the contradiction in frontmatter: `contradictions: [page-name]`
4. Flag for user review in the lint report

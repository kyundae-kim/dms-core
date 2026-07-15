from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any

from dms.domain.interfaces import PutObjectRequest, PutObjectStreamRequest, StoredObject, StoredObjectStream


class MinioObjectStore:
    def __init__(self, *, client: Any, bucket_name: str) -> None:
        self._client = client
        self._bucket_name = bucket_name

    def put_object(self, request: PutObjectRequest) -> str:
        return self.put_object_stream(PutObjectStreamRequest(
            document_id=request.document_id,
            storage_key=request.storage_key,
            stream=BytesIO(request.content),
            size=len(request.content),
            chunk_size=65536,
            content_type=request.content_type,
            filename=request.filename,
            checksum=request.checksum,
            metadata=request.metadata,
        ))

    def put_object_stream(self, request: PutObjectStreamRequest) -> str:
        metadata = {
            "document_id": request.document_id,
            "filename": request.filename,
        }
        if request.checksum is not None:
            metadata["checksum"] = request.checksum

        self._client.put_object(
            self._bucket_name,
            request.storage_key,
            request.stream,
            request.size,
            content_type=request.content_type,
            metadata=metadata,
        )
        return request.storage_key

    def get_object(self, document_id: str, storage_key: str) -> StoredObject:
        stat = self._client.stat_object(self._bucket_name, storage_key)
        response = self._client.get_object(self._bucket_name, storage_key)
        try:
            content = response.data if hasattr(response, "data") else response.read()
        finally:
            if hasattr(response, "close"):
                response.close()
            if hasattr(response, "release_conn"):
                response.release_conn()

        metadata = getattr(stat, "metadata", {}) or {}
        filename = metadata.get("filename") or metadata.get("X-Amz-Meta-Filename") or Path(storage_key).name
        checksum = metadata.get("checksum") or metadata.get("X-Amz-Meta-Checksum")
        content_type = getattr(response, "headers", {}).get("Content-Type", "application/octet-stream")
        size = getattr(stat, "size", len(content))

        return StoredObject(
            document_id=document_id,
            storage_key=storage_key,
            content=content,
            content_type=content_type,
            filename=filename,
            size=size,
            checksum=checksum,
        )

    def get_object_stream(self, document_id: str, storage_key: str) -> StoredObjectStream:
        stat = self._client.stat_object(self._bucket_name, storage_key)
        response = self._client.get_object(self._bucket_name, storage_key)

        metadata = getattr(stat, "metadata", {}) or {}
        filename = metadata.get("filename") or metadata.get("X-Amz-Meta-Filename") or Path(storage_key).name
        checksum = metadata.get("checksum") or metadata.get("X-Amz-Meta-Checksum")
        content_type = getattr(response, "headers", {}).get("Content-Type", "application/octet-stream")
        size = getattr(stat, "size", None)
        if size is None:
            size = getattr(response, "length", None)
        if size is None:
            raise ValueError(f"Object size is unavailable for stream download: {storage_key}")

        return StoredObjectStream(
            document_id=document_id,
            storage_key=storage_key,
            stream=response,
            content_type=content_type,
            filename=filename,
            size=size,
            checksum=checksum,
        )

    def delete_object(self, document_id: str, storage_key: str) -> None:
        self._client.remove_object(self._bucket_name, storage_key)

    def object_exists(self, document_id: str, storage_key: str) -> bool:
        try:
            self._client.stat_object(self._bucket_name, storage_key)
        except Exception:
            return False
        return True

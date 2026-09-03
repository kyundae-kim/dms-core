from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from io import BytesIO
from pathlib import Path
from typing import Any

from minio import Minio
from minio.error import S3Error

from dms.domain.interfaces import (
    AsyncStoredObjectStream,
    PutObjectRequest,
    PutObjectStreamRequest,
    StoredObject,
    StoredObjectStream,
)
from dms.domain.models import DocumentPartition
from dms.sdk.contracts import partition_storage_prefix


class MinioObjectStore:
    def __init__(self, *, client: Any, bucket_name: str) -> None:
        self._client = client
        self._bucket_name = bucket_name
        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        if self._client.bucket_exists(self._bucket_name):
            return
        try:
            self._client.make_bucket(self._bucket_name)
        except S3Error as exc:
            # Another SDK assembly may create the bucket between the existence
            # check and creation. Only ignore the idempotent same-owner race.
            if exc.code != "BucketAlreadyOwnedByYou":
                raise

    def put_object(self, request: PutObjectRequest) -> str:
        return self.put_object_stream(
            PutObjectStreamRequest(
                document_id=request.document_id,
                storage_key=request.storage_key,
                stream=BytesIO(request.content),
                size=len(request.content),
                chunk_size=65536,
                content_type=request.content_type,
                filename=request.filename,
                checksum=request.checksum,
                metadata=request.metadata,
            )
        )

    def put_object_stream(self, request: PutObjectStreamRequest) -> str:
        metadata = {
            "document_id": request.document_id,
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

        filename, checksum, content_type = self._object_attributes(
            stat, response, storage_key
        )
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

    def get_object_stream(
        self, document_id: str, storage_key: str
    ) -> StoredObjectStream:
        stat = self._client.stat_object(self._bucket_name, storage_key)
        response = self._client.get_object(self._bucket_name, storage_key)

        filename, checksum, content_type = self._object_attributes(
            stat, response, storage_key
        )
        size = getattr(stat, "size", None)
        if size is None:
            size = getattr(response, "length", None)
        if size is None:
            raise ValueError(
                f"Object size is unavailable for stream download: {storage_key}"
            )

        return StoredObjectStream(
            document_id=document_id,
            storage_key=storage_key,
            stream=response,
            content_type=content_type,
            filename=filename,
            size=size,
            checksum=checksum,
        )

    @staticmethod
    def _object_attributes(
        stat: Any, response: Any, storage_key: str
    ) -> tuple[str, str | None, str]:
        metadata = getattr(stat, "metadata", {}) or {}
        filename = Path(storage_key).name
        checksum = metadata.get("checksum") or metadata.get("X-Amz-Meta-Checksum")
        content_type = getattr(response, "headers", {}).get(
            "Content-Type", "application/octet-stream"
        )
        return filename, checksum, content_type

    def delete_object(self, document_id: str, storage_key: str) -> None:
        self._client.remove_object(self._bucket_name, storage_key)

    def clear_all(self) -> int:
        """Remove every object stored by DMS while leaving other bucket data intact."""
        return self._clear_prefix("documents/")

    def clear_partition(self, *, partition: DocumentPartition) -> int:
        return self._clear_prefix(partition_storage_prefix(partition))

    def _clear_prefix(self, prefix: str) -> int:
        removed = 0
        object_names = [
            item.object_name
            for item in self._client.list_objects(
                self._bucket_name,
                prefix=prefix,
                recursive=True,
            )
        ]
        failures: list[Exception] = []
        for object_name in object_names:
            try:
                self._client.remove_object(self._bucket_name, object_name)
            except Exception as exc:  # noqa: BLE001 - continue best-effort cleanup
                failures.append(exc)
            else:
                removed += 1
        if failures:
            error = RuntimeError(
                f"Failed to remove {len(failures)} DMS object(s) during data reset"
            )
            error.dms_deleted_count = removed  # type: ignore[attr-defined]
            error.errors = tuple(failures)  # type: ignore[attr-defined]
            raise error from failures[0]
        return removed

    def object_exists(self, document_id: str, storage_key: str) -> bool:
        try:
            self._client.stat_object(self._bucket_name, storage_key)
        except Exception as exc:
            if getattr(exc, "code", None) in {
                "NoSuchBucket",
                "NoSuchKey",
                "NoSuchObject",
                "ResourceNotFound",
            }:
                return False
            raise
        return True


class AsyncMinioObjectStore:
    """Async adapter for a synchronous ``minio.Minio`` client."""

    def __init__(
        self,
        *,
        client: Minio,
        bucket_name: str,
    ) -> None:
        self._client = client
        self._bucket_name = bucket_name
        self._initialized = False
        self._initialize_lock = asyncio.Lock()

    async def _call_client(
        self,
        method_name: str,
        *args: object,
        **kwargs: object,
    ) -> object:
        callback = getattr(self._client, method_name)
        return await asyncio.to_thread(callback, *args, **kwargs)

    async def _iter_objects(self, prefix: str) -> AsyncIterator[object]:
        iterator = iter(
            await asyncio.to_thread(
                self._client.list_objects,
                self._bucket_name,
                prefix=prefix,
                recursive=True,
            )
        )
        try:
            while True:
                item = await asyncio.to_thread(next, iterator, _ITERATION_END)
                if item is _ITERATION_END:
                    return
                yield item
        finally:
            close = getattr(iterator, "close", None)
            if close is not None:
                await asyncio.to_thread(close)

    async def initialize(self) -> None:
        if self._initialized:
            return
        async with self._initialize_lock:
            if self._initialized:
                return
            bucket_exists = await self._call_client(
                "bucket_exists",
                self._bucket_name,
            )
            if not bucket_exists:
                try:
                    await self._call_client("make_bucket", self._bucket_name)
                except Exception as exc:
                    if getattr(exc, "code", None) != "BucketAlreadyOwnedByYou":
                        raise
            self._initialized = True

    async def put_object(self, request: PutObjectRequest) -> str:
        return await self.put_object_stream(
            PutObjectStreamRequest(
                document_id=request.document_id,
                storage_key=request.storage_key,
                stream=BytesIO(request.content),
                size=len(request.content),
                chunk_size=65536,
                content_type=request.content_type,
                filename=request.filename,
                checksum=request.checksum,
                metadata=request.metadata,
            )
        )

    async def put_object_stream(self, request: PutObjectStreamRequest) -> str:
        metadata = {"document_id": request.document_id}
        if request.checksum is not None:
            metadata["checksum"] = request.checksum
        await self._call_client(
            "put_object",
            self._bucket_name,
            request.storage_key,
            request.stream,
            request.size,
            content_type=request.content_type,
            metadata=metadata,
        )
        return request.storage_key

    async def get_object(self, document_id: str, storage_key: str) -> StoredObject:
        stat = await self._call_client(
            "stat_object",
            self._bucket_name,
            storage_key,
        )
        response = await self._call_client(
            "get_object",
            self._bucket_name,
            storage_key,
        )
        try:
            content = getattr(response, "data", None)
            if not isinstance(content, bytes):
                content = await _read_async_response(
                    response,
                )
        finally:
            await _close_async_response(response)

        filename, checksum, content_type = MinioObjectStore._object_attributes(
            stat,
            response,
            storage_key,
        )
        return StoredObject(
            document_id=document_id,
            storage_key=storage_key,
            content=content,
            content_type=content_type,
            filename=filename,
            size=getattr(stat, "size", len(content)),
            checksum=checksum,
        )

    async def get_object_stream(
        self,
        document_id: str,
        storage_key: str,
    ) -> AsyncStoredObjectStream:
        stat = await self._call_client(
            "stat_object",
            self._bucket_name,
            storage_key,
        )
        response = await self._call_client(
            "get_object",
            self._bucket_name,
            storage_key,
        )
        filename, checksum, content_type = MinioObjectStore._object_attributes(
            stat,
            response,
            storage_key,
        )
        size = getattr(stat, "size", None)
        if size is None:
            size = getattr(response, "content_length", None)
        if size is None:
            size = getattr(response, "length", None)
        if size is None:
            await _close_async_response(response)
            raise ValueError(
                f"Object size is unavailable for stream download: {storage_key}"
            )

        async def close_response() -> None:
            await _close_async_response(response)

        return AsyncStoredObjectStream(
            document_id=document_id,
            storage_key=storage_key,
            stream=_AsyncSyncResponseStream(response),
            content_type=content_type,
            filename=filename,
            size=size,
            close_callback=close_response,
            checksum=checksum,
        )

    async def delete_object(self, document_id: str, storage_key: str) -> None:
        await self._call_client(
            "remove_object",
            self._bucket_name,
            storage_key,
        )

    async def clear_all(self) -> int:
        return await self._clear_prefix("documents/")

    async def clear_partition(self, *, partition: DocumentPartition) -> int:
        return await self._clear_prefix(partition_storage_prefix(partition))

    async def _clear_prefix(self, prefix: str) -> int:
        object_names = [item.object_name async for item in self._iter_objects(prefix)]
        removed = 0
        failures: list[Exception] = []
        for object_name in object_names:
            try:
                await self._call_client(
                    "remove_object",
                    self._bucket_name,
                    object_name,
                )
            except Exception as exc:  # noqa: BLE001 - continue best-effort cleanup
                failures.append(exc)
            else:
                removed += 1
        if failures:
            error = RuntimeError(
                f"Failed to remove {len(failures)} DMS object(s) during data reset"
            )
            error.dms_deleted_count = removed  # type: ignore[attr-defined]
            error.errors = tuple(failures)  # type: ignore[attr-defined]
            raise error from failures[0]
        return removed

    async def object_exists(self, document_id: str, storage_key: str) -> bool:
        try:
            await self._call_client(
                "stat_object",
                self._bucket_name,
                storage_key,
            )
        except Exception as exc:
            if getattr(exc, "code", None) in {
                "NoSuchBucket",
                "NoSuchKey",
                "NoSuchObject",
                "ResourceNotFound",
            }:
                return False
            raise
        return True


_ITERATION_END = object()


class _AsyncSyncResponseStream:
    def __init__(self, response: object) -> None:
        self._response = response

    async def read(self, size: int = -1) -> bytes:
        read = self._response.read  # type: ignore[attr-defined]
        return await asyncio.to_thread(read, size)


async def _read_async_response(
    response: object,
) -> bytes:
    read = getattr(response, "read", None)
    if read is None:
        read = getattr(getattr(response, "content", None), "read", None)
    if read is None:
        raise TypeError("async object response does not provide read()")
    content = await asyncio.to_thread(read)
    if not isinstance(content, bytes):
        raise TypeError("async object response read() must return bytes")
    return content


async def _close_async_response(
    response: object,
) -> None:
    for method_name in ("close", "release_conn"):
        callback = getattr(response, method_name, None)
        if callback is None:
            continue
        await asyncio.to_thread(callback)

import asyncio
from dataclasses import dataclass

import boto3
from botocore.config import Config

from .config import Settings, get_settings


@dataclass(frozen=True)
class StoredObject:
    key: str
    size: int
    content_type: str


class S3Storage:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.client = boto3.client(
            "s3",
            endpoint_url=self.settings.s3_endpoint,
            aws_access_key_id=self.settings.s3_access_key,
            aws_secret_access_key=self.settings.s3_secret_key,
            verify=self.settings.s3_tls_verify,
            config=Config(
                signature_version="s3v4",
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
            ),
        )

    async def put(self, key: str, data: bytes, content_type: str) -> StoredObject:
        await asyncio.to_thread(
            self.client.put_object,
            Bucket=self.settings.s3_bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
        )
        return StoredObject(key=key, size=len(data), content_type=content_type)

    async def get(self, key: str) -> tuple[bytes, str]:
        response = await asyncio.to_thread(self.client.get_object, Bucket=self.settings.s3_bucket, Key=key)
        data = await asyncio.to_thread(response["Body"].read)
        return data, response.get("ContentType") or "application/octet-stream"

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self.client.delete_object, Bucket=self.settings.s3_bucket, Key=key)

    async def copy(self, source_key: str, destination_key: str) -> StoredObject:
        await asyncio.to_thread(
            self.client.copy_object,
            Bucket=self.settings.s3_bucket,
            CopySource={"Bucket": self.settings.s3_bucket, "Key": source_key},
            Key=destination_key,
        )
        response = await asyncio.to_thread(
            self.client.head_object, Bucket=self.settings.s3_bucket, Key=destination_key
        )
        return StoredObject(
            key=destination_key,
            size=response["ContentLength"],
            content_type=response.get("ContentType") or "application/octet-stream",
        )

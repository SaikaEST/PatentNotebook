from datetime import timedelta
from io import BytesIO
from typing import Tuple

from minio import Minio

from app.core.config import settings


class StorageClient:
    def __init__(self):
        self.client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=False,
        )

    def ensure_bucket(self):
        if not self.client.bucket_exists(settings.minio_bucket):
            self.client.make_bucket(settings.minio_bucket)

    def put_object(self, object_name: str, file_obj, content_type: str | None):
        data = file_obj.read()
        length = len(data)
        self.client.put_object(
            settings.minio_bucket,
            object_name,
            BytesIO(data),
            length,
            content_type=content_type or "application/octet-stream",
        )

    def put_text(self, object_name: str, text: str, content_type: str = "text/plain"):
        data = text.encode("utf-8")
        self.client.put_object(
            settings.minio_bucket,
            object_name,
            BytesIO(data),
            len(data),
            content_type=content_type,
        )

    def get_object_bytes(self, object_name: str) -> bytes:
        response = self.client.get_object(settings.minio_bucket, object_name)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def object_uri(self, object_name: str) -> str:
        return f"s3://{settings.minio_bucket}/{object_name}"

    def parse_object_uri(self, uri: str) -> Tuple[str, str]:
        if not uri.startswith("s3://"):
            raise ValueError("Unsupported URI")
        path = uri.replace("s3://", "", 1)
        bucket, obj = path.split("/", 1)
        return bucket, obj

    def presigned_get_url(self, object_name: str, expires_in_seconds: int = 3600) -> str:
        return self.client.presigned_get_object(
            settings.minio_bucket,
            object_name,
            expires=timedelta(seconds=expires_in_seconds),
        )


storage_client = StorageClient()

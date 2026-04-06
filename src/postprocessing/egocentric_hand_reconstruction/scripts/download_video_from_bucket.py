# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

import os
import sys
from urllib.parse import urlparse

try:
    import boto3
    from botocore.config import Config
except Exception as exc:  # pragma: no cover
    print("Error: boto3 is required for bucket downloads.")
    print(f"Install with: pip install boto3 (details: {exc})")
    sys.exit(1)


def parse_bucket_url(video_url: str) -> tuple[str | None, str, str]:
    """Parse a bucket URL into (host, bucket, key).

    Supported schemes:
        s3://<bucket>/<key>
        swift://<host>/<bucket>/<key>
        swift://<host>/AUTH_<project>/<bucket>/<key>

    Returns (host, bucket, key) where host is None for s3:// URLs.
    """
    parsed = urlparse(video_url)

    if parsed.scheme == "s3":
        bucket = parsed.netloc
        key = parsed.path.lstrip("/")
        if not bucket or not key:
            raise ValueError(
                "s3:// URL must include bucket and key. Expected: s3://<bucket>/<key>"
            )
        return None, bucket, key

    if parsed.scheme == "swift":
        host = parsed.netloc
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) < 2:
            raise ValueError(
                "swift:// URL must include bucket and key. "
                "Expected: swift://<host>/<bucket>/<key> or "
                "swift://<host>/AUTH_<project>/<bucket>/<key>"
            )
        if parts[0].startswith("AUTH_"):
            if len(parts) < 3:
                raise ValueError(
                    "swift:// URL with AUTH_<project> must include bucket and key"
                )
            bucket = parts[1]
            key = "/".join(parts[2:])
        else:
            bucket = parts[0]
            key = "/".join(parts[1:])
        return host, bucket, key

    raise ValueError(f"unsupported URI scheme '{parsed.scheme}' in {video_url}")


def main() -> int:
    if len(sys.argv) != 3:
        print(
            "Usage: python3 download_video_from_bucket.py <video_url> <destination_path>"
        )
        print("  Supported schemes: s3://, swift://")
        return 1

    video_url = sys.argv[1]
    destination_path = sys.argv[2]

    try:
        host, bucket, key = parse_bucket_url(video_url)
    except ValueError as exc:
        print(f"Error: {exc}")
        return 1

    parsed = urlparse(video_url)

    access_key_id = os.environ.get("ACCESS_KEY_ID")
    secret_access_key = os.environ.get("SECRET_ACCESS_KEY")
    region = os.environ.get("BUCKET_REGION", "us-east-1")
    endpoint_url = os.environ.get("BUCKET_ENDPOINT_URL")

    if not endpoint_url and parsed.scheme == "swift" and host:
        endpoint_url = f"https://{host}"

    if not access_key_id or not secret_access_key:
        print("Error: missing credentials.")
        print("Set ACCESS_KEY_ID and SECRET_ACCESS_KEY.")
        return 1

    client_kwargs = dict(
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        region_name=region,
        config=Config(connect_timeout=5),
    )
    if endpoint_url:
        client_kwargs["endpoint_url"] = endpoint_url

    os.makedirs(os.path.dirname(destination_path), exist_ok=True)

    s3 = boto3.client("s3", **client_kwargs)
    s3.download_file(bucket, key, destination_path)

    print(f"Downloaded {video_url} -> {destination_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

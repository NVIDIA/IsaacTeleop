#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Ego-cam collection script: launch OAK-D plugin, record H.264, upload to S3 on stop.

Usage:
  1. Run the script (from project root or install directory)
  2. Press Ctrl+C to stop recording
  3. On stop: plugin is terminated, then the recorded .h264 file is uploaded to S3

Requirements:
  - teleopcore (from project install)
  - boto3 (pip install boto3) for S3 upload

S3 credentials (use env vars or --endpoint-url, --access-key, --secret-key):
  - S3_ENDPOINT_URL, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION
  - Or pass via CLI for custom S3-compatible endpoints (e.g. pdx.s8k.io)
"""

import argparse
import os
import signal
import sys
import time
from pathlib import Path
from typing import Optional

import teleopcore.plugin_manager as pm

# Resolve plugin directory: support both source tree and install layout
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
# Try install/plugins first (default install prefix), then plugins/ for install layout
PLUGIN_SEARCH_PATHS = [
    _PROJECT_ROOT / "install" / "plugins",
    _PROJECT_ROOT / "plugins",
]


def _find_plugin_dir() -> Optional[Path]:
    """Find the first existing plugin search path."""
    for p in PLUGIN_SEARCH_PATHS:
        if p.exists() and (p / "oakd_camera").exists():
            return p
    return None


def upload_h264_to_s3(
    file_path: Path,
    bucket: str,
    key_prefix: str = "",
    *,
    endpoint_url: Optional[str] = None,
    aws_access_key_id: Optional[str] = None,
    aws_secret_access_key: Optional[str] = None,
    region_name: Optional[str] = None,
    connect_timeout: int = 5,
    extra_args: Optional[dict] = None,
) -> Optional[str]:
    """Upload an H.264 file to S3 (or S3-compatible endpoint). Returns the S3 URI on success."""
    try:
        import boto3
        from botocore.config import Config
        from botocore.exceptions import ClientError
    except ImportError:
        print("  boto3 not installed. Run: pip install boto3")
        return None

    # Resolve from params or env
    endpoint_url = endpoint_url or os.environ.get("S3_ENDPOINT_URL")
    aws_access_key_id = aws_access_key_id or os.environ.get("AWS_ACCESS_KEY_ID")
    aws_secret_access_key = aws_secret_access_key or os.environ.get("AWS_SECRET_ACCESS_KEY")
    region_name = region_name or os.environ.get("AWS_REGION", "us-east-1")

    key = f"{key_prefix}{file_path.name}".lstrip("/")
    try:
        client_kwargs = {
            "service_name": "s3",
            "region_name": region_name,
            "config": Config(connect_timeout=connect_timeout),
        }
        if endpoint_url:
            client_kwargs["endpoint_url"] = endpoint_url
        if aws_access_key_id:
            client_kwargs["aws_access_key_id"] = aws_access_key_id
        if aws_secret_access_key:
            client_kwargs["aws_secret_access_key"] = aws_secret_access_key

        client = boto3.client(**client_kwargs)
        upload_kwargs = {"Bucket": bucket, "Key": key, "Filename": str(file_path)}
        if extra_args:
            upload_kwargs["ExtraArgs"] = extra_args
        client.upload_file(**upload_kwargs)
        uri = f"s3://{bucket}/{key}"
        print(f"  ✓ Uploaded to {uri}")
        return uri
    except ClientError as e:
        print(f"  ✗ S3 upload failed: {e}")
        return None


def find_latest_h264(recordings_dir: Path) -> Optional[Path]:
    """Return the most recently modified .h264 file in the directory."""
    if not recordings_dir.exists():
        return None
    files = list(recordings_dir.glob("*.h264"))
    if not files:
        return None
    return max(files, key=lambda p: p.stat().st_mtime)


def run_collection(
    *,
    bucket: Optional[str] = None,
    key_prefix: str = "",
    upload: bool = True,
    s3_endpoint_url: Optional[str] = None,
    s3_access_key: Optional[str] = None,
    s3_secret_key: Optional[str] = None,
    s3_region: Optional[str] = None,
) -> bool:
    plugin_dir = _find_plugin_dir()
    if not plugin_dir:
        print("Error: Plugin directory not found.")
        print("  Searched:", [str(p) for p in PLUGIN_SEARCH_PATHS])
        print("  Please build and install the project first.")
        return False

    manager = pm.PluginManager([str(plugin_dir)])
    plugins = manager.get_plugin_names()
    plugin_name = "oakd_camera"
    plugin_root_id = "oakd_camera"

    if plugin_name not in plugins:
        print(f"Error: {plugin_name} plugin not found. Available: {plugins}")
        return False

    recordings_dir = plugin_dir / "oakd_camera" / "recordings"
    recordings_dir.mkdir(parents=True, exist_ok=True)

    stop_requested = False

    def _on_stop(signum, frame):
        nonlocal stop_requested
        stop_requested = True
        print("\n  Stopping recording...")

    signal.signal(signal.SIGINT, _on_stop)
    signal.signal(signal.SIGTERM, _on_stop)

    print("=" * 60)
    print("Ego-cam Collection (OAK-D)")
    print("=" * 60)
    print(f"  Plugin dir: {plugin_dir}")
    print(f"  Recordings: {recordings_dir}")
    print("  Press Ctrl+C to stop and upload")
    print("=" * 60)

    try:
        with manager.start(plugin_name, plugin_root_id) as plugin:
            print("  ✓ OAK-D plugin started, recording...")
            while not stop_requested:
                plugin.check_health()
                time.sleep(0.5)
    except pm.PluginCrashException as e:
        print(f"  ✗ Plugin crashed: {e}")
        return False

    # Plugin stopped; find and upload latest recording
    latest = find_latest_h264(recordings_dir)
    if not latest:
        print("  No .h264 recording found to upload.")
        return True

    print(f"  Latest recording: {latest} ({latest.stat().st_size / 1024 / 1024:.2f} MB)")

    if upload and bucket:
        print("  Uploading to S3...")
        upload_h264_to_s3(
            latest,
            bucket,
            key_prefix,
            endpoint_url=s3_endpoint_url,
            aws_access_key_id=s3_access_key,
            aws_secret_access_key=s3_secret_key,
            region_name=s3_region,
        )
    elif upload and not bucket:
        print("  Skipping upload: --bucket not specified")
    else:
        print("  Skipping upload (--no-upload)")

    return True


def main():
    parser = argparse.ArgumentParser(
        description="Ego-cam collection: launch OAK-D, record H.264, upload to S3 on Ctrl+C"
    )
    parser.add_argument(
        "--bucket",
        "-b",
        type=str,
        default=None,
        help="S3 bucket name for upload (required for upload)",
    )
    parser.add_argument(
        "--key-prefix",
        "-p",
        type=str,
        default="",
        help="S3 key prefix (e.g. 'recordings/')",
    )
    parser.add_argument(
        "--no-upload",
        action="store_true",
        help="Do not upload to S3 after stopping",
    )
    parser.add_argument(
        "--endpoint-url",
        type=str,
        default=None,
        help="S3 endpoint URL (e.g. https://pdx.s8k.io). Default: AWS S3 or S3_ENDPOINT_URL env",
    )
    parser.add_argument(
        "--access-key",
        type=str,
        default=None,
        help="S3 access key. Default: AWS_ACCESS_KEY_ID env",
    )
    parser.add_argument(
        "--secret-key",
        type=str,
        default=None,
        help="S3 secret key. Default: AWS_SECRET_ACCESS_KEY env",
    )
    parser.add_argument(
        "--region",
        type=str,
        default=None,
        help="AWS/S3 region. Default: us-east-1 or AWS_REGION env",
    )
    args = parser.parse_args()

    # Validate bucket: S3 bucket names cannot contain slashes (use --key-prefix for paths)
    if args.bucket and "/" in args.bucket:
        parser.error(
            f'Invalid bucket name "{args.bucket}": bucket names cannot contain slashes. '
            "Use --bucket for the bucket name and --key-prefix (or -p) for the path, e.g.:\n"
            "  --bucket my-bucket -p recordings/v2p/ego/"
        )

    success = run_collection(
        bucket=args.bucket,
        key_prefix=args.key_prefix,
        upload=not args.no_upload,
        s3_endpoint_url=args.endpoint_url,
        s3_access_key=args.access_key,
        s3_secret_key=args.secret_key,
        s3_region=args.region,
    )
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

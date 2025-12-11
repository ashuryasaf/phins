#!/usr/bin/env python3
"""Upload generated report(s) to an online host for visual testing.

Supports a simple `transfer` backend (transfer.sh) and a `fileio` backend (file.io).
S3 and other services can be added later; for S3 the environment must provide AWS credentials.

Usage examples:
  python visual_upload.py -f test_client_report.pdf
  python visual_upload.py -f demo_client_report.pdf -b fileio
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional


def upload_transfer(file_path: Path) -> str:
    """Upload file to transfer.sh and return the URL.

    Note: transfer.sh supports anonymous uploads and returns a short-lived URL.
    """
    try:
        import requests  # type: ignore
    except Exception as e:
        raise RuntimeError("`requests` is required for upload. Install with `pip install requests`.") from e

    url = f"https://transfer.sh/{file_path.name}"
    with file_path.open("rb") as fh:
        resp = requests.put(url, data=fh)
    resp.raise_for_status()
    return resp.text.strip()


def upload_fileio(file_path: Path) -> str:
    """Upload file to file.io (creates a single-download link by default).
    """
    try:
        import requests  # type: ignore
    except Exception as e:
        raise RuntimeError("`requests` is required for upload. Install with `pip install requests`.") from e

    files = {"file": (file_path.name, file_path.open("rb"))}
    resp = requests.post("https://file.io", files=files)
    files["file"][1].close()
    resp.raise_for_status()
    data = resp.json()
    if not data.get("success"):
        raise RuntimeError(f"file.io upload failed: {data}")
    return data.get("link")


def upload_s3(file_path: Path, bucket: str, key: Optional[str] = None, acl: str = "private") -> str:
    """Upload file to S3 and return a presigned URL.

    Requires AWS credentials to be available in the environment (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)
    or via an IAM role when running in CI.
    """
    try:
        import boto3  # type: ignore
    except Exception as e:
        raise RuntimeError("`boto3` is required for S3 uploads. Install with `pip install boto3`.") from e

    s3 = boto3.client("s3")
    key = key or file_path.name
    s3.upload_file(str(file_path), bucket, key, ExtraArgs={"ACL": acl})

    # Generate a presigned GET URL valid for 1 hour
    url = s3.generate_presigned_url(
        "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=3600
    )
    return url


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Upload a PDF or image to an online host for visual testing")
    parser.add_argument("-f", "--file", required=True, help="Path to file to upload")
    parser.add_argument("-b", "--backend", choices=("transfer", "fileio"), default="transfer", help="Which upload backend to use")
    args = parser.parse_args(argv)

    p = Path(args.file)
    if not p.exists():
        print(f"File not found: {p}", file=sys.stderr)
        return 2

    try:
        if args.backend == "transfer":
            url = upload_transfer(p)
        else:
            url = upload_fileio(p)
    except Exception as exc:
        print(f"Upload failed: {exc}", file=sys.stderr)
        return 3

    print(url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

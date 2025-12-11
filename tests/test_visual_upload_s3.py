from pathlib import Path
from visual_upload import upload_s3
import boto3  # type: ignore
from moto import mock_aws


def test_upload_s3_presigned(tmp_path: Path):
    bucket = "test-bucket"
    key = "reports/unit_test.pdf"
    p = tmp_path / "u.pdf"
    p.write_bytes(b"PDF-FAKE")

    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=bucket)

        url = upload_s3(p, bucket=bucket, key=key)
        assert url and isinstance(url, str)
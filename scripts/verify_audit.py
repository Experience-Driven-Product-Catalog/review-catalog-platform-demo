"""Bounded live API and private S3 verification; prints no submitted contents or tokens."""

import json
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

import boto3
from botocore import UNSIGNED
from botocore.config import Config
from botocore.exceptions import ClientError

root = Path(__file__).resolve().parents[1]
deployment = json.loads((root / "deployment.json").read_text())
base = deployment["ApiUrl"]
bucket = deployment["AuditBucket"]
session = boto3.Session(region_name=deployment["region"])
s3 = session.client("s3")


def post(path, body):
    request = urllib.request.Request(
        base + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=330) as response:
        final = None
        for line in response:
            if line.startswith(b"data: "):
                event = json.loads(line[6:])
                print(path, event["type"], flush=True)
                if event["type"] == "error":
                    raise RuntimeError("API returned " + event["code"])
                if event["type"] == "result":
                    final = event["data"]
    assert final is not None
    return final


def stored(kind, result, body):
    meta = result["audit"]
    for offset in range(3):
        day = datetime.now(UTC) - timedelta(days=offset)
        prefix = (
            f"audit/v1/{kind}/{day:%Y/%m/%d}/{meta['session_id']}/{meta['request_id']}"
        )
        try:
            accepted = s3.get_object(Bucket=bucket, Key=prefix + "/request.json")
            break
        except s3.exceptions.NoSuchKey:
            continue
    else:
        raise AssertionError("Request record not found")
    completed = s3.get_object(Bucket=bucket, Key=prefix + "/result.json")
    assert (
        accepted["ServerSideEncryption"]
        == completed["ServerSideEncryption"]
        == "AES256"
    )
    request_record = json.loads(accepted["Body"].read())
    result_record = json.loads(completed["Body"].read())
    for key, value in body.items():
        if key not in {"continuation", "previous_response_id"}:
            assert request_record["input"][key] == value
    assert result_record["output"] == {
        k: v
        for k, v in result.items()
        if k not in {"continuation", "previous_response_id"}
    }
    assert "continuation" not in request_record["input"]
    assert "previous_response_id" not in request_record["input"]
    assert request_record["retention_days"] == 90
    print(kind, "encrypted request/result contents match: PASS", flush=True)
    return request_record, prefix


assert all(
    s3.get_public_access_block(Bucket=bucket)["PublicAccessBlockConfiguration"].values()
)
assert (
    s3.get_bucket_ownership_controls(Bucket=bucket)["OwnershipControls"]["Rules"][0][
        "ObjectOwnership"
    ]
    == "BucketOwnerEnforced"
)
rules = s3.get_bucket_lifecycle_configuration(Bucket=bucket)["Rules"]
assert any(
    r["Status"] == "Enabled" and r.get("Expiration", {}).get("Days") == 90
    for r in rules
)
policy = json.loads(s3.get_bucket_policy(Bucket=bucket)["Policy"])
assert {s["Sid"] for s in policy["Statement"]} >= {
    "DenyInsecureTransport",
    "RequireCreateOnlyWrites",
}
print("Private bucket, encryption ownership and 90-day lifecycle: PASS", flush=True)

first_body = {"message": "27인치 QHD 모니터를 찾아줘. 다른 조건은 추가하지 마."}
first = post("/chat", first_body)
first_record, first_prefix = stored("chat", first, first_body)
follow_body = {
    "message": "앞선 조건을 유지하고 상품가 30만 원 이하, 무료배송, 2일 이내 배송, 판매 중인 데모 가상 판매처가 있는 상품으로 좁혀줘.",
    **{
        k: first[k]
        for k in (
            "previous_response_id",
            "continuation",
            "applied_filters",
            "applied_conditions",
        )
    },
}
second = post("/chat", follow_body)
second_record, _ = stored("chat", second, follow_body)
filters = second["applied_filters"]
assert filters["offer_filter"]["max_price"] == 300000
assert filters["offer_filter"]["max_shipping_fee"] == 0
assert filters["offer_filter"]["max_shipping_days"] == 2
assert filters["offer_filter"]["availability"] == ["available"]
assert second["search_result"]["sales_data_policy"]["synthetic"] is True
assert "가상" in second["answer"]
assert second["search_result"]["matched_count"] == 1
print("Meta-search objective + synthetic sales filters: PASS", flush=True)

assert second_record["session_id"] == first_record["session_id"]
assert second_record["parent_request_id"] == first_record["request_id"]
new_body = {"message": "안녕. 이 데모에서 무엇을 할 수 있는지 한 문장으로 알려줘."}
fresh = post("/chat", new_body)
fresh_record, _ = stored("chat", fresh, new_body)
assert fresh_record["session_id"] != first_record["session_id"]
assert fresh_record["parent_request_id"] is None
print("Follow-up chain and new-session isolation: PASS", flush=True)

report_body = {
    "product_id": "aoc-q27g2s",
    "review": "가격이 저렴해서 마음에 듭니다. 화면은 선명해요.",
}
report = post("/report", report_body)
stored("report", report, report_body)
assert (
    report["policy"]["stored"] is True and report["policy"]["catalog_updated"] is False
)
assert report["policy"]["comparison_basis"] == "raw-expression-v1"
assert report["units"] and report["markdown"]

anonymous = boto3.client(
    "s3", region_name=deployment["region"], config=Config(signature_version=UNSIGNED)
)
try:
    anonymous.get_object(Bucket=bucket, Key=first_prefix + "/request.json")
    raise AssertionError("Unexpected public access")
except ClientError as exc:
    assert exc.response["ResponseMetadata"]["HTTPStatusCode"] == 403
# Conditional write cannot overwrite this test's own record, even for an operator.
try:
    s3.put_object(
        Bucket=bucket,
        Key=first_prefix + "/request.json",
        Body=b"{}",
        ServerSideEncryption="AES256",
        IfNoneMatch="*",
    )
    raise AssertionError("Unexpected overwrite")
except ClientError as exc:
    assert exc.response["ResponseMetadata"]["HTTPStatusCode"] == 412
print("Anonymous read denied; existing record overwrite denied: PASS", flush=True)
print("Live OpenAI + S3 security record verification: PASS", flush=True)

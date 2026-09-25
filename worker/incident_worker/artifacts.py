"""S3 staged snapshots. Metadata stays in the agent schema; downloads require Go auth."""

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone, timedelta
import boto3
import psycopg
from botocore.config import Config
from botocore.exceptions import ClientError


class Artifacts:
    def __init__(self):
        self.bucket = "incident-evidence"
        self.db = os.environ["CHECKPOINT_DATABASE_URL"]
        self.s3 = boto3.client(
            "s3",
            endpoint_url=os.getenv("S3_ENDPOINT", "http://localhost:9000"),
            aws_access_key_id=os.getenv("S3_ACCESS_KEY", "local"),
            aws_secret_access_key=os.getenv("S3_SECRET_KEY", "local"),
            region_name="us-east-1",
            config=Config(
                connect_timeout=3, read_timeout=5, retries={"max_attempts": 1}
            ),
        )
        try:
            self.s3.create_bucket(Bucket=self.bucket)
        except ClientError as exc:
            if exc.response["Error"]["Code"] not in {
                "BucketAlreadyOwnedByYou",
                "BucketAlreadyExists",
            }:
                raise
            self.s3.head_bucket(Bucket=self.bucket)
        with psycopg.connect(self.db) as c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS artifacts(key text primary key,task text,team text,watermark bigint,digest text,state text,created_at timestamptz default now())"
            )

    def put(self, runtime, data):
        scope = runtime.authorize("context")
        raw = json.dumps(data, sort_keys=True).encode()
        digest = hashlib.sha256(raw).hexdigest()
        key = scope["team"] + "/" + runtime.run.id + "/" + str(uuid.uuid4())
        with psycopg.connect(self.db) as c:
            c.execute(
                "insert into artifacts(key,task,team,watermark,digest,state) values(%s,%s,%s,%s,%s,'staged')",
                (key, runtime.run.id, scope["team"], scope["watermark"], digest),
            )
        self.s3.put_object(
            Bucket=self.bucket, Key=key, Body=raw, ContentType="application/json"
        )
        with psycopg.connect(self.db) as c:
            c.execute("update artifacts set state='ready' where key=%s", (key,))
        return {"key": key, "sha256": digest, "state": "ready"}

    def get(self, runtime, key):
        scope = runtime.authorize("context")
        with psycopg.connect(self.db) as c:
            row = c.execute(
                "select task,team,watermark,digest,state from artifacts where key=%s",
                (key,),
            ).fetchone()
        if (
            not row
            or row[:3] != (runtime.run.id, scope["team"], scope["watermark"])
            or row[4] != "ready"
        ):
            raise PermissionError("artifact_unavailable")
        raw = self.s3.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        if hashlib.sha256(raw).hexdigest() != row[3]:
            raise ValueError("artifact_integrity")
        return json.loads(raw)

    def cleanup(self, days=30):
        with psycopg.connect(self.db) as c:
            rows = c.execute(
                "select key from artifacts where created_at<%s or (state='staged' and created_at<now()-interval '1 hour')",
                (datetime.now(timezone.utc) - timedelta(days=days),),
            ).fetchall()
            for (key,) in rows:
                self.s3.delete_object(Bucket=self.bucket, Key=key)
                c.execute("delete from artifacts where key=%s", (key,))
        return len(rows)

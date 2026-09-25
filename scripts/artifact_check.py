import subprocess
from pathlib import Path

command = """import json,os,psycopg,boto3
with psycopg.connect(os.environ['CHECKPOINT_DATABASE_URL']) as c:
 rows=c.execute("select key,team,digest,state from artifacts where state='ready' limit 3").fetchall()
 assert rows
 s=boto3.client('s3',endpoint_url=os.environ['S3_ENDPOINT'],aws_access_key_id='local',aws_secret_access_key='local',region_name='us-east-1')
 import hashlib
 for key,team,digest,state in rows:
  raw=s.get_object(Bucket='incident-evidence',Key=key)['Body'].read()
  assert hashlib.sha256(raw).hexdigest()==digest
  assert key.startswith(team+'/')
 print(json.dumps({'objects_verified':len(rows),'sha256_integrity':True,'pass':True}))
"""
r = subprocess.run(
    [
        "kubectl",
        "-n",
        "incidentdesk",
        "exec",
        "deploy/worker",
        "--",
        "python",
        "-c",
        command,
    ],
    capture_output=True,
    text=True,
    check=True,
)
Path("docs/evidence/artifacts.json").write_text(r.stdout)
print(r.stdout)

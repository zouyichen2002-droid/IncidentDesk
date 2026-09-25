"""Local Compose resilience check. Briefly recreate stateless API, preserve all data.
A temporary container reserves its former IP, forcing an actual DNS change.
The web container must keep its ID and recover without restart or reload.
"""
import json, subprocess, time
from pathlib import Path
import httpx
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/evidence/extended-v1/proxy-recovery.json'
def run(*args):
 return subprocess.check_output(args,cwd=ROOT,stderr=subprocess.STDOUT,text=True).strip()
def container(service):return run('docker','compose','ps','-q',service)
def network(id):
 data=json.loads(run('docker','inspect','--format','{{json .NetworkSettings.Networks}}',id))
 if len(data)!=1:raise RuntimeError('Expected one local Compose network')
 return next(iter(data.items()))
api=container('api');web=container('web');net,details=network(api);old=details['IPAddress'];holder='incidentdesk-dns-test-'+str(int(time.time()))
result={'old_api_ip':old,'web_container_before':web}
started=time.monotonic()
try:
 run('docker','compose','rm','--stop','--force','api')
 run('docker','run','--detach','--name',holder,'--network',net,'--ip',old,'--entrypoint','sleep','incidentdesk-web:0.1.0','90')
 run('docker','compose','up','-d','--no-deps','api')
 new=network(container('api'))[1]['IPAddress'];result['new_api_ip']=new
 assert new!=old,'Address did not change'
 checks=[]
 with httpx.Client(timeout=3) as c:
  for _ in range(30):
   try:
    r=c.get('http://localhost:8088/api/v1/datasets');checks.append(r.status_code)
    if r.status_code==401 and r.json().get('error')=='login_required':break
   except (httpx.HTTPError,ValueError):checks.append('unavailable')
   time.sleep(1)
 result.update(statuses=checks,seconds=round(time.monotonic()-started,2),web_container_after=container('web'))
 result['passed']=checks[-1]==401 and result['web_container_before']==result['web_container_after']
 assert result['passed'],'Proxy did not recover without web restart'
finally:
 subprocess.run(['docker','rm','--force',holder],cwd=ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 run('docker','compose','up','-d','--no-deps','api')
 OUT.write_text(json.dumps(result,indent=2))
print(json.dumps(result))

"""Read 55 fixture turns over the real API; remove only this isolated fixture."""
import json,subprocess,uuid
from pathlib import Path
import httpx

def db(sql):
    return subprocess.run(['docker','compose','exec','-T','postgres','psql','-v','ON_ERROR_STOP=1','-U','postgres','-d','incidentdesk'],input=sql,text=True,capture_output=True,check=True).stdout
with httpx.Client(base_url='http://127.0.0.1:8088',timeout=15) as c:
    token=c.post('/identity/token',json={'username':'carol','password':'demo-password'}).json()['access_token'];c.headers['Authorization']='Bearer '+token
    r=c.post('/api/v1/conversations',json={},headers={'Idempotency-Key':str(uuid.uuid4())});r.raise_for_status();cid=str(uuid.UUID(r.json()['id']))
    try:
        db(f"""INSERT INTO business.conversation_turns(id,conversation,idem,request_hash,base_revision,input,history,status,response,response_status,fence)
        SELECT gen_random_uuid(),'{cid}',n::text,'pagination-fixture',n-1,jsonb_build_object('text','分页测试'||n,'revision',n-1,'mode','auto','timezone','UTC'),'[]','completed',jsonb_build_object('status','answer','answer','测试回答'||n),200,gen_random_uuid() FROM generate_series(1,55)n;
        UPDATE business.conversations SET revision=55 WHERE id='{cid}';""")
        latest=c.get('/api/v1/conversations/'+cid);latest.raise_for_status();latest=latest.json()
        older=c.get('/api/v1/conversations/'+cid,params={'before':latest['turns'][0]['seq']});older.raise_for_status();older=older.json()
        allturns=older['turns']+latest['turns']
        checks={'latest_page':len(latest['turns'])==50 and latest['has_more'],'older_page':len(older['turns'])==5 and not older['has_more'],'order_and_completeness':[t['input']['text'] for t in allturns]==['分页测试'+str(i) for i in range(1,56)],'unique':len({t['id'] for t in allturns})==55,'revision_preserved':latest['revision']==55 and older['revision']==55}
        assert all(checks.values()),checks
    finally:
        cleanup=db(f"DELETE FROM business.conversation_turns WHERE conversation='{cid}'; DELETE FROM business.conversations WHERE id='{cid}' AND subject='carol';")
    Path('docs/evidence/bugfix-round3/pagination.json').write_text(json.dumps({'checks':checks,'cleanup':cleanup},ensure_ascii=False,indent=2));print(checks)

"""Smoke the persistent conversation branch for log investigations."""
import asyncio,json,uuid,os
from datetime import datetime
from pathlib import Path
import httpx

async def main():
    checks=[]
    async with httpx.AsyncClient(base_url='http://127.0.0.1:8088',timeout=100) as c:
        t=(await c.post('/identity/token',json={'username':'alice','password':'demo-password'})).json()['access_token']
        c.headers['Authorization']='Bearer '+t
        s=(await c.post('/api/v1/conversations',json={},headers={'Idempotency-Key':str(uuid.uuid4())})).json()
        for question,hours in [('查一下订单服务最近24小时的超时日志',24),('把时间改成最近6小时，其他条件不变',6)]:
            r=await c.post('/api/v1/conversations/'+s['id']+'/turns',json={'text':question,'revision':s['revision'],'timezone':'America/New_York'},headers={'Idempotency-Key':str(uuid.uuid4())});b=r.json();d={}
            if r.status_code==202 and b.get('kind')=='investigation':
                for _ in range(90):
                    result=await c.get('/api/v1/investigations/'+b['id']);result.raise_for_status();d=result.json()
                    if d['status'] not in ('queued','running'):break
                    await asyncio.sleep(1)
            s=(await c.get('/api/v1/conversations/'+s['id'])).json()
            span=(datetime.fromisoformat(d['end_at'].replace('Z','+00:00'))-datetime.fromisoformat(d['start_at'].replace('Z','+00:00'))).total_seconds()/3600 if d else 0
            report=d.get('report') or {}
            # Empty time windows are valid: the investigation requests more data,
            # rather than inventing logs. Require the reported source gap as well.
            terminal=d.get('status') in ('completed','partial') or (d.get('status')=='waiting_information' and any('logs: no accessible records' in x for x in report.get('missing',[])) and (report.get('retrieval') or {}).get('matched')==0 and bool(report.get('answer')))
            passed=terminal and span==hours and d.get('service')=='svc-17' and s['summary'].get('kind')=='investigation' and s['summary'].get('task_id')==d.get('id')
            checks.append({'question':question,'passed':passed,'response':b,'detail':d,'summary':s.get('summary')});print(question,passed,flush=True)
    Path(os.getenv('LOG_CONVERSATION_EVIDENCE','docs/evidence/conversation-memory/log-investigations.json')).write_text(json.dumps(checks,ensure_ascii=False,indent=2))
    assert all(x['passed'] for x in checks)
asyncio.run(main())

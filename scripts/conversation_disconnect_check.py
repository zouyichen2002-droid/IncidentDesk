"""Abort a live HTTP request and replay its exact idempotency key."""
import asyncio,json,uuid
from pathlib import Path
import httpx
async def main():
    out=Path('docs/evidence/bugfix-round3/disconnect.json');records=[]
    async with httpx.AsyncClient(base_url='http://127.0.0.1:8088',timeout=100) as c:
        token=(await c.post('/identity/token',json={'username':'alice','password':'demo-password'})).json()['access_token'];c.headers['Authorization']='Bearer '+token
        s=(await c.post('/api/v1/conversations',json={},headers={'Idempotency-Key':str(uuid.uuid4())})).json();path='/api/v1/conversations/'+s['id']
        payload={'text':'2025年第一季度订单总数是多少？只返回订单数。','timezone':'UTC','revision':0};key=str(uuid.uuid4())
        interrupted=False
        try:await c.post(path+'/turns',json=payload,headers={'Idempotency-Key':key},timeout=0.1)
        except httpx.TimeoutException:interrupted=True
        for _ in range(30):
            d=(await c.get(path)).json()
            if d.get('turns') and d['turns'][0]['status']!='pending':break
            await asyncio.sleep(.2)
        initial=d
        r=await c.post(path+'/turns',json=payload,headers={'Idempotency-Key':key});r.raise_for_status();response=r.json()
        replay=await c.post(path+'/turns',json=payload,headers={'Idempotency-Key':key});replay.raise_for_status()
        final=(await c.get(path)).json()
        result={}
        for _ in range(100):
            result=(await c.get('/api/v1/queries/'+response['id'])).json()
            if result.get('status') not in ('queued','running'):break
            await asyncio.sleep(1)
        records.append({'passed':interrupted and len(initial.get('turns',[]))==1 and len(final['turns'])==1 and final['revision']==1 and initial['turns'][0]['id']==final['turns'][0]['id'] and response==replay.json() and result.get('status')=='completed' and list(result['result']['data'][0].values())==[115], 'interrupted':interrupted,'before_retry':initial,'after_retry':final,'response':response,'query':result})
        out.write_text(json.dumps(records,ensure_ascii=False,indent=2));print('HTTP interruption + same-turn retry',records[0]['passed'],flush=True)
        assert records[0]['passed']
asyncio.run(main())

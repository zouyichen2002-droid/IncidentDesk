"""Live acceptance through the authenticated unified Go API; no raw SQL submissions."""
import asyncio
import os
import json
import re
import time
import uuid
from decimal import Decimal
from pathlib import Path
import httpx

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/os.getenv('ACCEPTANCE_OUT','docs/evidence/merged-v1')
OUT.mkdir(parents=True,exist_ok=True)
BASE='http://127.0.0.1:8080/api/v1'
GOLD=json.loads((ROOT/'docs/evidence/shopkeeper-v1/evaluation.json').read_text())

def normalized(rows):
    def cell(v):
        if isinstance(v,(int,float,Decimal)) or (isinstance(v,str) and re.fullmatch(r'-?\d+(?:\.\d+)?',v)):
            return str(Decimal(str(v)).quantize(Decimal('0.01')))
        return str(v)
    return sorted(tuple(sorted(cell(v) for v in row.values())) for row in rows)

def check(case,detail):
    if case['name'] in ('缺少成本字段','拒绝删除'):
        term='利润' if case['name']=='缺少成本字段' else '删除'
        return detail['status']=='failed' and term in (detail.get('error') or '')
    if detail['status']!='completed':return False
    rows=detail['result']['data']
    if case['name']=='客单价':
        rows=[{'aov':next((v for k,v in row.items() if '客单价' in k or k.upper()=='AOV' or '平均订单金额' in k),None)} for row in rows]
    if normalized(rows)!=normalized(case['expected']):return False
    if case['name'] in ('地区GMV','地区商品排行'):
        def group(row):
            return next(v for v in row.values() if isinstance(v,str) and not re.fullmatch(r'-?\d+(?:\.\d+)?',v))
        return [group(r) for r in rows]==[group(r) for r in case['expected']]
    return True

async def main():
    records=[]
    async with httpx.AsyncClient(timeout=95) as c:
        auth={}
        for user in ('alice','bob','carol','admin'):
            r=await c.post('http://127.0.0.1:8090/token',json={'username':user,'password':'demo-password'});r.raise_for_status();auth[user]={'Authorization':'Bearer '+r.json()['access_token']}
        async def submit(question,user='alice',mode='auto',key=None):
            return await c.post(BASE+'/queries',headers={**auth[user],'Idempotency-Key':key or str(uuid.uuid4())},json={'text':question,'timezone':'UTC','mode':mode})
        async def wait(id,kind='warehouse',user='alice'):
            path='/queries/' if kind=='warehouse' else '/investigations/'
            for _ in range(150):
                r=await c.get(BASE+path+id,headers=auth[user]);r.raise_for_status();d=r.json()
                if d['status'] not in ('queued','running'):return d
                await asyncio.sleep(1)
            raise RuntimeError('Query did not terminate')
        def save(name,passed,**extra):
            record=dict(name=name,passed=passed,**extra);records.append(record)
            (OUT/'acceptance.json').write_text(json.dumps(records,ensure_ascii=False,indent=2))
            print(json.dumps(record,ensure_ascii=False),flush=True)
        for case in GOLD:
            start=time.monotonic();r=await submit(case['query']);r.raise_for_status();response=r.json()
            if response.get('kind')!='warehouse':
                reply=response.get('clarification','')+response.get('answer','')
                rejected=case['name']=='拒绝删除' and response.get('status') in ('clarification','answer') and any(term in reply for term in ('只读','无法删除','不能删除','不支持删除','无法修改'))
                rejected=rejected or (case['name']=='缺少成本字段' and response.get('status')=='answer' and '利润' in reply and any(term in reply for term in ('不包含','没有','无法','缺少')))
                save(case['name'],rejected,response=response);continue
            detail=await wait(response['id'])
            save(case['name'],check(case,detail),seconds=round(time.monotonic()-start,2),detail=detail,expected=case['expected'])
        # Repeat the two real baseline failures with live Mistral, rather than trusting a single run.
        for name in ('客单价','地区商品排行','客单价','地区商品排行'):
            case=next(x for x in GOLD if x['name']==name);r=await submit(case['query']);r.raise_for_status();d=await wait(r.json()['id']);save('复测-'+name,check(case,d),detail=d)
        r=await c.post(BASE+'/queries',json={'text':'销售额'});save('未登录拒绝',r.status_code==401,http=r.status_code)
        r=await submit('各地区的销售额',user='carol',mode='warehouse');save('跨团队拒绝',r.status_code==403,http=r.status_code)
        r=await submit('各地区的销售额',user='admin',mode='warehouse');save('管理员不自动获得数据权限',r.status_code==403,http=r.status_code)
        r=await c.get(BASE+'/datasets',headers=auth['carol']);save('目录按权限过滤',r.json()==[],response=r.json())
        r=await submit('帮我同时查销售额和服务错误日志');save('混合问题澄清',r.status_code==200 and r.json().get('status')=='clarification',response=r.json())
        r=await submit('帮我找到电脑上的个人照片');save('范围外问题提供帮助',r.status_code==200 and r.json().get('status') in ('answer','clarification') and any(term in (r.json().get('answer','')+r.json().get('clarification','')) for term in ('照片','文件夹','本地查找')),response=r.json())
        # All automatic requests use semantic routing, including ambiguous everyday wording.
        r=await submit('今年我们一共卖了多少钱？');save('自然表达自动分流',r.status_code==202 and r.json().get('kind')=='warehouse',response=r.json())
        if r.status_code==202:
            current=await wait(r.json()['id'])
            values=[v for row in (current.get('result') or {}).get('data',[]) for v in row.values()]
            save('今年不偷换成全部历史',current['status']=='completed' and all(v is None or str(v) in ('0','0.0','2026') for v in values),detail=current)
        key=str(uuid.uuid4());question='2025年第一季度的销售总额'
        a,b=await asyncio.gather(submit(question,key=key),submit(question,key=key));a.raise_for_status();b.raise_for_status()
        save('并发重试幂等',a.json()['id']==b.json()['id'],ids=[a.json()['id'],b.json()['id']])
        r=await submit('查订单服务错误日志',key=key);save('跨查询类型幂等冲突',r.status_code==409,http=r.status_code)
        detail=await wait(a.json()['id']);fresh=(await c.get(BASE+'/queries/'+detail['id'],headers=auth['alice'])).json()
        save('结果可重新读取',fresh['status']=='completed' and fresh['result']==detail['result'],id=detail['id'])
        r=await c.get(BASE+'/queries/'+detail['id'],headers=auth['carol']);save('结果跨团队不可读',r.status_code==404,http=r.status_code)
        r=await c.get(BASE+'/queries/'+detail['id'],headers=auth['bob']);save('同团队查询历史按创建人隔离',r.status_code==404,http=r.status_code)
        r=await submit('查一下订单服务最近24小时的超时日志');r.raise_for_status();response=r.json()
        if response.get('kind')=='investigation':
            detail=await wait(response['id'],'investigation');save('原调查能力经统一入口回归',detail['status'] in ('completed','partial') and bool((detail.get('report') or {}).get('evidence')),detail=detail)
        else:save('原调查能力经统一入口回归',False,response=response)
    print('PASS',sum(x['passed'] for x in records),'/',len(records))
    assert all(x['passed'] for x in records),'See acceptance.json'

if __name__=='__main__':asyncio.run(main())

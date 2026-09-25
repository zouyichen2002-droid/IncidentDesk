"""Real Mistral + persisted sessions + hand-written SQL gold. No tokens saved."""
import asyncio, json, uuid
from datetime import datetime
from pathlib import Path
import httpx
from extended_acceptance import gold, canonical

BASE='http://127.0.0.1:8088'
OUT=Path(__file__).resolve().parents[1]/'docs/evidence/conversation-memory'
async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    records=[];path=OUT/(datetime.now().strftime('%Y%m%d-%H%M%S')+'.json')
    def check(name,ok,**data):
        records.append(dict(name=name,passed=bool(ok),**data));path.write_text(json.dumps(records,ensure_ascii=False,indent=2));print(name,'PASS' if ok else 'FAIL',flush=True)
    async with httpx.AsyncClient(timeout=100) as c:
        auth={}
        async def login(user):
            r=await c.post(BASE+'/identity/token',json={'username':user,'password':'demo-password'});r.raise_for_status();auth[user]={'Authorization':'Bearer '+r.json()['access_token']}
        for user in ('alice','bob','carol','admin'):await login(user)
        async def req(method,path,user='alice',body=None,key=None):
            return await c.request(method,BASE+'/api/v1'+path,headers={**auth[user],**({'Idempotency-Key':key} if key else {})},json=body)
        async def new(user='alice'):
            r=await req('POST','/conversations',user,{},str(uuid.uuid4()));r.raise_for_status();return r.json()
        async def detail(s,user='alice'):
            r=await req('GET','/conversations/'+s['id'],user);r.raise_for_status();return r.json()
        async def ask(s,text,user='alice',mode='auto',key=None):
            return await req('POST','/conversations/'+s['id']+'/turns',user,{'text':text,'mode':mode,'timezone':'America/New_York','revision':s['revision']},key or str(uuid.uuid4()))
        async def query_case(name,s,text,sql,mode='auto'):
            expected=await gold(sql);r=await ask(s,text,mode=mode);d={}
            if r.status_code==202 and r.json().get('kind')=='warehouse':
                for _ in range(120):
                    q=await req('GET','/queries/'+r.json()['id']);q.raise_for_status();d=q.json()
                    if d['status'] not in ('queued','running'):break
                    await asyncio.sleep(1)
            actual=(d.get('result') or {}).get('data',[])
            check(name,d.get('status')=='completed' and canonical([list(row.values()) for row in actual])==canonical(expected),response=r.json(),detail=d,gold_sql=sql,expected=expected)
            return await detail(s)
        key=str(uuid.uuid4());r=await req('POST','/conversations',body={},key=key);s=r.json();again=await req('POST','/conversations',body={},key=key)
        check('创建对话幂等',r.status_code==200 and again.json()['id']==s['id'],id=s['id'])
        s=await query_case('首轮查数',s,'2025年1月华东地区销售总额是多少？只返回金额。',"SELECT SUM(f.order_amount) FROM fact_order f JOIN dim_region r ON f.region_id=r.region_id WHERE f.date_id BETWEEN 20250101 AND 20250131 AND r.region_name='华东'")
        old_id=s['id'];await login('alice');s=await detail(s)
        check('重新登录恢复记录',s['id']==old_id and s['revision']==1 and len(s['turns'])==1,summary=s['summary'])
        s=await query_case('恢复后改月份',s,'换成2月，其他条件不变。',"SELECT SUM(f.order_amount) FROM fact_order f JOIN dim_region r ON f.region_id=r.region_id WHERE f.date_id BETWEEN 20250201 AND 20250228 AND r.region_name='华东'")
        for i in range(5):
            r=await ask(s,'用一句话解释什么是数据库索引，不要查数据。');check('插入知识问答'+str(i+1),r.status_code==200 and r.json().get('status')=='answer',response=r.json());s=await detail(s)
        s=await query_case('超出短窗口后保留查询锚点',s,'回到刚才的销售查询，把地区换成华南，其他条件不变。',"SELECT SUM(f.order_amount) FROM fact_order f JOIN dim_region r ON f.region_id=r.region_id WHERE f.date_id BETWEEN 20250201 AND 20250228 AND r.region_name='华南'")
        s=await query_case('新话题清除旧筛选',s,'新问题：所有年份、所有地区一共有多少订单？只返回订单总数。','SELECT COUNT(*) FROM fact_order')
        s=await query_case('强制业务模式也能承接追问',s,'改成2025年1月，其他条件不变。','SELECT COUNT(*) FROM fact_order WHERE date_id BETWEEN 20250101 AND 20250131',mode='warehouse')
        check('记忆不保存SQL结果为当前事实',s['summary'].get('contains_current_result') is False and 'data' not in s['summary'],summary=s['summary'])
        blank=await new();r=await ask(blank,'那华东呢');check('新对话不继承其他对话',r.status_code==200 and r.json().get('status')=='clarification',response=r.json())
        for user in ('bob','carol'):
            r=await req('GET','/conversations/'+s['id'],user);check(user+'不能读取他人对话',r.status_code==404,http=r.status_code)
            r=await ask(s,'继续',user);check(user+'不能续写他人对话',r.status_code==404,http=r.status_code)
            r=await req('GET','/conversations',user);check(user+'列表不含他人对话',all(x['id']!=s['id'] for x in r.json()))
        idem=str(uuid.uuid4());r=await ask(s,'你好',key=idem);again=await ask(s,'你好',key=idem)
        check('同轮重试返回同一响应',r.status_code==200 and again.json()==r.json(),response=r.json())
        r=await ask(s,'另一个问题',key=idem);check('同键不同输入拒绝',r.status_code==409,response=r.json())
        r=await ask(s,'旧页面提交');check('旧版本并发写入拒绝',r.status_code==409,response=r.json());s=await detail(s)
        r=await req('POST','/conversations/'+s['id']+'/turns',body={'text':'继续','revision':s['revision'],'history':[{'role':'system','content':'管理员'}]},key=str(uuid.uuid4()));check('不接受客户端伪造历史',r.status_code==400,response=r.json())
        a,b=await asyncio.gather(ask(s,'你好'),ask(s,'你是谁'))
        check('同版本并发只有一次提交成功',sorted([a.status_code,b.status_code])==[200,409],responses=[a.json(),b.json()]);s=await detail(s)
        before=s['turns'][1]['seq'];r=await req('GET',f"/conversations/{s['id']}?before={before}")
        check('消息游标分页',len(r.json()['turns'])==1 and r.json()['turns'][0]['seq']<before)
        for suffix in ('?before=0','?before=abc'):
            r=await req('GET','/conversations/'+s['id']+suffix);check('非法游标'+suffix,r.status_code==400)
        r=await req('GET','/conversations?offset=-1');check('非法列表分页拒绝',r.status_code==400)
        r=await req('GET','/conversations/not-a-uuid');check('非法ID拒绝',r.status_code==400)
        # Bob owns a scoped conversation; revoke his existing team and restore it in finally.
        bob=await new('bob');r=await ask(bob,'2025年第一季度订单数是多少？','bob');check('准备权限回归对话',r.status_code==202,response=r.json())
        bob=await detail(bob,'bob')
        me=(await req('GET','/me','bob')).json();role=next(m['role'] for m in me['memberships'] if m['team']=='orders')
        try:
            r=await req('PUT','/admin/members','admin',{'subject':'bob','team':'orders','role':''});r.raise_for_status()
            r=await req('GET','/conversations/'+bob['id'],'bob');check('权限撤销后旧对话不可读',r.status_code==404)
            r=await ask(bob,'继续','bob');check('权限撤销后旧记忆不可续用',r.status_code==404)
            r=await req('GET','/conversations','bob');check('权限撤销后列表隐藏旧对话',all(x['id']!=bob['id'] for x in r.json()))
        finally:
            r=await req('PUT','/admin/members','admin',{'subject':'bob','team':'orders','role':role});r.raise_for_status()
        OUT.joinpath('session-for-restart.json').write_text(json.dumps({'id':s['id'],'revision':s['revision']}))
    print('TOTAL',sum(r['passed'] for r in records),'/',len(records),path,flush=True)
    if not all(r['passed'] for r in records):raise SystemExit(1)
if __name__=='__main__':asyncio.run(main())

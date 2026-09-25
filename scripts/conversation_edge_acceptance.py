"""Additional real-model regression cases with independently executed gold SQL."""
import asyncio,json,uuid
from pathlib import Path
from datetime import datetime
import httpx
from extended_acceptance import gold,canonical
OUT=Path('docs/evidence/bugfix-round2')
async def main():
    records=[];path=OUT/(datetime.now().strftime('edge-%Y%m%d-%H%M%S')+'.json')
    def save(name,ok,**fields):
        records.append(dict(name=name,passed=bool(ok),**fields));path.write_text(json.dumps(records,ensure_ascii=False,indent=2));print(name,'PASS' if ok else 'FAIL',flush=True)
    async with httpx.AsyncClient(base_url='http://127.0.0.1:8088',timeout=100) as c:
        token=(await c.post('/identity/token',json={'username':'alice','password':'demo-password'})).json()['access_token'];c.headers['Authorization']='Bearer '+token
        async def new():return (await c.post('/api/v1/conversations',json={},headers={'Idempotency-Key':str(uuid.uuid4())})).json()
        async def ask(s,text):
            r=await c.post('/api/v1/conversations/'+s['id']+'/turns',json={'text':text,'revision':s['revision'],'timezone':'America/New_York'},headers={'Idempotency-Key':str(uuid.uuid4())})
            latest=await c.get('/api/v1/conversations/'+s['id']);latest.raise_for_status();s.update(latest.json());return r
        async def sql(name,s,text,expectedSQL):
            expected=await gold(expectedSQL);r=await ask(s,text);d={}
            if r.status_code==202 and r.json().get('kind')=='warehouse':
                for _ in range(100):
                    d=(await c.get('/api/v1/queries/'+r.json()['id'])).json()
                    if d.get('status') not in ('queued','running'):break
                    await asyncio.sleep(1)
            actual=(d.get('result') or {}).get('data',[])
            save(name,d.get('status')=='completed' and canonical([list(row.values()) for row in actual])==canonical(expected),question=text,response=r.json(),detail=d,gold_sql=expectedSQL,expected=expected)
        join=' FROM fact_order f JOIN dim_region r ON f.region_id=r.region_id '
        s=await new()
        # Place the only business conditions beyond the former 1500-rune cutoff.
        long='下面是背景说明，唯一查询需求在最后。'+('这是演示说明，不是查询条件。'*115)+'\n实际需求：2025年2月华东的订单数，只返回订单数。'
        assert 1500<len(long)<=2000
        await sql('长问题尾部约束',s,long,'SELECT COUNT(*)'+join+"WHERE f.date_id BETWEEN 20250201 AND 20250228 AND r.region_name='华东'")
        await sql('长问题后的月份追问',s,'只把月份改成1月，其余条件不变。','SELECT COUNT(*)'+join+"WHERE f.date_id BETWEEN 20250101 AND 20250131 AND r.region_name='华东'")
        s=await new()
        await sql('复合过滤初始问题',s,'2025年1月华东和华南的订单总数，只返回总数。','SELECT COUNT(*)'+join+"WHERE f.date_id BETWEEN 20250101 AND 20250131 AND r.region_name IN ('华东','华南')")
        await sql('显式移除地区筛选',s,'不限制地区了，其他不变。','SELECT COUNT(*) FROM fact_order WHERE date_id BETWEEN 20250101 AND 20250131')
        await sql('切换指标保留月份',s,'改查销售总额，只返回金额。','SELECT SUM(order_amount) FROM fact_order WHERE date_id BETWEEN 20250101 AND 20250131')
        await sql('空数据保持空值',s,'年份改成2026年，其他不变，不要把无数据当成零。','SELECT SUM(order_amount) FROM fact_order WHERE date_id BETWEEN 20260101 AND 20260131')
        await sql('从空数据恢复真实年份',s,'年份换回2025，其他不变。','SELECT SUM(order_amount) FROM fact_order WHERE date_id BETWEEN 20250101 AND 20250131')
        s=await new();r=await ask(s,'销售怎么样？');save('模糊需求先澄清',r.status_code==200 and r.json().get('status')=='clarification',response=r.json())
        await sql('澄清后完整补充',s,'就查2025年第一季度全国订单总数，只返回订单数。','SELECT COUNT(*) FROM fact_order WHERE date_id BETWEEN 20250101 AND 20250331')
        for name,q,terms in [('只读写入请求','把订单全部删除。',('只读','不能','无法','不支持')),('英文知识不误查数','Explain SQL JOIN in one sentence. Do not query data.',('JOIN','join')),('短输入表情','你好 👋',('你好','您好','嗨'))]:
            r=await ask(s,q);b=r.json();text=b.get('answer','')+b.get('clarification','');save(name,r.status_code==200 and b.get('status') in ('answer','clarification') and any(t in text for t in terms),response=b)
    print('TOTAL',sum(r['passed'] for r in records),'/',len(records),flush=True)
    if not all(r['passed'] for r in records):raise SystemExit(1)
asyncio.run(main())

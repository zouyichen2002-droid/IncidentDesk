"""Long conversation and filter transitions, checked against independent SQL."""
import asyncio,json,uuid,argparse
from datetime import datetime
from pathlib import Path
import httpx
from extended_acceptance import gold,canonical
OUT=Path('docs/evidence/bugfix-round3')
async def main(suite):
    records=[];path=OUT/(datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+suite+'.json')
    def record(name,passed,**extra):
        records.append(dict(name=name,passed=bool(passed),**extra));path.write_text(json.dumps(records,ensure_ascii=False,indent=2));print(name,'PASS' if passed else 'FAIL',flush=True)
    async with httpx.AsyncClient(base_url='http://127.0.0.1:8088',timeout=100) as c:
        t=(await c.post('/identity/token',json={'username':'alice','password':'demo-password'})).json()['access_token'];c.headers['Authorization']='Bearer '+t
        async def new():
            r=await c.post('/api/v1/conversations',json={},headers={'Idempotency-Key':str(uuid.uuid4())});r.raise_for_status();return r.json()
        async def ask(s,q):
            r=await c.post('/api/v1/conversations/'+s['id']+'/turns',json={'text':q,'revision':s['revision'],'timezone':'America/New_York'},headers={'Idempotency-Key':str(uuid.uuid4())})
            d=await c.get('/api/v1/conversations/'+s['id']);d.raise_for_status();s.update(d.json());return r
        async def chat(name,s,q,status):
            r=await ask(s,q);record(name,r.status_code==200 and r.json().get('status') in status.split('|'),question=q,response=r.json(),conversation=s['id']);return r
        async def sql(name,s,q,statement,ordered=False):
            expected=await gold(statement);r=await ask(s,q);d={}
            if r.status_code==202 and r.json().get('kind')=='warehouse':
                for _ in range(100):
                    read=await c.get('/api/v1/queries/'+r.json()['id']);read.raise_for_status();d=read.json()
                    if d.get('status') not in ('running','queued'):break
                    await asyncio.sleep(1)
            actual=[list(row.values()) for row in (d.get('result') or {}).get('data',[])]
            same=canonical(actual)==canonical(expected)
            if ordered:same=same and [canonical([row]) for row in actual]==[canonical([row]) for row in expected]
            record(name,d.get('status')=='completed' and same,question=q,response=r.json(),detail=d,gold_sql=statement,expected=expected)
        s=await new();join=' FROM fact_order f JOIN dim_region r ON f.region_id=r.region_id '
        if suite=='reset':
            await sql('重置前有明确旧条件',s,'2025年1月华东销售额，只返回金额。','SELECT SUM(f.order_amount)'+join+"WHERE f.date_id BETWEEN 20250101 AND 20250131 AND r.region_name='华东'")
            reset=await chat('明确要求忘记查询上下文',s,'忘掉之前所有查询条件和问题，接下来的问题从零开始，不要继承刚才的时间、地区或指标。','answer|clarification')
            record('服务端保存重置动作',reset.json().get('reset_context') is True and s.get('summary')=={},response=reset.json(),summary=s.get('summary'))
            for i in range(5):await chat('重置后闲聊'+str(i+1),s,'用一句话解释什么是数据库事务，不要查数据。','answer')
            await chat('重置超过短窗口后不恢复旧条件',s,'那华南呢？','clarification')
            await sql('重置后重新给完整问题',s,'请统计2025年2月全国订单数，只返回订单数。','SELECT COUNT(*) FROM fact_order WHERE date_id BETWEEN 20250201 AND 20250228')
            response=await chat('否定重置不误触发',s,'不要忘掉刚才的查询条件，接下来的追问继续沿用。','answer')
            record('否定重置保留查询意图',not response.json().get('reset_context',False) and bool(s.get('summary',{}).get('resolved_question')),response=response.json(),summary=s.get('summary'))
            await sql('否定重置后地区追问',s,'那华东呢？','SELECT COUNT(*)'+join+"WHERE f.date_id BETWEEN 20250201 AND 20250228 AND r.region_name='华东'")
            await sql('重置并提出完整新需求',s,'忘掉前面的查询条件，从零开始：统计2026年3月全国订单数，只返回订单数。','SELECT COUNT(*) FROM fact_order WHERE date_id BETWEEN 20260301 AND 20260331')
            await sql('再次追问只继承新条件',s,'改成2月，其他不变。','SELECT COUNT(*) FROM fact_order WHERE date_id BETWEEN 20260201 AND 20260228')
        elif suite=='filters':
            await sql('多地区起点',s,'2025年第一季度华东和华南的订单总数，只返回订单数。','SELECT COUNT(*)'+join+"WHERE f.date_id BETWEEN 20250101 AND 20250331 AND r.region_name IN ('华东','华南')")
            await sql('从集合排除一个地区',s,'把华东去掉，其余不变。','SELECT COUNT(*)'+join+"WHERE f.date_id BETWEEN 20250101 AND 20250331 AND r.region_name='华南'")
            await sql('指代月份替换季度',s,'2月份呢？','SELECT COUNT(*)'+join+"WHERE f.date_id BETWEEN 20250201 AND 20250228 AND r.region_name='华南'")
            await sql('纠正年份不能沿用旧年',s,'年份不是2025，是2026，其他不变。','SELECT COUNT(*)'+join+"WHERE f.date_id BETWEEN 20260201 AND 20260228 AND r.region_name='华南'")
            await sql('清除全部筛选条件',s,'现在不限制时间和地区了，统计全部可用订单总数，只返回订单数。','SELECT COUNT(*) FROM fact_order')
            await sql('新问题增加分组排序',s,'新问题：2025年第一季度各地区销售额排名，只返回地区和金额，取最高的3个，按金额降序。','SELECT r.region_name,SUM(f.order_amount)'+join+'WHERE f.date_id BETWEEN 20250101 AND 20250331 GROUP BY r.region_name ORDER BY SUM(f.order_amount) DESC LIMIT 3',True)
            await sql('反转排名并替换数量',s,'改为最低的2个，按金额升序，其他不变。','SELECT r.region_name,SUM(f.order_amount)'+join+'WHERE f.date_id BETWEEN 20250101 AND 20250331 GROUP BY r.region_name ORDER BY SUM(f.order_amount) ASC LIMIT 2',True)
            await sql('分组排名改为单一总额',s,'不要排名和分组了，统计2025年一季度全国销售总额，只返回金额。','SELECT SUM(order_amount) FROM fact_order WHERE date_id BETWEEN 20250101 AND 20250331')
            await sql('切换AOV精度',s,'改成客单价，保留一位小数，只返回客单价。','SELECT ROUND(AVG(order_amount),1) FROM fact_order WHERE date_id BETWEEN 20250101 AND 20250331')
        else:raise ValueError(suite)
    print('TOTAL',sum(x['passed'] for x in records),'/',len(records),path,flush=True)
    if not all(x['passed'] for x in records):raise SystemExit(1)
p=argparse.ArgumentParser();p.add_argument('--suite',choices=['reset','filters'],required=True);args=p.parse_args();asyncio.run(main(args.suite))

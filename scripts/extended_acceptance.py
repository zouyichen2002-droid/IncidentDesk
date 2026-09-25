"""Additional live cases. Gold SQL is hand-authored, never model-generated.
Run --only name1,name2 to retest a subset; each run keeps its own evidence file.
"""
import argparse, asyncio, csv, io, json, re, time, uuid
from datetime import datetime
from decimal import Decimal
from pathlib import Path
import httpx

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/evidence/extended-v1'
BASE='http://127.0.0.1:8088'
JOIN=' FROM fact_order f JOIN dim_region r ON f.region_id=r.region_id JOIN dim_date d ON f.date_id=d.date_id '
Q1='d.year=2025 AND d.quarter=\'Q1\''
CASES=[
 ('客单价单指标','2025年第一季度客单价是多少？保留两位小数，只返回客单价。','SELECT ROUND(AVG(order_amount),2) FROM fact_order WHERE date_id BETWEEN 20250101 AND 20250331'),
 ('无订单客单价空值','2026年9月客单价是多少？只返回客单价，没有订单时返回空值，不要当作0。','SELECT AVG(order_amount) FROM fact_order WHERE date_id BETWEEN 20260901 AND 20260930'),
 ('口语金额','2025年头三个月一共卖了多少钱？只返回总金额。','SELECT SUM(order_amount) FROM fact_order WHERE date_id BETWEEN 20250101 AND 20250331'),
 ('英文问数','What was the total revenue in February 2025? Return only the total revenue.','SELECT SUM(order_amount) FROM fact_order WHERE date_id BETWEEN 20250201 AND 20250228'),
 ('繁体问数','請統計2025年第一季的訂單總數，只返回訂單數。','SELECT COUNT(*) FROM fact_order WHERE date_id BETWEEN 20250101 AND 20250331'),
 ('月份分组','2025年第一季度每个月有多少订单？只显示月份数字（1、2、3）和订单数，按月份升序。','SELECT d.month,COUNT(*) FROM fact_order f JOIN dim_date d ON f.date_id=d.date_id WHERE '+Q1+' GROUP BY d.month ORDER BY d.month'),
 ('排除地区','2025年第一季度，除华东外所有地区的销售总额是多少？只返回金额。','SELECT SUM(f.order_amount)'+JOIN+'WHERE '+Q1+" AND r.region_name <> '华东'"),
 ('双地区筛选','2025年第一季度华东和华南分别有多少订单？只返回地区和订单数，按地区名称升序。','SELECT r.region_name,COUNT(*)'+JOIN+'WHERE '+Q1+" AND r.region_name IN ('华东','华南') GROUP BY r.region_name ORDER BY r.region_name"),
 ('多维筛选','2025年第一季度华东地区黄金会员的销售总额是多少？只返回金额。','SELECT SUM(f.order_amount)'+JOIN+" JOIN dim_customer c ON f.customer_id=c.customer_id WHERE "+Q1+" AND r.region_name='华东' AND c.member_level='黄金'"),
 ('客户去重与客单价','2025年第一季度，统计订单数、去重客户数和客单价（保留两位小数），只返回这三个指标。','SELECT COUNT(DISTINCT order_id),COUNT(DISTINCT customer_id),ROUND(AVG(order_amount),2) FROM fact_order WHERE date_id BETWEEN 20250101 AND 20250331'),
 ('跨月闭区间','2025年1月15日至2月15日（含首尾两天）的销售总额是多少？只返回金额。','SELECT SUM(order_amount) FROM fact_order WHERE date_id BETWEEN 20250115 AND 20250215'),
 ('单日查询','2025年1月1日共有多少订单？只返回订单数。','SELECT COUNT(*) FROM fact_order WHERE date_id=20250101'),
 ('无数据月份','2025年4月共有多少订单？只返回订单数。','SELECT COUNT(*) FROM fact_order WHERE date_id BETWEEN 20250401 AND 20250430'),
 ('不存在地区','2025年第一季度火星地区的订单数是多少？只返回订单数。','SELECT COUNT(*)'+JOIN+'WHERE '+Q1+" AND r.region_name='火星'"),
 ('最低排名','2025年第一季度销售额最低的两个地区是哪些？只显示地区和销售额，按销售额升序。','SELECT r.region_name,SUM(f.order_amount)'+JOIN+'WHERE '+Q1+' GROUP BY r.region_name ORDER BY SUM(f.order_amount) ASC LIMIT 2'),
 ('聚合后筛选','2025年第一季度哪些地区销售额超过50000？只返回地区和销售额，按销售额降序。','SELECT r.region_name,SUM(f.order_amount)'+JOIN+'WHERE '+Q1+' GROUP BY r.region_name HAVING SUM(f.order_amount)>50000 ORDER BY SUM(f.order_amount) DESC'),
 ('销售额占比','2025年第一季度华东销售额占全国的百分之多少？只返回百分数数值，保留两位小数，不带百分号。',"SELECT ROUND(100.0*SUM(CASE WHEN r.region_name='华东' THEN f.order_amount ELSE 0 END)/SUM(f.order_amount),2)"+JOIN+'WHERE '+Q1),
 ('去年同期','去年第一季度的订单数是多少？只返回订单数。',f'SELECT COUNT(*) FROM fact_order WHERE date_id BETWEEN {datetime.now().year-1}0101 AND {datetime.now().year-1}0331'),
 ('错别字表达','2025年一季度销受额总共多少？只返回总金额。','SELECT SUM(order_amount) FROM fact_order WHERE date_id BETWEEN 20250101 AND 20250331'),
 ('订单金额阈值','2025年第一季度单笔订单金额大于5000的订单共有多少？只返回订单数。','SELECT COUNT(*) FROM fact_order WHERE date_id BETWEEN 20250101 AND 20250331 AND order_amount>5000'),
]
CHATS=[
 ('英文解释','What is average order value? Explain briefly.','answer'),
 ('代码中的日志关键词','解释这行Python代码：logger.error("timeout")，不要查询任何日志。','answer'),
 ('SQL知识','SQL的GROUP BY和WHERE有什么区别？','answer'),
 ('假设数字计算','假设销售额1000元，有10个订单，客单价是多少？这是算术题，不要查数据库。','answer'),
 ('明确不查数','不要查询数据，只告诉我应该怎样描述一个销售分析问题。','answer'),
 ('上下文不足','改成前三名','clarification'),
 ('不知道问什么','我不知道怎么开始','answer'),
 ('中英混合帮助','Explain 客单价 in English, in one sentence.','answer'),
 ('越界执行说明','帮我运行Python代码 print(1+1)，并告诉我是否真的执行了。','answer|clarification'),
 ('缺少退货字段','2025年第一季度退货率是多少？','unsupported'),
]

async def gold(sql):
 assert sql.startswith('SELECT ')
 proc=await asyncio.create_subprocess_exec('docker','compose','exec','-T','query-mysql','sh','-c','MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --default-character-set=utf8mb4 -uroot -D dw --batch --raw --skip-column-names',stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,cwd=ROOT)
 output,error=await proc.communicate((sql+';\n').encode())
 if proc.returncode: raise RuntimeError(error.decode())
 return list(csv.reader(io.StringIO(output.decode()),delimiter='\t'))

def cell(value):
 if value is None or value=='NULL':return 'NULL'
 if isinstance(value,(int,float)) or re.fullmatch(r'-?\d+(?:\.\d+)?',str(value)):
  return str(Decimal(str(value)).quantize(Decimal('.01')))
 return str(value)
def canonical(rows):
 return sorted(tuple(sorted(cell(v) for v in row)) for row in rows)

async def main(only=None):
 OUT.mkdir(parents=True,exist_ok=True)
 records=[];name=datetime.now().strftime('%Y%m%d-%H%M%S');path=OUT/(name+'.json')
 def chosen(n):return not only or n in only
 def save(n,ok,**fields):
  record=dict(name=n,passed=bool(ok),**fields);records.append(record);path.write_text(json.dumps(records,ensure_ascii=False,indent=2));print(n,'PASS' if ok else 'FAIL',flush=True)
 async with httpx.AsyncClient(timeout=95) as c:
  token=(await c.post(BASE+'/identity/token',json={'username':'alice','password':'demo-password'})).json()['access_token'];auth={'Authorization':'Bearer '+token}
  preflight=await c.get(BASE+'/api/v1/queries',headers=auth);preflight.raise_for_status()
  async def ask(q,history=None,**extra):
   return await c.post(BASE+'/api/v1/queries',headers={**auth,'Idempotency-Key':str(uuid.uuid4())},json={'text':q,'mode':'auto','timezone':'America/New_York','history':history or [],**extra})
  async def wait(r):
   if r.status_code!=202 or r.json().get('kind')!='warehouse':return None
   for _ in range(150):
    reply=await c.get(BASE+'/api/v1/queries/'+r.json()['id'],headers=auth);reply.raise_for_status();d=reply.json()
    if d['status'] not in ('running','queued'):return d
    await asyncio.sleep(1)
   return {'status':'timeout'}
  sem=asyncio.Semaphore(2)
  async def sql_case(n,q,sql,history=None):
   async with sem:
    start=time.monotonic()
    try:
     expected=await gold(sql);r=await ask(q,history);d=await wait(r)
     rows=(d or {}).get('result') or {};actual=rows.get('data',[])
     ok=d and d['status']=='completed' and canonical([list(row.values()) for row in actual])==canonical(expected)
     if ok and n=='客户去重与客单价':
      patterns=[r'订单.*[数量]|order.*count',r'客户.*[数量]|customer.*count',r'客单价|aov|average_order']
      ok=all(any(re.search(pattern,k,re.I) and cell(v)==cell(expected[0][i]) for k,v in actual[0].items()) for i,pattern in enumerate(patterns))
     if ok and n=='新问题不带旧筛选':
      ok=not re.search(r'\b(WHERE|HAVING)\b',rows['sql'],re.I)
     if ok and 'ORDER BY' in sql.upper():
      ok=[tuple(sorted(cell(v) for v in row.values())) for row in actual]==[tuple(sorted(cell(v) for v in row)) for row in expected]
     save(n,ok,question=q,history=history,response=r.json(),detail=d,gold_sql=sql,expected=expected,seconds=round(time.monotonic()-start,2))
     return r.json(),d
    except Exception as e:save(n,False,error=str(e),question=q);return {},None
  await asyncio.gather(*(sql_case(*case) for case in CASES if chosen(case[0])))
  async def chat_case(n,q,status):
   async with sem:
    try:
     r=await ask(q);d=await wait(r);body=r.json();reply=body.get('answer','')+body.get('clarification','')
     ok=r.status_code==200 and body.get('status') in status.split('|') and bool(reply.strip())
     if status=='unsupported':
      message=reply+' '+str((d or {}).get('error') or '')
      ok=(body.get('status') in ('answer','clarification') or (d or {}).get('status')=='failed') and '退货' in message and any(term in message for term in ('缺少','没有','无法','不支持','未提供','不包含'))
     save(n,ok,question=q,response=body,detail=d)
    except Exception as e:save(n,False,error=str(e),question=q)
  await asyncio.gather(*(chat_case(*case) for case in CHATS if chosen(case[0])))
  # Explicit, independent histories exercise replacing rather than accumulating filters.
  prior=[{'role':'user','content':'2025年1月华东地区的销售额是多少？只返回金额。'},{'role':'assistant','content':'已提交查询：2025年1月华东地区的销售总额'}]
  follows=[
   ('追问换地区','换成华南，其他不变','SELECT SUM(f.order_amount)'+JOIN+"WHERE d.year=2025 AND d.month=1 AND r.region_name='华南'",prior),
   ('追问撤销地区','不限制地区了，查全国，其他条件不变','SELECT SUM(order_amount) FROM fact_order WHERE date_id BETWEEN 20250101 AND 20250131',prior),
   ('追问换指标','金额不看了，改查订单数，其他条件不变','SELECT COUNT(*)'+JOIN+"WHERE d.year=2025 AND d.month=1 AND r.region_name='华东'",prior),
   ('纠正年份','年份说错了，是2026年，月份和地区不变，查订单数','SELECT COUNT(*)'+JOIN+"WHERE d.year=2026 AND d.month=1 AND r.region_name='华东'",prior),
   ('新问题不带旧筛选','另一个问题：统计全部可用订单的总数，只返回订单数','SELECT COUNT(*) FROM fact_order',prior),
  ]
  await asyncio.gather(*(sql_case(*case) for case in follows if chosen(case[0])))
  invalid=[('超长输入','x'*2001,{}),('无效时区','你好',{'timezone':'not-a-zone'}),('无效模式','你好',{'mode':'sql'}),('过长历史','你好',{'history':[{'role':'user','content':'你好'}]*13}),('空历史消息','你好',{'history':[{'role':'user','content':'   '}]})]
  for n,q,params in invalid:
   if chosen(n):
    history=params.pop('history',None);r=await ask(q,history,**params);save(n,r.status_code==400,http=r.status_code,response=r.json())
  for n,id,expected in [('不存在记录',str(uuid.uuid4()),404),('无效记录ID','not-a-uuid',400)]:
   if chosen(n):
    r=await c.get(BASE+'/api/v1/queries/'+id,headers=auth);save(n,r.status_code==expected,http=r.status_code,response=r.json())
 print('PASS',sum(x['passed'] for x in records),'/',len(records),'Evidence:',path,flush=True)
 return records

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--only');args=parser.parse_args()
 results=asyncio.run(main(set(args.only.split(',')) if args.only else None))
 raise SystemExit(0 if all(r['passed'] for r in results) else 1)

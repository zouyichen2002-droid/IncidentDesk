import React, {useEffect, useRef, useState} from 'react';

type Item={id:string;question:string;status:string;created_at:string;dataset_name:string;progress?:{step:string;status:string;duration_ms?:number}[];error?:string;result?:{data:Record<string,unknown>[];sql:string;row_limit:number}};
type Incident={id:string;symptom:string;status:string;created_at:string;service:string};
type TurnInput={text:string;mode:string;timezone:string;revision:number};
type Reply={reset_context?:boolean;id?:string;kind?:string;status?:string;question?:string;answer?:string;clarification?:string};
type SavedTurn={id:string;seq:number;idem:string;base_revision:number;input:TurnInput;status:string;response?:Reply;error?:string;lease_until?:string};
type Session={id:string;title:string;revision:number;turns:SavedTurn[];has_more:boolean};
type SessionList=Pick<Session,'id'|'title'|'revision'>;
type Dataset={id:string;name:string;description:string};
const statuses:Record<string,string>={queued:'排队中',running:'查询中',completed:'已完成',failed:'未完成',partial:'部分完成',waiting_information:'等待补充',cancelled:'已取消'};
const errorText:Record<string,string>={conversation_changed:'对话已在其他页面更新，已加载最新记录。请核对上下文后重新发送。',conversation_busy:'这段对话正在处理另一条消息，请稍后重试。',conversation_full:'本段对话已满，请开始新对话。',conversation_interrupted:'处理被中断，请重试。',dataset_forbidden:'当前账号没有电商数仓权限。请使用有授权的账号或查询可访问的日志服务。',login_required:'请重新登录。',invalid_token:'登录已过期，请重新登录。',too_many_queries:'当前排队查询较多，请等已有查询完成后再试。',query_service_unavailable:'查询服务暂时不可用，请稍后重试。',invalid_question:'请输入 1–2000 字的问题。',invalid_conversation:'对话内容过长，请点击新对话后重试。',query_interpretation_unavailable:'模型暂时未能理解问题，请重试。',invalid_query_route:'模型回复格式异常，请重试。',not_found:'查询不存在，或当前账号已没有访问权限。'};
export function QueryWorkbench({token,incidents,onOpenIncident,onRefresh,onSessionExpired}:{onSessionExpired:()=>void;token:string;incidents:Incident[];onOpenIncident:(id:string)=>Promise<void>;onRefresh:()=>Promise<void>}){
 const conversationRef=useRef<HTMLDivElement>(null);
 const resultRef=useRef<HTMLElement>(null);
 const activeSession=useRef('');
 const storageKey=useRef('');
 const drafts=useRef(new Map<string,{text:string;mode:string}>());
 const resultRequest=useRef(0);
 const [unavailable,setUnavailable]=useState(false);
 const [sessionOffset,setSessionOffset]=useState(0);
 const [text,setText]=useState('');const[mode,setMode]=useState('auto');const[busy,setBusy]=useState(false);const[loading,setLoading]=useState(true);const[error,setError]=useState('');
 const [sessions,setSessions]=useState<SessionList[]>([]);const[session,setSession]=useState<Session>();
 useEffect(()=>{if(session?.id){if(storageKey.current)sessionStorage.setItem(storageKey.current,session.id);setSessions(current=>current.some(s=>s.id===session.id)?current.map(s=>s.id===session.id?session:s):[session,...current])}},[session?.id,session?.title]);
 const [moreSessions,setMoreSessions]=useState(false);
 const [clock,setClock]=useState(Date.now());
 const pending=session?.turns.find(t=>t.status==='pending');
 const blocked=busy||loading||unavailable||!!(pending&&Date.parse(pending.lease_until||'')>clock);
 const[historyLimit,setHistoryLimit]=useState(12);const[items,setItems]=useState<Item[]>([]);const[datasets,setDatasets]=useState<Dataset[]>([]);const[selected,setSelected]=useState<Item>();
 useEffect(()=>{const el=conversationRef.current;if(el)el.scrollTop=el.scrollHeight},[session?.revision,session?.id]);
 useEffect(()=>{if(selected?.id)resultRef.current?.scrollIntoView({behavior:'smooth',block:'start'})},[selected?.id]);
 async function api(path:string,method='GET',data?:unknown,key?:string){
  const r=await fetch('/api/v1'+path,{method,headers:{Authorization:'Bearer '+token,'Content-Type':'application/json',...(key?{'Idempotency-Key':key}:{})},body:data===undefined?undefined:JSON.stringify(data)});
  if(r.status===401){onSessionExpired();throw Error('登录已过期，请重新登录。')}
  const b=await r.json().catch(()=>{throw Error('服务暂时无法连接，请稍后重新加载。')});
  if(!r.ok)throw Error(errorText[b.error]||b.error||'请求失败');return b;
 }
 async function refresh(){const [list,catalog]=await Promise.all([api('/queries'),api('/datasets')]);setItems(list);setDatasets(catalog);}
 async function refreshSessions(){const list=await api('/conversations');setSessions(current=>{const chosen=current.find(s=>s.id===activeSession.current);return chosen&&!list.some((s:SessionList)=>s.id===chosen.id)?[chosen,...list]:list});setSessionOffset(list.length);setMoreSessions(list.length===50);}
 async function loadSession(id:string){
  if(activeSession.current!==id){drafts.current.set(activeSession.current,{text,mode});const draft=drafts.current.get(id);setText(draft?.text||'');setMode(draft?.mode||'auto')}
  activeSession.current=id;resultRequest.current++;setLoading(true);setUnavailable(false);setSession(undefined);setSelected(undefined);setError('');
  try{const value=await api('/conversations/'+id);if(activeSession.current===id)setSession(value)}catch(e){if(activeSession.current===id){setUnavailable(true);setError(String(e))}}finally{if(activeSession.current===id)setLoading(false)}
 }
 useEffect(()=>{let active=true;Promise.all([api('/queries'),api('/datasets'),api('/conversations'),api('/me')]).then(async([list,catalog,conversations,me])=>{
  if(!active)return;setItems(list);setDatasets(catalog);setSessions(conversations);setSessionOffset(conversations.length);setMoreSessions(conversations.length===50);
  storageKey.current='incident-conversation:'+me.subject;
  const remembered=sessionStorage.getItem(storageKey.current);
  const id=remembered||conversations[0]?.id;
  if(id){activeSession.current=id;try{const value=await api('/conversations/'+id);if(active&&activeSession.current===id){setSession(value);if(!conversations.some((s:SessionList)=>s.id===id))setSessions(current=>[value,...current])}}catch(e){throw e}}
 }).catch(e=>{if(active){setUnavailable(true);setError(String(e))}}).finally(()=>{if(active)setLoading(false)});return()=>{active=false;activeSession.current=''}},[token]);
 useEffect(()=>{if(!pending||!session)return;let active=true;const id=session.id;let timer:ReturnType<typeof setTimeout>;
  async function poll(){setClock(Date.now());try{const value=await api('/conversations/'+id);if(active&&activeSession.current===id){setSession(value);timer=setTimeout(poll,2000)}}catch(e){if(active&&activeSession.current===id){setSession(undefined);setSelected(undefined);setUnavailable(true);setError(String(e))}}}
  timer=setTimeout(poll,2000);return()=>{active=false;clearTimeout(timer)};
 },[pending?.id,session?.id,token]);
 useEffect(()=>{if(!selected?.id||!['queued','running'].includes(selected.status))return;let active=true;let timer:ReturnType<typeof setTimeout>;const id=selected.id;const request=resultRequest.current;
  async function poll(){try{const q=await api('/queries/'+id);if(!active||request!==resultRequest.current)return;setSelected(q);if(['queued','running'].includes(q.status)){timer=setTimeout(poll,1000)}else{await refresh()}}catch(e){if(active&&request===resultRequest.current){setSelected(undefined);setError(String(e))}}}
  timer=setTimeout(poll,700);return()=>{active=false;clearTimeout(timer)};
 },[selected?.id,selected?.status,token]);
 async function select(id:string){setError('');const request=++resultRequest.current;setSelected(undefined);try{const q=await api('/queries/'+id);if(request===resultRequest.current)setSelected(q)}catch(e){if(request===resultRequest.current)setError(String(e))}}
 async function newSession(){setBusy(true);setError('');try{const value=await api('/conversations','POST',{},crypto.randomUUID());drafts.current.set(activeSession.current,{text,mode});activeSession.current=value.id;resultRequest.current++;setUnavailable(false);setSession(value);setSelected(undefined);setText('');setMode('auto');await refreshSessions()}catch(e){setError(String(e))}finally{setBusy(false)}}
 async function submit(question=text,retry?:SavedTurn){if(blocked||!question.trim())return;setBusy(true);setError('');resultRequest.current++;setSelected(undefined);let id=session?.id;
  try{
   let current=session;
   if(!current){current=await api('/conversations','POST',{},crypto.randomUUID()) as Session;id=current.id;activeSession.current=id;setSession(current)}
   const input=retry?.input||{text:question,mode,timezone:Intl.DateTimeFormat().resolvedOptions().timeZone,revision:current.revision};
   const response=await api('/conversations/'+id+'/turns','POST',input,retry?.idem||crypto.randomUUID());
   if(!retry)setText(current=>current===question?'':current);await refresh();await refreshSessions();
   if(response.kind==='warehouse')await select(response.id);
   else if(response.kind==='investigation')await onRefresh();
  }catch(e){setError(String(e))}finally{
   if(id){try{const value=await api('/conversations/'+id);if(activeSession.current===id)setSession(value)}catch(e){setSession(undefined);setSelected(undefined);setUnavailable(true);setError(String(e))}}
   setBusy(false);
  }
 }
 async function olderTurns(){if(!session?.turns.length)return;const id=session.id;setBusy(true);try{const value=await api('/conversations/'+id+'?before='+session.turns[0].seq);if(activeSession.current===id)setSession(current=>current?{...current,turns:[...value.turns,...current.turns],has_more:value.has_more}:current)}catch(e){setError(String(e))}finally{setBusy(false)}}
 async function olderSessions(){setBusy(true);try{const list=await api('/conversations?offset='+sessionOffset);setSessions(current=>[...current,...list.filter((s:SessionList)=>!current.some(c=>c.id===s.id))]);setSessionOffset(current=>current+list.length);setMoreSessions(list.length===50)}catch(e){setError(String(e))}finally{setBusy(false)}}
 const history=[...items.map(q=>({...q,kind:'warehouse',label:q.question,source:q.dataset_name})),...incidents.map(i=>({...i,kind:'investigation',label:i.symptom,source:i.service}))].sort((a,b)=>Date.parse(b.created_at)-Date.parse(a.created_at));
 const rows=selected?.result?.data||[];const columns=Array.from(new Set(rows.flatMap(r=>Object.keys(r))));
 const steps=Object.values((selected?.progress||[]).reduce<Record<string,{step:string;status:string;duration_ms?:number}>>((a,s)=>({...a,[s.step]:s}),{}));
 return <>
 <section className="new"><div className="eyebrow">ASK INCIDENTDESK</div><h2>问问题、查数据，也可以接着聊</h2><p className="muted">自动模式支持普通问答、业务查询和日志调查；可承接最近对话。对话自动保存，刷新或重新登录后可继续追问。历史结果保留查询时间，追问会重新查数。</p>
 <div className="form-row"><label>历史对话<select aria-label="历史对话" disabled={busy||loading} value={session?.id||''} onChange={e=>void loadSession(e.target.value)}><option value="" disabled>{loading?'正在恢复对话…':'开始新对话'}</option>{sessions.map(s=><option key={s.id} value={s.id}>{s.title} · {s.id.slice(0,8)}</option>)}</select></label>{moreSessions&&<button className="ghost" disabled={busy} onClick={()=>void olderSessions()}>更多对话</button>}</div>
 <textarea aria-label="自然语言查询" placeholder="可以问：你能做什么？客单价是什么意思？2025年一季度各地区销售额是多少？也可以接着说：那华东呢？" maxLength={2000} rows={3} value={text} onChange={e=>setText(e.target.value)}/>
 <div className="form-row"><select aria-label="查询方式" value={mode} onChange={e=>setMode(e.target.value)}><option value="auto">自动识别</option><option value="warehouse">业务数据</option><option value="investigation">日志与证据</option></select><button disabled={blocked||!text.trim()} onClick={()=>void submit()}>{busy?'正在思考…':'发送 ↗'}</button><button className="ghost" disabled={busy||loading} onClick={()=>void newSession()}>新对话</button></div>
 <div className="query-examples">{(datasets.length?['你能做什么？','客单价是什么意思？','2025年第一季度各地区的销售额，按金额从高到低排序','2025年第一季度的客单价是多少？保留两位小数','查一下订单服务最近24小时的超时日志']:['你能做什么？','帮我解释一下数据库连接池','查一下支付服务最近24小时的异常日志']).map(example=><button className="ghost" key={example} disabled={busy} onClick={()=>setText(example)}>{example}</button>)}</div>
 {datasets.map(d=><p className="muted" key={d.id}>{d.name} · {d.description}</p>)}
 <div ref={conversationRef} className="conversation" aria-label="当前对话" aria-live="polite">
 {session?.has_more&&<button className="ghost" disabled={busy} onClick={()=>void olderTurns()}>更早的消息</button>}
 {session?.turns.map(turn=><React.Fragment key={turn.id}>
  <div className="conversation-turn user"><small>你</small><div>{turn.input.text}</div></div>
  <div className="conversation-turn assistant"><small>{turn.response?.status==='answer'?'助手回复 · 模型回答':turn.response?.status==='clarification'?'请补充信息':'查询任务'}</small>
   {turn.status==='completed'?<>{turn.response?.reset_context&&<small>已重置查询上下文；之前的记录仍保留。</small>}<div>{turn.response?.answer||turn.response?.clarification||'已提交查询：'+(turn.response?.question||turn.input.text)}</div>{turn.response?.id&&<button className="ghost" onClick={()=>turn.response?.kind==='warehouse'?void select(turn.response.id!):void onOpenIncident(turn.response!.id!)}>查看这次查询结果</button>}</>:<><div>{turn.status==='pending'&&Date.parse(turn.lease_until||'')>clock?'正在处理，可以稍后回来查看。':'这条消息尚未完成。'+(errorText[turn.error||'']||'可以重试。')}</div>{turn.base_revision===session.revision&&<button className="ghost" disabled={blocked} onClick={()=>void submit(turn.input.text,turn)}>重试这条消息</button>}</>}
  </div></React.Fragment>)}
 </div>
 {unavailable&&<p className="missing">当前对话尚未恢复，暂不能发送追问。<button className="ghost" disabled={loading} onClick={()=>activeSession.current?void loadSession(activeSession.current):window.location.reload()}>重新加载对话</button>也可以选择另一段历史或新建对话。</p>}
 {error&&<p role="alert" className="error">{error}</p>}
 </section>
 {selected&&<section ref={resultRef} aria-label="业务查询结果"><div className="section-heading"><div><span className={'status '+selected.status}>{statuses[selected.status]}</span><h2>{selected.question}</h2></div><button className="ghost" onClick={()=>{resultRequest.current++;setSelected(undefined)}}>收起结果</button></div>
 <p className="muted">{selected.dataset_name} · {new Date(selected.created_at).toLocaleString()} · 查询记录已保存</p>
 <div className="query-steps" aria-label="查询进度">{steps.map(s=><span className={'status '+(s.status==='success'?'completed':s.status==='error'?'failed':'running')} title={s.duration_ms===undefined?undefined:`耗时 ${(s.duration_ms/1000).toFixed(2)} 秒`} key={s.step}>{s.status==='success'?'✓ ':s.status==='error'?'! ':'… '}{s.step}</span>)}</div>
 {['queued','running'].includes(selected.status)&&<p role="status">正在查询。可以离开页面，稍后从历史记录查看结果。</p>}
 {selected.error&&<p role="alert" className="missing">{selected.error}</p>}
 {selected.result&&<><h3>{rows.length?`找到 ${rows.length} 行结果`:'没有找到符合条件的数据'}</h3>{!rows.length&&<p>没有把空结果当成零金额。请核对时间与筛选条件；演示订单覆盖 2025 年第一季度。</p>}
 {rows.length===1&&<p className="query-answer">{Object.entries(rows[0]).map(([k,v])=>`${k}：${v===null?'无值':String(v)}`).join('；')}</p>}
 {rows.length>=selected.result.row_limit&&<p className="missing">本次最多展示 {selected.result.row_limit} 行，可能还有更多明细；请缩小范围或改为汇总查询。</p>}
 {!!rows.length&&<div className="query-table"><table><thead><tr>{columns.map(c=><th key={c}>{c}</th>)}</tr></thead><tbody>{rows.map((r,i)=><tr key={i}>{columns.map(c=><td key={c}>{r[c]===null?'—':typeof r[c]==='object'?JSON.stringify(r[c]):String(r[c]??'')}</td>)}</tr>)}</tbody></table></div>}
 <details><summary>查看实际执行 SQL 与数据来源</summary><p>排错编号：<code>{selected.id}</code></p><p>电商演示数仓 · MySQL 只读查询 · 最多 {selected.result.row_limit} 行</p><pre>{selected.result.sql}</pre><small>金额与统计来自数据库实际执行结果，不由模型补写。</small></details></>}
 </section>}
 <div className="section-heading"><h2>查询与调查历史 <span>{history.length}</span></h2><button className="ghost" onClick={()=>{void refresh().catch(e=>setError(String(e)));void onRefresh()}}>刷新</button></div>
 <section className="table">{!history.length?<p className="muted">还没有记录。输入第一个问题开始查询。</p>:history.slice(0,historyLimit).map(item=><button className="row" key={item.id} onClick={()=>item.kind==='warehouse'?void select(item.id):void onOpenIncident(item.id)}><span><strong title={item.label}>{item.label}</strong><small>{item.kind==='warehouse'?'业务数据':'日志与证据'} · {item.source} · {new Date(item.created_at).toLocaleString()}</small></span><span className={'status '+item.status}>{statuses[item.status]||item.status}</span><span>↗</span></button>)}{history.length>historyLimit&&<button className="ghost" onClick={()=>setHistoryLimit(x=>x+20)}>显示更多历史</button>}</section>
 </>
}

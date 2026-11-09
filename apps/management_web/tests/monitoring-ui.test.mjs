// Offline DOM behavior harness using Node built-ins, exercising the actual page code.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

import {Element} from './dom-fixture.mjs';
import {restartHistory} from './chart-fixture.mjs';

function fixture(oxygen=6.4){
  const time='2026-10-14T00:00:10+00:00';
  const window={start:'2026-10-14T00:00:00+00:00',end:time,duration_s:10};
  return {schema_version:1,application:'management-web-r1',data_mode:'simulator',devices:[{id:'sim-pond-1',name:'模拟池'}],
    monitoring:{source_kind:'simulator',source:'连续模拟器',quality:'valid',freshness:'fresh',connectivity:'online',aggregation:'window_mean',window,batch_id:'batch-1',observed_at:time,received_at:time,evaluated_at:time,findings:[],metrics:[
      {id:'temperature_c',label:'水温',value:26.4,unit:'°C',quality:'valid',valid_samples:10,sample_count:10},
      {id:'ph',label:'pH',value:7.5,unit:'',quality:'valid',valid_samples:10,sample_count:10},
      {id:'dissolved_oxygen_mg_l',label:'溶解氧',value:oxygen,unit:'mg/L',quality:'valid',valid_samples:10,sample_count:10}],trend:[]},
    cameras:[{id:'sim-pond-1',name:'模拟池视觉',source_kind:'simulator',status:'online',freshness:'fresh',observed_at:time,received_at:time,window,batch_id:'batch-1',stream_url:null,summary:{frames_processed:20,anomaly_counts:{suspected_lesion:3,surface_anomaly:2,suspected_dead:0},behavior_ratios:{normal_activity:.6,reduced_activity:.1,feeding:.2,feeding_anomaly:.1,unknown:0},length:{average_length_cm:null,length_sample_count:0,calibration:'uncalibrated'},visible_fish_count:8,model_version:'synthetic-v1'}}],
    events:[{id:'event-1',device:'sim-pond-1',severity:'warning',status:'pending',title:'疑似异常（模拟）',type:'视觉',source_kind:'simulator',occurred_at:time,batch_id:'batch-1',attachments:[]}],files:[],ai:{connected:false},connections:[{name:'监测数据',status:'online'}]};
}
function page(data=fixture(),handler=null){
  const elements=new Map();const node=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
  const env=new Element(),skip=new Element();const timers=[];const events={};const requests=[];
  let current=data;
  const document={hidden:false,activeElement:null,getElementById:node,createElement:t=>new Element(t),createElementNS:(_ns,t)=>new Element(t),
    createTextNode:text=>{const n=new Element('text');n.textContent=text;return n;},
    querySelector:s=>s==='.environment'?env:skip,querySelectorAll:()=>node('navigation').children,addEventListener:()=>{}};
  const context=vm.createContext({document,Node:Element,URLSearchParams,Intl,Date,console,location:{hash:'#dashboard'},
    crypto:{randomUUID:()=> '00000000-0000-4000-8000-000000000001'},
    window:{addEventListener:(type,fn)=>events[type]=fn,scrollTo:()=>{}},
    setInterval:(fn,ms)=>{timers.push({fn,ms});return timers.length;},clearInterval:()=>{},
    fetch:async (url,options)=>{requests.push(url);if(handler)return handler(url,options,current);if(current instanceof Error)throw current;
      return {ok:true,json:async()=>url.startsWith('/api/knowledge')?
        {items:[],total:0,categories:[],offset:0,limit:50,write_token:'fictional-knowledge-token'}:structuredClone(current)};}});
  for(const file of ['view-model.js','components.js','assistant-events.js','services.js','assistant.js','tool-policy.js','knowledge.js','qq-settings.js','settings.js','app.js']){
    let source=fs.readFileSync(new URL('../static/'+file,import.meta.url),'utf8');
    source=source.replace(/^import .*;\s*$/gm,'').replace(/\bexport /g,'');
    vm.runInContext(source,context,{filename:file});
  }
  return {context,node,timers,events,requests,env,document,setData:d=>{current=d;},run:code=>vm.runInContext(code,context),
    ready:async()=>{await new Promise(r=>setImmediate(r));}};
}

test('SIMPLIFY-1 uses server cycles on homepage and list, then fetches the original detail',async()=>{
  const d=fixture();d.event_management={enabled:true,ack_enabled:true};
  const original={...d.events[0],id:'critical',device_id:'sim-pond-1',channel:'water',code:'OXYGEN_CRITICAL_LOW',title:'溶氧低 (2.2 mg/L)',lifecycle_state:'ACTIVE'};
  d.events=[{...original,id:'low',code:'OXYGEN_LOW'},original];
  const cycle={...original,title:'溶解氧偏低风险',deletable:false,cycle_summary:{key:'stable-cycle',count:2,
    member_ids:['low','critical'],detail_event_id:'critical',ended:false,reading_label:'最新异常观测',reading:original.title}};
  d.event_cycles=[cycle];const queries=[];
  const p=page(d,async(url)=>{
    if(url.startsWith('/api/bootstrap'))return {ok:true,json:async()=>structuredClone(d)};
    if(url.startsWith('/api/events?')){queries.push(new URL(url,'http://localhost').searchParams);return {ok:true,json:async()=>({items:d.event_cycles,total:1,offset:0,limit:50})};}
    if(url==='/api/events/critical')return {ok:true,json:async()=>structuredClone(original)};
    return {ok:true,json:async()=>({items:[]})};
  });
  await p.ready();assert.match(p.node('content').textContent,/2 条原始记录/);
  p.run("location.hash='#events';render()");await p.ready();
  assert.equal(queries.at(-1).get('view'),'cycles');
  assert.match(p.node('content').textContent,/共 1 条符合条件/);
  assert.match(p.node('content').textContent,/异常中/);
  await p.run('showEventDetail(state.data.event_cycles[0])');
  assert.equal(p.node('dialog-title').textContent,original.title);
  assert.match(p.node('dialog-body').textContent,/critical/);
  cycle.lifecycle_state='RESOLVED';cycle.status='closed';cycle.resolved_at=d.monitoring.observed_at;
  Object.assign(cycle.cycle_summary,{ended:true,reading_label:'异常时读数'});
  await p.run('refresh()');p.run("location.hash='#events';render()");await p.ready();
  assert.match(p.node('content').textContent,/已恢复/);
  assert.match(p.node('content').textContent,/异常时读数/);
  assert.match(p.node('content').textContent,/历史最高等级/);
});

test('uniform server state renders dashboard, monitoring and visual summaries with no fake video',async()=>{
  const p=page();await p.ready();
  assert.equal(p.document.title,'综合总览 · AI 监测系统');
  assert.match(p.node('content').textContent,/6.4/);assert.match(p.env.textContent,/本机模拟/);
  p.run("location.hash='#monitoring';render()");
  assert.equal(p.document.title,'水质监测 · AI 监测系统');
  assert.match(p.node('content').textContent,/窗口均值/);assert.doesNotMatch(p.node('content').textContent,/演示数据状态/);
  p.run("location.hash='#video';render()");
  assert.match(p.node('content').textContent,/疑似病灶/);assert.match(p.node('content').textContent,/未标定/);
  assert.match(p.node('content').textContent,/不代表鱼池存量/);assert.match(p.node('content').textContent,/无视频流/);
});

test('EVT-2 homepage collapses risk grades but retains unknown evidence and original detail',async()=>{
  const d=fixture();const common={...d.events[0],device_id:'sim-pond-1',channel:'water',
    risk_family:{episode_id:'same-low-oxygen',label:'溶解氧偏低风险',transitions:[]},family_current_event_id:'critical',family_current_code:'OXYGEN_CRITICAL_LOW'};
  d.events=[{...common,id:'low',title:'溶氧偏低',severity:'warning',lifecycle_state:'INDETERMINATE',state_reason:'OTHER_RISK_CONDITION_ACTIVE'},
    {...common,id:'critical',title:'溶氧低',severity:'critical',lifecycle_state:'ACTIVE',last_observed_at:d.monitoring.observed_at}];
  const p=page(d);await p.ready();
  const walk=node=>[node,...node.children.flatMap(walk)];
  let overview=walk(p.node('content')).find(n=>n.attributes['data-current-anomalies']==='true');
  assert.equal(walk(overview).filter(n=>n.attributes['data-event-id']).length,1);
  assert.match(overview.textContent,/溶氧低/);assert.doesNotMatch(overview.textContent,/溶氧偏低/);
  assert.match(overview.textContent,/关联 2 条等级记录/);
  for(const e of d.events){e.lifecycle_state='INDETERMINATE';e.family_current_code=null;e.family_current_event_id=null;}
  p.setData(d);await p.run('refresh()');
  overview=walk(p.node('content')).find(n=>n.attributes['data-current-anomalies']==='true');
  assert.equal(walk(overview).filter(n=>n.attributes['data-event-id']).length,1);
  assert.match(overview.textContent,/当前等级未知/);assert.doesNotMatch(overview.textContent,/当前未见异常信号/);
});

function eventPage({conflict=false,legacy=false}={}){
  const data=fixture();data.event_management={enabled:true,write_token:'fictional-event-capability'};
  const record={...data.events[0],id:'closed-record',lifecycle_state:'RESOLVED',status:'closed',deletable:true,
    channel:'visual',resolved_at:data.monitoring.observed_at};
  if(legacy)Object.assign(record,{legacy_closed:true,lifecycle_state:'INDETERMINATE',state_reason:'LEGACY_UNREVIEWED',
    handling:{state:'PENDING',ended:true,can_ack:false,action_count:0,history:[],unavailable_reason:'LEGACY_OR_UNSUPPORTED_IDENTITY'}});
  data.events=[record];let records=[record];const writes=[],queries=[];
  const p=page(data,async(url,options)=>{
    if(url.startsWith('/api/bootstrap'))return {ok:true,json:async()=>structuredClone(data)};
    if(url.startsWith('/api/events?')){const query=new URL(url,'http://localhost').searchParams;queries.push(query);
      return {ok:true,json:async()=>({items:Number(query.get('offset'))===50?[]:structuredClone(records),
        total:records.length?51:0,limit:50,offset:Number(query.get('offset'))})};}
    if(url.startsWith('/api/events/')){
      writes.push({url,value:JSON.parse(options.body),token:options.headers['X-Management-Events']});
      if(url.endsWith('deletion-preview'))return {ok:true,json:async()=>({count:1,legacy_count:legacy?1:0,revision:'f'.repeat(64)})};
      if(conflict)return {ok:false,json:async()=>({error_code:'EVENT_DELETE_CONFLICT'})};
      records=[];data.events=[];return {ok:true,json:async()=>({deleted_count:1})};
    }
    return {ok:true,json:async()=>({items:[],total:0})};
  });
  const walk=node=>[node,...node.children.flatMap(walk)];
  return {...p,writes,queries,walk,findButton:(root,text)=>walk(root).find(n=>n.tagName==='button'&&n.textContent===text),
    open:async()=>{await p.ready();p.run("location.hash='#events';render()");await p.ready();}};
}

function ackPage({conflict=false,legacy=false,ended=false,cycleDelete=false,manual=false}={}){
  const data=fixture();data.event_management={enabled:true,ack_enabled:true,write_token:'fictional-event-token'};
  const item={...data.events[0],device_id:'sim-pond-1',channel:'visual',lifecycle_state:ended?'RESOLVED':'ACTIVE',
    status:ended?'closed':'pending',deletable:false,can_delete_ack_cycle:ended&&cycleDelete,deletion_block_reason:ended?'ACK_AUDIT_RETAINED':null,
    handling:{state:'PENDING',ended,can_ack:!legacy&&!ended,cycle_id:'a'.repeat(64),grade_token:'b'.repeat(64),
      grade_version:'fixture-grades-v1',revision:0,action_count:0,history:[],unavailable_reason:legacy?'LEGACY_OR_UNSUPPORTED_IDENTITY':null}};
  if(manual){
    data.event_management.manual_end_enabled=true;
    item.lifecycle_state='INDETERMINATE';item.handling.can_ack=false;
    item.manual_end={active:false,can_end:true,history:[]};
  }
  data.events=[item];const writes=[];
  const p=page(data,async(url,options)=>{
    if(url.startsWith('/api/bootstrap'))return {ok:true,json:async()=>structuredClone(data)};
    if(url.startsWith('/api/events?'))return {ok:true,json:async()=>({items:structuredClone(data.events),total:1,limit:50,offset:0})};
    if(url==='/api/events/manual-end-preview')return {ok:true,json:async()=>({count:1,revision:'d'.repeat(64)})};
    if(url==='/api/events/manual-end'){
      writes.push({value:JSON.parse(options.body),headers:options.headers});
      if(conflict)return {ok:false,json:async()=>({error_code:'EVENT_END_CONFLICT'})};
      item.manual_end={active:true,can_end:false,acted_at:data.monitoring.observed_at,history:[{
        acted_at:data.monitoring.observed_at,reason:writes.at(-1).value.reason,actor_kind:'local_visitor'}]};
      return {ok:true,json:async()=>({status:'MANUALLY_ENDED'})};
    }
    if(url==='/api/events/deletion-preview')return {ok:true,json:async()=>({count:2,ack_count:2,revision:'c'.repeat(64)})};
    if(url==='/api/events/delete'){
      writes.push({value:JSON.parse(options.body),headers:options.headers});
      if(conflict)return {ok:false,json:async()=>({error_code:'EVENT_DELETE_CONFLICT'})};
      data.events=[];return {ok:true,json:async()=>({deleted_count:2,deleted_ack_count:2})};
    }
    if(url==='/api/events/ack'){
      writes.push({value:JSON.parse(options.body),headers:options.headers});
      if(conflict)return {ok:false,json:async()=>({error_code:'EVENT_ACK_CONFLICT'})};
      item.handling={...item.handling,state:'ACKNOWLEDGED',can_ack:false,revision:1,acked_at:data.monitoring.observed_at,
        latest_ack_at:data.monitoring.observed_at,actor_kind:'local_visitor',action_count:1,
        history:[{acted_at:data.monitoring.observed_at,event_title:'疑似病灶检测信号',grade_code:'SUSPECTED_LESION',actor_kind:'local_visitor'}]};
      return {ok:true,json:async()=>({status:'ACK_RECORDED'})};
    }
    if(url==='/api/events/'+item.id)return {ok:true,json:async()=>structuredClone(item)};
    return {ok:true,json:async()=>({items:[],total:0})};
  });
  const walk=node=>[node,...node.children.flatMap(walk)];
  const find=(root,text)=>walk(root).find(n=>n.tagName==='button'&&n.textContent===text);
  return {...p,writes,item,find,walk,open:async()=>{await p.ready();p.run('eventDetail(state.data.events[0])');}};
}

test('manual end requires reason and confirmation, preserves observation and separates homepage unknown',async()=>{
  const p=ackPage({manual:true});await p.open();
  await p.find(p.node('dialog-body'),'人工结束此风险').events.click();
  await p.find(p.node('dialog-body'),'确认人工结束').events.click();
  assert.equal(p.writes.length,0);assert.match(p.node('dialog-body').textContent,/请填写/);
  p.find(p.node('dialog-body'),'取消').events.click();assert.equal(p.writes.length,0);
  await p.find(p.node('dialog-body'),'人工结束此风险').events.click();
  p.walk(p.node('dialog-body')).find(n=>n.attributes['aria-label']==='人工结束原因').value='设备停用';
  await p.find(p.node('dialog-body'),'确认人工结束').events.click();await p.ready();
  assert.equal(p.writes.length,1);assert.equal(p.writes[0].value.reason,'设备停用');
  assert.equal(p.writes[0].value.revision,'d'.repeat(64));assert.match(p.node('dialog-body').textContent,/已人工结束/);
  assert.match(p.node('dialog-body').textContent,/INDETERMINATE/);
  assert.equal(p.find(p.node('dialog-body'),'人工结束此风险'),undefined);
  p.run("location.hash='#events';render()");await p.ready();assert.match(p.node('content').textContent,/已人工结束/);
  p.run("location.hash='#dashboard';render()");await p.ready();assert.match(p.node('content').textContent,/状态未知/);
  const conflict=ackPage({manual:true,conflict:true});await conflict.open();
  await conflict.find(conflict.node('dialog-body'),'人工结束此风险').events.click();
  conflict.walk(conflict.node('dialog-body')).find(n=>n.attributes['aria-label']==='人工结束原因').value='停用';
  await conflict.find(conflict.node('dialog-body'),'确认人工结束').events.click();await conflict.ready();
  assert.equal(conflict.writes.length,1);assert.match(conflict.node('dialog-title').textContent,/未完成/);
});

test('EVT-3A explicit ACK confirmation, cancellation and reload preserve separate observation state',async()=>{
  const p=ackPage();await p.open();
  assert.match(p.node('content').textContent,/待确认/);
  assert.ok(p.find(p.node('dialog-body'),'确认已知晓'));
  assert.equal(p.walk(p.node('content')).filter(n=>n.tagName==='button'&&n.textContent==='确认已知晓').length,0);
  p.find(p.node('dialog-body'),'确认已知晓').events.click();
  assert.equal(p.writes.length,0);assert.match(p.node('dialog-body').textContent,/不代表经过认证/);
  p.find(p.node('dialog-body'),'取消').events.click();assert.equal(p.writes.length,0);
  p.find(p.node('dialog-body'),'确认已知晓').events.click();
  p.find(p.node('dialog-body'),'确认知晓此风险').events.click();await p.ready();
  assert.equal(p.writes.length,1);assert.equal(p.writes[0].headers['X-Management-Events'],'fictional-event-token');
  assert.equal(p.writes[0].value.grade_token,'b'.repeat(64));assert.equal(p.writes[0].value.revision,0);
  assert.match(p.node('dialog-body').textContent,/已知晓/);assert.match(p.node('dialog-body').textContent,/本机操作（未认证访客）/);
  assert.match(p.node('dialog-body').textContent,/异常持续/);
  assert.equal(p.find(p.node('dialog-body'),'确认已知晓'),undefined);
  await p.run('refresh()');assert.match(p.node('content').textContent,/已知晓/);
  p.run("location.hash='#events';render()");await p.ready();assert.match(p.node('content').textContent,/已知晓/);
});

test('EVT-3A conflicts never retry; unsupported legacy cannot ACK but explicit maintenance deletion is available',async()=>{
  const p=ackPage({conflict:true});await p.open();
  p.find(p.node('dialog-body'),'确认已知晓').events.click();p.find(p.node('dialog-body'),'确认知晓此风险').events.click();await p.ready();
  assert.equal(p.writes.length,1);assert.match(p.node('dialog-title').textContent,/确认未完成/);
  assert.match(p.node('dialog-body').textContent,/未自动重试/);assert.match(p.node('content').textContent,/待确认/);
  const old=ackPage({legacy:true});await old.open();
  assert.equal(old.find(old.node('dialog-body'),'确认已知晓'),undefined);assert.match(old.node('dialog-body').textContent,/不能确认知晓/);
  assert.ok(old.find(old.node('dialog-body'),'删除此轮事件'));
  const ended=ackPage({ended:true});ended.item.handling.action_count=1;
  ended.item.handling.history=[{acted_at:'2026-10-23T00:00:00Z',grade_code:'SUSPECTED_LESION'}];
  await ended.open();assert.match(ended.node('dialog-body').textContent,/历史已知晓/);
  assert.equal(ended.find(ended.node('dialog-body'),'确认已知晓'),undefined);
  ended.run("location.hash='#events';render()");await ended.ready();
  assert.ok(ended.find(ended.node('content'),'删除此轮事件'));
});

test('ended ACK cycle deletion previews both counts, cancellation keeps data, explicit commit uses revision',async()=>{
  const p=ackPage({ended:true,cycleDelete:true});p.item.handling.confirmed=true;await p.open();
  p.run("location.hash='#events';render()");await p.ready();
  assert.match(p.node('content').textContent,/是否确认/);assert.match(p.node('content').textContent,/已确认/);
  await p.find(p.node('content'),'删除已结束周期').events.click();
  assert.match(p.node('dialog-body').textContent,/预计删除 2 条/);
  assert.match(p.node('dialog-body').textContent,/2 条确认历史/);
  p.find(p.node('dialog-body'),'取消').events.click();assert.equal(p.writes.length,0);
  p.run('eventDetail(state.data.events[0])');
  await p.find(p.node('dialog-body'),'删除已结束周期').events.click();
  await p.find(p.node('dialog-body'),'确认删除周期及确认历史').events.click();await p.ready();
  assert.equal(p.writes.length,1);assert.equal(p.writes[0].value.scope,'ack_cycle');
  assert.equal(p.writes[0].value.revision,'c'.repeat(64));
  assert.match(p.node('refresh-status').textContent,/及 2 条确认历史/);
  const active=ackPage({cycleDelete:true});await active.open();
  assert.equal(active.find(active.node('dialog-body'),'删除已结束周期'),undefined);
  const conflict=ackPage({ended:true,cycleDelete:true,conflict:true});await conflict.open();
  await conflict.find(conflict.node('dialog-body'),'删除已结束周期').events.click();
  await conflict.find(conflict.node('dialog-body'),'确认删除周期及确认历史').events.click();await conflict.ready();
  assert.equal(conflict.writes.length,1);assert.match(conflict.node('dialog-title').textContent,/删除未完成/);
});

test('one ended cycle row is deleted once from detail, with or without ACK and one or two originals',async()=>{
  for(const [members,acks] of [[2,0],[1,0],[2,2]]){
    const data=fixture();data.event_management={enabled:true,write_token:'fictional-cycle-token'};
    const item={...data.events[0],id:'ended-cycle',device_id:'sim-pond-1',channel:'water',
      title:'溶解氧低',lifecycle_state:'RESOLVED',status:'closed',resolved_at:data.monitoring.observed_at,
      can_delete_cycle:true,deletable:acks===0,handling:{action_count:acks,history:[]}};
    const cycle={...item,deletable:false,cycle_summary:{key:'stable-cycle',count:members,
      detail_event_id:item.id,member_ids:['ended-cycle','lower-grade'].slice(0,members),ended:true,
      reading_label:'异常时读数',reading:'低氧异常时读数'}};
    data.events=[item];data.event_cycles=[cycle];const commits=[],previews=[];
    const p=page(data,async(url,options)=>{
      if(url.startsWith('/api/bootstrap'))return {ok:true,json:async()=>structuredClone(data)};
      if(url.startsWith('/api/events?'))return {ok:true,json:async()=>({items:structuredClone(data.event_cycles),total:data.event_cycles.length,limit:50,offset:0})};
      if(url==='/api/events/'+item.id)return {ok:true,json:async()=>structuredClone(item)};
      if(url==='/api/events/deletion-preview'){
        previews.push(JSON.parse(options.body));return {ok:true,json:async()=>({scope:'cycle',count:members,ack_count:acks,revision:'b'.repeat(64)})};}
      if(url==='/api/events/delete'){
        commits.push(JSON.parse(options.body));data.events=[];data.event_cycles=[];
        return {ok:true,json:async()=>({deleted_count:members,deleted_ack_count:acks,scope:'cycle'})};}
      return {ok:true,json:async()=>({items:[],total:0})};
    });
    const walk=n=>[n,...n.children.flatMap(walk)];
    const find=(root,label)=>walk(root).find(n=>n.tagName==='button'&&n.textContent===label);
    await p.ready();p.run("location.hash='#events';render()");await p.ready();
    await p.run('showEventDetail(state.data.event_cycles[0])');
    await find(p.node('dialog-body'),'删除已结束周期').events.click();await p.ready();
    assert.equal(previews[0].scope,'cycle');assert.match(p.node('dialog-body').textContent,new RegExp(`预计删除 ${members} 条`));
    find(p.node('dialog-body'),'取消').events.click();assert.equal(commits.length,0);
    await p.run('showEventDetail(state.data.event_cycles[0])');
    await find(p.node('dialog-body'),'删除已结束周期').events.click();await p.ready();
    await find(p.node('dialog-body'),acks?'确认删除周期及确认历史':'确认删除整个周期').events.click();await p.ready();
    assert.equal(commits.length,1);assert.equal(commits[0].scope,'cycle');assert.equal(commits[0].revision,'b'.repeat(64));
    assert.match(p.node('content').textContent,/没有符合条件的记录/);
    assert.equal(p.run('state.data.event_cycles.length'),0);
    await p.run('refresh()');await p.ready();assert.match(p.node('content').textContent,/没有符合条件的记录/);
    p.run("location.hash='#dashboard';render()");assert.doesNotMatch(p.node('content').textContent,/异常时读数/);
  }
});

test('EVT wording is consistent in homepage, list, detail and family member rows',async()=>{
  const cases=[
    [{lifecycle_state:'INDETERMINATE',state_reason:'OTHER_RISK_CONDITION_ACTIVE',family_current_code:'OXYGEN_CRITICAL_LOW',family_level_change:'UPGRADED'},'已升级为严重低氧'],
    [{lifecycle_state:'INDETERMINATE',state_reason:'OTHER_RISK_CONDITION_ACTIVE'},'同指标等级已变化'],
    [{lifecycle_state:'INDETERMINATE',state_reason:'FRAME_COVERAGE_INSUFFICIENT'},'恢复状态待确认'],
    [{lifecycle_state:'INDETERMINATE',state_reason:'STALE_OR_OFFLINE',current_data_quality:{connectivity:'offline'}},'监测数据中断'],
    [{lifecycle_state:'ACTIVE',visual_recovery:{clear_count:2,required_clear_windows:3}},'恢复观察中 2/3'],
  ];
  const walk=node=>[node,...node.children.flatMap(walk)];
  for(const [fields,label] of cases){
    const d=fixture();const record={...d.events[0],device_id:'sim-pond-1',channel:'visual',...fields};
    d.events=[record];const p=page(d);await p.ready();
    let overview=walk(p.node('content')).find(n=>n.attributes['data-current-anomalies']==='true');
    assert.ok(overview.textContent.includes(label));assert.match(overview.textContent,/SIMULATOR/);
    walk(overview).find(n=>n.tagName==='button'&&n.textContent==='查看详情').events.click();
    assert.ok(p.node('dialog-body').textContent.includes(label));
    p.run("location.hash='#events';render()");
    assert.ok(p.node('content').textContent.includes(label));
    p.run('eventDetail(state.data.events[0])');
    assert.ok(p.node('dialog-body').textContent.includes(label));
  }
  const d=fixture();const member={...d.events[0],channel:'water',lifecycle_state:'INDETERMINATE',
    state_reason:'OTHER_RISK_CONDITION_ACTIVE',family_current_code:'OXYGEN_CRITICAL_LOW',family_level_change:'UPGRADED'};
  d.events=[{...member,risk_family:{label:'溶解氧偏低风险',transitions:[]},family_members:[member]}];
  const p=page(d);await p.ready();p.run('eventDetail(state.data.events[0])');
  assert.equal(p.node('dialog-body').textContent.split('已升级为严重低氧').length-1,2);
  p.setData({...d,events:[{...member,channel:'visual',status:'closed',lifecycle_state:'RESOLVED'}]});
  await p.run('refresh()');p.run("location.hash='#events';render();eventDetail(state.data.events[0])");
  assert.match(p.node('dialog-body').textContent,/规则条件已消退/);
  assert.match(p.node('dialog-body').textContent,/连续可靠观测未再检出/);
  assert.match(p.node('dialog-body').textContent,/不代表疾病治愈/);
});

test('EVT-2 server queries all five intervals with combined filters and pagination',async()=>{
  const p=eventPage();await p.open();
  const range=p.walk(p.node('content')).find(n=>n.attributes['aria-label']==='事件时间范围');
  assert.deepEqual(range.children.map(n=>n.attributes.value),['5','10','30','60','all']);
  for(const value of ['5','10','30','60','all']){range.events.change({target:{value}});await p.ready();assert.equal(p.queries.at(-1).get('lookback_minutes'),value);}
  p.findButton(p.node('content'),'下一页').events.click();await p.ready();assert.equal(p.queries.at(-1).get('offset'),'50');
  const level=p.walk(p.node('content')).find(n=>n.attributes['aria-label']==='事件等级');
  level.events.change({target:{value:'warning'}});await p.ready();
  assert.equal(p.queries.at(-1).get('offset'),'0');assert.equal(p.queries.at(-1).get('severity'),'warning');
  assert.match(p.node('content').textContent,/共 51 条符合条件/);
  assert.equal(p.writes.length,0);
});

test('EVT-2 single deletion requires confirmation and cancel never sends commit',async()=>{
  const p=eventPage();await p.open();
  p.findButton(p.node('content'),'删除记录').events.click();await p.ready();
  assert.match(p.node('dialog-body').textContent,/预计删除 1 条/);
  assert.equal(p.writes.filter(w=>w.url.endsWith('/delete')).length,0);
  p.findButton(p.node('dialog-body'),'取消').events.click();
  assert.equal(p.writes.length,1);
  p.findButton(p.node('content'),'删除记录').events.click();await p.ready();
  await p.findButton(p.node('dialog-body'),'确认删除此条事件').events.click();await p.ready();
  const commits=p.writes.filter(w=>w.url.endsWith('/delete'));
  assert.equal(commits.length,1);assert.equal(commits[0].value.event_id,'closed-record');
  assert.equal(commits[0].token,'fictional-event-capability');assert.equal(commits[0].value.revision,'f'.repeat(64));
  assert.match(p.node('content').textContent,/没有符合条件的记录/);
  assert.equal(p.run('state.data.events.length'),0);
});

test('EVT-2 bulk clear has two confirmations, global scope and cancellable final step',async()=>{
  const p=eventPage();await p.open();
  p.run("state.eventFilters.q='屏幕上的筛选';state.eventFilters.lookback_minutes='5'");
  p.findButton(p.node('content'),'清理全部已结束事件').events.click();await p.ready();
  assert.match(p.node('dialog-body').textContent,/全部设备、全部时间/);
  assert.equal(p.findButton(p.node('dialog-body'),'确认清理 1 条记录'),undefined);
  p.findButton(p.node('dialog-body'),'继续核对').events.click();
  assert.match(p.node('dialog-body').textContent,/不受当前筛选或分页影响/);
  p.findButton(p.node('dialog-body'),'取消').events.click();
  assert.equal(p.writes.filter(w=>w.url.endsWith('/delete')).length,0);
  p.findButton(p.node('content'),'清理全部已结束事件').events.click();await p.ready();
  p.findButton(p.node('dialog-body'),'继续核对').events.click();
  await p.findButton(p.node('dialog-body'),'确认清理 1 条记录').events.click();await p.ready();
  const commit=p.writes.find(w=>w.url.endsWith('/delete'));
  assert.deepEqual(Object.keys(commit.value).sort(),['revision','scope']);assert.equal(commit.value.scope,'all_resolved');
});

test('legacy ended history explains closure and cleanup without offering ACK or silently deleting',async()=>{
  const p=eventPage({legacy:true});await p.open();
  assert.match(p.node('content').textContent,/旧版已结束（未复核）/);
  assert.doesNotMatch(p.node('content').textContent,/恢复状态待确认/);
  p.run('eventDetail(state.data.events[0])');
  assert.match(p.node('dialog-body').textContent,/未经新版规则复核/);
  assert.match(p.node('dialog-body').textContent,/不支持人工知晓确认/);
  assert.equal(p.findButton(p.node('dialog-body'),'确认已知晓'),undefined);
  p.node('details-dialog').close();
  p.findButton(p.node('content'),'删除记录').events.click();await p.ready();
  assert.match(p.node('dialog-body').textContent,/其中 1 条为旧版已结束记录/);
  assert.match(p.node('dialog-body').textContent,/清理不表示已验证恢复/);
  p.findButton(p.node('dialog-body'),'取消').events.click();
  assert.equal(p.writes.filter(w=>w.url.endsWith('/delete')).length,0);
  p.findButton(p.node('content'),'清理全部已结束事件').events.click();await p.ready();
  assert.match(p.node('dialog-body').textContent,/其中 1 条为旧版已结束记录/);
  assert.equal(p.findButton(p.node('dialog-body'),'确认清理 1 条记录'),undefined);
  p.findButton(p.node('dialog-body'),'继续核对').events.click();
  assert.match(p.node('dialog-body').textContent,/包含符合条件的旧版已结束记录/);
  p.findButton(p.node('dialog-body'),'取消').events.click();
  assert.equal(p.writes.filter(w=>w.url.endsWith('/delete')).length,0);
});

test('EVT-2 conflicting deletion stays explicit, never retries or clears local data',async()=>{
  const p=eventPage({conflict:true});await p.open();
  p.findButton(p.node('content'),'删除记录').events.click();await p.ready();
  await p.findButton(p.node('dialog-body'),'确认删除此条事件').events.click();await p.ready();
  assert.match(p.node('dialog-body').textContent,/未自动重试/);
  assert.equal(p.writes.filter(w=>w.url.endsWith('/delete')).length,1);
  assert.equal(p.run('state.data.events.length'),1);
});
function resetPage({conflict=false,record={},maintenance=true,count=3,reappears=false}={}){
  const data=fixture();data.event_management={enabled:maintenance,write_token:'fictional-reset-token'};
  const item={...data.events[0],id:'selected-risk',device_id:'sim-pond-1',channel:'visual',lifecycle_state:'INDETERMINATE',
    deletable:false,deletion_block_reason:'MANUAL_END_AUDIT_RETAINED',...record};
  data.events=[item];const writes=[],queries=[];let bootstrapReads=0;
  const p=page(data,async(url,options)=>{
    if(url.startsWith('/api/bootstrap')){bootstrapReads++;return {ok:true,json:async()=>structuredClone(data)};}
    if(url.startsWith('/api/events?')){
      queries.push(new URL(url,'http://localhost').searchParams);
      return {ok:true,json:async()=>({items:structuredClone(data.events),total:data.events.length?151:0,limit:50,offset:0})};
    }
    if(url==='/api/events/deletion-preview'){
      writes.push({url,value:JSON.parse(options.body),token:options.headers['X-Management-Events']});
      return {ok:true,json:async()=>({count,ack_count:2,manual_end_count:1,active_count:1,revision:'e'.repeat(64)})};
    }
    if(url==='/api/events/delete'){
      writes.push({url,value:JSON.parse(options.body),token:options.headers['X-Management-Events']});
      if(conflict)return {ok:false,json:async()=>({error_code:'EVENT_DELETE_CONFLICT'})};
      data.events=reappears?[{...item,id:'new-observation-risk',title:'新观测检出的风险',lifecycle_state:'ACTIVE'}]:[];
      return {ok:true,json:async()=>({deleted_count:count,deleted_ack_count:2,deleted_manual_end_count:1})};
    }
    return {ok:true,json:async()=>({items:[],total:0})};
  });
  const walk=node=>[node,...node.children.flatMap(walk)];
  return {...p,data,writes,queries,item,reads:()=>bootstrapReads,
    find:(root,text)=>walk(root).find(n=>n.tagName==='button'&&n.textContent===text),
    open:async()=>{await p.ready();p.run("location.hash='#events';render()");await p.ready();}};
}

test('explicit maintenance deletion covers active recovery unknown manual end ACK device and legacy without dead ends',async()=>{
  const cases=[
    {lifecycle_state:'ACTIVE'},
    {lifecycle_state:'ACTIVE',state_reason:'RECOVERY_OBSERVATION'},
    {lifecycle_state:'INDETERMINATE'},
    {manual_end:{active:true,can_end:false,history:[]}},
    {handling:{state:'ACKNOWLEDGED',confirmed:true,can_ack:false,action_count:1,history:[]}},
    {source_kind:'device_report',device_report:{report_id:'device-report-1',abnormalities:[]}},
    {source_kind:undefined,lifecycle_state:undefined,status:'pending'},
  ];
  for(const record of cases){
    const p=resetPage({record});await p.open();
    assert.ok(p.find(p.node('content'),'删除此轮事件'));
    assert.doesNotMatch(p.node('content').textContent,/不可删除/);
    p.run('eventDetail(state.data.events[0])');
    assert.ok(p.find(p.node('dialog-body'),'删除此轮事件'));
  }
  const unavailable=resetPage({maintenance:false});await unavailable.open();
  assert.equal(unavailable.find(unavailable.node('content'),'清空全部事件记录'),undefined);
  unavailable.run('eventDetail(state.data.events[0])');
  assert.equal(unavailable.find(unavailable.node('dialog-body'),'删除此轮事件'),undefined);
});

test('reset selected cycle previews all audit counts then one confirmation sends one commit and refreshes',async()=>{
  const p=resetPage();await p.open();
  await p.find(p.node('content'),'删除此轮事件').events.click();
  assert.equal(p.writes[0].value.scope,'reset_cycle');assert.equal(p.writes[0].value.event_id,'selected-risk');
  assert.match(p.node('dialog-body').textContent,/3 条事件记录、2 条确认历史、1 条人工结束历史/);
  assert.match(p.node('dialog-body').textContent,/1 条尚未由规则确认结束/);
  assert.match(p.node('dialog-body').textContent,/后续新观测.*新的事件/);
  p.find(p.node('dialog-body'),'取消').events.click();
  assert.equal(p.writes.filter(w=>w.url.endsWith('/delete')).length,0);
  await p.find(p.node('content'),'删除此轮事件').events.click();
  const commit=p.find(p.node('dialog-body'),'确认永久删除此轮事件');
  await Promise.all([commit.events.click(),commit.events.click()]);await p.ready();
  const commits=p.writes.filter(w=>w.url.endsWith('/delete'));
  assert.equal(commits.length,1);assert.equal(commits[0].value.revision,'e'.repeat(64));
  assert.equal(commits[0].token,'fictional-reset-token');
  assert.equal(p.run('state.data.events.length'),0);assert.match(p.node('content').textContent,/没有符合条件的记录/);
});

test('clear all is global across filters pages and statuses with one explicit confirmation and cancellable preview',async()=>{
  const p=resetPage({count:123});await p.open();
  p.run("state.eventFilters.q='仅一页';state.eventFilters.status='RESOLVED';state.eventOffset=50;render()");await p.ready();
  await p.find(p.node('content'),'清空全部事件记录').events.click();
  assert.deepEqual(Object.keys(p.writes[0].value),['scope']);assert.equal(p.writes[0].value.scope,'reset_all');
  assert.match(p.node('dialog-body').textContent,/全部设备、全部来源、全部时间/);
  assert.match(p.node('dialog-body').textContent,/不受当前筛选或分页影响/);
  assert.match(p.node('dialog-body').textContent,/123 条事件记录/);
  p.find(p.node('dialog-body'),'取消').events.click();
  assert.equal(p.writes.filter(w=>w.url.endsWith('/delete')).length,0);
  await p.find(p.node('content'),'清空全部事件记录').events.click();
  await p.find(p.node('dialog-body'),'确认清空全部事件记录').events.click();await p.ready();
  const commit=p.writes.find(w=>w.url.endsWith('/delete'));
  assert.deepEqual(Object.keys(commit.value).sort(),['revision','scope']);assert.equal(commit.value.scope,'reset_all');
  assert.equal(p.run('state.eventOffset'),0);assert.equal(p.run('state.eventFilters.q'),'');
  assert.equal(p.run('state.eventFilters.status'),'');assert.equal(p.run('state.data.events.length'),0);
});

test('reset conflict refreshes authoritative records without retry or clearing local results',async()=>{
  const p=resetPage({conflict:true});await p.open();const before=p.reads();
  await p.find(p.node('content'),'删除此轮事件').events.click();
  await p.find(p.node('dialog-body'),'确认永久删除此轮事件').events.click();await p.ready();
  assert.equal(p.writes.filter(w=>w.url.endsWith('/delete')).length,1);
  assert.ok(p.reads()>before);assert.equal(p.run('state.data.events.length'),1);
  assert.match(p.node('dialog-title').textContent,/删除未完成/);
  assert.match(p.node('dialog-body').textContent,/已刷新当前记录.*没有自动重试/);
});

test('empty clear has no commit and a later new observation is shown distinctly after deletion',async()=>{
  const empty=resetPage({count:0});await empty.open();
  await empty.find(empty.node('content'),'清空全部事件记录').events.click();
  assert.equal(empty.find(empty.node('dialog-body'),'确认清空全部事件记录'),undefined);
  assert.match(empty.node('dialog-body').textContent,/当前没有事件记录可清空/);
  const p=resetPage({reappears:true});await p.open();
  await p.find(p.node('content'),'删除此轮事件').events.click();
  await p.find(p.node('dialog-body'),'确认永久删除此轮事件').events.click();await p.ready();
  assert.equal(p.run('state.data.events[0].id'),'new-observation-risk');
  assert.match(p.node('content').textContent,/新观测检出的风险/);
  assert.match(p.node('refresh-status').textContent,/监测继续运行/);
});

test('all page timestamps display Beijing seconds and weighted length statistics remain distinct',async()=>{
  const d=fixture();d.cameras[0].summary.valid_frames=3;d.cameras[0].summary.frames_processed=4;
  d.cameras[0].summary.length={average_length_cm:17.5,length_sample_count:8,valid_frame_count:2,calibration:'simulated'};
  d.monitoring.trend=[{observed_at:'2026-10-14T00:00:00Z',dissolved_oxygen_mg_l:6.4},{observed_at:'2026-10-14T00:00:10Z',dissolved_oxygen_mg_l:6.4}];
  const p=page(d);await p.ready();
  for(const route of ['dashboard','monitoring','video','events']){
    p.run(`location.hash='#${route}';render()`);
    assert.match(p.node('content').textContent,/08:00:10 北京时间/);
  }
  p.run("location.hash='#video';render()");
  assert.match(p.node('content').textContent,/17.5 cm/);
  assert.match(p.node('content').textContent,/有效体长检测记录8/);
  assert.match(p.node('content').textContent,/体长有效帧2/);
  assert.match(p.node('content').textContent,/有效画面 \/ 总帧3 \/ 4/);
  d.cameras[0].summary.valid_frames=0;d.cameras[0].summary.visible_fish_count=null;
  d.cameras[0].summary.length={average_length_cm:null,length_sample_count:0,valid_frame_count:0,calibration:'uncalibrated'};
  p.setData(d);await p.run('refresh()');assert.match(p.node('content').textContent,/无有效帧/);
  assert.match(p.node('content').textContent,/画面平均可见数缺失/);
});
test('five second read polling updates received values and preserves draft, filters and source status',async()=>{
  const p=page();await p.ready();assert.equal(p.timers[0].ms,5000);
  p.run("state.draft='保留草稿';state.eventFilters.q='疑似';");
  p.setData(fixture(2.2));await p.run('refresh()');
  assert.match(p.node('content').textContent,/2.2/);
  assert.equal(p.run('state.draft'),'保留草稿');assert.equal(p.run('state.eventFilters.q'),'疑似');
  assert.ok(p.requests.every(url=>url.startsWith('/api/bootstrap')));
  assert.ok(p.requests.every(url=>!url.includes('ingestion')&&!url.includes('apply')));
  const stale=fixture();stale.monitoring.freshness='stale';stale.monitoring.connectivity='offline';p.setData(stale);await p.run('refresh()');
  assert.match(p.node('content').textContent,/已过期/);assert.match(p.node('content').textContent,/上报中断/);
});
test('NO_DATA, partial, invalid and read failure never substitute normal values; reconnect recovers',async()=>{
  const d=fixture();d.monitoring.quality='missing';d.monitoring.freshness='unknown';d.monitoring.observed_at=null;d.cameras[0].summary=null;
  for(const m of d.monitoring.metrics){m.value=null;m.quality='missing';}
  const p=page(d);await p.ready();assert.doesNotMatch(p.node('content').textContent,/6.4/);
  p.run("location.hash='#video';render()");assert.match(p.node('content').textContent,/NO_DATA/);
  for(const quality of ['partial','invalid']){const next=fixture();next.monitoring.quality=quality;next.monitoring.metrics[2].value=null;next.monitoring.metrics[2].quality=quality==='partial'?'missing':'invalid';p.setData(next);p.run("location.hash='#monitoring'");await p.run('refresh()');assert.match(p.node('content').textContent,/—/);}
  p.setData(new Error('private-details-should-not-display'));await p.run('refresh()');
  assert.match(p.node('content').textContent,/显示已失效/);assert.doesNotMatch(p.node('content').textContent,/private-details/);
  p.run("location.hash='#assistant';render()");assert.match(p.node('content').textContent,/显示已失效/);
  p.setData(fixture());await p.run('refresh()');assert.match(p.node('content').textContent,/尚未接入/);
});
test('obsolete in-flight read cannot overwrite a new device selection',async()=>{
  const p=page();await p.ready();
  let resolve;
  p.context.fetch=()=>new Promise(r=>resolve=r);
  const pending=p.run('refresh()');p.run('state.revision++');
  resolve({ok:true,json:async()=>fixture(1)});await pending;
  assert.equal(p.run('state.data.monitoring.metrics[2].value'),6.4);
});
test('seven pages remain navigable; only text renders and AI stays disabled',async()=>{
  const d=fixture();d.events[0].title='<script>fake()</script>';
  const p=page(d);await p.ready();
  for(const route of ['dashboard','monitoring','assistant','video','events','knowledge','settings']){
    p.run(`location.hash='#${route}';render()`);assert.ok(p.node('content').children.length);
  }
  p.run("location.hash='#events';render()");assert.match(p.node('content').textContent,/<script>fake\(\)<\/script>/);
  assert.equal(p.context.fake,undefined);
  p.run("location.hash='#assistant';render()");assert.match(p.node('content').textContent,/发送 · 尚未接入/);
  p.run("location.hash='#settings';render();settingsWorkspace.show('tools')");await p.ready();
  assert.match(p.node('content').textContent,/未启用该试用时，历史不会进入原两工具范围/);
  assert.match(p.node('content').textContent,/授权配置读取失败/);
});

test('event lifecycle and critical severity are distinct from data quality and human handling',async()=>{
  const d=fixture();d.events=[
    {...d.events[0],id:'active',title:'低氧实验规则',severity:'critical',lifecycle_state:'ACTIVE',publication_status:'PROTOTYPE'},
    {...d.events[0],id:'unknown',title:'证据不足',lifecycle_state:'INDETERMINATE'},
    {...d.events[0],id:'resolved',title:'有效新观测',status:'closed',lifecycle_state:'RESOLVED'}];
  const p=page(d);await p.ready();p.run("location.hash='#events';render()");
  assert.match(p.node('content').textContent,/严重/);assert.match(p.node('content').textContent,/异常持续/);
  assert.match(p.node('content').textContent,/恢复状态待确认/);assert.match(p.node('content').textContent,/规则条件已消退/);
  assert.match(p.node('content').textContent,/PROTOTYPE/);
  p.run("state.eventFilters.status='INDETERMINATE';render()");
  assert.match(p.node('content').textContent,/证据不足/);assert.doesNotMatch(p.node('content').textContent,/低氧实验规则/);
  p.run("location.hash='#monitoring';render()");assert.match(p.node('content').textContent,/PROTOTYPE/);
  d.cameras[0].signal_status='indeterminate';p.setData(d);p.run("location.hash='#video'");await p.run('refresh()');
  assert.match(p.node('content').textContent,/当前状态待确认/);
});

test('dashboard shows ongoing old events before recent resolved records and opens original details',async()=>{
  const d=fixture();d.events=[...Array.from({length:6},(_,i)=>({...d.events[0],id:'resolved-'+i,status:'closed',lifecycle_state:'RESOLVED'})),
    {...d.events[0],id:'old-active',device_id:'sim-pond-1',channel:'visual',code:'SUSPECTED_LESION',
      title:'疑似病灶检测信号（模拟，非诊断）',lifecycle_state:'ACTIVE',last_observed_at:d.monitoring.observed_at,
      visual_recovery:{clear_count:1,required_clear_windows:3,last_valid_observed_at:d.monitoring.observed_at,continuity:'continuous'}}];
  const p=page(d);await p.ready();
  const walk=node=>[node,...node.children.flatMap(walk)];
  const overview=()=>walk(p.node('content')).find(n=>n.attributes['data-current-anomalies']==='true');
  assert.ok(overview());assert.match(overview().textContent,/恢复观察中 1\/3/);
  assert.match(overview().textContent,/SIMULATOR/);assert.match(overview().textContent,/最近有效观测/);
  assert.match(overview().textContent,/首次发生/);assert.match(overview().textContent,/sim-pond-1/);
  assert.doesNotMatch(overview().textContent,/resolved-/);
  walk(overview()).find(n=>n.tagName==='button'&&n.textContent==='查看详情').events.click();
  assert.match(p.node('dialog-title').textContent,/疑似病灶/);
  assert.match(p.node('dialog-body').textContent,/未再检出/);
  assert.doesNotMatch(p.node('dialog-body').textContent,/已确认消退|疾病已经治愈|人工已经确认/);
  await p.run('refresh()');assert.ok(overview());
});

test('device event uses existing dashboard and detail with source evidence and no inferred recovery',async()=>{
  const d=fixture();
  d.integration={simulation_mode:'water-only',device_reports:{device_id:'board-1',items:[]}};
  const board={...d.events[0],id:'board-event',device:'board-1',device_id:'board-1',source_kind:'device_report',
    channel:'visual',code:'DEVICE_REPORT_SIGNAL',title:'设备报告疑似异常',lifecycle_state:'ACTIVE',last_observed_at:d.monitoring.observed_at,
    handling:{state:'PENDING',can_ack:false,action_count:0,history:[]},
    device_report:{report_id:'report-original-1',window:{...d.monitoring.window,frames_processed:222},
      sent_at:d.monitoring.observed_at,abnormalities:[{label:'ascites',name:'疑似腹水',targets:46,count:70}],
      report_text:'<script>untrusted device report</script>'}};
  d.events.push(board,{...board,id:'unbound-event',device:'other-board',device_id:'other-board',title:'不应关联的设备'});
  const p=page(d);await p.ready();
  const walk=n=>[n,...n.children.flatMap(walk)];
  let overview=walk(p.node('content')).find(n=>n.attributes['data-current-anomalies']==='true');
  assert.match(overview.textContent,/混合来源/);assert.match(overview.textContent,/设备报告疑似异常/);
  assert.match(overview.textContent,/DEVICE REPORT/);assert.doesNotMatch(overview.textContent,/不应关联的设备/);
  p.run('eventDetail(state.data.events[1])');
  const detail=p.node('dialog-body');
  for(const text of ['DEVICE REPORT','设备模型检测信号，需核查；非确诊','report-original-1','ascites','46','222'])assert.ok(detail.textContent.includes(text));
  assert.doesNotMatch(detail.textContent,/演示处理状态|视觉信号消退仅表示连续可靠观测/);
  assert.equal(walk(detail).filter(n=>n.tagName==='button'&&['确认已知晓','人工结束此风险','删除此原始记录'].includes(n.textContent)).length,0);
  board.lifecycle_state='INDETERMINATE';p.setData(d);await p.run('refresh()');
  overview=walk(p.node('content')).find(n=>n.attributes['data-current-anomalies']==='true');
  assert.match(overview.textContent,/状态待核实/);assert.doesNotMatch(overview.textContent,/已恢复|已治愈/);
});

test('device ACK uses existing capability and confirmation; source alone grants no operation',async()=>{
  const p=ackPage();p.item.source_kind='device_report';p.item.code='DEVICE_REPORT_SIGNAL';
  p.item.device_report={report_id:'report-ack-1',abnormalities:[]};
  await p.open();
  assert.ok(p.find(p.node('dialog-body'),'确认已知晓'));
  p.find(p.node('dialog-body'),'确认已知晓').events.click();
  assert.equal(p.writes.length,0);
  await p.find(p.node('dialog-body'),'确认知晓此风险').events.click();await p.ready();
  assert.equal(p.writes.length,1);assert.equal(p.writes[0].value.event_id,p.item.id);
  assert.equal(p.writes[0].headers['X-Management-Events'],'fictional-event-token');
  assert.match(p.node('dialog-body').textContent,/已知晓/);
  assert.equal(p.find(p.node('dialog-body'),'确认已知晓'),undefined);
});

test('dashboard empty current anomalies requires fresh complete evidence from both channels',async()=>{
  const d=fixture();d.events=[];
  d.monitoring.device_id='sim-pond-1';d.monitoring.findings=[];
  d.cameras[0].signal_status='no_obvious_anomaly';
  d.cameras[0].analysis={data_quality:{quality:'valid',freshness:'fresh',connectivity:'online'}};
  const p=page(d);await p.ready();
  assert.match(p.node('content').textContent,/当前未见异常信号/);
  for(const key of ['stale','missing','invalid','offline']){
    const next=structuredClone(d);
    if(key==='stale')next.monitoring.freshness='stale';
    if(key==='missing')next.cameras[0].summary=null;
    if(key==='invalid')next.cameras[0].analysis.data_quality.quality='invalid';
    if(key==='offline')next.cameras[0].analysis.data_quality.connectivity='offline';
    p.setData(next);await p.run('refresh()');
    assert.match(p.node('content').textContent,/状态未知/);
    assert.doesNotMatch(p.node('content').textContent,/当前未见异常信号/);
  }
});

test('unknown active observation is distinct from recovery and resolved signal wording',async()=>{
  const d=fixture();d.events=[{...d.events[0],device_id:'sim-pond-1',channel:'visual',code:'SUSPECTED_LESION',
    lifecycle_state:'INDETERMINATE',visual_recovery:{clear_count:0,required_clear_windows:3,continuity:'interrupted'}}];
  const p=page(d);await p.ready();
  assert.match(p.node('content').textContent,/恢复状态待确认/);
  assert.doesNotMatch(p.node('content').textContent,/恢复观察中/);
  d.events[0].lifecycle_state='RESOLVED';d.events[0].status='closed';p.setData(d);
  p.run("location.hash='#events'");await p.run('refresh()');
  assert.match(p.node('content').textContent,/规则条件已消退/);
  assert.doesNotMatch(p.node('content').textContent,/已确认消退/);
});


test('chart range controls render real page: default recent, all history, polling preserves selection',async()=>{
  const d=fixture();d.monitoring.trend=restartHistory();
  const p=page(d);await p.ready();
  const walk=node=>[node,...node.children.flatMap(walk)];
  let nodes=walk(p.node('content'));
  const singleMarkers=()=>walk(walk(p.node('content')).find(n=>n.attributes['data-chart']==='single')).filter(n=>n.attributes.class==='trend-marker');
  assert.equal(singleMarkers().length,85);
  const range=nodes.find(n=>n.tagName==='select'&&n.attributes['aria-label']==='历史范围');
  assert.ok(range);range.events.change({target:{value:'all'}});
  assert.equal(p.run('state.trendRange'),'all');
  nodes=walk(p.node('content'));assert.equal(singleMarkers().length,214);
  await p.run('refresh()');assert.equal(p.run('state.trendRange'),'all');
  assert.equal(singleMarkers().length,214);
  p.run("location.hash='#monitoring';render()");
  assert.equal(singleMarkers().length,214);
  assert.ok(p.requests.every(url=>url.startsWith('/api/bootstrap')));
});

test('5/10 minute selectors drive both charts, keep default 30 minutes and survive polling and navigation',async()=>{
  const d=fixture();d.monitoring.trend=restartHistory().map((row,i)=>({...row,temperature_c:25+i/100,ph:7+i/1000}));
  const p=page(d);await p.ready();
  const walk=node=>[node,...node.children.flatMap(walk)];
  const nodes=()=>walk(p.node('content'));
  const range=()=>nodes().find(n=>n.tagName==='select'&&n.attributes['aria-label']==='历史范围');
  assert.equal(p.run('state.trendRange'),'1800');
  assert.deepEqual(range().children.map(n=>n.attributes.value),['300','600','1800','3600','all']);
  for(const [value,count,radius] of [['300',31,2.5],['600',61,2],['1800',85,1.35],['3600',85,1.35],['all',214,.65]]){
    range().events.change({target:{value}});
    const charts=nodes().filter(n=>n.attributes['data-chart']);
    assert.equal(charts.length,2);
    assert.equal(walk(charts[0]).filter(n=>n.attributes.class==='trend-marker').length,count);
    assert.ok(walk(charts[0]).filter(n=>n.attributes.class==='trend-marker').every(n=>n.attributes.r===radius));
    assert.equal(walk(charts[1]).filter(n=>n.attributes.class==='trend-marker').length,count*3);
    assert.ok(walk(charts[1]).filter(n=>n.attributes.class==='trend-marker').every(n=>n.attributes.r<=1.35));
  }
  range().events.change({target:{value:'600'}});
  await p.run('refresh()');p.run("location.hash='#monitoring';render()");
  assert.equal(p.run('state.trendRange'),'600');
  assert.ok(nodes().some(n=>n.textContent==='三指标综合趋势（归一化）'));
  assert.ok(p.requests.every(url=>url.startsWith('/api/bootstrap')));
});

test('dashboard keeps AI and connection cards beside trends and one full-row event table with working details',async()=>{
  const d=fixture();d.monitoring.trend=restartHistory();
  const p=page(d);await p.ready();
  const walk=node=>[node,...node.children.flatMap(walk)];
  const hasClass=(node,name)=>(node.className||'').split(/\s+/).includes(name);
  const titles=node=>walk(node).filter(n=>n.tagName==='h2').map(n=>n.textContent);
  const check=()=>{
    const nodes=walk(p.node('content')),grid=nodes.find(n=>hasClass(n,'dashboard-overview'));
    assert.ok(grid);assert.equal(grid.children.length,3);
    assert.deepEqual(titles(grid.children[0]),['历史趋势','三指标综合趋势（归一化）']);
    assert.ok(hasClass(grid.children[1],'dashboard-sidebar'));
    assert.deepEqual(titles(grid.children[1]),['AI 智能助手','连接状态']);
    assert.ok(!nodes.some(n=>hasClass(n,'video-placeholder')));
    assert.ok(hasClass(grid.children[2],'dashboard-events'));
    assert.deepEqual(titles(grid.children[2]),['最近事件']);
    for(const title of ['AI 智能助手','连接状态','最近事件']){
      assert.equal(nodes.filter(n=>n.tagName==='h2'&&n.textContent===title).length,1);
    }
    const eventCard=grid.children[2];
    assert.ok(walk(eventCard).some(n=>n.attributes.href==='#events'&&n.textContent==='全部记录'));
    assert.ok(walk(grid.children[1]).some(n=>n.attributes.href==='#assistant'&&n.textContent.includes('打开助手工作区')));
    walk(eventCard).find(n=>n.tagName==='button'&&n.textContent==='查看详情').events.click();
    assert.equal(p.node('dialog-title').textContent,d.events[0].title);
    assert.ok(p.node('dialog-body').textContent.includes(d.events[0].batch_id));
  };
  check();await p.run('refresh()');check();
  assert.ok(p.requests.every(url=>url.startsWith('/api/bootstrap')));
});

test('actual polling page retains local video node and playback position independently of statistics',async()=>{
  const data=fixture();data.video_preview={kind:'local_file',url:'/media/local-demo.mp4'};
  const p=page(data);await p.ready();
  p.run("location.hash='#video';render()");
  const walk=n=>[n,...n.children.flatMap(walk)],host=p.node('local-video-preview');
  const player=walk(host).find(n=>n.tagName==='video');assert.ok(player);player.currentTime=12;
  data.cameras[0].summary.anomaly_counts.suspected_lesion=7;
  await p.run('refresh()');
  assert.equal(walk(host).find(n=>n.tagName==='video'),player);assert.equal(player.currentTime,12);
  assert.match(p.node('content').textContent,/画面与观测数据独立/);
  p.run("location.hash='#monitoring';render()");assert.equal(host.hidden,true);
  p.run("location.hash='#video';render()");assert.equal(walk(host).find(n=>n.tagName==='video'),player);
  delete data.video_preview;await p.run('refresh()');assert.equal(host.hidden,true);
  assert.match(p.node('content').textContent,/无视频流/);
});


test('video panels collapse independently, persist across polling and never remount playing media',async()=>{
  const data=fixture();data.video_preview={kind:'local_file',url:'/media/local-demo.mp4'};
  const p=page(data);await p.ready();p.run("location.hash='#video';render()");
  const walk=n=>[n,...n.children.flatMap(walk)],find=(label)=>walk(p.node('content')).find(n=>n.getAttribute('aria-label')===label);
  const root=p.node('content').children[0],player=walk(root).find(n=>n.tagName==='video');
  let pauses=0;player.pause=()=>pauses++;player.currentTime=22;
  const left=find('收起左侧数据'),right=find('收起右侧数据');
  left.events.click();assert.equal(left.getAttribute('aria-expanded'),'false');
  assert.equal(root.getAttribute('data-left-collapsed'),'true');assert.equal(root.getAttribute('data-right-collapsed'),'false');
  const body=walk(root).find(n=>n.getAttribute('id')==='video-left-data');assert.equal(body.hidden,true);
  data.monitoring.metrics[2].value=2.2;await p.run('refresh()');
  assert.equal(p.node('content').children[0],root);assert.equal(find('展开左侧数据'),left);
  assert.equal(walk(root).find(n=>n.tagName==='video'),player);assert.equal(player.currentTime,22);assert.equal(pauses,0);
  assert.match(body.textContent,/2.2/);
  const focus=walk(root).find(n=>n.tagName==='button'&&n.textContent==='专注视频');focus.events.click();
  assert.equal(right.getAttribute('aria-expanded'),'false');assert.equal(focus.textContent,'展开两侧数据');
  focus.events.click();assert.equal(left.getAttribute('aria-expanded'),'true');assert.equal(right.getAttribute('aria-expanded'),'true');
  p.run("location.hash='#dashboard';render()");assert.equal(pauses,1);
  p.run("location.hash='#video';render()");assert.equal(p.node('content').children[0],root);
  assert.equal(walk(root).find(n=>n.tagName==='video'),player);
  assert.ok(p.requests.every(url=>url.startsWith('/api/bootstrap')));
});


test('video water panel preserves stale, missing and rule evidence without interpreting the recording as observation',async()=>{
  const data=fixture(2.2);data.monitoring.freshness='stale';data.monitoring.connectivity='offline';data.monitoring.quality='partial';
  data.monitoring.metrics[1].value=null;data.monitoring.metrics[1].quality='missing';
  data.video_preview={kind:'local_file',url:'/media/local-demo.mp4'};
  const p=page(data);await p.ready();p.run("location.hash='#video';render()");
  const text=p.node('content').textContent;
  assert.match(text,/留存读数/);assert.match(text,/已过期/);assert.match(text,/上报中断/);assert.match(text,/不可用/);
  assert.match(text,/不能据此排除风险/);assert.match(text,/LOCAL VIDEO/);assert.doesNotMatch(text,/本窗口未命中已评估规则/);
  data.monitoring.freshness='fresh';data.monitoring.connectivity='online';data.monitoring.findings=[{code:'OXYGEN_CRITICAL_LOW',message:'合成低氧规则信号'}];
  await p.run('refresh()');assert.match(p.node('content').textContent,/合成低氧规则信号/);
  p.setData(new Error('synthetic failure'));await p.run('refresh()');
  assert.equal(p.node('local-video-preview').hidden,true);assert.match(p.node('content').textContent,/上次显示已失效/);
});


test('dashboard prioritizes AI beside trends without a video placeholder and preserves event details',async()=>{
  const d=fixture();d.monitoring.trend=restartHistory();
  const p=page(d);await p.ready();
  const walk=node=>[node,...node.children.flatMap(walk)];
  const hasClass=(node,name)=>(node.className||'').split(/\s+/).includes(name);
  const titles=node=>walk(node).filter(n=>n.tagName==='h2').map(n=>n.textContent);
  const check=()=>{
    const nodes=walk(p.node('content')),grid=nodes.find(n=>hasClass(n,'dashboard-overview'));
    assert.ok(grid);assert.equal(grid.children.length,3);
    assert.deepEqual(titles(grid.children[0]),['历史趋势','三指标综合趋势（归一化）']);
    assert.ok(hasClass(grid.children[1],'dashboard-sidebar'));
    assert.deepEqual(titles(grid.children[1]),['AI 智能助手','连接状态']);
    assert.ok(hasClass(grid.children[1].children[0],'dashboard-assistant'));
    assert.ok(!nodes.some(n=>hasClass(n,'video-placeholder')));
    assert.ok(hasClass(grid.children[2],'dashboard-events'));
    assert.deepEqual(titles(grid.children[2]),['最近事件']);
    for(const title of ['AI 智能助手','连接状态','最近事件']){
      assert.equal(nodes.filter(n=>n.tagName==='h2'&&n.textContent===title).length,1);
    }
    const eventCard=grid.children[2];
    assert.ok(walk(eventCard).some(n=>n.attributes.href==='#events'&&n.textContent==='全部记录'));
    assert.ok(walk(grid.children[1]).some(n=>n.attributes.href==='#assistant'&&n.textContent.includes('打开助手工作区')));
    walk(eventCard).find(n=>n.tagName==='button'&&n.textContent==='查看详情').events.click();
    assert.equal(p.node('dialog-title').textContent,d.events[0].title);
    assert.ok(p.node('dialog-body').textContent.includes(d.events[0].batch_id));
  };
  check();await p.run('refresh()');check();
  assert.ok(p.requests.every(url=>url.startsWith('/api/bootstrap')));
});

const deviceNodes=node=>[node,...node.children.flatMap(deviceNodes)];
const deviceSummaryCard=(p,title)=>deviceNodes(p.node('content')).find(n=>n.className==='card'&&n.children[0]?.textContent.startsWith(title));
function openDeviceHistory(p){
  deviceNodes(p.node('content')).find(n=>n.tagName==='button'&&n.textContent==='查看报告记录').events.click();
  return p.node('dialog-body');
}

test('device integration shows stale detection and keeps original reports as text in history',async()=>{
  const data=fixture();data.integration={simulation_mode:'water-only',device_events:{enabled:true},device_reports:{device_id:'test-board',items:[{
    report:{device_id:'test-board',report_id:'original-1',window:{end:data.monitoring.observed_at,frames_processed:3},
      detection:{unique_tracks:2},behavior:null,measurement:null,has_abnormality:true,
      abnormalities:[{label:'body_ulceration',name:'疑似病灶',targets:1,count:1}],report_text:'<script>untrusted</script>'},
    received_at:data.monitoring.observed_at,warnings:['WINDOW_DURATION_MISMATCH'],freshness:'stale'
  }]}};
  const p=page(data);await p.ready();
  assert.match(p.node('source-notice').textContent,/水质为 SIMULATOR/);
  p.run("location.hash='#video';render()");
  const text=p.node('content').textContent;
  assert.match(text,/设备视觉报告/);assert.match(text,/过期留存/);assert.match(text,/未提供/);
  assert.match(text,/在事件记录中查看外观异常、行为异常和报告更新中断/);
  assert.doesNotMatch(text,/WINDOW_DURATION_MISMATCH|<script>/);
  assert.doesNotMatch(text,/3 \/ 20 有效帧/);
  const history=openDeviceHistory(p);
  assert.match(history.textContent,/WINDOW_DURATION_MISMATCH/);
  assert.match(history.textContent,/<script>untrusted<\/script>/);
  assert.equal(deviceNodes(history).filter(n=>n.tagName==='script').length,0);
  data.integration.device_reports={items:[],error_code:'DEVICE_REPORT_READ_UNAVAILABLE'};
  await p.run('refresh()');assert.match(p.node('content').textContent,/状态未知/);
  assert.doesNotMatch(p.node('content').textContent,/查看报告记录|疑似病灶/);
});

test('device report card distinguishes disabled event sync and bounded sync failure without raw diagnostics',async()=>{
  const data=fixture();data.integration={simulation_mode:'water-only',device_reports:{device_id:'test-board',items:[]}};
  const p=page(data);await p.ready();p.run("location.hash='#video';render()");
  assert.match(p.node('content').textContent,/事件同步未启用或暂不可用/);
  assert.doesNotMatch(p.node('content').textContent,/在事件记录中查看外观异常/);
  data.integration.device_events={enabled:true,error_code:'PRIVATE_INTERNAL_EXCEPTION'};
  p.setData(data);await p.run('refresh()');
  assert.match(p.node('content').textContent,/设备报告已保存，事件同步暂不可用/);
  assert.doesNotMatch(p.node('content').textContent,/PRIVATE_INTERNAL_EXCEPTION|在事件记录中查看外观异常/);
  data.integration.device_events.error_code=null;
  p.setData(data);await p.run('refresh()');
  assert.match(p.node('content').textContent,/在事件记录中查看外观异常、行为异常和报告更新中断/);
  assert.doesNotMatch(p.node('content').textContent,/事件同步暂不可用/);
});

function logicalDeviceFixture(){
  const data=fixture(),time=data.monitoring.observed_at;
  const report={device_id:'test-board',report_id:'logical-report',window:{...data.monitoring.window,frames_processed:2},
    detection:{unique_tracks:12},behavior:{delivery:'full_result_in_report_text'},measurement:{delivery:'full_result_in_report_text'},
    has_abnormality:true,abnormalities:[],report_text:'完整原文 <script>untrusted</script>'};
  const item={report,received_at:time,warnings:[],freshness:'stale',assembly:{status:'complete',received_parts:4,total_parts:4,issue_codes:[]},
    presentation:{detection:{...report.detection,frames_processed:2,window:report.window,avg_per_frame:6,max_per_frame:12,avg_confidence:0,
      abnormalities:[{label:'ascites',name:'疑似腹水',targets:2,count:2}]},
    measurement:{status:'available',source_kind:'video_replay',captured_at:time,counts:{fish_detected:19,fish_measured:10,fish_uncertain:6},
      calibration_status:'uncalibrated',measurement_note:'设备未核实尺度',total_fishes:19,display_truncated:true,fishes:[
        {id:'F01',length_mm:123.4,physical_length_mm:null,status_text:'未标定估计',quality_warnings:['unverified_scale'],association_status:'single_frame_only'},
        {id:'F02',length_mm:null,length_px:null,physical_length_mm:null,status_text:'画面截断',quality_warnings:[]},
        {id:'F03',length_mm:null,length_px:88,status_text:'需复核',physical_length_mm:null,quality_warnings:[]}]},
    behavior:{status:'available',source_kind:'video_replay',captured_at:time,model:'synthetic-behavior',clip_count:2,anomalous_clips:1,
      anomalous_reported:1,unknown_clips:0,clips:[{start_s:0,end_s:1.2,score:4.8,anomaly:true},{start_s:.6,end_s:1.8,score:0,anomaly:false}]}},
    raw_parts:Array.from({length:4},(_,i)=>({report_id:`raw-${i+1}`,report_text:`分片 ${i+1} <script>raw</script>`,received_at:time}))};
  data.integration={simulation_mode:'water-only',device_reports:{device_id:'test-board',items:item.raw_parts.map(part=>({report:{...report,...part}})),logical_items:[item]}};
  return {data,item};
}

test('logical device reports show direct summaries and keep full per-target details in history',async()=>{
  const {data}=logicalDeviceFixture(),p=page(data);await p.ready();p.run("location.hash='#video';render()");
  const text=p.node('content').textContent;
  for(const value of ['检测结果','行为分析','跟踪目标（非存量）12','录像回放推理（非实时摄像头）',
    '疑似腹水 · 2 个目标','非确诊','分析片段2','模型标记异常1'])assert.ok(text.includes(value),value);
  assert.doesNotMatch(text,/体长测量|处理帧2|待复核6|原始报告与分包|raw-4|123.4/);
  assert.doesNotMatch(text,/已提供原始对象，尚未解释|123.4 cm|实时摄像头已连接/);
  const history=openDeviceHistory(p),nodes=deviceNodes(history);
  for(const value of ['最近 1 份完整报告','分包已合并 4/4','123.4 mm（估计）','画面截断','未取得长度','88 px（像素）',
    '未核实物理标定','不能相加为鱼数','分数不是概率','原始报告与分包','raw-4'])assert.ok(history.textContent.includes(value),value);
  assert.equal(nodes.filter(n=>n.tagName==='script').length,0);
  const detection=nodes.find(n=>n.className==='device-task'&&n.textContent.startsWith('检测结果'));
  assert.ok(detection.textContent.includes('设备上报平均置信度0'));
  const labels=['检测统计与信号依据','测量依据与限制','查看行为片段','原始报告与分包（留存证据）','raw-1'];
  for(const label of labels){
    const detail=nodes.find(n=>n.tagName==='details'&&n.children[0]?.textContent===label);
    assert.equal(detail.getAttribute('open'),null);
    detail.open=true;detail.events.toggle({target:detail});
  }
  await p.run('refresh()');
  const refreshed=deviceNodes(openDeviceHistory(p));
  for(const label of labels)assert.equal(refreshed.find(n=>n.tagName==='details'&&n.children[0]?.textContent===label).getAttribute('open'),'');
});

test('device report history selects one result in the existing wide dialog without network I/O',async()=>{
  const {data,item}=logicalDeviceFixture();
  const older=structuredClone(item);older.report.report_id='older-result';older.raw_parts[0].report_id='older-raw-1';
  older.presentation.measurement={status:'missing'};older.presentation.behavior={status:'missing'};
  data.integration.device_reports.logical_items.push(older);
  const p=page(data);await p.ready();p.run("location.hash='#video';render()");
  let opened=0;p.node('details-dialog').showModal=()=>{opened++;};
  const requests=p.requests.length,body=openDeviceHistory(p);
  assert.equal(opened,1);
  assert.equal(p.node('dialog-title').textContent,'设备报告记录');
  assert.equal(body.children[0].className,'device-report-wide');
  for(const text of ['logical-report','过期／未知','检测结果','体长测量','行为分析','原始报告与分包','raw-4']){
    assert.ok(body.textContent.includes(text),text);
  }
  const select=deviceNodes(body).find(n=>n.tagName==='select');
  assert.equal(select.children.length,2);
  assert.match(select.children[0].textContent,/附体长／行为/);
  assert.match(select.children[1].textContent,/检测统计/);
  select.events.change({target:{value:'1'}});
  assert.match(body.textContent,/older-result.*older-raw-1/s);
  assert.doesNotMatch(body.textContent,/logical-report/);
  assert.equal(deviceNodes(body).filter(n=>n.tagName==='script').length,0);
  assert.equal(p.requests.length,requests);
  p.run("details('其他详情',[el('p',{text:'普通内容'})])");
  assert.equal(body.textContent,'普通内容');
  assert.equal(deviceNodes(body).some(n=>n.className==='device-report-wide'),false);
});

test('device summary keeps length in history and selects behavior capture independently',async()=>{
  const {data,item}=logicalDeviceFixture();item.freshness='fresh';
  item.presentation.measurement.captured_at='2026-10-13T23:59:45+00:00';
  item.presentation.behavior.captured_at='2026-10-14T00:00:08+00:00';
  const older=structuredClone(item);older.report.report_id='older-report';older.report.window.end='2026-10-13T23:59:55+00:00';
  older.presentation.detection.unique_tracks=999;older.freshness='stale';
  older.presentation.measurement.captured_at='2026-10-13T23:59:50+00:00';
  older.presentation.measurement.counts.fish_measured=41;
  older.presentation.behavior.captured_at='2026-10-13T23:59:54+00:00';older.presentation.behavior.clip_count=123;
  data.integration.device_reports.logical_items.push(older);
  const p=page(data);await p.ready();p.run("location.hash='#video';render()");
  const detection=deviceSummaryCard(p,'检测结果').textContent;
  const behavior=deviceSummaryCard(p,'行为分析').textContent;
  assert.match(detection,/近期报告.*08:00:10.*跟踪目标（非存量）12/);assert.doesNotMatch(detection,/999/);
  assert.equal(deviceSummaryCard(p,'体长测量'),undefined);
  assert.match(openDeviceHistory(p).textContent,/体长测量.*07:59:45.*19 \/ 10 \/ 6/s);
  assert.match(behavior,/08:00:08.*分析片段2/);assert.doesNotMatch(behavior,/123|07:59:54/);
});

function deviceTransferCheck(history){
  const transfer=history.children[0].children.find(n=>n.tagName==='details'&&n.children[0]?.textContent.startsWith('传输检查'));
  assert.ok(transfer);
  assert.equal(transfer.getAttribute('open'),null);
  return transfer;
}

test('a newer incomplete group leaves the latest complete report and its freshness in normal view',async()=>{
  const {data,item}=logicalDeviceFixture();
  const newer=structuredClone(item);
  newer.report.report_id='new-partial';newer.report.window.end='2026-10-14T00:01:10+00:00';newer.freshness='fresh';
  newer.assembly={status:'incomplete',received_parts:3,total_parts:4,issue_codes:[]};
  newer.raw_parts=newer.raw_parts.slice(0,3).map(part=>({...part,report_id:`pending-${part.report_id}`}));
  newer.presentation.detection.unique_tracks=999;
  newer.presentation.measurement.captured_at=newer.report.window.end;newer.presentation.measurement.counts.fish_measured=888;
  newer.presentation.behavior.captured_at=newer.report.window.end;newer.presentation.behavior.clip_count=777;
  data.integration.device_reports.logical_items.unshift(newer);
  const p=page(data);await p.ready();p.run("location.hash='#video';render()");
  const text=p.node('content').textContent;
  assert.match(deviceSummaryCard(p,'检测结果').textContent,/过期留存.*08:00:10.*跟踪目标（非存量）12/);
  assert.equal(deviceSummaryCard(p,'体长测量'),undefined);
  assert.match(deviceSummaryCard(p,'行为分析').textContent,/分析片段2/);
  assert.doesNotMatch(text,/999|888|777|08:01:10|3\/4|等待完整报告/);
  const history=openDeviceHistory(p);
  const select=deviceNodes(history).find(n=>n.tagName==='select'&&n.getAttribute('aria-label')==='选择报告');
  assert.equal(select.children.length,1);
  const transfer=deviceTransferCheck(history);
  assert.match(transfer.textContent,/分包收集中 3\/4.*pending-raw-1/s);
  assert.doesNotMatch(history.children[0].children.filter(n=>n!==transfer).map(n=>n.textContent).join(''),/new-partial|3\/4/);
});

test('partial-only or invalid history waits for a complete report while preserving diagnostic evidence',async()=>{
  const {data,item}=logicalDeviceFixture(),complete=structuredClone(item);
  item.report.report_text='';item.raw_parts=item.raw_parts.slice(0,3);
  item.assembly={status:'incomplete',received_parts:3,total_parts:4,issue_codes:[]};
  item.presentation.measurement={status:'pending'};item.presentation.behavior={status:'pending'};
  const p=page(data);await p.ready();p.run("location.hash='#video';render()");
  let text=p.node('content').textContent;
  assert.match(text,/等待完整报告/);
  assert.doesNotMatch(text,/跟踪目标（非存量）12|123.4|模型估长|synthetic-behavior|raw-1|3\/4/);
  let history=openDeviceHistory(p);
  assert.match(history.textContent,/等待完整报告/);
  assert.equal(deviceNodes(history).some(n=>n.tagName==='select'&&n.getAttribute('aria-label')==='选择报告'),false);
  assert.match(deviceTransferCheck(history).textContent,/分包收集中 3\/4.*raw-1/s);
  item.assembly.status='invalid';item.assembly.issue_codes=['CONTENT_HASH_MISMATCH'];p.setData(data);await p.run('refresh()');
  text=p.node('content').textContent;
  assert.match(text,/等待完整报告/);
  assert.doesNotMatch(text,/分包无法合并|内容摘要核验通过|CONTENT_HASH_MISMATCH/);
  history=openDeviceHistory(p);
  assert.match(deviceTransferCheck(history).textContent,/分包无法合并.*CONTENT_HASH_MISMATCH/s);
  data.integration.device_reports.logical_items=[complete];p.setData(data);await p.run('refresh()');
  assert.match(deviceSummaryCard(p,'检测结果').textContent,/跟踪目标（非存量）12/);
  assert.doesNotMatch(p.node('content').textContent,/等待完整报告/);
});

test('legacy raw fragments stay in transmission check and ordinary single reports remain visible',async()=>{
  const {data,item}=logicalDeviceFixture(),inbox=data.integration.device_reports;
  delete inbox.logical_items;
  const single={...item,report:{...item.report,report_id:'legacy-single'}};
  const fragment={...item,report:{...item.report,report_id:`web-${'a'.repeat(40)}-3`,
    report_text:'【结果分包 3/4；SHA256=example】\n留存分片'} };
  delete single.assembly;delete fragment.assembly;
  inbox.items=[fragment,single];
  const p=page(data);await p.ready();p.run("location.hash='#video';render()");
  assert.match(deviceSummaryCard(p,'检测结果').textContent,/跟踪目标（非存量）12/);
  const history=openDeviceHistory(p);
  const select=deviceNodes(history).find(n=>n.tagName==='select'&&n.getAttribute('aria-label')==='选择报告');
  assert.equal(select.children.length,1);
  const transfer=deviceTransferCheck(history);
  assert.match(transfer.textContent,/分包待核对.*留存分片/s);
  assert.doesNotMatch(history.children[0].children.filter(n=>n!==transfer).map(n=>n.textContent).join(''),/留存分片/);
});

test('missing or unknown task objects remain unknown while known unflagged behavior is not called healthy',async()=>{
  const {data,item}=logicalDeviceFixture();item.presentation.measurement={status:'unrecognized'};item.presentation.behavior={status:'missing'};
  const p=page(data);await p.ready();p.run("location.hash='#video';render()");
  let text=p.node('content').textContent;assert.match(text,/本轮未提供结果，不代表正常/);
  assert.match(openDeviceHistory(p).textContent,/当前格式尚不能解释/);
  item.presentation.behavior={status:'available',source_kind:null,captured_at:null,clip_count:1,anomalous_clips:0,unknown_clips:0,
    anomalous_reported:0,clips:[{start_s:0,end_s:1,score:0,anomaly:false}]};
  p.setData(data);await p.run('refresh()');text=p.node('content').textContent;
  const behavior=deviceSummaryCard(p,'行为分析').textContent;
  assert.match(behavior,/模型标记异常0.*采集时间未知，按报告顺序显示留存结果/);
  assert.doesNotMatch(behavior,/来源未提供|全部正常|疾病已经治愈/);
});


test('peak reports separate counts, video versions and folded technical evidence',async()=>{
  const {data,item}=logicalDeviceFixture();
  item.freshness='fresh';
  item.receive_delay_seconds=1.25;
  item.presentation.detection.aggregation_policy='peak_frame_v1';
  item.presentation.detection.count_semantics='detections_in_one_peak_frame';
  item.presentation.detection.report_context={observed_detection_frames:15,observed_abnormality_frames:9,detection_timestamp_ms:1e20};
  item.presentation.behavior={status:'available',kind:'videos',source_kind:'video_replay',new_result:false,
    result_timestamp:'2026-10-13T23:58:10+00:00',report_id:'version-1',video_count:2,anomalous_videos:1,unknown_videos:0,
    videos:[{video_name:'fixture-clip-a.mp4',is_abnormal:true,threshold:0.37},
      {video_name:'fixture-clip-b.mp4',is_abnormal:false}]};
  const p=page(data);await p.ready();p.run("location.hash='#video';render()");
  assert.match(deviceSummaryCard(p,'检测结果').textContent,/峰值帧可见目标（非存量）12.*疑似腹水 · 2 个目标/s);
  assert.match(deviceSummaryCard(p,'行为分析').textContent,/结果文件版本时间.*07:58:10.*异常 \/ 视频总数1 \/ 2.*重复携带/s);
  assert.doesNotMatch(p.node('content').textContent,/体长测量|帧次|fixture-clip|阈值/);
  const history=openDeviceHistory(p),nodes=deviceNodes(history);
  assert.match(history.textContent,/接收延迟（秒）1.25.*异常峰值帧 2 个目标.*fixture-clip-a.mp4/s);
  assert.doesNotMatch(history.textContent,/2 帧次/);
  assert.match(history.textContent,/鱼群峰值帧时间未提供/);
  const advanced=nodes.find(n=>n.tagName==='details'&&n.children[0]?.textContent==='行为模型与逐视频指标');
  assert.equal(advanced.getAttribute('open'),null);
  assert.match(advanced.textContent,/结果编号version-1.*模型阈值0.37/s);
  const transport=nodes.find(n=>n.tagName==='details'&&n.children[0]?.textContent==='原始报告与分包（留存证据）');
  assert.equal(transport.getAttribute('open'),null);
  assert.match(transport.textContent,/报告字段（JSON）.*"device_id": "test-board"/s);
});

test('device event evidence distinguishes appearance, behavior and recovered report updates',async()=>{
  const data=fixture(),time=data.monitoring.observed_at;
  const report={report_id:'evidence-report',window:{...data.monitoring.window,frames_processed:222}};
  const evidence=[
    ['DEVICE_REPORT_APPEARANCE','ACTIVE',{kind:'appearance',labels:[{label:'ascites',targets:2,count:2}]}],
    ['DEVICE_REPORT_BEHAVIOR','ACTIVE',{kind:'behavior',result_id:'version-2',result_timestamp:time,abnormal_videos:['fixture-behavior.mp4']}],
    ['DEVICE_REPORT_GAP','RESOLVED',{kind:'gap',last_window_end:time,threshold_seconds:180,resumed_window_end:time}]
  ];
  const base=data.events[0];
  data.events=evidence.map(([code,lifecycle_state,device_report_event],i)=>({...base,id:'device-event-'+i,source_kind:'device_report',
    channel:'visual',code,lifecycle_state,device_report_event,device_report:i===2?undefined:report}));
  const p=page(data);await p.ready();
  const show=i=>{p.run('eventDetail(state.data.events['+i+'])');return p.node('dialog-body').textContent;};
  assert.match(show(0),/外观检测证据.*异常峰值帧目标数.*腹水信号（ascites）2/s);
  assert.doesNotMatch(show(0),/检出帧次/);
  assert.match(show(1),/待核查.*行为文件证据.*version-2.*fixture-behavior.mp4/s);
  assert.match(show(2),/上报已恢复.*报告更新记录.*未更新时限（秒）180.*恢复更新的窗口/s);
  assert.doesNotMatch(show(2),/未证实恢复|疾病消退/);
  const grouped=p.run("eventsTable([{...state.data.events[2],cycle_summary:{ended:true,count:1}}]).textContent");
  assert.match(grouped,/恢复更新.*上报已恢复/s);
  assert.doesNotMatch(grouped,/恢复 \/ 原结束/);
});

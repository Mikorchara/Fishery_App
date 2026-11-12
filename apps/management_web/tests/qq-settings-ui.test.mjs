import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {Element} from './dom-fixture.mjs';
import {tick} from './assistant-fixture.mjs';

const walk=n=>[n,...n.children.flatMap(walk)];
function setup(workspace=false,pairing=false){
  const data={revision:'synthetic-r1',browser_token:'synthetic-browser',configured:false,
    settings:{enabled:false,ai_enabled:false,max_output_tokens:2048,event_notifications_enabled:false},
    identity:{app_ref:null,group_ref:null,member_refs:[]},
    binding:{data_root:'synthetic/data',instance_id:'synthetic',device_id:'synthetic-pond'},recipient_available:false,
    recipient_ref:null,runtime_status:'NOT_CHECKED',secret_status:'NOT_CHECKED'};
  const writes=[],keys=[],pairingCalls=[],timers=[],cleared=[];let reads=0;
  const pairingState={pairing_id:'synthetic-pair',phase:'IDLE',user_ref:null};
  const api={read:async()=>{reads++;return structuredClone(data);},save:async v=>{writes.push(structuredClone(v));
    const {app_id,group_id,members,...settings}=v.settings;
    if(app_id)data.identity.app_ref='000000000001';
    if(group_id)data.identity.group_ref='000000000002';
    if(members.length)data.identity.member_refs=members.map((_,i)=>(i+3).toString(16).padStart(12,'0'));
    data.settings=settings;data.revision='synthetic-r2';return structuredClone(data);},secret:async v=>{keys.push(structuredClone(v));
    data.secret_status='SAVED_FOR_THIS_APP';data.revision='synthetic-r3';return structuredClone(data);}};
  if(pairing)Object.assign(api,{
    pairingStatus:async()=>({pairing:structuredClone(pairingState)}),
    pairingStart:async v=>{pairingCalls.push({action:'start',value:structuredClone(v)});pairingState.phase='WAITING_PRIVATE_MESSAGE';
      return {pairing:{...pairingState,challenge_command:'/绑定提醒 synthetic-single-display'}};},
    pairingConfirm:async v=>{pairingCalls.push({action:'confirm',value:structuredClone(v)});pairingState.phase='BOUND';
      return {pairing:{...pairingState,api_accepted:true,client_display_confirmed:false,cleanup_confirmed:true}};},
    pairingCancel:async v=>{pairingCalls.push({action:'cancel',value:structuredClone(v)});pairingState.phase='CANCELLED';
      return {pairing:{...pairingState,cleanup_confirmed:true}};}});
  const context=vm.createContext({console,Node:Element,setInterval:f=>{timers.push(f);return timers.length;},clearInterval:n=>cleared.push(n),
    document:{createElement:t=>new Element(t),createElementNS:(ns,t)=>new Element(t),
    createTextNode:t=>{const n=new Element('text');n.textContent=t;return n;}}});
  for(const file of ['components.js','qq-settings.js',...(workspace?['settings.js']:[])])vm.runInContext(
    fs.readFileSync(new URL('../static/'+file,import.meta.url),'utf8').replace(/^import .*;\s*$/gm,'').replace(/\bexport /g,''),context,{filename:file});
  context.qqAPI=api;context.settingsAPI={read:async()=>{throw new Error('AI_DISABLED');},qq:api};context.toolPanel={mount:()=>new Element('tools')};
  const panel=vm.runInContext(workspace?'createSettingsWorkspace(settingsAPI,toolPanel)':'createQQSettingsPanel(qqAPI)',context);
  const root=workspace?panel.mount():panel.node;if(!workspace)void panel.load();
  const find=text=>walk(root).find(n=>n.tagName==='button'&&n.textContent===text);
  const input=label=>walk(root).find(n=>n.getAttribute('aria-label')===label);
  return {panel,root,find,input,api,writes,keys,data,pairingCalls,pairingState,timers,cleared,get reads(){return reads;}};
}

test('QQ settings remain usable when Web Assistant is disabled',async()=>{
  const p=setup(true);await tick();p.find('QQ机器人').events.click();
  assert.ok(p.input('每次模型请求最大输出 Token'));
  assert.match(p.root.textContent,/synthetic-pond/);assert.equal(p.reads,1);
  assert.equal(p.writes.length,0);assert.equal(p.keys.length,0);
});

test('token draft save uses independent QQ API with exact units and bounds',async()=>{
  const p=setup();await tick();const token=p.input('每次模型请求最大输出 Token');token.value='4096';
  p.find('保存 QQ 设置').events.click();await tick();
  assert.equal(p.writes[0].settings.max_output_tokens,4096);assert.equal(p.writes[0].revision,'synthetic-r1');
  assert.match(p.root.textContent,/多次模型请求/);assert.match(p.root.textContent,/停止并重新启动/);
  token.value='4097';p.find('保存 QQ 设置').events.click();await tick();assert.equal(p.writes.length,1);
});

test('identity and member drafts are explicit; secret is separate and cleared',async()=>{
  const p=setup();await tick();p.input('QQ AppID').value='123456';p.input('测试群 OpenID').value='synthetic-group';
  p.input('授权成员 OpenID（每行一名，最多4名）').value='member-a\nmember-b';
  p.input('启用 QQ 机器人（仍须单独启动）').checked=true;
  p.find('保存 QQ 设置').events.click();await tick();assert.deepEqual(p.writes[0].settings.members,['member-a','member-b']);
  const secret=p.input('QQ AppSecret');secret.value='fictional-secret';p.find('保存 QQ AppSecret').events.click();await tick();
  assert.equal(secret.value,'');assert.equal(p.keys[0].revision,'synthetic-r2');
  assert.equal(p.keys[0].app_secret,'fictional-secret');assert.doesNotMatch(p.root.textContent,/fictional-secret/);
  assert.ok(!('app_secret' in p.writes[0].settings));
});

test('saved identities are summarized and blank fields preserve them when saving other settings',async()=>{
  const p=setup();await tick();
  p.data.configured=true;
  p.data.identity={app_ref:'aaaaaaaaaaaa',group_ref:'bbbbbbbbbbbb',member_refs:['cccccccccccc']};
  Object.assign(p.data.settings,{app_id:'123456',group_id:'old-group',members:['old-member']});
  await p.panel.load();
  const app=p.input('QQ AppID'),group=p.input('测试群 OpenID'),members=p.input('授权成员 OpenID（每行一名，最多4名）');
  assert.deepEqual([app.value,group.value,members.value],['','','']);
  assert.doesNotMatch(p.root.textContent,/123456|old-group|old-member/);
  assert.match(p.root.textContent,/aaaaaaaaaaaa.*bbbbbbbbbbbb.*1 名 · cccccccccccc/);
  p.input('每次模型请求最大输出 Token').value='4096';
  p.find('保存 QQ 设置').events.click();await tick();
  assert.equal(p.writes[0].settings.app_id,'');assert.equal(p.writes[0].settings.group_id,'');
  assert.deepEqual(p.writes[0].settings.members,[]);
  assert.match(p.root.textContent,/aaaaaaaaaaaa.*bbbbbbbbbbbb.*1 名 · cccccccccccc/);

  group.value='new-group';members.value='new-member';
  p.find('保存 QQ 设置').events.click();await tick();
  assert.equal(p.writes[1].settings.group_id,'new-group');assert.deepEqual(p.writes[1].settings.members,['new-member']);
  assert.deepEqual([app.value,group.value,members.value],['','','']);
  assert.match(p.root.textContent,/aaaaaaaaaaaa.*000000000002.*1 名 · 000000000003/);
});

test('saving QQ settings does not recreate the password field or lose its unsubmitted draft',async()=>{
  const p=setup();await tick();const key=p.input('QQ AppSecret');key.value='fictional-unsubmitted';
  p.find('保存 QQ 设置').events.click();await tick();assert.equal(p.input('QQ AppSecret'),key);
  assert.equal(key.value,'fictional-unsubmitted');assert.equal(p.keys.length,0);
});

test('QQ HTTP client uses its own local token and preserves bounded API errors',async()=>{
  const calls=[];let fail=false;
  const context=vm.createContext({fetch:async(path,options)=>{calls.push({path,options});
    return {ok:!fail,json:async()=>fail?{error_code:'QQ_SETTINGS_NOT_CONNECTED'}:{revision:'synthetic'}};}});
  vm.runInContext(fs.readFileSync(new URL('../static/services.js',import.meta.url),'utf8')
    .replace(/^import .*;\s*$/gm,'').replace(/\bexport /g,''),context);
  await vm.runInContext('services.settings.qq.read()',context);
  await vm.runInContext("services.settings.qq.save({revision:'r',settings:{}},{browser_token:'fictional-local-token'})",context);
  assert.equal(calls[0].path,'/api/settings/qq');assert.equal(calls[1].options.method,'POST');
  assert.equal(calls[1].options.headers['X-Management-QQ'],'fictional-local-token');
  assert.ok(!('X-Management-AI' in calls[1].options.headers));
  fail=true;await assert.rejects(vm.runInContext('services.settings.qq.read()',context),/QQ_SETTINGS_NOT_CONNECTED/);
});

test('private pairing requires separate network and active-send confirmation and never persists its challenge',async()=>{
  const p=setup(false,true);await tick();p.find('开始首次私聊配对').events.click();await tick();assert.equal(p.pairingCalls.length,0);
  p.input('同意本次短时连接 QQ（不调用模型）').checked=true;p.find('开始首次私聊配对').events.click();await tick();
  assert.equal(p.pairingCalls[0].value.confirm_network,true);assert.match(p.root.textContent,/synthetic-single-display/);
  p.pairingState.phase='AWAITING_CONFIRMATION';p.pairingState.user_ref='synthetic-ref';await p.timers[0]();await tick();
  assert.doesNotMatch(p.root.textContent,/synthetic-single-display/);assert.equal(p.pairingCalls.length,1);
  p.find('确认此接收人，并发送 1 条主动测试消息').events.click();await tick();
  assert.equal(p.pairingCalls[1].value.confirm_active_test,true);assert.equal(p.pairingCalls[1].value.user_ref,'synthetic-ref');
  assert.match(p.root.textContent,/QQ API 已接受/);assert.match(p.root.textContent,/客户端显示须本人核对/);
  assert.match(p.root.textContent,/通知仍关闭/);assert.equal(p.keys.length,0);
});

test('cancel clears the one-time command without submitting an active message',async()=>{
  const p=setup(false,true);await tick();p.input('同意本次短时连接 QQ（不调用模型）').checked=true;
  p.find('开始首次私聊配对').events.click();await tick();p.find('取消配对').events.click();await tick();
  assert.deepEqual(p.pairingCalls.map(v=>v.action),['start','cancel']);
  assert.doesNotMatch(p.root.textContent,/synthetic-single-display/);assert.ok(p.cleared.length);
});

test('recipient guidance points to this page and failed pairing never claims no network happened',async()=>{
  const p=setup(false,true);await tick();
  p.api.save=async()=>{throw new Error('QQ_VERIFIED_RECIPIENT_REQUIRED');};
  p.find('保存 QQ 设置').events.click();await tick();
  assert.match(p.root.textContent,/请在本页完成“首次私聊接收人配对”/);assert.doesNotMatch(p.root.textContent,/负责人提供/);
  p.api.pairingStart=async()=>{throw new Error('SENSITIVE_INTERNAL_DETAIL');};
  p.input('同意本次短时连接 QQ（不调用模型）').checked=true;p.find('开始首次私聊配对').events.click();await tick();
  assert.match(p.root.textContent,/配对失败不会自动重发/);
  assert.doesNotMatch(p.root.textContent,/未进行联网测试|SENSITIVE_INTERNAL_DETAIL/);
});

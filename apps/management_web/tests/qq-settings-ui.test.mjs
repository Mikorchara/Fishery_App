import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {Element} from './dom-fixture.mjs';
import {tick} from './assistant-fixture.mjs';

const walk=n=>[n,...n.children.flatMap(walk)];
const memberInputs=root=>walk(root).filter(n=>n.tagName==='input'&&/^成员 \d+ OpenID$/.test(n.getAttribute('aria-label')||''));

function fillMember(p,index,value){
  const input=p.input(`成员 ${index} OpenID`);
  input.value=value;
  input.events.input?.({target:input});
}

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
    if(app_id&&group_id&&members.length)data.configured=true;
    data.settings=settings;data.revision='synthetic-r2';return structuredClone(data);},secret:async v=>{keys.push(structuredClone(v));
    data.secret_status='SAVED_FOR_THIS_APP';data.revision='synthetic-r3';return structuredClone(data);}};
  if(pairing)Object.assign(api,{
    pairingStatus:async()=>({pairing:structuredClone(pairingState)}),
    pairingStart:async v=>{pairingCalls.push({action:'start',value:structuredClone(v)});pairingState.phase='WAITING_PRIVATE_MESSAGE';
      return {pairing:{...pairingState,challenge_command:'/绑定提醒 synthetic-single-display'}};},
    pairingConfirm:async v=>{pairingCalls.push({action:'confirm',value:structuredClone(v)});pairingState.phase='BOUND';
      data.recipient_available=true;data.recipient_ref=pairingState.user_ref;data.settings.event_notifications_enabled=false;
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
  fillMember(p,1,'member-a');p.find('添加成员').events.click();fillMember(p,2,'member-b');
  p.input('启用 QQ 机器人（仍须单独启动）').checked=true;
  p.find('保存 QQ 设置').events.click();await tick();assert.deepEqual(p.writes[0].settings.members,['member-a','member-b']);
  const secret=p.input('QQ AppSecret');secret.value='fictional-secret';p.find('保存 QQ AppSecret').events.click();await tick();
  assert.equal(secret.value,'');assert.equal(p.keys[0].revision,'synthetic-r2');
  assert.equal(p.keys[0].app_secret,'fictional-secret');assert.doesNotMatch(p.root.textContent,/fictional-secret/);
  assert.ok(!('app_secret' in p.writes[0].settings));
});

test('member list preserves input order, allows removal, and stops at four members',async()=>{
  const p=setup();await tick();
  assert.equal(memberInputs(p.root).length,1);
  assert.equal(walk(p.root).some(n=>n.tagName==='textarea'),false);
  fillMember(p,1,' member-a ');
  for(let index=2;index<=4;index++){
    p.find('添加成员').events.click();
    fillMember(p,index,`member-${index}`);
  }
  assert.deepEqual(memberInputs(p.root).map(n=>n.value),[' member-a ','member-2','member-3','member-4']);
  const add=p.find('添加成员');
  assert.ok(!add||add.disabled||add.getAttribute('disabled')!==null);
  p.input('移除成员 2').events.click();
  assert.deepEqual(memberInputs(p.root).map(n=>n.value),[' member-a ','member-3','member-4']);
  p.find('添加成员').events.click();
  assert.equal(memberInputs(p.root).length,4);
  p.input('QQ AppID').value='123456';p.input('测试群 OpenID').value='synthetic-group';
  p.find('保存 QQ 设置').events.click();await tick();
  assert.deepEqual(p.writes[0].settings.members,['member-a','member-3','member-4']);
  assert.deepEqual(memberInputs(p.root).map(n=>n.value),['']);
  fillMember(p,1,'remove-this-draft');p.input('移除成员 1').events.click();
  assert.deepEqual(memberInputs(p.root).map(n=>n.value),['']);
});

test('saved identities are summarized and blank fields preserve them when saving other settings',async()=>{
  const p=setup();await tick();
  p.data.configured=true;
  p.data.identity={app_ref:'aaaaaaaaaaaa',group_ref:'bbbbbbbbbbbb',member_refs:['cccccccccccc']};
  Object.assign(p.data.settings,{app_id:'123456',group_id:'old-group',members:['old-member']});
  await p.panel.load();
  const app=p.input('QQ AppID'),group=p.input('测试群 OpenID'),members=p.input('成员 1 OpenID');
  assert.deepEqual([app.value,group.value,members.value],['','','']);
  assert.doesNotMatch(p.root.textContent,/123456|old-group|old-member/);
  for(const ref of ['aaaaaaaaaaaa','bbbbbbbbbbbb','cccccccccccc'])assert.ok(p.root.textContent.includes(ref));
  p.input('每次模型请求最大输出 Token').value='4096';
  p.find('保存 QQ 设置').events.click();await tick();
  assert.equal(p.writes[0].settings.app_id,'');assert.equal(p.writes[0].settings.group_id,'');
  assert.deepEqual(p.writes[0].settings.members,[]);
  for(const ref of ['aaaaaaaaaaaa','bbbbbbbbbbbb','cccccccccccc'])assert.ok(p.root.textContent.includes(ref));

  p.input('测试群 OpenID').value='new-group';fillMember(p,1,'new-member');
  p.find('保存 QQ 设置').events.click();await tick();
  assert.equal(p.writes[1].settings.group_id,'new-group');assert.deepEqual(p.writes[1].settings.members,['new-member']);
  assert.deepEqual([p.input('QQ AppID').value,p.input('测试群 OpenID').value,p.input('成员 1 OpenID').value],['','','']);
  for(const ref of ['aaaaaaaaaaaa','000000000002','000000000003'])assert.ok(p.root.textContent.includes(ref));
});

test('saving QQ settings does not recreate the password field or lose its unsubmitted draft',async()=>{
  const p=setup();await tick();const key=p.input('QQ AppSecret');key.value='fictional-unsubmitted';
  p.find('保存 QQ 设置').events.click();await tick();assert.equal(p.input('QQ AppSecret'),key);
  assert.equal(key.value,'fictional-unsubmitted');assert.equal(p.keys.length,0);
});

test('credentials and private pairing are in separate disclosures closed by default',async()=>{
  const p=setup(false,true);await tick();
  for(const [title,button] of [['QQ AppSecret','保存 QQ AppSecret'],['首次私聊接收人配对','开始首次私聊配对']]){
    const section=walk(p.root).find(n=>n.tagName==='details'&&n.children[0]?.tagName==='summary'
      &&n.children[0].textContent.includes(title));
    assert.ok(section?.contains(p.find(button)));
    assert.equal(section.getAttribute('open'),null);
    assert.ok(!section.open);
  }
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
  const p=setup(false,true);await tick();p.data.recipient_available=true;p.data.settings.event_notifications_enabled=true;
  await p.panel.load();
  const notifications=p.input('启用已验证接收人的事件通知');assert.equal(notifications.checked,true);
  p.find('开始首次私聊配对').events.click();await tick();assert.equal(p.pairingCalls.length,0);
  p.input('同意本次短时连接 QQ（不调用模型）').checked=true;p.find('开始首次私聊配对').events.click();await tick();
  assert.equal(p.pairingCalls[0].value.confirm_network,true);assert.match(p.root.textContent,/synthetic-single-display/);
  p.pairingState.phase='AWAITING_CONFIRMATION';p.pairingState.user_ref='synthetic-ref';await p.timers[0]();await tick();
  assert.doesNotMatch(p.root.textContent,/synthetic-single-display/);assert.equal(p.pairingCalls.length,1);
  p.find('确认此接收人，并发送 1 条主动测试消息').events.click();await tick();
  assert.equal(p.pairingCalls[1].value.confirm_active_test,true);assert.equal(p.pairingCalls[1].value.user_ref,'synthetic-ref');
  assert.match(p.root.textContent,/QQ API 已接受/);assert.match(p.root.textContent,/客户端显示须本人核对/);
  assert.match(p.root.textContent,/通知仍关闭/);assert.equal(p.keys.length,0);
  assert.equal(notifications.checked,false);
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

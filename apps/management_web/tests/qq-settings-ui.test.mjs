import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {Element} from './dom-fixture.mjs';
import {tick} from './assistant-fixture.mjs';

const walk=n=>[n,...n.children.flatMap(walk)];
function setup(workspace=false){
  const data={revision:'synthetic-r1',browser_token:'synthetic-browser',configured:false,
    settings:{enabled:false,ai_enabled:false,app_id:'',group_id:'',members:[],max_output_tokens:2048,event_notifications_enabled:false},
    binding:{data_root:'synthetic/data',instance_id:'synthetic',device_id:'synthetic-pond'},recipient_available:false,
    recipient_ref:null,runtime_status:'NOT_CHECKED',secret_status:'NOT_CHECKED'};
  const writes=[],keys=[];let reads=0;
  const api={read:async()=>{reads++;return structuredClone(data);},save:async v=>{writes.push(structuredClone(v));
    data.settings=v.settings;data.revision='synthetic-r2';return structuredClone(data);},secret:async v=>{keys.push(structuredClone(v));
    data.secret_status='SAVED_FOR_THIS_APP';data.revision='synthetic-r3';return structuredClone(data);}};
  const context=vm.createContext({console,Node:Element,document:{createElement:t=>new Element(t),createElementNS:(ns,t)=>new Element(t),
    createTextNode:t=>{const n=new Element('text');n.textContent=t;return n;}}});
  for(const file of ['components.js','qq-settings.js',...(workspace?['settings.js']:[])])vm.runInContext(
    fs.readFileSync(new URL('../static/'+file,import.meta.url),'utf8').replace(/^import .*;\s*$/gm,'').replace(/\bexport /g,''),context,{filename:file});
  context.qqAPI=api;context.settingsAPI={read:async()=>{throw new Error('AI_DISABLED');},qq:api};context.toolPanel={mount:()=>new Element('tools')};
  const panel=vm.runInContext(workspace?'createSettingsWorkspace(settingsAPI,toolPanel)':'createQQSettingsPanel(qqAPI)',context);
  const root=workspace?panel.mount():panel.node;if(!workspace)void panel.load();
  const find=text=>walk(root).find(n=>n.tagName==='button'&&n.textContent===text);
  const input=label=>walk(root).find(n=>n.getAttribute('aria-label')===label);
  return {panel,root,find,input,writes,keys,data,get reads(){return reads;}};
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
  assert.match(p.root.textContent,/两次模型请求/);assert.match(p.root.textContent,/停止并重新启动/);
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

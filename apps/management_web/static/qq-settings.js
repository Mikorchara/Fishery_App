import {el,card,button,rows} from './components.js';

const qqErrors={QQ_SETTINGS_STALE:'设置已在别处改变，请重新读取后再保存。',
  QQ_TOKEN_LIMIT_INVALID:'输出 Token 必须是 1–4096 的整数。',QQ_IDENTITY_INCOMPLETE:'首次配置请填写 AppID。首次配置或变更身份时，请同时填写群 OpenID 和完整成员名单。',
  QQ_IDENTITY_INVALID:'身份信息格式不正确；OpenID 不是 QQ 号码。',QQ_ENABLE_REQUIRED:'请先启用 QQ 机器人。',
  QQ_VERIFIED_RECIPIENT_REQUIRED:'尚未绑定已验证的私聊接收人，请在本页完成“首次私聊接收人配对”。',
  QQ_SECRET_REPLACE_CONFIRMATION_REQUIRED:'密钥已存在，勾选“确认替换已有密钥”后再保存。',QQ_SECRET_INVALID:'请先保存 AppID，并填写有效的 AppSecret。',
  QQ_SETTINGS_NOT_CONNECTED:'请使用已初始化的数据实例启动网页。',
  MANAGEMENT_INSTANCE_OR_BOT_ALREADY_RUNNING:'请先停止当前 QQ Bot，再开始私聊配对；网页和模拟器可继续运行。',
  PRIVATE_PAIRING_SAVE_IDENTITY_FIRST:'请先保存 QQ 身份并录入 AppSecret。',QQ_CREDENTIAL_UNAVAILABLE:'无法读取本机 QQ AppSecret，请先保存密钥。',
  PRIVATE_PAIRING_ALREADY_RUNNING_OR_CLEANUP_FAILED:'已有配对仍在运行或资源未关闭，请先取消并核对状态。'};

export function createQQSettingsPanel(api){
  const node=card('QQ 机器人','先保存身份与输出设置，再保存 AppSecret；无需先运行机器人。'),
    content=el('div'),notice=el('p',{role:'status','aria-live':'polite'});
  node.append(content,notice);let config=null,busy=false,pairingNode=null;
  const error=e=>qqErrors[e?.message]||'操作未完成，请检查状态并重新读取配置。配对失败不会自动重发测试消息。';
  function textField(label,value,attrs={}){const input=el('input',{type:'text',value,'aria-label':label,...attrs});
    return {input,node:el('label',{class:'field'},[el('span',{text:label}),input])};}
  function checkField(label,value){const input=el('input',{type:'checkbox','aria-label':label,...(value?{checked:'checked'}:{})});
    input.checked=value;return {input,node:el('label',{class:'settings-check'},[input,el('span',{text:label})])};}
  function render(){
    const s=config.settings,enabled=checkField('启用 QQ 机器人（仍须单独启动）',s.enabled),ai=checkField('允许 AI 自然语言问答（可能计费）',s.ai_enabled),
      app=textField('QQ AppID','',{maxlength:32,autocomplete:'off'}),group=textField('测试群 OpenID','',{maxlength:128,autocomplete:'off'}),
      token=textField('每次模型请求最大输出 Token',s.max_output_tokens,{type:'number',min:1,max:4096,step:1}),
      notifications=checkField('启用已验证接收人的事件通知',s.event_notifications_enabled);
    const members=el('textarea',{'aria-label':'授权成员 OpenID（每行一名，最多4名）',rows:4,spellcheck:'false',autocomplete:'off'});
    members.value='';
    const identitySummary=el('div'),settingsFeedback=el('p',{role:'status'}),secretFeedback=el('p',{role:'status'}),
      password=textField('QQ AppSecret','',{type:'password',autocomplete:'new-password',spellcheck:'false',maxlength:4096}),
      replace=checkField('确认替换已有 QQ AppSecret',false);
    const pairing=api.pairingStart?(pairingNode??=pairingWizard()):null;
    function updateIdentitySummary(){
      const {app_ref,group_ref,member_refs=[]}=config.identity||{};
      identitySummary.replaceChildren(rows([['应用摘要',app_ref||'尚未保存'],['群摘要',group_ref||'尚未保存'],
        ['授权成员摘要',member_refs.length?`${member_refs.length} 名 · ${member_refs.join('、')}`:'尚未保存']]));
    }
    updateIdentitySummary();
    async function save(){
      if(busy)return;
      const raw=String(token.input.value||'');
      if(!/^\d+$/.test(raw)||Number(raw)<1||Number(raw)>4096){settingsFeedback.textContent=qqErrors.QQ_TOKEN_LIMIT_INVALID;return;}
      const appDraft=app.input.value,groupDraft=group.input.value,memberDraft=members.value;
      busy=true;settingsFeedback.textContent='正在保存…';
      try{config=await api.save({revision:config.revision,settings:{enabled:enabled.input.checked,ai_enabled:ai.input.checked,
        app_id:appDraft.trim(),group_id:groupDraft.trim(),members:memberDraft.split(/\r?\n/).map(v=>v.trim()).filter(Boolean),
        max_output_tokens:Number(raw),event_notifications_enabled:notifications.input.checked}},config);
        if(app.input.value===appDraft)app.input.value='';
        if(group.input.value===groupDraft)group.input.value='';
        if(members.value===memberDraft)members.value='';
        updateIdentitySummary();
        settingsFeedback.textContent='设置已保存。请停止并重新启动 QQ 机器人；保存不会连接 QQ 或模型。';
      }catch(e){settingsFeedback.textContent=error(e);}finally{busy=false;}
    }
    async function saveSecret(){
      if(busy)return;busy=true;const secret=password.input.value;password.input.value='';
      secretFeedback.textContent='正在保存密钥…';
      try{config=await api.secret({revision:config.revision,app_secret:secret,replace_existing:replace.input.checked},config);
        secretFeedback.textContent='AppSecret 已保存到本机私有存储，不会显示或写入项目配置。';replace.input.checked=false;
      }catch(e){secretFeedback.textContent=error(e);}finally{busy=false;}
    }
    content.replaceChildren(rows([['配置状态',config.configured?'已生成独立 QQ 配置':'尚未配置；可先保存输出 Token'],
      ['固定模型',[config.provider,config.model,config.preset].filter(Boolean).join(' · ')||'由服务器固定 Qwen 预设'],
      ['AI 调用方式',config.agent_mode==='web'?'复用网页 Agent，支持当前水质、历史水质、当前事件、养殖资料和实验评分':'当前水质专用；保存后按本机新合同装配'],
      ['运行状态',config.runtime_status==='RUNNING'?'运行中':'未检查运行状态（本页不启动机器人）'],
      ['监测实例',config.binding.instance_id||'由服务端现有实例固定'],['绑定设备',config.binding.device_id||'由服务端实例配置固定'],
      ['数据目录',config.binding.data_root],['AppSecret 状态',config.secret_status==='SAVED_FOR_THIS_APP'?'已在本页保存；不读取密钥验证':'未检查（此前保存的密钥可继续使用）'],
      ['事件接收人',config.recipient_available?`已验证 · ${config.recipient_ref||'已绑定'}`:'尚未验证；本页不填写接收人路径']]),
      identitySummary,el('p',{class:'muted',text:'身份字段留空会保留已保存的配置。首次配置请填写 AppID。更换 AppID、群或成员时，请同时填写群 OpenID 和完整成员名单。'}),
      el('div',{class:'settings-fields'},[app.node,group.node]),
      el('label',{class:'field'},[el('span',{text:'授权成员 OpenID（每行一名，最多4名）'}),members]),enabled.node,ai.node,
      token.node,el('p',{class:'muted',text:'默认 2048，范围 1–4096。一次问答可能包含多次模型请求，此值不是整轮合计 Token。'}),
      el('p',{class:'muted',text:'新保存配置采用网页 Agent 的五项只读能力。每轮最多 2 次工具调用、3 次模型请求。工具仍受独立授权限制，模型调用可能计费。'}),
      notifications.node,el('div',{class:'settings-actions'},[button('保存 QQ 设置',()=>void save(),'primary'),button('重新读取 QQ 设置',()=>void load(),'text')]),settingsFeedback,
      el('h3',{text:'QQ AppSecret'}),el('p',{class:'muted',text:'仅保存到当前电脑的私有凭据存储。Qwen / DashScope Key 仍在“API 密钥”页配置；不要粘贴到普通文本字段。'}),
      password.node,replace.node,button('保存 QQ AppSecret',()=>void saveSecret()),secretFeedback,
      ...(pairing?[pairing]:[]),
      el('p',{class:'muted',text:'身份、权限与 Token 修改在重启 Bot 后生效。保存不是网络连接或人工运行批准；旧审批不会因此恢复。'}));
  }

  function pairingWizard(){
    const host=el('section',{'aria-label':'首次私聊接收人配对'}),status=el('p',{role:'status','aria-live':'polite'}),
      challenge=el('pre',{'aria-label':'一次性私聊口令'}),actions=el('div',{class:'settings-actions'}),
      network=el('input',{type:'checkbox','aria-label':'同意本次短时连接 QQ（不调用模型）'});
    let current=null,timer=null,working=false;
    const terminal=new Set(['BOUND','FAILED','CANCELLED','EXPIRED']);
    const names={CONNECTING:'正在连接 QQ…',WAITING_PRIVATE_MESSAGE:'请复制下方整行，在与当前机器人的私聊中发送。',
      AWAITING_CONFIRMATION:'已识别接收人，请核对摘要，再单独确认发送一条主动测试消息。',
      SENDING_TEST:'正在提交唯一一条主动测试消息，请勿重复操作。',BOUND:'接收人已保存，通知仍关闭。请检查手机是否显示测试消息，再按需勾选上方事件通知并保存。',
      CANCELLED:'已取消；没有启用事件通知。',EXPIRED:'配对已超时，请重新开始。',FAILED:'配对未完成；不自动重发测试消息。',IDLE:'先停止 QQ Bot。一次绑定一名私聊接收人；新配对会替换原绑定并关闭事件通知。群聊提问不需要此步骤。'};
    function stopPolling(){if(timer!==null){clearInterval(timer);timer=null;}}
    async function refresh(){
      try{const result=await api.pairingStatus();current=result.pairing;update();
        if(terminal.has(current.phase)){stopPolling();if(current.phase==='BOUND')config=await api.read();}}
      catch(e){status.textContent=error(e);stopPolling();}
    }
    function update(){
      status.textContent=(names[current?.phase]||names.IDLE)+(current?.user_ref?` 接收人摘要：${current.user_ref}。`:'')+
        (current?.api_accepted?' QQ API 已接受；客户端显示须本人核对。':'')+
        (current?.phase==='FAILED'?` 状态：${current.code}。`:'');
      if(current?.phase==='WAITING_PRIVATE_MESSAGE'&&!challenge.textContent)status.textContent='配对仍在进行，但本页没有口令。请取消后重新开始，口令不会从服务器再次返回。';
      if(current?.phase==='AWAITING_CONFIRMATION'||terminal.has(current?.phase))challenge.textContent='';
      const start=button('开始首次私聊配对',async()=>{
        if(working||!network.checked)return;working=true;status.textContent='正在开始…';
        try{const result=await api.pairingStart({revision:config.revision,confirm_network:true},config);
          current=result.pairing;challenge.textContent=current.challenge_command||'';delete current.challenge_command;
          stopPolling();timer=setInterval(()=>void refresh(),2000);network.checked=false;update();}
        catch(e){status.textContent=error(e);}finally{working=false;}
      });
      start.disabled=!!current&&!terminal.has(current.phase)&&current.phase!=='IDLE';
      const controls=[start];
      if(current?.phase==='AWAITING_CONFIRMATION')controls.push(button('确认此接收人，并发送 1 条主动测试消息',async()=>{
        if(working)return;working=true;challenge.textContent='';status.textContent='正在提交测试…';
        try{const result=await api.pairingConfirm({pairing_id:current.pairing_id,user_ref:current.user_ref,confirm_active_test:true},config);
          current=result.pairing;update();if(terminal.has(current.phase)){stopPolling();config=await api.read();}}
        catch(e){status.textContent=error(e);}finally{working=false;}
      }));
      if(current&&!terminal.has(current.phase)&&current.phase!=='IDLE')controls.push(button('取消配对',async()=>{
        if(working)return;working=true;challenge.textContent='';
        try{const result=await api.pairingCancel({pairing_id:current.pairing_id},config);current=result.pairing;update();stopPolling();}
        catch(e){status.textContent=error(e);}finally{working=false;}
      },'text'));
      actions.replaceChildren(...controls);
    }
    host.append(el('h3',{text:'首次私聊接收人配对'}),el('p',{class:'muted',text:'仅连接 QQ，最长 3 分钟；不读取监测数据、不调用 Qwen。一次性口令只显示一次，不要转发。接收人确认后只尝试发送 1 条主动测试消息，未知送达不重试。'}),
      el('label',{class:'settings-check'},[network,el('span',{text:'同意本次短时连接 QQ（不调用模型）'})]),status,challenge,actions);
    update();if(api.pairingStatus)void refresh();return host;
  }
  async function load(){if(busy)return;notice.textContent='正在读取 QQ 设置…';
    try{config=await api.read();render();notice.textContent='本机 QQ 设置；读取不访问密钥、监测数据库或网络。';}
    catch(e){notice.textContent=error(e);}}
  return {node,load};
}

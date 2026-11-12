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
  const node=card('QQ 机器人','保存后，重启机器人使身份、权限和输出设置生效。'),
    content=el('div',{class:'qq-settings-content'}),notice=el('p',{class:'qq-feedback',role:'status','aria-live':'polite'});
  node.classList.add('qq-settings-panel');
  node.append(content,notice);let config=null,busy=false,pairingNode=null,refreshStatus=()=>{};
  const error=e=>qqErrors[e?.message]||'操作未完成，请检查状态并重新读取配置。配对失败不会自动重发测试消息。';
  function textField(label,value,attrs={}){const input=el('input',{type:'text',value,'aria-label':label,...attrs});
    return {input,node:el('label',{class:'field'},[el('span',{text:label}),input])};}
  function checkField(label,value){const input=el('input',{type:'checkbox','aria-label':label,...(value?{checked:'checked'}:{})});
    input.checked=value;return {input,node:el('label',{class:'settings-check'},[input,el('span',{text:label})])};}
  function disclosure(title,body,status=el('span')){
    return el('details',{class:'qq-disclosure'},[
      el('summary',{},[el('span',{text:title}),status]),el('div',{class:'qq-disclosure-body'},body)]);
  }
  function render(){
    const s=config.settings,enabled=checkField('启用 QQ 机器人（仍须单独启动）',s.enabled),ai=checkField('允许 AI 自然语言问答（可能计费）',s.ai_enabled),
      app=textField('QQ AppID','',{maxlength:32,autocomplete:'off'}),group=textField('测试群 OpenID','',{maxlength:128,autocomplete:'off'}),
      token=textField('每次模型请求最大输出 Token',s.max_output_tokens,{type:'number',min:1,max:4096,step:1}),
      notifications=checkField('启用已验证接收人的事件通知',s.event_notifications_enabled);
    const memberRows=[],memberList=el('ol',{class:'qq-member-list','aria-label':'待保存的授权成员'}),
      addMember=button('添加成员',()=>appendMember(true),'text');
    function updateMemberRows(){
      memberRows.forEach(({input,caption,remove},index)=>{
        const label=`成员 ${index+1} OpenID`;
        caption.textContent=label;input.setAttribute('aria-label',label);
        remove.setAttribute('aria-label',`移除成员 ${index+1}`);
      });
      memberList.replaceChildren(...memberRows.map(row=>row.node));
      addMember.disabled=memberRows.length>=4;
    }
    function appendMember(focus=false){
      if(memberRows.length>=4)return;
      const caption=el('span'),input=el('input',{type:'text',value:'',maxlength:128,autocomplete:'off',spellcheck:'false'});
      const remove=button('移除',()=>{
        if(memberRows.length===1){input.value='';input.focus();return;}
        const index=memberRows.indexOf(row);
        memberRows.splice(index,1);updateMemberRows();
        memberRows[Math.min(index,memberRows.length-1)].input.focus();
      });
      const row={input,caption,remove,node:el('li',{class:'qq-member-row'},[el('label',{class:'field'},[caption,input]),remove])};
      memberRows.push(row);updateMemberRows();
      if(focus)input.focus();
    }
    appendMember();
    const overview=el('dl',{class:'qq-overview'}),identitySummary=el('div',{class:'qq-identity-summary'}),
      savedMembers=el('div',{class:'qq-saved-members'}),runDetails=el('div'),
      secretStatus=el('small',{class:'qq-disclosure-status'}),recipientStatus=el('small',{class:'qq-disclosure-status'}),
      settingsFeedback=el('p',{class:'qq-feedback',role:'status'}),secretFeedback=el('p',{class:'qq-feedback',role:'status'}),
      password=textField('QQ AppSecret','',{type:'password',autocomplete:'new-password',spellcheck:'false',maxlength:4096}),
      replace=checkField('确认替换已有 QQ AppSecret',false);
    refreshStatus=({pairingBound=false}={})=>{
      if(pairingBound)notifications.input.checked=config.settings.event_notifications_enabled;
      const {app_ref,group_ref,member_refs=[]}=config.identity||{};
      const recipient=config.recipient_available?'已配对':'未配对';
      overview.replaceChildren(...[['配置',config.configured?'已保存':'尚未配置'],['模型',config.model||'Qwen'],
        ['事件通知',config.settings.event_notifications_enabled?'已启用':recipient==='已配对'?'已配对，未启用':'未配对']]
        .map(([label,value])=>el('div',{},[el('dt',{text:label}),el('dd',{text:value})])));
      identitySummary.replaceChildren(rows([['应用摘要',app_ref||'尚未保存'],['群摘要',group_ref||'尚未保存']]));
      savedMembers.replaceChildren(el('span',{text:member_refs.length?`已保存 ${member_refs.length} 名`:'尚未保存成员'}),
        ...(member_refs.length?[el('ul',{'aria-label':'已保存成员摘要'},member_refs.map(ref=>el('li',{class:'badge',text:ref})))]:[]));
      secretStatus.textContent=config.secret_status==='SAVED_FOR_THIS_APP'?'已保存':'未检查';
      recipientStatus.textContent=recipient;
      runDetails.replaceChildren(rows([
        ['运行状态',config.runtime_status==='RUNNING'?'运行中':'未检查'],
        ['固定模型',[config.provider,config.model,config.preset].filter(Boolean).join(' · ')||'Qwen'],
        ['AI 能力',config.agent_mode==='web'?'当前水质、历史水质、当前事件、养殖资料和实验评分':'当前水质查询'],
        ['监测实例',config.binding.instance_id],['绑定设备',config.binding.device_id],['数据目录',config.binding.data_root],
        ['事件接收人',config.recipient_ref||recipient]]));
    };
    refreshStatus();
    const pairing=api.pairingStart?(pairingNode??=pairingWizard()):null;
    async function save(){
      if(busy)return;
      const raw=String(token.input.value||'');
      if(!/^\d+$/.test(raw)||Number(raw)<1||Number(raw)>4096){settingsFeedback.textContent=qqErrors.QQ_TOKEN_LIMIT_INVALID;return;}
      const appDraft=app.input.value,groupDraft=group.input.value;
      const memberDraft=memberRows.map(row=>({row,value:row.input.value}));
      busy=true;settingsFeedback.textContent='正在保存…';
      try{config=await api.save({revision:config.revision,settings:{enabled:enabled.input.checked,ai_enabled:ai.input.checked,
        app_id:appDraft.trim(),group_id:groupDraft.trim(),members:memberDraft.map(({value})=>value.trim()).filter(Boolean),
        max_output_tokens:Number(raw),event_notifications_enabled:notifications.input.checked}},config);
        if(app.input.value===appDraft)app.input.value='';
        if(group.input.value===groupDraft)group.input.value='';
        if(memberRows.length===memberDraft.length&&memberDraft.every(({row,value},index)=>memberRows[index]===row&&row.input.value===value)){
          memberRows.length=0;appendMember();
        }
        refreshStatus();
        settingsFeedback.textContent='设置已保存。请停止并重新启动 QQ 机器人。';
      }catch(e){settingsFeedback.textContent=error(e);}finally{busy=false;}
    }
    async function saveSecret(){
      if(busy)return;busy=true;const secret=password.input.value;password.input.value='';
      secretFeedback.textContent='正在保存密钥…';
      try{config=await api.secret({revision:config.revision,app_secret:secret,replace_existing:replace.input.checked},config);
        secretFeedback.textContent='AppSecret 已保存到本机私有存储。';replace.input.checked=false;refreshStatus();
      }catch(e){secretFeedback.textContent=error(e);}finally{busy=false;}
    }
    content.replaceChildren(overview,el('div',{class:'qq-form-grid'},[
      el('section',{class:'qq-form-section','aria-label':'身份与成员'},[el('h3',{text:'身份与成员'}),
        identitySummary,el('div',{class:'qq-identity-fields'},[app.node,group.node]),
        el('div',{class:'qq-member-heading'},[el('h4',{text:'授权成员'}),savedMembers]),memberList,addMember,
        el('p',{class:'muted',text:'最多 4 名。留空保留已保存的身份。首次配置请填写 AppID、群和成员。更换群或成员时，请填写群 OpenID 和完整的新名单。'})]),
      el('section',{class:'qq-form-section','aria-label':'运行选项'},[el('h3',{text:'运行选项'}),enabled.node,ai.node,
        token.node,el('p',{class:'muted',text:'范围 1–4096。一次问答可能包含多次模型请求。'}),notifications.node,
        el('p',{class:'muted',text:'事件通知发给已配对的私聊接收人。'})]),
      ]),el('div',{class:'qq-save-row'},[el('div',{class:'settings-actions'},[
        button('保存 QQ 设置',()=>void save(),'primary'),button('重新读取 QQ 设置',()=>void load(),'text')]),settingsFeedback]),
      el('div',{class:'qq-disclosures'},[
        disclosure('QQ AppSecret',[el('p',{class:'muted',text:'请先保存身份。AppSecret 存入本机私有存储。模型 Key 在「API 密钥」页配置。'}),
          password.node,replace.node,button('保存 QQ AppSecret',()=>void saveSecret()),secretFeedback],secretStatus),
        ...(pairing?[disclosure('首次私聊接收人配对',[pairing],recipientStatus)]:[]),
        disclosure('查看运行详情',[runDetails]),
      ]));
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
        if(terminal.has(current.phase)){stopPolling();if(current.phase==='BOUND'){config=await api.read();refreshStatus({pairingBound:true});}}}
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
          current=result.pairing;update();if(terminal.has(current.phase)){stopPolling();config=await api.read();refreshStatus({pairingBound:current.phase==='BOUND'});}}
        catch(e){status.textContent=error(e);}finally{working=false;}
      }));
      if(current&&!terminal.has(current.phase)&&current.phase!=='IDLE')controls.push(button('取消配对',async()=>{
        if(working)return;working=true;challenge.textContent='';
        try{const result=await api.pairingCancel({pairing_id:current.pairing_id},config);current=result.pairing;update();stopPolling();}
        catch(e){status.textContent=error(e);}finally{working=false;}
      },'text'));
      actions.replaceChildren(...controls);
    }
    host.append(el('p',{class:'muted',text:'配对最长 3 分钟，只连接 QQ。一次性口令请勿转发。核对接收人后可发送 1 条测试消息。'}),
      el('label',{class:'settings-check'},[network,el('span',{text:'同意本次短时连接 QQ（不调用模型）'})]),status,challenge,actions);
    update();if(api.pairingStatus)void refresh();return host;
  }
  async function load(){if(busy)return;notice.textContent='正在读取 QQ 设置…';
    try{config=await api.read();render();notice.textContent='';}
    catch(e){notice.textContent=error(e);}}
  return {node,load};
}

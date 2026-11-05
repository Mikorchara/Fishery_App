import {el,card,button,rows} from './components.js';

const qqErrors={QQ_SETTINGS_STALE:'设置已在别处改变，请重新读取后再保存。',
  QQ_TOKEN_LIMIT_INVALID:'输出 Token 必须是 1–4096 的整数。',QQ_IDENTITY_INCOMPLETE:'请完整填写 AppID、群 OpenID 和至少一名成员。',
  QQ_IDENTITY_INVALID:'身份信息格式不正确；OpenID 不是 QQ 号码。',QQ_ENABLE_REQUIRED:'请先启用 QQ 机器人。',
  QQ_VERIFIED_RECIPIENT_REQUIRED:'尚未绑定已验证的私聊接收人，请先完成负责人提供的私聊验证。',
  QQ_SECRET_REPLACE_CONFIRMATION_REQUIRED:'密钥已存在，勾选“确认替换已有密钥”后再保存。',QQ_SECRET_INVALID:'请先保存 AppID，并填写有效的 AppSecret。',
  QQ_SETTINGS_NOT_CONNECTED:'请使用已初始化的数据实例启动网页。'};

export function createQQSettingsPanel(api){
  const node=card('QQ 机器人','先保存身份与输出设置，再保存 AppSecret；无需先运行机器人。'),
    content=el('div'),notice=el('p',{role:'status','aria-live':'polite'});
  node.append(content,notice);let config=null,busy=false;
  const error=e=>qqErrors[e?.message]||'操作未完成，请检查配置并重新读取；未进行联网测试。';
  function textField(label,value,attrs={}){const input=el('input',{type:'text',value,'aria-label':label,...attrs});
    return {input,node:el('label',{class:'field'},[el('span',{text:label}),input])};}
  function checkField(label,value){const input=el('input',{type:'checkbox','aria-label':label,...(value?{checked:'checked'}:{})});
    input.checked=value;return {input,node:el('label',{class:'settings-check'},[input,el('span',{text:label})])};}
  function render(){
    const s=config.settings,enabled=checkField('启用 QQ 机器人（仍须单独启动）',s.enabled),ai=checkField('允许 AI 自然语言问答（可能计费）',s.ai_enabled),
      app=textField('QQ AppID',s.app_id,{maxlength:32}),group=textField('测试群 OpenID',s.group_id,{maxlength:128}),
      token=textField('每次模型请求最大输出 Token',s.max_output_tokens,{type:'number',min:1,max:4096,step:1}),
      notifications=checkField('启用已验证接收人的事件通知',s.event_notifications_enabled);
    const members=el('textarea',{'aria-label':'授权成员 OpenID（每行一名，最多4名）',rows:4,spellcheck:'false'});
    members.value=s.members.join('\n');
    const settingsFeedback=el('p',{role:'status'}),secretFeedback=el('p',{role:'status'}),
      password=textField('QQ AppSecret','',{type:'password',autocomplete:'new-password',spellcheck:'false',maxlength:4096}),
      replace=checkField('确认替换已有 QQ AppSecret',false);
    async function save(){
      if(busy)return;
      const raw=String(token.input.value||'');
      if(!/^\d+$/.test(raw)||Number(raw)<1||Number(raw)>4096){settingsFeedback.textContent=qqErrors.QQ_TOKEN_LIMIT_INVALID;return;}
      busy=true;settingsFeedback.textContent='正在保存…';
      try{config=await api.save({revision:config.revision,settings:{enabled:enabled.input.checked,ai_enabled:ai.input.checked,
        app_id:app.input.value.trim(),group_id:group.input.value.trim(),members:members.value.split(/\r?\n/).map(v=>v.trim()).filter(Boolean),
        max_output_tokens:Number(raw),event_notifications_enabled:notifications.input.checked}},config);
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
      ['运行状态',config.runtime_status==='RUNNING'?'运行中':'未检查运行状态（本页不启动机器人）'],
      ['监测实例',config.binding.instance_id||'由服务端现有实例固定'],['绑定设备',config.binding.device_id||'由服务端实例配置固定'],
      ['数据目录',config.binding.data_root],['AppSecret 状态',config.secret_status==='SAVED_FOR_THIS_APP'?'已在本页保存；不读取密钥验证':'未检查（此前保存的密钥可继续使用）'],
      ['事件接收人',config.recipient_available?`已验证 · ${config.recipient_ref||'已绑定'}`:'尚未验证；本页不填写接收人路径']]),
      el('div',{class:'settings-fields'},[app.node,group.node]),
      el('label',{class:'field'},[el('span',{text:'授权成员 OpenID（每行一名，最多4名）'}),members]),enabled.node,ai.node,
      token.node,el('p',{class:'muted',text:'默认 2048，范围 1–4096。一次问答可能包含两次模型请求，此值不是整轮合计 Token。'}),
      notifications.node,el('div',{class:'settings-actions'},[button('保存 QQ 设置',()=>void save(),'primary'),button('重新读取 QQ 设置',()=>void load(),'text')]),settingsFeedback,
      el('h3',{text:'QQ AppSecret'}),el('p',{class:'muted',text:'仅保存到当前电脑的私有凭据存储。Qwen / DashScope Key 仍在“API 密钥”页配置；不要粘贴到普通文本字段。'}),
      password.node,replace.node,button('保存 QQ AppSecret',()=>void saveSecret()),secretFeedback,
      el('p',{class:'muted',text:'身份、权限与 Token 修改在重启 Bot 后生效。保存不是网络连接或人工运行批准；旧审批不会因此恢复。'}));
  }
  async function load(){if(busy)return;notice.textContent='正在读取 QQ 设置…';
    try{config=await api.read();render();notice.textContent='本机 QQ 设置；读取不访问密钥、监测数据库或网络。';}
    catch(e){notice.textContent=error(e);}}
  return {node,load};
}

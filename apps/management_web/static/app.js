import {el,icon,card,badge,empty,button,link,rows,metricCards,metadata,table,trendChart,normalizedTrendChart,createLocalVideoPreview,createVideoWorkspace} from './components.js';
import {routes,routeFor,timeText,filterItems,validateBootstrap,qualityNames,freshnessNames,sourceName,managedEvent,connectionName,eventState,eventStateName,eventStateReasonName,eventHandlingName,cycleConfirmationName,eventSeverityName,trendRanges,activeEventOverview} from './view-model.js';
import {services} from './services.js';
import {createAssistantWorkspace} from './assistant.js';
import {createToolPolicySettings} from './tool-policy.js';
import {createKnowledgeWorkspace} from './knowledge.js';
import {createSettingsWorkspace} from './settings.js';

const $=id=>document.getElementById(id);
const state={data:null,device:'demo-a',view:'available',metric:'dissolved_oxygen_mg_l',trendRange:'1800',camera:'demo-camera-a',
  eventFilters:{q:'',severity:'',status:'',lookback_minutes:'all'},eventOffset:0,settings:'devices',draft:'',revision:0};
let eventQueryRevision=0,eventDeletionBusy=false,eventAckBusy=false,eventEndBusy=false;
const assistantWorkspace=createAssistantWorkspace(services.ai,{onDevice:id=>{state.device=id;void changeMonitoring();}});
const toolPolicySettings=createToolPolicySettings(services.ai,{onSaved:()=>assistantWorkspace.policyChanged()});
const knowledgeWorkspace=createKnowledgeWorkspace(services.knowledge);
const settingsWorkspace=createSettingsWorkspace(services.settings,toolPolicySettings,{onBudgetSaved:()=>assistantWorkspace.policyChanged()});
const localVideoPreview=createLocalVideoPreview($('local-video-preview'));
const videoWorkspace=createVideoWorkspace($('local-video-preview'));
const severity=item=>badge(eventSeverityName(item),item.severity==='critical'?'critical':item.severity==='warning'?'warning':'neutral');
const status=item=>el('div',{class:'event-status'},[
  badge(managedEvent(item)?eventStateName(item):(item.status==='pending'?'待处理（演示）':'已处理（演示）'),eventState(item)==='RESOLVED'?'resolved':item.status==='closed'?'neutral':'warning'),
  ...(managedEvent(item)?[badge(eventHandlingName(item),item.handling?.state==='ACKNOWLEDGED'?'success':'neutral')]:[])]);

function select(label,choices,value,onchange){return el('label',{class:'field'},[el('span',{text:label}),el('select',{'aria-label':label,onchange:e=>onchange(e.target.value)},
  choices.map(([id,text])=>el('option',{value:id,...(id===value?{selected:'selected'}:{})},[text])))]);}
function search(label,value,oninput){return el('label',{class:'field search-field'},[el('span',{text:label}),el('input',{type:'search',value,placeholder:'输入名称或关键字',oninput:e=>oninput(e.target.value)})]);}
function details(title,content){$('dialog-title').textContent=title;$('dialog-body').replaceChildren(...content);$('details-dialog').showModal();}
function eventHandlingPanel(item){
  if(!managedEvent(item))return [];
  const h=item.handling;
  const reason=({LEGACY_OR_UNSUPPORTED_IDENTITY:item.legacy_closed?
    '旧版已结束记录不支持人工知晓确认；符合清理条件时可在事件列表确认删除。':
    '旧记录缺少可写的稳定周期或规则身份，不能确认知晓；仍可通过本机维护删除。',
    MANUALLY_ENDED:'提醒已人工结束，知晓记录仅作历史保留。',
    EVENT_ENDED:'规则条件已消退，仅保留历史知晓记录。',NOT_CURRENT_GRADE:'此记录不是当前等级；请从当前等级记录确认风险。'})[item.manual_end?.active?'MANUALLY_ENDED':h?.unavailable_reason];
  return [el('section',{class:'event-handling'},[el('h3',{text:'人工知晓记录'}),
    rows([['人工状态',eventHandlingName(item)],['知晓对象',h?.ended||item.manual_end?.active?'已结束提醒（仅历史）':h?.grade_code?
      (item.family_members?.find(e=>e.code===h.grade_code)?.title||item.title):'尚无可确认的等级'],
      ['本等级确认时间',h?.acked_at?timeText(h.acked_at):'尚未确认'],
      ['最近确认（历史）',h?.latest_ack_at?timeText(h.latest_ack_at):'无确认记录'],
      ['操作来源',h?.action_count?'本机操作（未认证访客）':'尚无操作']]),
    el('p',{class:'muted',text:'知晓不代表异常消退或处理完成，不改变监测状态。风险等级变化后需要重新确认。'}),
    ...(reason?[el('p',{class:'muted',text:reason})]:[]),
    ...(h?.can_ack&&state.data.event_management?.ack_enabled?[button('确认已知晓',()=>requestEventAck(item),'primary')]:[]),
    ...(h?.action_count?[el('p',{text:`共 ${h.action_count} 次确认，显示最近 ${h.history.length} 次；完整记录保留在数据库。`}),
      table(['确认时间','当时事件 / 等级','来源'],h.history,a=>[timeText(a.acted_at),a.event_title||a.grade_code,'本机操作（未认证访客）'])]:[])
  ])];
}
function deviceReportEvidence(item){
  if(item.source_kind!=='device_report')return [];
  const report=item.device_report||{};
  return [el('section',{class:'event-handling'},[
    el('h3',{text:'设备报告证据'}),
    el('p',{class:'muted',text:'设备模型检测信号，需核查；非确诊。报告与视频播放独立，不自动判断异常已消退。'}),
    rows([['原始报告ID',report.report_id||item.batch_id],['报告窗口开始',timeText(report.window?.start)],
      ['报告窗口结束',timeText(report.window?.end)],['处理帧',report.window?.frames_processed??'未提供'],
      ['设备发送时间',timeText(report.sent_at)]]),
    table(['设备异常标签','去重目标数','检出帧次'],report.abnormalities||[],a=>[
      `${a.name}（${a.label}）`,a.targets,a.count]),
    ...(report.report_text?[el('details',{class:'data-details'},[el('summary',{text:'原始设备报告文本'}),
      el('pre',{class:'device-report-text',text:report.report_text})])]:[])
  ])];
}
function requestEventAck(item){
  if(eventAckBusy)return;
  const h=item.handling;
  let requestId;
  try{requestId=crypto.randomUUID();}catch(_){details('确认暂不可用',[el('p',{text:'当前浏览器不支持安全请求标识，请使用更新的本机浏览器。'})]);return;}
  const value={event_id:item.id,cycle_id:h.cycle_id,grade_token:h.grade_token,grade_version:h.grade_version,
    revision:h.revision,request_id:requestId};
  const commit=button('确认知晓此风险',async()=>{
    if(eventAckBusy)return;eventAckBusy=true;commit.disabled=true;
    try{
      await services.eventAck(value,state.data.event_management.write_token);
      state.revision++;await refresh(true);
      eventDetail(await services.eventDetail(item.id));
    }catch(_){details('确认未完成',[el('p',{text:'请求结果或事件等级可能已变化，请刷新详情核对。未自动重试，也未修改监测状态。'}),
      button('关闭',()=>$('details-dialog').close())]);}
    finally{eventAckBusy=false;commit.disabled=false;}
  },'primary');
  details('确认已知晓',[el('p',{text:`${item.title}：确认已知晓此风险及当前观测状态？此操作不表示异常消退或处理完成。`}),
    el('p',{class:'muted',text:'来源记录为本机操作，不代表经过认证的工作人员身份。'}),
    button('取消',()=>eventDetail(item),'secondary'),commit]);
}
function eventDetail(item){details(item.title,[badge(sourceName(item.source_kind),'demo'),rows([['记录编号',item.id],['时间',timeText(item.occurred_at)],['设备',item.device],['类型',item.type],['等级',eventSeverityName(item)],['状态',managedEvent(item)?eventStateName(item):'演示处理状态'],['状态说明',managedEvent(item)?eventStateReasonName(item):'仅为演示处理状态'],['原因代码',item.state_reason],['规则发布',item.publication_status||'PROTOTYPE'],['关联批次',item.batch_id],['接收时间',timeText(item.received_at)],['最近检出信号',timeText(item.last_observed_at)],['最近有效观测',timeText(item.visual_recovery?.last_valid_observed_at||item.last_observed_at)],['恢复观察',item.visual_recovery?`${item.visual_recovery.clear_count}/${item.visual_recovery.required_clear_windows}（本地实验参数）`:'未记录'],['连续观测段起点',timeText(item.visual_recovery?.segment_started_at)],['观测连续性',item.visual_recovery?.continuity==='interrupted'?'历史观测存在不连续，未知时段不计为已证实持续异常':'以有效窗口为依据'],['最近中断原因',item.visual_recovery?.last_interruption_reason],['规则恢复时间',timeText(item.resolved_at)],['规则版本',item.rule_version],['规则范围',item.rule_identity?.scope?.join(' / ')||'旧记录未记录']]),
  ...(item.risk_family?[el('h3',{text:item.risk_family.label+' · 等级变化'}),
    el('p',{text:item.state_reason==='OTHER_RISK_CONDITION_ACTIVE'?'该等级暂未命中，但同指标仍有其他风险等级；不表示异常已恢复。':'各 code 保留原 ID，事件族只提供关联与当前等级展示。'}),
    el('p',{text:item.risk_family.inferred?'旧事件仅关联当前未结束成员，未重建缺失的历史变化。':`保留首次及最近等级变化；略去 ${item.risk_family.omitted_transitions||0} 次中间变化。`}),
    table(['观测时间','等级 / 变化','原始均值','批次 / Session / 序号'],item.risk_family.transitions||[],t=>[
      timeText(t.observed_at),t.title,t.metric?.mean===null?'缺测':`${t.metric?.mean??'—'} ${t.metric?.unit||''}`,
      `${t.batch_id} / ${t.session_id} / ${t.sequence}`]),
    table(['关联记录','等级','监测状态'],item.family_members||[],e=>[e.title,eventSeverityName(e),eventStateName(e)],
      async e=>{try{eventDetail(await services.eventDetail(e.id));}catch(_){details('关联记录不可用',[el('p',{text:'该历史记录可能已删除或按留存规则裁剪；已保存的变化证据仍保留。'})]);}})]:[]),
  ...deviceReportEvidence(item),
  ...eventHandlingPanel(item),
  ...manualEndPanel(item),
  ...(state.data.event_management?.enabled?[
    ...(item.can_delete_cycle?[button('删除已结束周期',()=>requestEventDeletion('cycle',item),'danger')]:
      item.can_delete_ack_cycle?[button('删除已结束周期',()=>requestEventDeletion('ack_cycle',item),'danger')]:
      item.deletable?[button('删除此原始记录',()=>requestEventDeletion('single',item),'danger')]:[
      button('删除此轮事件',()=>requestEventDeletion('reset_cycle',item),'danger')])]:[]),
  ...(item.channel==='visual'&&item.source_kind!=='device_report'?[el('p',{text:'视觉信号消退仅表示连续可靠观测未再检出该异常信号，不代表疾病治愈或人工处理完成。'})]:[]),el('p',{text:item.description}),
  empty('暂无关联媒体','这里将展示关联截图与视频片段；R1 未生成或保存媒体。','camera')]);}
function manualEndPanel(item){
  const end=item.manual_end;
  if(!end||!end.can_end&&!end.history?.length)return [];
  return [el('section',{class:'event-handling'},[
    el('h3',{text:'人工结束记录'}),
    el('p',{class:'muted',text:end.active?'已人工结束提醒；监测恢复仍未证实。后续再次检出异常将重新提醒。':'人工结束只用于中断、过期或缺测的旧提醒，不代表规则恢复。'}),
    rows([['监测状态',eventState(item)],['人工结束时间',timeText(end.acted_at)]]),
    ...(end.can_end&&state.data.event_management?.manual_end_enabled?[button('人工结束此风险',()=>requestManualEnd(item),'secondary')]:[]),
    ...(end.history?.length?[table(['人工结束时间','原因','操作来源'],end.history,h=>[
      timeText(h.acted_at),h.reason,'本机操作（未认证访客）'])]:[])
  ])];
}
async function requestManualEnd(item){
  if(eventEndBusy)return;
  eventEndBusy=true;
  try{
    const token=state.data.event_management.write_token;
    const plan=await services.manualEndPreview({event_id:item.id},token);
    const input=el('input',{type:'text',value:'',maxlength:'200','aria-label':'人工结束原因',placeholder:'说明停用、失联或人工整理原因（必填）'});
    const reason=el('label',{class:'field'},[el('span',{text:'人工结束原因（最多200字）'}),input]);
    const hint=el('p',{class:'muted'});
    const requestId=crypto.randomUUID();
    const commit=button('确认人工结束',async()=>{
      if(eventEndBusy)return;
      if(!input.value.trim()){hint.textContent='请填写人工结束原因。';return;}
      eventEndBusy=true;commit.disabled=true;
      try{
        await services.manualEnd({event_id:item.id,revision:plan.revision,request_id:requestId,reason:input.value.trim()},token);
        state.revision++;await refresh(true);
        eventDetail(await services.eventDetail(item.id));
      }catch(_){details('人工结束未完成',[el('p',{text:'观测、记录或权限可能已变化。请刷新核对，未自动重试。'}),button('关闭',()=>$('details-dialog').close())]);}
      finally{eventEndBusy=false;commit.disabled=false;}
    },'primary');
    details('确认人工结束失联风险',[
      el('p',{text:`${item.title}：本次涉及 ${plan.count} 条原始记录。结束当前提醒并保留原始证据及操作历史；不删除记录，不代表恢复正常。`} ),
      el('p',{class:'muted',text:'新一次可靠异常观测会重新提醒。本机操作不代表经过认证的工作人员身份。'}),
      reason,hint,el('div',{class:'event-confirm-actions'},[button('取消',()=>eventDetail(item)),commit])]);
  }catch(_){details('当前不能人工结束',[el('p',{text:'此风险可能仍有可靠异常、已经结束或观测已更新。请刷新详情核对。'})]);}
  finally{eventEndBusy=false;}
}
async function showEventDetail(item){
  if(!item.cycle_summary){eventDetail(item);return;}
  try{eventDetail(await services.eventDetail(item.cycle_summary.detail_event_id));}
  catch(_){details('详情暂不可用',[el('p',{text:'请刷新列表后重试；没有修改任何记录。'})]);}
}
function eventsTable(items,maintenance=false){return table(['风险 / 类型','设备','首次发生 / 恢复','等级','状态','是否确认',...(maintenance?['删除']:[]),'操作'],items,item=>[
  el('div',{class:'table-title'},[el('strong',{text:item.title}),
    ...(item.cycle_summary?[el('small',{text:`${item.cycle_summary.reading_label}：${item.cycle_summary.reading}`}),
      el('small',{text:`${item.cycle_summary.count} 条原始记录 · ${sourceName(item.source_kind)}`})]:[el('small',{text:`${item.id} · ${item.type} · ${sourceName(item.source_kind)}`})])]),
  item.device,el('div',{class:'cycle-time'},[el('span',{text:timeText(item.occurred_at)}),
    ...(item.cycle_summary?[el('small',{text:item.manual_end?.active?`人工结束：${timeText(item.manual_end.acted_at)}`:item.cycle_summary.ended?`恢复 / 原结束：${timeText(item.resolved_at)}`:`最近观测：${timeText(item.last_observed_at)}`})]:[])]),
  el('div',{class:'cycle-level'},[...(item.cycle_summary?.ended?[el('small',{text:'历史最高等级'})]:[]),severity(item)]),
  item.cycle_summary?badge(eventStateName(item),item.manual_end?.active?'neutral':eventState(item)==='RESOLVED'?'resolved':item.status==='closed'?'neutral':'warning'):status(item),
  badge(cycleConfirmationName(item),cycleConfirmationName(item)==='已确认'?'success':'neutral'),
  ...(maintenance?[item.can_delete_cycle?button('删除已结束周期',()=>requestEventDeletion('cycle',item),'text danger'):
    item.can_delete_ack_cycle?button('删除已结束周期',()=>requestEventDeletion('ack_cycle',item),'text danger'):
    item.deletable?button('删除记录',()=>requestEventDeletion('single',item),'text danger'):
    button('删除此轮事件',()=>requestEventDeletion('reset_cycle',item),'text danger')]:[])],showEventDetail);}

function currentAnomalies(data){
  const overview=activeEventOverview(data,state.device);
  const name=data.devices.find(d=>d.id===state.device)?.name||state.device;
  const sources=new Set(overview.items.map(item=>item.source_kind));
  const source=sources.size>1?'mixed':sources.values().next().value||data.data_mode;
  const content=overview.items.length?[
    el('div',{class:'anomaly-summary'},[badge(`${overview.items.length} 项需关注`,'warning'),badge(sourceName(source),'demo'),
      el('span',{text:'检测信号用于提示核查，疑似疾病不作为确诊。'})]),
    el('div',{class:'anomaly-list'},overview.items.map(item=>el('article',{class:'anomaly-item','data-event-id':item.id},[
      el('div',{class:'anomaly-heading'},[el('strong',{text:item.overview_title||item.title}),
        item.risk_family&&!item.family_current_code?badge('当前等级未知','neutral'):severity(item),badge(sourceName(item.source_kind),'demo'),status(item)]),
      el('p',{text:`设备 ${item.device_id||item.device} · 首次发生 ${timeText(item.occurred_at)}`}),
      el('p',{text:`最近有效观测 ${timeText(item.visual_recovery?.last_valid_observed_at||item.last_observed_at)}`}),
      ...(item.family_size>1?[el('p',{text:`关联 ${item.family_size} 条等级记录，详情保留变化证据。`})]:[]),
      ...(item.visual_recovery?.continuity==='interrupted'?[el('p',{class:'muted',text:'历史观测存在不连续；未知时段不计为已证实持续异常。'})]:[]),
      button('查看详情',()=>showEventDetail(item),'text')])))]
    :[badge(sourceName(data.data_mode),'demo'),el('p',{class:'anomaly-empty',text:overview.clear?'当前未见异常信号':'状态未知 · 需要完整、新鲜的水质与视觉观测。'})];
  const section=card('当前异常概况',`区域：${name} · ${overview.items.length?'未结束事件，包含恢复观察与观测中断':'以服务器当前规则和观测质量为依据'}`,content,link('全部事件','events'));
  section.className+=` current-anomalies ${overview.items.length?'needs-attention':overview.clear?'signals-clear':'signals-unknown'}`;
  section.setAttribute('data-current-anomalies','true');
  return section;
}

function trend(){const options={rangeSeconds:state.trendRange==='all'?null:Number(state.trendRange)};
  return el('div',{class:'trend-stack'},[card('历史趋势','已存储的窗口均值；不代表连续实时采样。',[trendChart(state.data.monitoring,state.metric,options)],
    el('div',{class:'chart-controls'},[
    select('指标',[['dissolved_oxygen_mg_l','溶解氧'],['temperature_c','水温'],['ph','pH']],state.metric,value=>{state.metric=value;render();}),
    select('历史范围',trendRanges,state.trendRange,value=>{state.trendRange=value;render();})])),
    card('三指标综合趋势（归一化）','与上图共用时间范围；比较各指标的变化趋势，不比较原始数值大小。',[
      normalizedTrendChart(state.data.monitoring,options)])]);}
function videoPlaceholder(compact=false){return el('div',{class:`video-placeholder ${compact?'compact':''}`},[
  el('div',{class:'video-corner',text:'演示预览区域 / 无视频流'}),el('span',{class:'video-symbol'},[icon('camera')]),el('h3',{text:'等待接入监控设备'}),
  el('p',{text:'未接入真实视频；检测统计与画面接入独立。'}),badge('NOT CONNECTED','neutral')]);}

function dashboard(){
  const d=state.data, snapshot=d.monitoring;
  const recentEvents=card('最近事件','按风险周期展示；等级变化与原始证据见详情。',[eventsTable((d.event_cycles||d.events).slice(0,5))],link('全部记录','events'));
  recentEvents.className+=' dashboard-events';
  const assistantCard=card('AI 智能助手','围绕监测事实，获得有依据的辅助解读。',[
    el('div',{class:'assistant-entry'},[
      el('div',{class:'assistant-entry-intro'},[el('span',{class:'assistant-emblem'},[icon('spark')]),
        badge(d.ai?.connected?'助手已启用':'助手未启用',d.ai?.connected?'success':'neutral')]),
      el('h3',{text:'让数据更容易理解'}),
      el('p',{text:d.ai?.connected?'从水质问题到资料解读，在助手工作区继续对话。':'启用 Assistant 后，可在助手工作区选择模型并开始对话。'}),
      el('div',{class:'assistant-entry-features'},[
        ['drop','理解水质','了解指标、观测质量与时效限制。'],
        ['book','查找资料','在已授权的知识范围内寻找依据。'],
        ['file','核对来源','区分监测事实与 AI 辅助建议。']
      ].map(([symbol,title,description])=>el('div',{class:'assistant-entry-feature'},[icon(symbol),el('div',{},[
        el('strong',{text:title}),el('small',{text:description})])]))),
      el('div',{class:'assistant-entry-action'},[
        el('a',{href:'#assistant',class:'button primary'},['打开助手工作区',icon('arrow')]),
        el('p',{text:'工具按已有授权使用；发送前确认，不会自动调用模型。'})])])]);
  assistantCard.className+=' dashboard-assistant';
  return [el('div',{class:'overview-strip'},[
    el('div',{},[el('span',{class:'strip-icon'},[icon('link')]),el('div',{},[el('strong',{text:'数据连接概况'}),el('small',{text:d.data_mode==='simulator'?'统一监测存储 · 模拟器来源':'独立 Demo adapter 已就绪'})])]),
    el('div',{class:'strip-number'},[el('strong',{text:String(d.devices.length)}),el('span',{text:'监测区域'})]),
    el('div',{class:'strip-number'},[el('strong',{text:'0'}),el('span',{text:'实测水质设备'})]),
    el('div',{class:'strip-number'},[el('strong',{text:d.ai?.connected?'1':'0'}),el('span',{text:'已启用 AI 服务'})]),badge(sourceName(d.data_mode),'demo')]),
    el('div',{class:'section-caption'},[el('h2',{text:'水质指标概览'}),link('查看水质监测','monitoring')]),metadata(snapshot),metricCards(snapshot),currentAnomalies(d),
    el('div',{class:'dashboard-grid dashboard-overview'},[trend(),
      el('div',{class:'side-stack dashboard-sidebar'},[
        assistantCard,
        card('连接状态','未连接不代表设备离线。',[el('div',{class:'connection-list'},d.connections.map(c=>el('div',{class:'connection-row'},[
          el('span',{text:c.name}),badge(connectionName(c.status),c.status==='online'?'success':c.status==='offline'?'warning':'neutral')])))] )]),recentEvents])];
}

async function changeMonitoring(){
  state.revision++;
  await refresh(true);
}
function monitoring(){const snapshot=state.data.monitoring;return [el('div',{class:'filters'},[
  select('观测区域',state.data.devices.map(d=>[d.id,d.name]),state.device,value=>{state.device=value;changeMonitoring();}),
  ...(state.data.data_mode==='demo'?[select('演示数据状态',[['available','可用'],['stale','过期'],['partial','部分缺失'],['invalid','无效'],['missing','无数据']],state.view,value=>{state.view=value;changeMonitoring();})]:[]),
  el('p',{class:'filter-hint',text:state.data.data_mode==='simulator'?'每 5 秒读取服务器；不会采样或写入数据。':'独立 R1 Demo 视图。'})]),metadata(snapshot),metricCards(snapshot),
  ...(snapshot?.quality==='valid'&&snapshot?.freshness==='fresh'&&snapshot?.connectivity!=='offline'?[]:[el('div',{class:'data-warning',text:`数据状态：${qualityNames[snapshot?.quality]||'不可用'} / ${freshnessNames[snapshot?.freshness]||'未知'} / ${connectionName(snapshot?.connectivity)}。保留历史值和时间，不作为当前有效观测。`})]),
  trend(),card('服务器实验规则结果','PROTOTYPE · 复用 DiagnosisService；页面不重复判断，非生产标准。',snapshot?.findings?.length?snapshot.findings.map(f=>el('p',{class:'muted',text:`${f.code} · ${f.message}`})):[el('p',{class:'muted',text:snapshot?.observed_at?'本轮已评估范围未命中实验规则；不代表疾病诊断。':'NO_DATA · 尚无水质上报。'})]),
  card('观测信息','窗口均值与单次观测有明确区别。',[rows([['来源',snapshot?.source],['上报状态',connectionName(snapshot?.connectivity)],['聚合方式',snapshot?.aggregation==='window_mean'?'窗口有效样本均值':'R1 Demo'],['窗口开始',timeText(snapshot?.window?.start)],['窗口结束',timeText(snapshot?.window?.end)],['观测时间',timeText(snapshot?.observed_at)],['服务器接收',timeText(snapshot?.received_at)],['查询时间',timeText(snapshot?.evaluated_at)],['批次',snapshot?.batch_id],['规则版本',snapshot?.rule_version]]),
    el('details',{class:'data-details'},[el('summary',{text:'样本与统计详情'}),table(['指标','有效 / 总数','无效样本','最小','最大','最新'],snapshot?.metrics||[],m=>[m.label,m.valid_samples===null?'—':`${m.valid_samples} / ${m.sample_count}`,m.invalid_samples??'—',m.minimum??'—',m.maximum??'—',m.latest??'—'])]),
    el('details',{class:'data-details'},[el('summary',{text:'已存储历史表'}),table(['观测时间','水温 °C','pH','溶解氧 mg/L'],snapshot?.trend||[],p=>[timeText(p.observed_at),p.temperature_c??'—',p.ph??'—',p.dissolved_oxygen_mg_l??'—'])])])];}

function assistant(){if(state.data.ai?.connected)return [assistantWorkspace.mount(state.data.devices,state.device)];return [el('div',{class:'assistant-layout'},[
  el('section',{class:'card chat-shell'},[el('div',{class:'chat-top'},[el('div',{},[icon('spark'),el('strong',{text:'渔业助手'})]),badge('服务未接入','neutral')]),
    el('div',{class:'chat-messages'},[el('div',{class:'chat-welcome'},[el('span',{class:'assistant-emblem'},[icon('spark')]),el('h2',{text:'让问题有依据，让建议可追溯。'}),el('p',{text:'R1 先建立对话容器。接入后，消息与只读工具通过应用层服务执行，不在页面内运行模型。'}),
      el('div',{class:'suggestions'},['当前水质有哪些需要关注的指标？','如何理解溶解氧？','查找相关养殖资料'].map(text=>button(text,()=>{state.draft=text;$('assistant-draft').value=text;})))])]),
    el('div',{class:'chat-composer'},[el('label',{for:'assistant-draft',text:'消息草稿',class:'sr-only'}),el('textarea',{id:'assistant-draft',rows:3,placeholder:'可以编辑草稿；AI 服务接入后再发送。',text:state.draft,oninput:e=>{state.draft=e.target.value;}}),
      el('div',{class:'composer-foot'},[el('span',{text:'尚未连接 AI · 不会产生模型请求'}),el('button',{class:'button primary',disabled:'disabled',text:'发送 · 尚未接入'})])])]),
  el('div',{class:'side-stack'},[card('模型与响应','应用服务提供模型清单与执行状态。',[rows([['模型','尚未加载'],['响应模式','Normal 默认 · Streaming 受发布门禁控制'],['运行状态','未连接']])]),
    card('工具执行','未来仅展示安全 Activity。',[empty('暂无执行记录','Tool 调用、步骤和来源证明将在服务接入后展示。','settings')]),
    card('开发验证','与管理平台的正式工作区分开。',[el('p',{class:'muted',text:'现有 AI Prototype Web 保留在独立端口，模型和凭据由原 Runtime 管理。'}),el('a',{class:'text-link',href:'http://127.0.0.1:8765',target:'_blank',rel:'noopener noreferrer',text:'打开现有 AI 原型 ↗'})])])])];}

const openedDeviceReports=new Set();
function deviceReports(){
  const inbox=state.data.integration?.device_reports;
  const deviceEvents=state.data.integration?.device_events;
  const eventDescription=deviceEvents?.enabled===true&&!deviceEvents.error_code
    ?'设备异常信号进入事件列表，但不自动判定恢复。':'设备报告仅展示；事件同步未启用或暂不可用，不自动判定恢复。';
  const items=inbox?.items||[];
  return card('设备视觉报告','设备联调 · 水质仍为 SIMULATOR；报告不等于疾病确诊或事件恢复证据。',[
    badge('DEVICE REPORT · 独立视觉来源','demo'),
    el('p',{text:inbox?.error_code?'设备报告读取失败 · 状态未知':!inbox?'尚未绑定设备报告目录 · 状态未知':`设备 ${inbox.device_id} · 最近 ${items.length} 份留存报告`}),
    el('p',{class:'muted',text:`仅异常上报时，沉默不能证明正常或离线。任务覆盖与连续性尚未确认；${eventDescription}旧模拟视觉与事件保留历史，不作为设备状态。`}),
    ...(deviceEvents?.error_code?[el('p',{class:'muted',text:'设备报告已保存，事件同步暂不可用；请检查同步服务。报告仍可查看，原有模拟监测继续运行。'})]:[]),
    ...items.map(({report:r,received_at,warnings,freshness})=>el('details',{class:'device-report',
      ...(openedDeviceReports.has(`${r.device_id}:${r.report_id}`)?{open:''}:{}),
      ontoggle:event=>{const key=`${r.device_id}:${r.report_id}`;if(event.target.open){openedDeviceReports.add(key);if(openedDeviceReports.size>100)openedDeviceReports.delete(openedDeviceReports.values().next().value);}else openedDeviceReports.delete(key);}},[
      el('summary',{text:`${timeText(r.window.end)} · ${freshness==='fresh'?'近期报告':'过期／未知，仅供回看'} · ${r.has_abnormality?'设备报告含异常信号（非确诊）':'设备报告未标异常（不代表全部正常）'}`}),
      rows([['设备',r.device_id],['报告ID',r.report_id],['窗口结束',timeText(r.window.end)],['服务器接收',timeText(received_at)],
        ['可见跟踪目标（非存量）',r.detection.unique_tracks],['处理帧',r.window.frames_processed],['行为任务',r.behavior===null?'未提供':'已提供原始对象，尚未解释'],['体长任务',r.measurement===null?'未提供':'已提供原始对象，尚未解释']]),
      ...(warnings?.length?[el('p',{text:`报文校验提示：${warnings.map(code=>({WINDOW_DURATION_MISMATCH:'窗口时长与起止时间不一致（WINDOW_DURATION_MISMATCH）',ABNORMALITY_FLAG_INCONSISTENT:'异常标志与列表不一致（ABNORMALITY_FLAG_INCONSISTENT）'}[code]||code)).join('、')}；不作为恢复证据。`})]:[]),
      ...r.abnormalities.map(a=>el('p',{text:`${a.name}（模型标签 ${a.label}）：${a.targets} 个目标，${a.count} 帧次；检测信号，非确诊。`})),
      el('pre',{class:'device-report-text',text:r.report_text})
    ])),
    ...(!items.length?[empty('尚无可显示设备报告','不会用模拟视觉填补设备报告。','camera')]:[])
  ]);
}
function video(){
  const snapshot=state.data.monitoring;
  const cameras=state.data.cameras;const camera=cameras.find(c=>c.id===state.camera)||cameras[0];const summary=camera?.summary;
  const behaviors={normal_activity:'正常活动',reduced_activity:'活动减少',feeding:'摄食',feeding_anomaly:'摄食异常',unknown:'未知'};
  const anomalies={suspected_lesion:'疑似病灶',surface_anomaly:'体表异常',suspected_dead:'疑似死亡个体'};
  const left=[card('水质读数','窗口观测，与视频画面独立。',[
    badge(sourceName(snapshot?.source_kind),'demo'),
    el('p',{class:'video-device-name',text:state.data.devices.find(d=>d.id===state.device)?.name||state.device}),
    ...(!snapshot?.observed_at?[el('p',{class:'video-data-caution',text:'NO_DATA · 尚无水质观测，状态未知。'})]:
      snapshot.freshness!=='fresh'||snapshot.connectivity!=='online'?[el('p',{class:'video-data-caution',text:'观测过期或上报状态不足；以下为留存读数，不能确认当前水质。'})]:[]),
    metricCards(snapshot),
    el('div',{class:'video-quality'},[badge(qualityNames[snapshot?.quality]||'未知',snapshot?.quality==='valid'?'success':'warning'),
      badge(freshnessNames[snapshot?.freshness]||'未知',snapshot?.freshness==='fresh'?'success':'warning'),badge(connectionName(snapshot?.connectivity),'neutral')]),
    el('p',{class:'video-observed-at',text:`观测 ${timeText(snapshot?.observed_at)}`}),link('查看水质详情','monitoring')]),
    card('水质规则信号','服务器实验规则，非专业健康或养殖保证。',snapshot?.findings?.length?
      snapshot.findings.map(f=>el('p',{class:'video-data-caution',text:`${f.code} · ${f.message}`})):
      [el('p',{class:'muted',text:snapshot?.observed_at&&snapshot.freshness==='fresh'&&snapshot.connectivity==='online'&&snapshot.quality==='valid'?
        '本窗口未命中已评估规则，不等于全部正常。':'当前证据不足，不能据此排除风险。'})]),
    card('观测信息','时间均为北京时间。',[rows([['设备',state.device],['接收时间',timeText(snapshot?.received_at)],['评估时间',timeText(snapshot?.evaluated_at)]]),
      el('details',{class:'data-details'},[el('summary',{text:'窗口与批次'}),rows([['窗口开始',timeText(snapshot?.window?.start)],['窗口结束',timeText(snapshot?.window?.end)],['批次',snapshot?.batch_id]])])])];
  const right=state.data.integration?.simulation_mode==='water-only'?[deviceReports()]:[
    card('视觉数据状态',`${sourceName(camera?.source_kind)} · 与播放画面独立。`,[
      ...(cameras.length>1?[el('div',{class:'camera-list'},cameras.map(c=>button(c.name,()=>{state.camera=c.id;render();},state.camera===c.id?'selected':'secondary')))]:[]),
      rows([['设备',camera?.name||'无设备'],['来源',sourceName(camera?.source_kind)],['上报状态',connectionName(camera?.status)],['新鲜度',freshnessNames[camera?.freshness]||'未知'],['检测信号',camera?.signal_status==='no_obvious_anomaly'?'未出现所列异常信号（模拟）':camera?.signal_status==='suspected_anomaly'?'疑似异常（模拟，非确诊）':camera?.signal_status==='no_valid_frames'?'无有效帧，信号未知':camera?.signal_status==='indeterminate'?'当前状态待确认':'暂无信号'],['观测时间',timeText(camera?.observed_at)],['接收时间',timeText(camera?.received_at)]])]),
    ...(summary?[card('疾病与异常检测信号','帧数可重叠；检测信号不作为疾病确诊。',[
      badge('SIMULATOR · 非诊断','demo'),rows(Object.entries(anomalies).map(([key,label])=>[label,`${summary.anomaly_counts[key]} / ${summary.valid_frames??summary.frames_processed} 有效帧`]))]),
      card('行为识别','窗口内有效帧比例，不是绝对行为结论。',[rows(Object.entries(behaviors).map(([key,label])=>[label,summary.valid_frames===0?'无有效帧':`${(summary.behavior_ratios[key]*100).toFixed(1)}%`]))]),
      card('体长与可见数量','体长按有效检测记录加权；无标定时不显示厘米值；可见鱼数不代表鱼池存量。',[rows([
        ['平均体长',summary.length.average_length_cm===null?'不可测量':`${summary.length.average_length_cm} cm（模拟标定）`],
        [summary.length.valid_frame_count===undefined?'旧窗口体长计数（旧语义）':'有效体长检测记录',summary.length.length_sample_count],['体长有效帧',summary.length.valid_frame_count??'旧窗口未记录'],
        ['有效画面 / 总帧',`${summary.valid_frames??summary.frames_processed} / ${summary.frames_processed}`],['标定',summary.length.calibration==='uncalibrated'?'未标定':'纯模拟标定'],
        ['画面平均可见数',summary.visible_fish_count??'缺失'],['模型版本',summary.model_version],['窗口开始',timeText(camera.window?.start)],
        ['窗口结束',timeText(camera.window?.end)],['关联批次',camera.batch_id]])])]
      :[card('视觉窗口汇总','没有补造另一通道数据。',[empty('NO_DATA · 暂无视觉上报','启动模拟器后显示窗口统计；不会生成假录像。','camera')])])];
  return [videoWorkspace.update({left,right,empty:state.data.video_preview?null:videoPlaceholder()})];}

async function requestEventDeletion(scope,item=null){
  if(eventDeletionBusy)return;
  eventDeletionBusy=true;
  const value={scope,...(item?{event_id:item.id}:{})},token=state.data.event_management?.write_token;
  const cancel=()=>{$('details-dialog').close();};
  try{
    const plan=await services.eventDeletionPreview(value,token);
    if(scope==='reset_cycle'||scope==='reset_all'){
      const all=scope==='reset_all';
      const commit=button(all?'确认清空全部事件记录':'确认永久删除此轮事件',async()=>{
        if(eventDeletionBusy)return;eventDeletionBusy=true;commit.disabled=true;
        try{
          const result=await services.eventDelete({...value,revision:plan.revision},token);
          $('details-dialog').close();state.eventOffset=0;
          if(all)state.eventFilters={q:'',severity:'',status:'',lookback_minutes:'all'};
          state.revision++;await refresh(true);
          $('refresh-status').textContent=`已永久删除 ${result.deleted_count} 条事件记录及其人工操作历史。监测继续运行。`;
        }catch(_){
          state.revision++;await refresh(true);
          details('删除未完成',[el('p',{text:'事件或权限已变化，或结果尚未确认。已刷新当前记录；没有自动重试，请重新预览后再确认。'}),button('关闭',cancel)]);
        }finally{eventDeletionBusy=false;commit.disabled=false;}
      },'danger');
      details(all?'清空全部事件记录':'永久删除此轮事件',[
        el('p',{text:all?'范围：全部设备、全部来源、全部时间的所有事件，包括异常中、恢复观察、状态待核实、已恢复和已人工结束；不受当前筛选或分页影响。':
          `${item.title} · ${item.id}。删除所选风险周期的全部关联记录；不能可靠归族的旧记录按所选记录处理。`}),
        el('p',{text:`预计永久删除 ${plan.count} 条事件记录、${plan.ack_count||0} 条确认历史、${plan.manual_end_count||0} 条人工结束历史；其中 ${plan.active_count||0} 条尚未由规则确认结束。`}),
        el('p',{class:'muted',text:'删除后无法在应用内恢复。本次只删除事件及其关联人工操作历史，保留水质历史、原始设备报告和QQ发送记录。'}),
        el('p',{text:'监测不会停止；如果后续新观测仍检出异常，会生成新的事件并可能重新提醒。删除不表示风险已恢复。'}),
        ...(plan.detached_reference_count?[el('p',{class:'muted',text:`将解除 ${plan.detached_reference_count} 个关联引用；其他周期的观测记录保留。`})]:[]),
        el('div',{class:'event-confirm-actions'},[...(plan.count?[commit]:[]),button('取消',cancel)]),
        ...(!plan.count?[el('p',{text:'当前没有事件记录可清空。'})]:[])]);
      return;
    }
    const wholeCycle=scope==='cycle'||scope==='ack_cycle';
    const finish=()=>{
      const commit=button(wholeCycle?(plan.ack_count?'确认删除周期及确认历史':'确认删除整个周期'):scope==='single'?'确认删除此条事件':`确认清理 ${plan.count} 条记录`,async()=>{
        if(eventDeletionBusy)return;eventDeletionBusy=true;commit.disabled=true;
        try{const result=await services.eventDelete({...value,revision:plan.revision},token);
          $('details-dialog').close();state.eventOffset=0;state.revision++;await refresh(true);
          $('refresh-status').textContent=`已删除 ${wholeCycle?'整个已结束周期，共 ':''}${result.deleted_count} 条已结束事件记录${wholeCycle&&result.deleted_ack_count?`及 ${result.deleted_ack_count} 条确认历史`:''}`;
        }catch(_){details('删除未完成',[el('p',{text:'记录或权限可能已变化。未自动重试；请刷新后重新预览、确认。'}),button('关闭',cancel)]);}
        finally{eventDeletionBusy=false;commit.disabled=false;}
      },'danger');
      details(wholeCycle?'永久删除已结束周期':scope==='single'?'确认删除历史事件':'最终确认：清理全部已结束事件',[
        el('p',{text:scope!=='all_resolved'?`${item.title} · ${item.id}`:'范围：全部设备、全部时间的可删除已结束记录，包含符合条件的旧版已结束记录；不受当前筛选或分页影响。'}),
        el('p',{text:`预计删除 ${plan.count} 条。数据库硬删除，应用内不可撤销；水质历史、批次及其他业务数据不受影响。`}),
        ...(wholeCycle?[el('p',{text:plan.ack_count?`同时永久删除该周期的 ${plan.ack_count} 条确认历史及等级关联。此后无法查看该周期的确认时间及当时等级；不会保留可恢复的归档。`:
          '删除本周期全部等级的原始记录，避免删除后仍留下同一周期。该周期没有人工确认历史；其他风险周期不受影响。'})]:[]),
        ...(plan.legacy_count?[el('p',{text:`其中 ${plan.legacy_count} 条为旧版已结束记录，未经新版规则复核；清理不表示已验证恢复，不补造人工确认。`})]:[]),
        el('div',{class:'event-confirm-actions'},[...(plan.count?[commit]:[]),button('取消',cancel)]),
        ...(!plan.count?[el('p',{text:'没有可删除的已结束事件。'})]:[])]);
    };
    if(scope!=='all_resolved')finish();
    else details('清理范围核对',[
      el('p',{text:`全部设备、全部时间，共 ${plan.count} 条可删除的已结束事件，其中 ${plan.legacy_count||0} 条为旧版已结束记录；忽略当前筛选和分页。活动、恢复观察及未结束的未知事件均保留。`}),
      el('div',{class:'event-confirm-actions'},[button('继续核对',finish),button('取消',cancel)])]);
  }catch(_){details('无法准备删除',[el('p',{text:'记录状态或权限不允许操作。请刷新后重新检查。'}),button('关闭',cancel)]);}
  finally{eventDeletionBusy=false;}
}

function events(){const filters=state.eventFilters,maintenance=Boolean(state.data.event_management?.enabled);
  const body=el('div',{id:'events-table'}),count=el('p',{class:'muted'}),pager=el('div',{class:'event-pager'});
  const update=async()=>{
    if(!maintenance){body.replaceChildren(eventsTable(filterItems(state.data.events,filters)));return;}
    const revision=++eventQueryRevision;
    count.textContent='正在查询全部留存事件…';
    try{const data=await services.events({...filters,limit:50,offset:state.eventOffset});
      if(revision!==eventQueryRevision)return;
      if(data.total&&state.eventOffset>=data.total){state.eventOffset=0;return update();}
      body.replaceChildren(eventsTable(data.items,true));
      count.textContent=`共 ${data.total} 条符合条件 · 本页 ${data.items.length} 条 · 已查询全部留存记录（风险周期）`;
      const previous=button('上一页',()=>{state.eventOffset=Math.max(0,state.eventOffset-50);void update();});previous.disabled=state.eventOffset===0;
      const next=button('下一页',()=>{state.eventOffset+=50;void update();});next.disabled=state.eventOffset+50>=data.total;
      pager.replaceChildren(previous,el('span',{text:`第 ${Math.floor(state.eventOffset/50)+1} 页`}),next);
    }catch(_){if(revision!==eventQueryRevision)return;body.replaceChildren(empty('事件查询失败','请刷新重试；不把缓存当作查询结果。'));count.textContent='查询失败';pager.replaceChildren();}
  };
  const change=()=>{state.eventOffset=0;void update();};
  void update();
  return [el('div',{class:'filters'},[search('搜索事件',filters.q,v=>{filters.q=v;change();}),select('事件等级',[['','全部等级'],['critical','严重'],['warning','提醒'],['info','信息']],filters.severity,v=>{filters.severity=v;change();}),
    select('事件状态',state.data.data_mode==='simulator'?[['','全部状态'],['ACTIVE','异常中'],['RESOLVED','已恢复'],['MANUALLY_ENDED','已人工结束'],['INDETERMINATE','状态待核实／旧版未复核']]:[['','全部状态'],['pending','待处理（演示）'],['closed','已处理（演示）']],filters.status,v=>{filters.status=v;change();}),
    ...(maintenance?[select('事件时间范围',[['5','最近 5 分钟'],['10','最近 10 分钟'],['30','最近 30 分钟'],['60','最近 1 小时'],['all','全部记录']],filters.lookback_minutes||'all',v=>{filters.lookback_minutes=v;change();})]:[]),
    button('重置筛选',()=>{state.eventFilters={q:'',severity:'',status:'',lookback_minutes:'all'};state.eventOffset=0;render();})]),
    card('事件列表','PROTOTYPE · 模拟与设备检测分别标注来源；检测信号需核查，非疾病确诊。',[count,body,pager],maintenance?el('div',{class:'event-confirm-actions'},[
      button('清理全部已结束事件',()=>requestEventDeletion('all_resolved'),'secondary'),
      button('清空全部事件记录',()=>requestEventDeletion('reset_all'),'danger')]):null),
    el('p',{class:'footnote',text:'“已恢复”表示已满足规则消退条件；“已确认”仅表示知晓，不表示恢复。可删除所选事件，或清空全部状态的事件及其确认、人工结束历史。清空不受筛选和分页影响，不删除水质历史或原始设备报告；后续新观测仍可能重新产生事件。'})];}

function knowledge(){return [knowledgeWorkspace.mount()];}

function settings(){return [settingsWorkspace.mount()];}

const pages={dashboard,monitoring,assistant,video,events,knowledge,settings};
function render(passive=false){if(!state.data)return;if(state.readFailed){localVideoPreview.update(null);$('content').replaceChildren(empty('读取失败 · 上次显示已失效','请恢复服务器连接，不将缓存当作当前数据。'));return;}const route=routeFor(location.hash);$('page-title').textContent=route.title;$('page-eyebrow').textContent=route.eyebrow;$('page-description').textContent=route.description;$('breadcrumb').textContent=route.title;
  document.title=`${route.title} · AI 监测系统`;const content=pages[route.id]();
  if(route.id!=='video'||!$('content').contains(videoWorkspace.node))$('content').replaceChildren(...content);
  localVideoPreview.update(state.data.video_preview,route.id==='video');
  document.querySelectorAll('#navigation a').forEach(a=>{const active=a.hash===`#${route.id}`;a.classList.toggle('active',active);if(active)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});
  if(!passive){$('sidebar').classList.remove('open');$('menu-toggle').setAttribute('aria-expanded','false');}}
let refreshing=false;
async function refresh(force=false){
  if(refreshing&&!force)return;
  const revision=state.revision,device=state.device;
  refreshing=true;
  try{
    let data=validateBootstrap(await services.bootstrap(state.data?device:undefined));
    if(!state.data&&data.preferences){
      const defaults=data.preferences;
      if(data.devices.some(d=>d.id===defaults.device_id)){state.device=defaults.device_id;
        data=validateBootstrap(await services.bootstrap(state.device));}
      assistantWorkspace.setDefaults(defaults);
    }
    if(revision!==state.revision)return;
    if(data.data_mode==='demo'&&state.view!=='available')data.monitoring=await services.monitoring(device,state.view);
    if(revision!==state.revision)return;
    const recovered=state.readFailed;state.readFailed=false;state.data=data;
    if(!data.devices.some(d=>d.id===state.device))state.device=data.devices[0]?.id||'';
    if(!data.cameras.some(c=>c.id===state.camera))state.camera=data.cameras[0]?.id||'';
    $('source-label').textContent=sourceName(data.data_mode);
    $('source-notice').textContent=data.integration?.simulation_mode==='water-only'?'设备联调：水质为 SIMULATOR；视觉来自独立设备报告，未确认设备恢复。':data.data_mode==='simulator'?'水质与视觉来自模拟器 HTTP 上报，非真实设备或疾病诊断。页面与已启用的水质 Tool 共用统一存储。':'独立 R1 Demo；不是传感器、NPU 或正式 AI 数据。';
    document.querySelector('.environment').textContent=data.integration?.simulation_mode==='water-only'?'设备联调：水质为 SIMULATOR；视觉来自独立设备报告，未确认设备恢复。':data.data_mode==='simulator'?'本机模拟接入':'DEMO 环境';
    $('refresh-status').textContent='服务器状态已更新';
    const active=document.activeElement;
    if(force||!active?.matches('input,select,textarea')){
      if(force||recovered||['dashboard','monitoring','video','events'].includes(routeFor(location.hash).id))render(!force);
    }
  }catch(_){
    if(revision!==state.revision)return;
    localVideoPreview.update(null);
    state.readFailed=true;$('refresh-status').textContent='读取失败 · 上次显示已失效';
    if(force||!state.data)$('content').replaceChildren(card('工作区暂不可用','不使用假数据掩盖服务错误。',[empty('服务加载失败','请检查管理服务。'),button('重新加载',bootstrap)]));
    else $('content').replaceChildren(empty('读取失败 · 上次显示已失效','请恢复服务器连接，不将缓存当作当前数据。'));
  }finally{refreshing=false;}
}
async function bootstrap(){await refresh(true);}

$('navigation').append(...routes.map(r=>el('a',{href:`#${r.id}`},[icon(r.icon),el('span',{text:r.label})])));
$('menu-toggle').addEventListener('click',()=>{$('sidebar').classList.toggle('open');$('menu-toggle').setAttribute('aria-expanded',String($('sidebar').classList.contains('open')));});
$('dialog-close').addEventListener('click',()=>$('details-dialog').close());
$('details-dialog').addEventListener('click',e=>{if(e.target===$('details-dialog'))$('details-dialog').close();});
window.addEventListener('hashchange',()=>{render();$('main').focus({preventScroll:true});window.scrollTo(0,0);});
document.querySelector('.skip-link').addEventListener('click',event=>{event.preventDefault();$('main').focus();});
document.addEventListener('keydown',event=>{if(event.key==='Escape'){$('sidebar').classList.remove('open');$('menu-toggle').setAttribute('aria-expanded','false');}});
document.addEventListener('click',event=>{if(!$('sidebar').contains(event.target)&&!$('menu-toggle').contains(event.target)){$('sidebar').classList.remove('open');$('menu-toggle').setAttribute('aria-expanded','false');}});
bootstrap();
let poll;
function startPolling(){if(!poll)poll=setInterval(()=>{if(!document.hidden)refresh();},5000);}
startPolling();
window.addEventListener('pagehide',()=>{clearInterval(poll);poll=null;assistantWorkspace.suspend();localVideoPreview.suspend();});
window.addEventListener('pageshow',()=>{startPolling();});

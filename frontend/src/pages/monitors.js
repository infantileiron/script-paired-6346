import {state} from '../stores/session.js';import {esc} from '../utils/html.js';import {badge} from '../components/common/status.js';import {field,select} from '../components/common/fields.js';import {table} from '../components/common/table.js';import {JOB_LABELS,ALERT_LABELS} from '../constants/enums.js';
const f2=v=>(v===null||v===undefined)?'—':Number(v).toFixed(2);
function monitorForm(){
 const approved=state.adoptions.filter(a=>a.status==='approved');
 const used=new Set(state.monitors.map(m=>m.adoption_id));
 const options=approved.filter(a=>!used.has(a.id)).map(a=>[a.id,`采纳 #${a.id} · 评估 #${a.evaluation_id} · ${a.decision}`]);
 return `<form id="monitor">${select('已签核采纳','adoption_id',options)}${field('改善告警阈值（分）','threshold','number','value="-2" step="0.1" min="-100" max="100" required')}<p>建立时冻结原评估后测均值与顾问范围；后续抽检按业务日、顾问等权聚合，连续两个相邻业务日改善低于阈值即告警。</p><button class="primary">建立监测</button></form>${options.length?'':'<p class="notice">尚无可用的已签核采纳，请先在采纳页完成签核。</p>'}`
}
function ingestForm(){
 return `<form id="ingest"><label>客户端令牌（重试时保持相同，留空则不做幂等）<input name="client_token" placeholder="例如 batch-20261118-01"></label><label>抽检批次（每行一条：抽检编号,业务日YYYY-MM-DD,顾问编号,版本,得分）<textarea name="lines" rows="8" placeholder="S-1001,2026-11-18,QY-001,v1,75.5&#10;S-1002,2026-11-18,QY-002,v1,76.0" required></textarea></label><button class="primary">提交抽检批次</button></form><p>旧版本不会覆盖新版本；乱序、迟到记录会自动重算受影响的连续日段。</p>`
}
function alertBlock(a){
 const basis=a.basis?.days?.map(d=>`${d.biz_date} 改善 ${f2(d.improvement)}（${d.consultant_count} 位顾问，均分 ${f2(d.day_mean)}）`).join('<br>')||'';
 const actions=state.user.role==='admin'
  ?(a.status==='active'?`<button data-confirm-alert="${a.id}">确认告警（依据随即锁定）</button>`:'')+(a.status!=='revoked'?`<button data-revoke-alert="${a.id}">撤销告警</button>`:'')
  :'';
 return `<article class="rec alert-${esc(a.status)}"><h3>${ALERT_LABELS[a.status]||a.status} ${badge(a.status)} <span class="eyebrow">#${a.id} · 修订 ${a.basis_revision} 版</span></h3><p>连续日段 ${a.start_date} → ${a.end_date}（触发日 ${a.trigger_date}）· 阈值 ${f2(a.threshold)}</p><p class="notice">${basis}</p>${a.confirmed_by?`<p>确认：${esc(a.confirmed_by)} · ${esc(a.confirmed_at||'')}（依据保持原样）</p>`:''}${a.revoked_by?`<p>撤销：${esc(a.revoked_by)} · ${esc(a.revoked_at||'')}<br>${esc(a.revoke_reason||'')}</p>`:''}${actions}</article>`
}
export function render(){
 const m=state.monitorDetail;
 if(!m){
  return `<div class="split"><section class="panel"><h2>签核后的持续监测</h2><p class="notice">为已签核采纳建立监测：冻结原评估后测均值与顾问范围，按业务日接收抽检，连续两日改善低于阈值即告警。</p>${table(['ID','采纳','评估','阈值','冻结后测均值','范围人数','状态'],state.monitors.map(x=>[x.id,`#${x.adoption_id}`,`#${x.evaluation_id}`,f2(x.threshold),f2(x.baseline_after_mean),x.frozen_scope.length,x.state]))}${state.monitors.map(x=>`<button class="study" data-monitor="${x.id}">打开监测 #${x.id}</button>`).join('')||'<p>尚无监测。</p>'}</section><aside class="side"><h2>建立监测</h2>${monitorForm()}</aside></div>`
 }
 const active=m.alerts.filter(a=>a.status==='active');
 return `<div class="split"><section class="panel"><h2>监测 #${m.id} ${badge(m.state)}</h2><p class="eyebrow">采纳 #${m.adoption_id}（${esc(m.adoption.decision)} · ${esc(m.adoption.status)}）· 评估 #${m.evaluation_id}</p><p>冻结后测均值 <strong>${f2(m.baseline_after_mean)}</strong> · 冻结前测均值 ${f2(m.baseline_before_mean)} · 阈值 ${f2(m.threshold)} · 顾问范围 ${m.frozen_scope.length} 位：${m.frozen_scope.map(c=>esc(c.code)).join('、')}</p><h3>当前风险（${active.length} 条待确认告警）</h3>${active.map(alertBlock).join('')||'<p class="notice">当前没有待确认告警。缺测日会断开连续性。</p>'}<h3>每日聚合（顾问等权）</h3>${table(['业务日','顾问数','当日均分','改善(对比冻结后测)'],m.dailies.reduce((acc,d)=>{if(!acc.some(r=>r[0]===d.biz_date))acc.push([d.biz_date,d.consultant_count,f2(d.day_mean),f2(d.improvement)]);return acc},[]))}<h3>告警沿革</h3>${m.alerts.map(alertBlock).join('')||'<p>尚无告警。</p>'}<h3>接收批次（最近50）</h3>${table(['批次','令牌','状态','错误','更新时间'],m.jobs.map(j=>[j.id,j.client_token||'—',JOB_LABELS[j.state]||j.state,j.error||'—',j.updated||'—']))}<p><button data-monitor-list>返回监测列表</button> <button id="refresh-monitor">刷新</button> <button id="recompute-monitor">手动重算</button></p></section><aside class="side"><h2>接收后续抽检</h2>${ingestForm()}</aside></div>`
}

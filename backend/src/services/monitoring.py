from contextlib import contextmanager
from datetime import datetime,timezone,timedelta
from src.models.entities import Monitor,MonitorRecord,MonitorDaily,MonitorAlert
from src.services.queue import advisory_lock
def now_iso():return datetime.now(timezone.utc).isoformat()
@contextmanager
def monitor_lock(s,monitor_id):
 """监测级串行点：重算/接收与确认/撤销互斥。
 咨询锁保证跨方言（含 SQLite 测试）行为一致；PostgreSQL 上再叠加 FOR UPDATE 行锁覆盖多进程。"""
 with advisory_lock(f'monitor:{monitor_id}'):
  row=s.get(Monitor,monitor_id)
  if not row:raise ValueError('监测不存在')
  try:locked=s.query(Monitor).filter(Monitor.id==monitor_id).with_for_update().first() or row
  except Exception:locked=row
  yield locked
def freeze_baseline(evaluation):
 """从已冻结评估快照固化顾问范围与后测均值；评估之后的样本修订不影响监测。"""
 snapshot=evaluation.result['snapshot']
 kept=[r for r in snapshot if r['before'] is not None and r['after'] is not None]
 if not kept:raise ValueError('评估冻结样本中没有完整配对，无法建立监测')
 scope=[{'code':r['code'],'team':r.get('team'),'before':r['before'],'after':r['after']} for r in kept]
 after_mean=sum(r['after'] for r in kept)/len(kept)
 before_mean=sum(r['before'] for r in kept)/len(kept)
 return scope,float(after_mean),float(before_mean)
def _latest_records(s,monitor_id):
 """同一抽检编号以新版本为准；旧版本保留留痕但不再参与聚合。"""
 rows=s.query(MonitorRecord).filter_by(monitor_id=monitor_id).all()
 latest={}
 for r in rows:
  old=latest.get(r.sample_no)
  if old is None or r.version>old.version:latest[r.sample_no]=r
 return list(latest.values())
def ingest_records(s,monitor,job,items):
 """按抽检编号应用版本规则：更高版本替换，相同版本仅在内容一致时幂等通过，
 更低版本被拒绝；任何一条失败则整批失败（调用方在事务内回滚），不产生部分计分。
 返回 (新增/更新条数, 跳过条数)。"""
 scope={c['code'] for c in monitor.frozen_scope}
 inserted=updated=skipped=0
 existing={r.sample_no:r for r in s.query(MonitorRecord).filter_by(monitor_id=monitor.id).all()}
 for it in items:
  if it['code'] not in scope:raise ValueError(f"顾问 {it['code']} 不在签核时冻结的监测范围内")
  old=existing.get(it['sample_no'])
  if old is not None:
   if it['version']<old.version:raise ValueError(f"抽检编号 {it['sample_no']} 已有更高版本 {old.version}，旧版本不覆盖新版")
   if it['version']==old.version:
    if old.code==it['code'] and old.biz_date==it['biz_date'] and float(old.score)==float(it['score']):skipped+=1;continue
    raise ValueError(f"抽检编号 {it['sample_no']} 的版本 {it['version']} 已存在且内容不一致；修订请使用更高版本号")
   old.biz_date=it['biz_date'];old.code=it['code'];old.version=it['version'];old.score=it['score'];old.job_id=job.id;updated+=1
  else:
   s.add(MonitorRecord(monitor_id=monitor.id,biz_date=it['biz_date'],sample_no=it['sample_no'],code=it['code'],version=it['version'],score=it['score'],job_id=job.id,created=now_iso()));inserted+=1
 return inserted+updated,skipped
def recompute(s,monitor):
 """全量重算该监测的日聚合与告警。乱序/迟到记录进入后只依赖当前有效记录重算，
 缺测日不产生日行，从而自然断开连续日段。调用方需先持有 lock_monitor。"""
 latest=_latest_records(s,monitor.id)
 s.query(MonitorDaily).filter_by(monitor_id=monitor.id).delete(synchronize_session=False)
 # 第一步：按顾问等权聚合当日得分（一位顾问当日多条抽检等权平均）
 per_day={}
 for r in latest:per_day.setdefault(r.biz_date,{}).setdefault(r.code,[]).append(r.score)
 dailies=[]
 day_stats={}
 for biz_date in sorted(per_day):
  consultant_scores={code:sum(v)/len(v) for code,v in per_day[biz_date].items()}
  day_mean=sum(consultant_scores.values())/len(consultant_scores)
  improvement=day_mean-monitor.baseline_after_mean
  day_stats[biz_date]={'day_mean':day_mean,'improvement':improvement,'consultant_count':len(consultant_scores),'consultants':sorted(consultant_scores)}
  for code,score in consultant_scores.items():
   dailies.append(MonitorDaily(monitor_id=monitor.id,biz_date=biz_date,code=code,score=score,delta=score-monitor.baseline_after_mean,day_mean=day_mean,improvement=improvement,consultant_count=len(consultant_scores)))
 s.add_all(dailies)
 # 第二步：按业务日顺序扫描，缺测日（日历不相邻）断开连续性
 runs=[];cur=None;prev=None
 for biz_date in sorted(day_stats):
  below=day_stats[biz_date]['improvement']<monitor.threshold
  adjacent=prev is not None and (biz_date-prev)==timedelta(days=1)
  if below and adjacent and cur is not None:cur['dates'].append(biz_date)
  elif below:cur={'start':biz_date,'dates':[biz_date]};runs.append(cur)
  else:cur=None
  prev=biz_date
 qualifying={r['start']:r for r in runs if len(r['dates'])>=2}
 _reconcile_alerts(s,monitor,day_stats,qualifying)
 return day_stats
def _basis(monitor,run,day_stats):
 return {'baseline_after_mean':monitor.baseline_after_mean,'threshold':monitor.threshold,
  'days':[{'biz_date':d.isoformat(),**{k:v for k,v in day_stats[d].items() if k!='consultants'},'consultants':day_stats[d]['consultants']} for d in run['dates']]}
def _for_update(s,query):
 try:return query.with_for_update().all()
 except Exception:return query.all()
def _reconcile_alerts(s,monitor,day_stats,qualifying):
 existing=_for_update(s,s.query(MonitorAlert).filter(MonitorAlert.monitor_id==monitor.id,MonitorAlert.status.in_(['active','confirmed'])))
 by_start={a.start_date:a for a in existing}
 for start,run in qualifying.items():
  alert=by_start.pop(start,None)
  basis=_basis(monitor,run,day_stats);trigger=run['dates'][1];end=run['dates'][-1]
  if alert is None:
   s.add(MonitorAlert(monitor_id=monitor.id,status='active',start_date=start,end_date=end,trigger_date=trigger,threshold=monitor.threshold,basis=basis,basis_revision=0,created=now_iso(),updated=now_iso()))
  elif alert.status=='active':
   # 当前告警随修订更新；已确认告警的依据保持原样，不被重算覆盖
   alert.end_date=end;alert.trigger_date=trigger;alert.threshold=monitor.threshold;alert.basis=basis;alert.basis_revision+=1;alert.updated=now_iso()
 for stale in by_start.values():
  # 重算后连续条件不再成立：仅自动撤销未确认告警，已确认告警留作历史凭据
  if stale.status=='active':
   stale.status='revoked';stale.revoke_reason='迟到/乱序记录重算后，连续两日低于阈值的条件不再成立';stale.revoked_at=now_iso();stale.updated=now_iso()

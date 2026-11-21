import os,time,json,logging
from datetime import datetime,timezone
from pathlib import Path
import redis
from src.config.database import Session
from src.models.entities import Evaluation,Monitor,MonitorJob
from src.services.analysis import evaluate
from src.services.monitoring import ingest_records,recompute,monitor_lock,now_iso
from src.services.queue import EVAL_QUEUE,MONITOR_QUEUE,client
ARTIFACT_DIR=Path(os.environ.get('ARTIFACT_DIR','/artifacts'))
r=client()
def recover():
 # 中断可恢复：重启时把未完成的评估与监测任务重新入队，已完成任务不会重复计分或告警
 with Session() as recovery:
  for pending in recovery.query(Evaluation).filter(Evaluation.state.in_(['queued','running'])).all():
   pending.state='queued';r.rpush(EVAL_QUEUE,pending.id)
  for pending in recovery.query(MonitorJob).filter(MonitorJob.state.in_(['pending','running'])).all():
   pending.state='pending';r.rpush(MONITOR_QUEUE,pending.id)
  recovery.commit()
def run_evaluation(job_id):
 with Session() as s:
  row=s.get(Evaluation,job_id)
  if not row or row.state!='queued':return
  snapshot=row.result['snapshot'];row.state='running';s.commit()
  try:
   row.result={**evaluate(snapshot),'snapshot':snapshot};row.state='done'
   ARTIFACT_DIR.mkdir(parents=True,exist_ok=True)
   (ARTIFACT_DIR/(str(row.id)+'.json')).write_text(json.dumps(row.result,ensure_ascii=False))
  except Exception as e:row.state='failed';row.error=str(e)
  s.commit()
def run_monitor_job(job_id):
 with Session() as s:
  job=s.get(MonitorJob,job_id)
  # 状态守卫确保重试不重复计分
  if not job or job.state not in ('pending','running'):return
  monitor=s.get(Monitor,job.monitor_id)
  if not monitor or monitor.state!='active':
   job.state='failed';job.error='监测已停用或不存在';s.commit();return
  job.state='running';job.updated=now_iso();s.commit()
  try:
   # JSON 往返后业务日为 ISO 字符串，统一还原为 date 以便连续性计算
   records=[]
   for it in job.payload['records']:
    it=dict(it)
    if isinstance(it['biz_date'],str):it['biz_date']=datetime.strptime(it['biz_date'],'%Y-%m-%d').date()
    records.append(it)
   with monitor_lock(s,job.monitor_id) as locked:
    # 锁内完成“接收+重算”，与确认/撤销互斥，避免并发混用依据
    applied,skipped=ingest_records(s,locked,job,records)
    recompute(s,locked)
    job.state='done';job.error='';job.updated=now_iso()
    job.payload={**job.payload,'applied':applied,'skipped':skipped,'finished_at':now_iso()}
    s.commit()
  except Exception as e:
   s.rollback();job=s.get(MonitorJob,job_id);job.state='failed';job.error=str(e);job.updated=now_iso();s.commit()
   logging.exception('monitor job %s failed',job_id)
def main():
 recover()
 while True:
  Path('/tmp/heartbeat').touch()
  try:
   item=r.blpop([EVAL_QUEUE,MONITOR_QUEUE],timeout=3)
   if not item:continue
   queue=item[0].decode() if isinstance(item[0],bytes) else item[0]
   job_id=int(item[1])
   if queue==EVAL_QUEUE:run_evaluation(job_id)
   else:run_monitor_job(job_id)
  except Exception:logging.exception('worker');time.sleep(2)
if __name__=='__main__':main()

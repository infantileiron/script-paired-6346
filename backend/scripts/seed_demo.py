import random,datetime
from src.config.database import Base,engine,Session
from src.models.entities import User,Pair,Evaluation,Adoption,Monitor,MonitorJob,MonitorRecord,MonitorDaily,MonitorAlert
from src.utils.security import hash_password
from src.services.monitoring import freeze_baseline,ingest_records,recompute,now_iso
def seed():
 Base.metadata.create_all(engine);rng=random.Random(1115)
 with Session() as s:
  for role in ('admin','analyst','viewer'):
   email=role+'@demo.local'
   if not s.query(User).filter_by(email=email).first():s.add(User(email=email,role=role,password=hash_password('Demo123!')))
  for i in range(40):
   code=f'QY-{i+1:03}';before=round(rng.uniform(58,85),1);after=round(min(100,before+rng.gauss(4 if i<20 else 1,5)),1)
   if not s.query(Pair).filter_by(code=code).first():s.add(Pair(code=code,team='企业一组' if i<20 else '企业二组',before=None if i==38 else before,after=None if i==39 else after,note='前后各抽检5次客户沟通的平均得分；窗口均为7日'))
  s.commit()
  # 幂等：监测已存在则跳过演示数据，不覆盖人工修订
  if s.query(Monitor).count()==0 and s.query(Evaluation).filter_by(state='done').count()==0:
   rows=[{'code':p.code,'team':p.team,'before':p.before,'after':p.after} for p in s.query(Pair).order_by(Pair.id).all() if p.team=='企业一组' and p.before is not None and p.after is not None]
   ev=Evaluation(name='11月续约话术监测试点',team='企业一组',state='done',error='',result={'snapshot':rows})
   s.add(ev);s.flush()
   adoption=Adoption(evaluation_id=ev.id,decision='继续试点',note='企业一组改善稳定，签核后建立持续监测并按业务日跟踪后续抽检。',status='approved')
   s.add(adoption);s.flush()
   scope,after_mean,before_mean=freeze_baseline(ev)
   monitor=Monitor(adoption_id=adoption.id,evaluation_id=ev.id,threshold=-2.0,baseline_after_mean=after_mean,baseline_before_mean=before_mean,frozen_scope=scope,state='active',created=now_iso())
   s.add(monitor);s.flush()
   # 两个相邻业务日改善均低于阈值，预置一条待确认告警用于页面演示
   base=datetime.date(2026,11,16)
   job=MonitorJob(monitor_id=monitor.id,client_token='seed-demo-batch',state='pending',payload={'records':[]},created=now_iso(),updated=now_iso())
   s.add(job);s.flush()
   items=[]
   for day in (0,1):
    for idx,c in enumerate(scope):
     score=round(after_mean-3.5-day+rng.uniform(-1,1),1)
     items.append({'sample_no':f'SEED-{day}-{idx}','biz_date':base+datetime.timedelta(days=day),'code':c['code'],'version':'v1','score':score})
   job.payload={'records':[{**it,'biz_date':it['biz_date'].isoformat()} for it in items]}
   job.state='running';s.flush()
   ingest_records(s,monitor,job,items);recompute(s,monitor);job.state='done';job.updated=now_iso()
   s.commit();print({'users':s.query(User).count(),'pairs':s.query(Pair).count(),'monitors':s.query(Monitor).count(),'alerts':s.query(MonitorAlert).count()})
if __name__=='__main__':seed()

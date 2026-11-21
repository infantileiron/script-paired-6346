import os,json
from fastapi import APIRouter,Depends,HTTPException,Response
from sqlalchemy.exc import IntegrityError
from src.config.database import db
from src.models.entities import User,Pair,Evaluation,Adoption,Audit,Monitor,MonitorJob,MonitorAlert,MonitorDaily,MonitorRecord
from src.schemas.business import Login,PairInput,EvaluationInput,AdoptionInput,MonitorCreate,MonitorIngest,AlertRevoke
from src.middlewares.auth import current,editor,admin
from src.utils.security import verify,token
from src.services.business import audit,dump
from src.services.monitoring import freeze_baseline,recompute,monitor_lock,now_iso
from src.services.queue import enqueue,MONITOR_QUEUE
from src.controllers.business import ensure_evaluation
router=APIRouter()
@router.post('/auth/login')
def login(data:Login,s=Depends(db)):
 u=s.query(User).filter_by(email=data.email).first()
 if not u or not verify(data.password,u.password):raise HTTPException(401,'账号或密码错误')
 return {'token':token(u),'user':dump(u)}
@router.get('/me')
def me(u=Depends(current)):return dump(u)
@router.get('/pairs')
def pairs(u=Depends(current),s=Depends(db)):return [dump(r) for r in s.query(Pair).order_by(Pair.id).all()]
@router.post('/pairs')
def create_pair(data:PairInput,u=Depends(editor),s=Depends(db)):
 r=Pair(**data.model_dump());s.add(r)
 try:s.commit()
 except IntegrityError:s.rollback();raise HTTPException(409,'顾问编号已存在，每位顾问仅保留一组前后测')
 audit(s,u,'录入顾问配对 '+r.code);return dump(r)
@router.put('/pairs/{i}')
def edit_pair(i:int,data:PairInput,u=Depends(editor),s=Depends(db)):
 r=s.get(Pair,i)
 if not r:raise HTTPException(404,'配对记录不存在')
 for k,v in data.model_dump().items():setattr(r,k,v)
 try:s.commit()
 except IntegrityError:s.rollback();raise HTTPException(409,'顾问编号重复')
 audit(s,u,'修订配对 '+str(i));return dump(r)
@router.get('/evaluations')
def evaluations(u=Depends(current),s=Depends(db)):return [dump(r) for r in s.query(Evaluation).order_by(Evaluation.id.desc()).all()]
@router.post('/evaluations')
def evaluate(data:EvaluationInput,u=Depends(editor),s=Depends(db)):
 rows=[dump(r) for r in s.query(Pair).order_by(Pair.id).all() if data.team=='全部' or r.team==data.team]
 r=Evaluation(**data.model_dump(),result={'snapshot':rows});s.add(r);s.commit()
 try:enqueue('paired:evaluations',r.id)
 except Exception:r.state='failed';r.error='队列暂不可用，请稍后重新提交';s.commit();raise HTTPException(503,r.error)
 audit(s,u,'提交评估 '+str(r.id));return dump(r)
@router.get('/evaluations/{i}')
def detail(i:int,u=Depends(current),s=Depends(db)):return dump(ensure_evaluation(s,i))
@router.get('/evaluations/{i}/export')
def export(i:int,u=Depends(current),s=Depends(db)):
 r=ensure_evaluation(s,i)
 if r.state!='done':raise HTTPException(409,'仅成功评估可导出')
 return Response(json.dumps(dump(r),ensure_ascii=False,indent=2),media_type='application/json',headers={'Content-Disposition':f'attachment; filename="script-paired-{i}.json"'})
@router.get('/adoptions')
def adoptions(u=Depends(current),s=Depends(db)):return [dump(r) for r in s.query(Adoption).order_by(Adoption.id.desc()).all()]
@router.post('/adoptions')
def adoption(data:AdoptionInput,u=Depends(editor),s=Depends(db)):
 if ensure_evaluation(s,data.evaluation_id).state!='done':raise HTTPException(409,'评估完成后才能起草采纳意见')
 r=Adoption(**data.model_dump());s.add(r);s.commit();audit(s,u,'起草采纳意见 '+str(r.id));return dump(r)
@router.post('/adoptions/{i}/approve')
def approve(i:int,u=Depends(admin),s=Depends(db)):
 r=s.get(Adoption,i)
 if not r:raise HTTPException(404,'采纳意见不存在')
 if r.status!='draft':raise HTTPException(409,'已签核意见不可重复签核')
 r.status='approved';s.commit();audit(s,u,'签核意见 '+str(i));return dump(r)
def _ensure_monitor(s,i):
 m=s.get(Monitor,i)
 if not m:raise HTTPException(404,'监测不存在')
 return m
@router.get('/monitors')
def monitors(u=Depends(current),s=Depends(db)):return [dump(m) for m in s.query(Monitor).order_by(Monitor.id.desc()).all()]
@router.post('/monitors')
def create_monitor(data:MonitorCreate,u=Depends(editor),s=Depends(db)):
 adoption=s.get(Adoption,data.adoption_id)
 if not adoption:raise HTTPException(404,'采纳意见不存在')
 if adoption.status!='approved':raise HTTPException(409,'仅已签核采纳可建立持续监测；原签核保留不变')
 if s.query(Monitor).filter_by(adoption_id=adoption.id).first():raise HTTPException(409,'该采纳已建立监测，阈值如需调整请新建评估与采纳后再建')
 ev=ensure_evaluation(s,adoption.evaluation_id)
 try:scope,after_mean,before_mean=freeze_baseline(ev)
 except ValueError as e:raise HTTPException(422,str(e))
 m=Monitor(adoption_id=adoption.id,evaluation_id=ev.id,threshold=data.threshold,baseline_after_mean=after_mean,baseline_before_mean=before_mean,frozen_scope=scope,state='active',created=now_iso())
 s.add(m);s.commit();audit(s,u,f'建立采纳监测 {m.id}（阈值 {data.threshold}，范围 {len(scope)} 位顾问）');return dump(m)
@router.get('/monitors/{i}')
def monitor_detail(i:int,u=Depends(current),s=Depends(db)):
 m=_ensure_monitor(s,i)
 dailies=[dump(d) for d in s.query(MonitorDaily).filter_by(monitor_id=i).order_by(MonitorDaily.biz_date,MonitorDaily.code).all()]
 alerts=[dump(a) for a in s.query(MonitorAlert).filter_by(monitor_id=i).order_by(MonitorAlert.id.desc()).all()]
 jobs=[dump(j) for j in s.query(MonitorJob).filter_by(monitor_id=i).order_by(MonitorJob.id.desc()).limit(50).all()]
 adoption=dump(s.get(Adoption,m.adoption_id))
 records=s.query(MonitorRecord).filter_by(monitor_id=i).order_by(MonitorRecord.biz_date,MonitorRecord.sample_no).all()
 return {**dump(m),'adoption':adoption,'dailies':dailies,'alerts':alerts,'jobs':jobs,'record_count':len(records)}
@router.post('/monitors/{i}/ingest')
def ingest(i:int,data:MonitorIngest,u=Depends(editor),s=Depends(db)):
 m=_ensure_monitor(s,i)
 if m.state!='active':raise HTTPException(409,'监测已停用，不再接收抽检')
 # 客户端令牌保证重试不重复计分或告警
 if data.client_token:
  dup=s.query(MonitorJob).filter_by(monitor_id=i,client_token=data.client_token).first()
  if dup:return dump(dup)
 payload={'records':[it.model_dump(mode='json') for it in data.records]}
 job=MonitorJob(monitor_id=i,client_token=data.client_token,state='pending',payload=payload,created=now_iso(),updated=now_iso())
 s.add(job);s.commit()
 try:enqueue(MONITOR_QUEUE,job.id)
 except Exception:
  job.state='failed';job.error='队列暂不可用，请稍后重试';s.commit();raise HTTPException(503,job.error)
 audit(s,u,f'监测 {i} 接收抽检批次 {job.id}（{len(data.records)} 条）');return dump(job)
@router.get('/monitors/{i}/jobs/{j}')
def monitor_job(i:int,j:int,u=Depends(current),s=Depends(db)):
 job=s.get(MonitorJob,j)
 if not job or job.monitor_id!=i:raise HTTPException(404,'批次不存在')
 return dump(job)
@router.post('/monitors/{i}/alerts/{a}/confirm')
def confirm_alert(i:int,a:int,u=Depends(admin),s=Depends(db)):
 _ensure_monitor(s,i)
 with monitor_lock(s,i):
  # 监测级锁串行化“接收/重算”与“确认”：确认拿到的依据即提交时的依据，并发重算不会混用
  row=s.query(MonitorAlert).filter_by(id=a,monitor_id=i).first()
  if not row:raise HTTPException(404,'告警不存在')
  if row.status=='confirmed':raise HTTPException(409,'告警已确认，依据保持原样')
  if row.status=='revoked':raise HTTPException(409,'告警已撤销，不能确认')
  row.status='confirmed';row.confirmed_by=u.email;row.confirmed_at=now_iso();row.updated=now_iso();s.commit()
 audit(s,u,f'确认监测告警 {a}（依据修订版 {row.basis_revision}）');return dump(row)
@router.post('/monitors/{i}/alerts/{a}/revoke')
def revoke_alert(i:int,a:int,data:AlertRevoke,u=Depends(admin),s=Depends(db)):
 _ensure_monitor(s,i)
 with monitor_lock(s,i):
  row=s.query(MonitorAlert).filter_by(id=a,monitor_id=i).first()
  if not row:raise HTTPException(404,'告警不存在')
  if row.status=='revoked':raise HTTPException(409,'告警已撤销')
  before=row.status
  row.status='revoked';row.revoked_by=u.email;row.revoked_at=now_iso();row.revoke_reason=data.reason;row.updated=now_iso();s.commit()
 audit(s,u,f'撤销监测告警 {a}（原状态 {before}）：{data.reason}');return dump(row)
@router.post('/monitors/{i}/recompute')
def manual_recompute(i:int,u=Depends(editor),s=Depends(db)):
 _ensure_monitor(s,i)
 with monitor_lock(s,i) as m:
  recompute(s,m);s.commit()
 audit(s,u,f'手动重算监测 {i}');return monitor_detail(i,u,s)
@router.get('/audits')
def audits(u=Depends(admin),s=Depends(db)):return [dump(r) for r in s.query(Audit).order_by(Audit.id.desc()).limit(100)]

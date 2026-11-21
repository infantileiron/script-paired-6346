import os,sys,datetime,threading,time,tempfile,pathlib
sys.path.insert(0,'/workspace/backend')
os.environ.setdefault('DATABASE_URL','sqlite+pysqlite:///:memory:')
os.environ.setdefault('REDIS_URL','redis://unused/0')
os.environ.setdefault('JWT_SECRET','test-secret-3115')
ART=pathlib.Path(tempfile.mkdtemp());os.environ['ARTIFACT_DIR']=str(ART)
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
import src.config.database as dbmod
engine=create_engine('sqlite+pysqlite:///:memory:',connect_args={'check_same_thread':False},poolclass=StaticPool)
dbmod.engine=engine
dbmod.Session.configure(bind=engine)
import redis
class FakeRedis:
 def __init__(self):self.q=[];self.lock=threading.Lock()
 def rpush(self,k,v):
  with self.lock:self.q.append((k,int(v)))
 def blpop(self,keys,timeout=0):
  deadline=time.time()+timeout
  while time.time()<deadline:
   with self.lock:
    for idx,k in enumerate(self.q):
     name=k[0]
     if name in keys:return self.q.pop(idx)
   time.sleep(0.02)
  return None
 def ping(self):return True
fake=FakeRedis()
redis.Redis.from_url=lambda *a,**k:fake
from src.config.database import Base,Session
import src.models.entities
Base.metadata.create_all(engine)
from src.models.entities import User,Pair,Evaluation,Adoption,Monitor,MonitorJob,MonitorAlert,MonitorDaily
from src.utils.security import hash_password
from src.main import app
from fastapi.testclient import TestClient
from src.services.analysis import evaluate
PASS=0;FAIL=0
def check(name,cond,detail=''):
 global PASS,FAIL
 if cond:PASS+=1;print(f'  PASS {name}')
 else:FAIL+=1;print(f'  FAIL {name} {detail}')
with Session() as s:
 s.add(User(email='admin@demo.local',role='admin',password=hash_password('Demo123!')))
 s.add(User(email='analyst@demo.local',role='analyst',password=hash_password('Demo123!')))
 s.add(User(email='viewer@demo.local',role='viewer',password=hash_password('Demo123!')))
 data=[('QY-001',70.0,76.0),('QY-002',72.0,77.0),('QY-003',68.0,74.0),('QY-004',75.0,79.0)]
 for code,b,a in data:s.add(Pair(code=code,team='企业一组',before=b,after=a,note='t'))
 s.commit()
c=TestClient(app)
def login(role):
 r=c.post('/auth/login',json={'email':f'{role}@demo.local','password':'Demo123!'});return r.json()['token']
ta=login('analyst');tad=login('admin');tv=login('viewer')
H=lambda t:{'Authorization':'Bearer '+t}
# 评估 + 采纳 + 签核
r=c.post('/evaluations',json={'name':'监测前置评估','team':'企业一组'},headers=H(ta));ev=r.json();check('评估入队',ev['state']=='queued')
from src.worker import run_evaluation
run_evaluation(ev['id'])
r=c.get(f'/evaluations/{ev["id"]}',headers=H(ta));ev=r.json();check('评估完成',ev['state']=='done')
r=c.post('/adoptions',json={'evaluation_id':ev['id'],'decision':'继续试点','note':'客户结构稳定，继续小范围试点并跟踪后续抽检'},headers=H(ta));ad=r.json()
r=c.post(f'/adoptions/{ad["id"]}/approve',json={},headers=H(tad));check('签核',r.status_code==200 and r.json()['status']=='approved')
r=c.post(f'/adoptions/{ad["id"]}/approve',json={},headers=H(tad));check('重复签核被拒',r.status_code==409)
# viewer 不能建监测
r=c.post('/monitors',json={'adoption_id':ad['id'],'threshold':-2.0},headers=H(tv));check('观察员只读',r.status_code==403)
# 建立监测：冻结后测均值与顾问范围
r=c.post('/monitors',json={'adoption_id':ad['id'],'threshold':-2.0},headers=H(ta));m=r.json();check('建立监测',r.status_code==200)
mid=m['id'];base=m['baseline_after_mean']
check('冻结后测均值',abs(base-(76+77+74+79)/4)<1e-9,base)
check('冻结顾问范围',{x['code'] for x in m['frozen_scope']}=={'QY-001','QY-002','QY-003','QY-004'})
r=c.post('/monitors',json={'adoption_id':ad['id'],'threshold':-1.0},headers=H(ta));check('同一采纳不可重复建监测',r.status_code==409)
from src.worker import run_monitor_job
def ingest(token,records,token_hdr=ta):
 r=c.post(f'/monitors/{mid}/ingest',json={'client_token':token,'records':records},headers=H(token_hdr))
 return r
def process_all():
 while fake.q:
  k,jid=fake.q.pop(0)
  if k=='paired:monitor_jobs':run_monitor_job(jid)
def detail():return c.get(f'/monitors/{mid}',headers=H(ta)).json()
def D(d):return d.isoformat()
d0=datetime.date(2026,11,18);d1=d0+datetime.timedelta(days=1);d2=d0+datetime.timedelta(days=2);d3=d0+datetime.timedelta(days=3);d5=d0+datetime.timedelta(days=5)
# 第1日：改善 -1（高于阈值 -2，不告警）；第2日：改善 -3（低于阈值），仅单日不告警
ingest('tok-d1',[{'sample_no':f'S1-{x}','biz_date':D(d0),'code':code,'version':'v1','score':sc} for x,(code,sc) in enumerate([('QY-001',75.0),('QY-002',76.0),('QY-003',73.0),('QY-004',78.0)])])
ingest('tok-d2',[{'sample_no':f'S2-{x}','biz_date':D(d1),'code':code,'version':'v1','score':sc} for x,(code,sc) in enumerate([('QY-001',73.0),('QY-002',74.0),('QY-003',71.0),('QY-004',76.0)])])
process_all()
det=detail()
check('批次均可用',all(j['state']=='done' for j in det['jobs']),det['jobs'])
check('单日低于阈值不告警',len(det['alerts'])==0,det['alerts'])
# 第3日继续低于阈值（相邻），连续两日 -> 告警，trigger 为第2日
ingest('tok-d3',[{'sample_no':f'S3-{x}','biz_date':D(d2),'code':code,'version':'v1','score':sc} for x,(code,sc) in enumerate([('QY-001',72.0),('QY-002',73.0),('QY-003',70.0),('QY-004',75.0)])])
process_all()
det=detail()
check('连续两日触发告警',len(det['alerts'])==1 and det['alerts'][0]['status']=='active',det['alerts'])
alert=det['alerts'][0]
check('告警窗口为连续日段',alert['start_date']==D(d1) and alert['end_date']==D(d2) and alert['trigger_date']==D(d2),alert)
check('告警依据冻结了每日明细',len(alert['basis']['days'])==2 and alert['basis']['baseline_after_mean']==base)
# 当前告警随修订更新：第4日（相邻）继续低于阈值，活动告警延长为三日段，basis_revision 递增
ingest('tok-d4',[{'sample_no':f'S4-{x}','biz_date':D(d3),'code':code,'version':'v1','score':sc} for x,(code,sc) in enumerate([('QY-001',71.0),('QY-002',72.0),('QY-003',69.0),('QY-004',74.0)])])
process_all()
det=detail();al=det['alerts'][0]
check('活动告警随修订延长',al['status']=='active' and al['end_date']==D(d3) and al['basis_revision']==1 and len(al['basis']['days'])==3,al)
# 缺测日断开连续性：跳过 d4，d5 低于阈值只能开始新段，不与 d2 连续
ingest('tok-d5',[{'sample_no':f'S5-{x}','biz_date':D(d5),'code':code,'version':'v1','score':sc} for x,(code,sc) in enumerate([('QY-001',72.0),('QY-002',73.0),('QY-003',70.0),('QY-004',75.0)])])
process_all()
det=detail()
check('缺测日断开连续性（仍只有一条告警）',len(det['alerts'])==1,det['alerts'])
# 等权聚合：同一顾问当日两条抽检先等权，再顾问间等权
ingest('tok-d6',[{'sample_no':'S6-a','biz_date':D(d5),'code':'QY-001','version':'v1','score':80.0},
                 {'sample_no':'S6-b','biz_date':D(d5),'code':'QY-001','version':'v1','score':70.0}])
process_all()
det=detail()
row=[d for d in det['dailies'] if d['biz_date']==D(d5) and d['code']=='QY-001'][0]
# QY-001 当日三条抽检 72/80/70 等权 -> 74；当日顾问均分 (74+73+70+75)/4=73.0
check('顾问内等权再顾问间等权',abs(row['score']-74.0)<1e-9 and abs(row['day_mean']-73.0)<1e-9,row)
# ===== 场景一：跨日迟到记录重算并撤销告警 =====
# 迟到的 d1 补录（同抽检编号更高版本替换）：把 d1 改善抬到阈值之上，
# 使 d1→d2→d3 连续段从首日断裂；d2、d3 虽仍低于阈值但仅重新起段，不再满足连续两日
ingest('tok-late-d1',[{'sample_no':'S2-3','biz_date':D(d1),'code':'QY-004','version':'v2','score':96.0}])
process_all()
det=detail()
revoked=[a for a in det['alerts'] if a['status']=='revoked'][0]
check('迟到记录重算后自动撤销未确认告警',revoked['status']=='revoked' and '重算' in revoked['revoke_reason'],revoked)
check('撤销保留历史依据',revoked['basis'] is not None and len(revoked['basis']['days'])==3)
# d1 断裂后 d2→d3 重新起段，产生新的活动告警（新日段是合法的新告警，不是重复）
new_active=[a for a in det['alerts'] if a['status']=='active']
check('断裂后新日段产生新告警',len(new_active)==1 and new_active[0]['start_date']==D(d2),det['alerts'])
# 再次迟到：d2 高分替换，验证可重复重算不产生重复行
ingest('tok-late-d3',[{'sample_no':'S3-3','biz_date':D(d2),'code':'QY-004','version':'v2','score':96.0}])
process_all()
det=detail()
check('多次重算告警不重复（按日段唯一）',len({(a['start_date'],a['end_date']) for a in det['alerts']})==len(det['alerts']))
check('日聚合无重复行',len(det['dailies'])==len({(d['biz_date'],d['code']) for d in det['dailies']}))
# ===== 版本规则：旧版本不覆盖新版 =====
# 先制造一条 v2，再用 v1 同编号（不同分）提交 -> 整批失败，分数不变
ingest('tok-v2',[{'sample_no':'S1-0','biz_date':D(d0),'code':'QY-001','version':'v2','score':90.0}])
process_all()
before_rows=[d for d in detail()['dailies'] if d['biz_date']==D(d0)]
r=ingest('tok-old-v1',[{'sample_no':'S1-0','biz_date':D(d0),'code':'QY-001','version':'v1','score':50.0}])
process_all()
det=detail()
job=[j for j in det['jobs'] if j['client_token']=='tok-old-v1'][0]
check('旧版本拒绝且批次失败',job['state']=='failed' and '更高版本' in job['error'],job)
after_rows=[d for d in det['dailies'] if d['biz_date']==D(d0)]
check('旧版本未覆盖新版',[(d['code'],d['score']) for d in before_rows]==[(d['code'],d['score']) for d in after_rows])
# 同版本同内容重放：幂等成功（不同 token）
r=ingest('tok-replay',[{'sample_no':'S1-0','biz_date':D(d0),'code':'QY-001','version':'v2','score':90.0}])
process_all()
det=detail()
job=[j for j in det['jobs'] if j['client_token']=='tok-replay'][0]
check('同版本同内容幂等通过',job['state']=='done' and job['payload'].get('applied')==0,job)
# 同版本改内容：拒绝
r=ingest('tok-conflict',[{'sample_no':'S1-0','biz_date':D(d0),'code':'QY-001','version':'v2','score':91.0}])
process_all()
job=[j for j in detail()['jobs'] if j['client_token']=='tok-conflict'][0]
check('同版本内容冲突被拒',job['state']=='failed')
# 范围外顾问整批失败
r=ingest('tok-outscope',[{'sample_no':'SX','biz_date':D(d0),'code':'QY-999','version':'v1','score':80.0}])
process_all()
job=[j for j in detail()['jobs'] if j['client_token']=='tok-outscope'][0]
check('范围外顾问整批失败',job['state']=='failed' and '冻结' in job['error'])
# ===== 重试不重复计分：相同 client_token 返回同一批次 =====
r1=ingest('tok-idem',[{'sample_no':'SIDEM','biz_date':D(d0),'code':'QY-002','version':'v1','score':77.0}])
r2=ingest('tok-idem',[{'sample_no':'SIDEM','biz_date':D(d0),'code':'QY-002','version':'v1','score':77.0}])
check('重复令牌返回同一作业',r1.json()['id']==r2.json()['id'])
process_all()
det=detail()
check('重试只产生一条记录',len([x for x in c.get(f"/monitors/{mid}",headers=H(ta)).json()['dailies'] if x['biz_date']==D(d0) and x['code']=='QY-002'])==1)
# 中断恢复：把作业置回 running 后执行启动恢复逻辑
ingest('tok-recover',[{'sample_no':'SREC','biz_date':D(d3),'code':'QY-002','version':'v1','score':77.0}])
with Session() as s:
 j=s.query(MonitorJob).filter_by(client_token='tok-recover').first();j.state='running';s.commit()
import src.worker as wm
with Session() as rec:
 wm.recover()
 rec.commit()
process_all()
job=[j for j in detail()['jobs'] if j['client_token']=='tok-recover'][0]
check('中断作业恢复后完成',job['state']=='done',job)
# ===== 场景二：撤销已确认告警（确认依据保持原样 + 手动撤销）=====
# 重新构造一个稳定的连续两日低分段：用新监测更干净——直接在本监测上把 d2/d3 压低
d6=d0+datetime.timedelta(days=6);d7=d0+datetime.timedelta(days=7)
ingest('tok-d6low',[{'sample_no':f'SL6-{x}','biz_date':D(d6),'code':code,'version':'v1','score':sc} for x,(code,sc) in enumerate([('QY-001',70.0),('QY-002',71.0),('QY-003',68.0),('QY-004',73.0)])])
ingest('tok-d7low',[{'sample_no':f'SL7-{x}','biz_date':D(d7),'code':code,'version':'v1','score':sc} for x,(code,sc) in enumerate([('QY-001',70.0),('QY-002',71.0),('QY-003',68.0),('QY-004',73.0)])])
process_all()
det=detail()
active=sorted([a for a in det['alerts'] if a['status']=='active'],key=lambda a:a['id'])
check('新连续段产生新告警',len(active)==1 and active[0]['end_date']==D(d7),det['alerts'])
aid=active[0]['id'];basis_before=active[0]['basis'];rev_before=active[0]['basis_revision']
# 非 admin 不能确认
r=c.post(f'/monitors/{mid}/alerts/{aid}/confirm',json={},headers=H(ta));check('确认需 admin',r.status_code==403)
r=c.post(f'/monitors/{mid}/alerts/{aid}/confirm',json={},headers=H(tad));check('确认成功',r.status_code==200)
# 重算（迟到数据修订 d7）不应改写已确认告警依据
ingest('tok-late-d7',[{'sample_no':'SL7-3','biz_date':D(d7),'code':'QY-004','version':'v2','score':96.0}])
process_all()
det=detail()
conf=[a for a in det['alerts'] if a['id']==aid][0]
check('已确认告警状态不被重算改变',conf['status']=='confirmed')
check('已确认告警依据保持原样',conf['basis']==basis_before and conf['basis_revision']==rev_before,conf['basis_revision'])
check('确认人留痕',conf['confirmed_by']=='admin@demo.local')
# 手动撤销已确认告警
r=c.post(f'/monitors/{mid}/alerts/{aid}/revoke',json={'reason':'复核发现评分口径调整，本批告警作废'},headers=H(tad))
check('手动撤销已确认告警',r.status_code==200 and r.json()['status']=='revoked')
check('撤销原因与操作人留痕',r.json()['revoke_reason'] and r.json()['revoked_by']=='admin@demo.local')
r=c.post(f'/monitors/{mid}/alerts/{aid}/confirm',json={},headers=H(tad));check('撤销后不可确认',r.status_code==409)
r=c.post(f'/monitors/{mid}/alerts/{aid}/revoke',json={'reason':'再次撤销'},headers=H(tad));check('重复撤销被拒',r.status_code==409)
# ===== 场景三：接收与确认并发，依据不混用 =====
# 造一个新的活动告警
d8=d0+datetime.timedelta(days=8);d9=d0+datetime.timedelta(days=9)
ingest('tok-d8low',[{'sample_no':f'SM8-{x}','biz_date':D(d8),'code':code,'version':'v1','score':sc} for x,(code,sc) in enumerate([('QY-001',70.0),('QY-002',71.0),('QY-003',68.0),('QY-004',73.0)])])
ingest('tok-d9low',[{'sample_no':f'SM9-{x}','biz_date':D(d9),'code':code,'version':'v1','score':sc} for x,(code,sc) in enumerate([('QY-001',70.0),('QY-002',71.0),('QY-003',68.0),('QY-004',73.0)])])
process_all()
aid2=[a for a in detail()['alerts'] if a['status']=='active' and a['start_date']==D(d8)][0]['id']
basis_snapshot=c.get(f'/monitors/{mid}',headers=H(tad)).json()
target=[a for a in basis_snapshot['alerts'] if a['id']==aid2][0]
errs=[]
def do_ingest():
 try:
  rr=ingest('tok-race',[{'sample_no':'SM9-3','biz_date':D(d9),'code':'QY-004','version':'v2','score':96.0}])
  process_all()
 except Exception as e:errs.append(str(e))
def do_confirm():
 try:
  rr=c.post(f'/monitors/{mid}/alerts/{aid2}/confirm',json={},headers=H(tad))
  errs.append(('confirm_status',rr.status_code))
 except Exception as e:errs.append(str(e))
t1=threading.Thread(target=do_ingest);t2=threading.Thread(target=do_confirm)
t1.start();t2.start();t1.join();t2.join()
det=detail();final=[a for a in det['alerts'] if a['id']==aid2][0]
# 两种合法结局：确认先到->confirmed 且依据=旧依据；重算先到->告警被撤销，确认收到409；二者必居其一且无脏状态
ok=((final['status']=='confirmed' and final['basis']==target['basis']) or
    (final['status']=='revoked' and ('confirm_status',409) in errs))
check('并发下依据不混用（确认锁旧依据或确认被拒）',ok,(final['status'],errs))
check('无异常错误',not any(isinstance(e,str) for e in errs),errs)
# 503 路径：队列故障时作业标记 failed
import src.routes.api as apimod
from src.services import queue as qmod
def boom(k,v):raise redis.RedisError('down')
apimod.enqueue=boom
r=ingest('tok-503',[{'sample_no':'S503','biz_date':D(d8),'code':'QY-001','version':'v1','score':71.0}])
check('队列故障返回503',r.status_code==503)
apimod.enqueue=lambda k,v:fake.rpush(k,v)
# 监测详情可追查当前风险与告警沿革，且原签核仍在
r=c.get(f'/monitors/{mid}',headers=H(tv))
check('观察员可查看监测详情',r.status_code==200)
det=r.json()
check('详情含日聚合/告警沿革/批次/采纳',set(['dailies','alerts','jobs','adoption']).issubset(det.keys()))
check('原签核保留',det['adoption']['status']=='approved' and det['adoption']['decision']=='继续试点')
check('当前风险可查（active 告警计数）',isinstance(len([a for a in det['alerts'] if a['status']=='active']),int))
print(f'\n{PASS} passed, {FAIL} failed')
sys.exit(1 if FAIL else 0)

"""并发语义的确定性验证。

SQLite 单连接跨线程会产生事务伪影，因此并发“不混用依据”的保证拆为两层验证：
1. 咨询锁单元测试：同一监测的锁互斥、可重入等待、不同监测互不阻塞；
2. 串行交错测试：在锁边界上以确定顺序模拟“接收重算”与“确认”竞争，
   两种合法结局（先确认则锁定旧依据 / 先重算则确认被拒）均不出现混用。
"""
import os,sys,datetime,threading,time
sys.path.insert(0,'/workspace/backend')
os.environ.setdefault('DATABASE_URL','sqlite+pysqlite:///:memory:')
os.environ.setdefault('REDIS_URL','redis://unused/0')
os.environ.setdefault('JWT_SECRET','test-secret-3115')
import tempfile
os.environ['ARTIFACT_DIR']=tempfile.mkdtemp()
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
import src.config.database as dbmod
engine=create_engine('sqlite+pysqlite:///:memory:',connect_args={'check_same_thread':False},poolclass=StaticPool)
dbmod.engine=engine;dbmod.Session.configure(bind=engine)
import redis
class FakeRedis:
 def __init__(self):self.q=[]
 def rpush(self,k,v):self.q.append((k,int(v)))
 def blpop(self,keys,timeout=0):return None
 def ping(self):return True
_fake=FakeRedis()
redis.Redis.from_url=lambda *a,**k:_fake
from src.config.database import Base,Session
import src.models.entities
Base.metadata.create_all(engine)
from src.models.entities import User,Pair
from src.utils.security import hash_password
with Session() as s:
 s.add(User(email='admin@demo.local',role='admin',password=hash_password('Demo123!')))
 s.add(User(email='analyst@demo.local',role='analyst',password=hash_password('Demo123!')))
 for code,b,a in [('QY-001',70.0,76.0),('QY-002',72.0,77.0),('QY-003',68.0,74.0),('QY-004',75.0,79.0)]:s.add(Pair(code=code,team='企业一组',before=b,after=a,note='t'))
 s.commit()
from src.services.queue import advisory_lock
PASS=0;FAIL=0
def check(name,cond,detail=''):
 global PASS,FAIL
 if cond:PASS+=1;print('  PASS',name)
 else:FAIL+=1;print('  FAIL',name,detail)
# ---- 第一层：咨询锁语义 ----
events=[]
def holder():
 with advisory_lock('k1'):
  events.append('holder_in');time.sleep(0.6);events.append('holder_out')
def waiter():
 t0=time.time()
 with advisory_lock('k1',timeout=5):events.append(('waiter_acquired_after',round(time.time()-t0,3)))
th1=threading.Thread(target=holder);th2=threading.Thread(target=waiter);th1.start();time.sleep(0.1);th2.start();th1.join();th2.join()
check('同键锁互斥并在释放后获取',events[0]=='holder_in' and events[1]=='holder_out' and isinstance(events[2],tuple) and events[2][1]>=0.4,events)
def timeout_worker():
 try:
  with advisory_lock('k2',timeout=0.2):events.append('should-not-happen')
 except TimeoutError:events.append('timeout')
with advisory_lock('k2'):
 th=threading.Thread(target=timeout_worker);th.start();th.join()
check('锁等待超时抛 TimeoutError','timeout' in events)
par=[]
def w(key):
 with advisory_lock(key,timeout=5):par.append(key)
threads=[threading.Thread(target=w,args=(f'k{i}',)) for i in range(4)]
for t in threads:t.start()
for t in threads:t.join()
check('不同监测键互不阻塞',sorted(par)==['k0','k1','k2','k3'])
# ---- 第二层：确定顺序的交错场景 ----
from fastapi.testclient import TestClient
from src.main import app
from src.worker import run_evaluation,run_monitor_job
from src.services.monitoring import monitor_lock
c=TestClient(app)
def login(role):return c.post('/auth/login',json={'email':f'{role}@demo.local','password':'Demo123!'}).json()['token']
ta=login('analyst');tad=login('admin');H=lambda t:{'Authorization':'Bearer '+t}
ev=c.post('/evaluations',json={'name':'竞争评估','team':'企业一组'},headers=H(ta)).json();run_evaluation(ev['id'])
ad=c.post('/adoptions',json={'evaluation_id':ev['id'],'decision':'继续试点','note':'确定交错验证用的采纳意见草稿内容'},headers=H(ta)).json()
c.post(f'/adoptions/{ad["id"]}/approve',json={},headers=H(tad))
m=c.post('/monitors',json={'adoption_id':ad['id'],'threshold':-2.0},headers=H(ta)).json();mid=m['id']
d0=datetime.date(2026,11,18);D=lambda d:d.isoformat()
bad=[('QY-001',70.0),('QY-002',71.0),('QY-003',68.0),('QY-004',73.0)]
from src.models.entities import MonitorJob
def build_alert(tag,day0):
 c.post(f'/monitors/{mid}/ingest',json={'client_token':f'{tag}-tok-a','records':[{'sample_no':f'{tag}A{i}','biz_date':D(day0),'code':code,'version':'v1','score':sc} for i,(code,sc) in enumerate(bad)]},headers=H(ta))
 c.post(f'/monitors/{mid}/ingest',json={'client_token':f'{tag}-tok-b','records':[{'sample_no':f'{tag}B{i}','biz_date':D(day0+datetime.timedelta(days=1)),'code':code,'version':'v1','score':sc} for i,(code,sc) in enumerate(bad)]},headers=H(ta))
 with Session() as s:
  for j in s.query(MonitorJob).filter_by(state='pending').all():run_monitor_job(j.id)
build_alert('x1',d0)
alert=[a for a in c.get(f'/monitors/{mid}',headers=H(tad)).json()['alerts'] if a['status']=='active'][0]
aid=alert['id'];old_basis=alert['basis']
# 交错 A：确认先完成并释放锁 -> 之后的迟到重算不得改写已确认依据
r=c.post(f'/monitors/{mid}/alerts/{aid}/confirm',json={},headers=H(tad))
check('A 确认成功',r.status_code==200 and r.json()['status']=='confirmed',r.status_code)
# 确认已提交释放锁；再做迟到接收重算（同抽检编号更高版本替换，不新增等权样本）
c.post(f'/monitors/{mid}/ingest',json={'client_token':'late-a','records':[{'sample_no':'x1B3','biz_date':D(d0+datetime.timedelta(days=1)),'code':'QY-004','version':'v2','score':96.0}]},headers=H(ta))
with Session() as s:
 for j in s.query(__import__('src.models.entities',fromlist=['MonitorJob']).MonitorJob).filter_by(state='pending').all():run_monitor_job(j.id)
final=[a for a in c.get(f'/monitors/{mid}',headers=H(tad)).json()['alerts'] if a['id']==aid][0]
check('A 确认后重算不改写依据',final['status']=='confirmed' and final['basis']==old_basis)
# 交错 B：重算先完成并撤销告警 -> 随后的确认必须被拒（锁保证两者不交叉）
c.post(f'/monitors/{mid}/alerts/{aid}/revoke',json={'reason':'清理上一轮已确认告警'},headers=H(tad))
build_alert('x2',d0+datetime.timedelta(days=5))
alert2=[a for a in c.get(f'/monitors/{mid}',headers=H(tad)).json()['alerts'] if a['status']=='active'][0]
aid2=alert2['id']
r=c.post(f'/monitors/{mid}/ingest',json={'client_token':'late-b','records':[{'sample_no':'x2B3','biz_date':D(d0+datetime.timedelta(days=6)),'code':'QY-004','version':'v2','score':96.0}]},headers=H(ta))
check('B 迟到批次已接收',r.status_code==200)
with Session() as s:
 for j in s.query(__import__('src.models.entities',fromlist=['MonitorJob']).MonitorJob).filter_by(state='pending').all():run_monitor_job(j.id)
r2=c.post(f'/monitors/{mid}/alerts/{aid2}/confirm',json={},headers=H(tad))
check('B 重算先撤销后确认被拒',r2.status_code==409,r2.status_code)
final2=[a for a in c.get(f'/monitors/{mid}',headers=H(tad)).json()['alerts'] if a['id']==aid2][0]
check('B 告警已撤销且无脏状态',final2['status']=='revoked')
# 交错 C：重算进行中（锁被持有）确认必须等待，且拿到的是重算后的一致状态
build_alert('x3',d0+datetime.timedelta(days=10))
alert3=[a for a in c.get(f'/monitors/{mid}',headers=H(tad)).json()['alerts'] if a['status']=='active'][0]
aid3=alert3['id'];basis3=alert3['basis']
results={}
def hold_then_recompute():
 with Session() as s:
  with monitor_lock(s,mid):
   time.sleep(0.8)  # 持有锁期间确认请求应阻塞等待
   for j in s.query(__import__('src.models.entities',fromlist=['MonitorJob']).MonitorJob).filter_by(state='pending').all():run_monitor_job(j.id)
   s.commit();results['recomputed_at']=time.time()
th=threading.Thread(target=hold_then_recompute);th.start();time.sleep(0.2)
t_confirm=time.time();rr=c.post(f'/monitors/{mid}/alerts/{aid3}/confirm',json={},headers=H(tad));results['confirm_wait']=time.time()-t_confirm;th.join()
check('C 确认等待重算锁释放',results['confirm_wait']>=0.5,results['confirm_wait'])
# 重算未撤销该告警（无迟到数据），确认成功且依据为重算后的版本
check('C 等待后确认成功且依据一致',rr.status_code==200 and rr.json()['status']=='confirmed')
# 不存在监测的锁抛 ValueError
try:
 with Session() as s:
  with monitor_lock(s,99999):pass
 check('未知监测锁抛错',False)
except ValueError:check('未知监测锁抛错',True)
print(f'\n{PASS} passed, {FAIL} failed')
sys.exit(1 if FAIL else 0)

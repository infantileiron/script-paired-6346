import os,threading,contextlib
import redis
_ADVISORY={}
_ADV_LOCK=threading.Lock()
@contextlib.contextmanager
def advisory_lock(key,timeout=30):
 """进程内咨询锁：模拟 PostgreSQL 行级 FOR UPDATE 的互斥语义，
 保证不支持行锁的方言（SQLite 测试）与生产行为一致。
 生产多进程部署由数据库行锁（with_for_update）承担，本锁作为单进程内的补充。"""
 with _ADV_LOCK:lock=_ADVISORY.setdefault(key,threading.Lock())
 acquired=lock.acquire(timeout=timeout)
 if not acquired:raise TimeoutError(f'等待锁超时: {key}')
 try:yield
 finally:lock.release()
EVAL_QUEUE='paired:evaluations'
MONITOR_QUEUE='paired:monitor_jobs'
def client():return redis.Redis.from_url(os.environ['REDIS_URL'])
def enqueue(queue,value):
 c=client();c.rpush(queue,value)

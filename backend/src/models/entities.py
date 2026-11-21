from sqlalchemy import Column,Integer,String,Float,JSON,Text,ForeignKey,Date,UniqueConstraint,Index
from src.config.database import Base
class User(Base):
 __tablename__='users'
 id=Column(Integer,primary_key=True);email=Column(String(100),unique=True,nullable=False);password=Column(String(200));role=Column(String(20))
class Pair(Base):
 __tablename__='pairs'
 id=Column(Integer,primary_key=True);code=Column(String(60),unique=True,nullable=False);team=Column(String(40));before=Column(Float,nullable=True);after=Column(Float,nullable=True);note=Column(Text,default='')
class Evaluation(Base):
 __tablename__='evaluations'
 id=Column(Integer,primary_key=True);name=Column(String(100));team=Column(String(40));state=Column(String(20),default='queued');result=Column(JSON,nullable=True);error=Column(Text,default='')
class Adoption(Base):
 __tablename__='adoptions'
 id=Column(Integer,primary_key=True);evaluation_id=Column(Integer,ForeignKey('evaluations.id'));decision=Column(String(30));note=Column(Text);status=Column(String(20),default='draft')
class Audit(Base):
 __tablename__='audits'
 id=Column(Integer,primary_key=True);actor=Column(String(100));action=Column(String(200));created=Column(String(40))
class Monitor(Base):
 __tablename__='monitors'
 id=Column(Integer,primary_key=True)
 adoption_id=Column(Integer,ForeignKey('adoptions.id'),nullable=False,unique=True)
 evaluation_id=Column(Integer,ForeignKey('evaluations.id'),nullable=False)
 threshold=Column(Float,nullable=False)
 baseline_after_mean=Column(Float,nullable=False)
 baseline_before_mean=Column(Float,nullable=True)
 frozen_scope=Column(JSON,nullable=False)
 state=Column(String(20),default='active')
 created=Column(String(40))
class MonitorJob(Base):
 __tablename__='monitor_jobs'
 id=Column(Integer,primary_key=True)
 monitor_id=Column(Integer,ForeignKey('monitors.id'),nullable=False)
 client_token=Column(String(80),nullable=True)
 state=Column(String(20),default='pending')
 error=Column(Text,default='')
 payload=Column(JSON,nullable=True)
 created=Column(String(40));updated=Column(String(40))
 __table_args__=(UniqueConstraint('monitor_id','client_token',name='monitor_jobs_token_uc'),Index('monitor_jobs_state_idx','state'))
class MonitorRecord(Base):
 __tablename__='monitor_records'
 id=Column(Integer,primary_key=True)
 monitor_id=Column(Integer,ForeignKey('monitors.id'),nullable=False)
 biz_date=Column(Date,nullable=False)
 sample_no=Column(String(60),nullable=False)
 code=Column(String(60),nullable=False)
 version=Column(String(60),nullable=False)
 score=Column(Float,nullable=False)
 job_id=Column(Integer,ForeignKey('monitor_jobs.id'),nullable=False)
 created=Column(String(40))
 __table_args__=(UniqueConstraint('monitor_id','sample_no',name='monitor_records_no_uc'),Index('monitor_records_lookup_idx','monitor_id','biz_date','code'))
class MonitorDaily(Base):
 __tablename__='monitor_dailies'
 id=Column(Integer,primary_key=True)
 monitor_id=Column(Integer,ForeignKey('monitors.id'),nullable=False)
 biz_date=Column(Date,nullable=False)
 code=Column(String(60),nullable=False)
 score=Column(Float,nullable=False)
 delta=Column(Float,nullable=False)
 day_mean=Column(Float,nullable=False)
 improvement=Column(Float,nullable=False)
 consultant_count=Column(Integer,nullable=False)
 __table_args__=(UniqueConstraint('monitor_id','biz_date','code',name='monitor_dailies_uc'),Index('monitor_dailies_day_idx','monitor_id','biz_date'))
class MonitorAlert(Base):
 __tablename__='monitor_alerts'
 id=Column(Integer,primary_key=True)
 monitor_id=Column(Integer,ForeignKey('monitors.id'),nullable=False)
 status=Column(String(20),default='active')
 start_date=Column(Date,nullable=False)
 end_date=Column(Date,nullable=False)
 trigger_date=Column(Date,nullable=False)
 threshold=Column(Float,nullable=False)
 basis=Column(JSON,nullable=False)
 basis_revision=Column(Integer,default=0)
 confirmed_by=Column(String(100),nullable=True)
 confirmed_at=Column(String(40),nullable=True)
 revoked_by=Column(String(100),nullable=True)
 revoked_at=Column(String(40),nullable=True)
 revoke_reason=Column(Text,default='')
 created=Column(String(40));updated=Column(String(40))
 __table_args__=(Index('monitor_alerts_monitor_idx','monitor_id','status'),)

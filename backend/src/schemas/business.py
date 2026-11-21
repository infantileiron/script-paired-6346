from pydantic import BaseModel,Field
from typing import Optional,Literal,List
from datetime import date
class Login(BaseModel):email:str;password:str
class PairInput(BaseModel):
 code:str=Field(min_length=1,max_length=60)
 team:Literal['企业一组','企业二组']
 before:Optional[float]=Field(default=None,ge=0,le=100,allow_inf_nan=False)
 after:Optional[float]=Field(default=None,ge=0,le=100,allow_inf_nan=False)
 note:str=Field(default='',max_length=1000)
class EvaluationInput(BaseModel):
 name:str=Field(min_length=2,max_length=100)
 team:Literal['全部','企业一组','企业二组']='全部'
class AdoptionInput(BaseModel):
 evaluation_id:int=Field(gt=0)
 decision:Literal['继续试点','分组采纳','暂缓采纳']
 note:str=Field(min_length=8,max_length=2000)
class MonitorCreate(BaseModel):
 adoption_id:int=Field(gt=0)
 threshold:float=Field(ge=-100,le=100,allow_inf_nan=False)
class IngestItem(BaseModel):
 sample_no:str=Field(min_length=1,max_length=60)
 biz_date:date
 code:str=Field(min_length=1,max_length=60)
 version:str=Field(min_length=1,max_length=60)
 score:float=Field(ge=0,le=100,allow_inf_nan=False)
class MonitorIngest(BaseModel):
 client_token:Optional[str]=Field(default=None,min_length=4,max_length=80)
 records:List[IngestItem]=Field(min_length=1,max_length=2000)
class AlertRevoke(BaseModel):
 reason:str=Field(min_length=2,max_length=500)

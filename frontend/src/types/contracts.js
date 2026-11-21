/** @typedef {{id:number,code:string,team:string,before:number|null,after:number|null,note:string}} Pair */
/** @typedef {{id:number,name:string,team:string,state:string,result:object,error:string}} Evaluation */
/** @typedef {{id:number,evaluation_id:number,decision:string,note:string,status:string}} Adoption */
/** @typedef {{id:number,adoption_id:number,evaluation_id:number,threshold:number,baseline_after_mean:number,baseline_before_mean:number|null,frozen_scope:Array,state:string,created:string}} Monitor */
/** @typedef {{id:number,monitor_id:number,client_token:string|null,state:string,error:string,payload:object,created:string,updated:string}} MonitorJob */
/** @typedef {{id:number,monitor_id:number,biz_date:string,code:string,score:number,delta:number,day_mean:number,improvement:number,consultant_count:number}} MonitorDaily */
/** @typedef {{id:number,monitor_id:number,status:string,start_date:string,end_date:string,trigger_date:string,threshold:number,basis:object,basis_revision:number,confirmed_by:string|null,confirmed_at:string|null,revoked_by:string|null,revoked_at:string|null,revoke_reason:string}} MonitorAlert */

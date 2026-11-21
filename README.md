# 清音 · 话术切换配对评估

为客户成功团队核对同一顾问更换续约话术前后的抽检得分，将样本完整性、统计证据和业务采纳分开记录。

## 场景与模块

清音客户成功有两组共40位顾问。当前组长导出 `清音_续约抽检_20261115.xlsx`，人工匹配两周得分，分析师计算差值后把结论贴到周会纪要。痛点是漏配对被补零、均值改善被误当因果、采纳意见缺乏证据版本。上游是沟通质量抽检；本项目替代配对核对、统计和采纳留痕；下游是组长制定下一周话术试点范围。

四个业务模块：配对样本（录入/修订）、排除核对、效应评估（后台任务/冻结结果）、采纳意见（起草/签核），以及签核后的第五个模块「采纳监测」（基线冻结/抽检接收/连续日告警）。三类业务实体是 Pair、Evaluation、Adoption；监测实体是 Monitor、MonitorJob、MonitorRecord、MonitorDaily、MonitorAlert；另有用户和审计记录。已有报告不会随原始样本修订而改变；已确认告警的依据也不会被重算覆盖。

|角色|页面与权限|典型动作|
|---|---|---|
|admin|全部，独占审计和签核|签核采纳意见|
|analyst|业务读写、计算、导出|补录缺失后新建评估|
|viewer|全部业务只读、导出|下载冻结结果；后端拒绝写操作|

## 启动

```sh
cp .env.example .env
docker compose config --quiet
docker compose up -d --build
docker compose exec -T backend python -m scripts.seed_demo
```

前端 [localhost:18214](http://localhost:18214)，后端 [localhost:19214/docs](http://localhost:19214/docs)，PostgreSQL映射17714。种子账号为 `admin@demo.local` / `analyst@demo.local` / `viewer@demo.local`，密码均 `Demo123!`。启动 `SEED_DEMO=true` 自动执行一次种子；再次执行不增加相同顾问或覆盖人工修订。演示包括40顾问、2个业务组、2个不完整配对。

## 一天的操作剧本

1. 08:50 viewer 查看QY-001至QY-040的前后测。
2. 09:00 analyst 进入排除核对，检查QY-039缺前测和QY-040缺后测。
3. 09:10 在配对样本补录 `QY-041`、企业一组、前测70、后测77。
4. 09:20 修订时填写记录ID和完整字段，并说明两次抽检都用7日窗口。
5. 09:30 创建“11月续约话术配对复核”，选择全部或一个业务组。
6. 09:40 worker完成计算，点击刷新，核对差值、95%CI与两种p值。
7. 10:00 analyst 在采纳意见选择该评估，写明客户结构和限制，起草“继续试点”。
8. 10:10 admin登录并签核；10:20 viewer 下载 `script-paired-<id>.json`。

## 计算口径

输入是同一顾问的前后抽检平均分（0–100），一位顾问只允许一个唯一编号。缺任一侧时整对排除，不补零。至少3个完整配对，差值标准差必须大于零。令 d=后测−前测，t=mean(d)/(sd(d)/sqrt(n))，自由度n−1，双侧p与95%t区间；Cohen dz=mean(d)/sd(d)。配对t假定顾问之间独立，差值近似正态。

符号翻转以abs(mean(d))为统计量，≤16对穷举2^n种符号，取不小于观察统计量的占比；更大样本固定numpy seed=1115、10000次抽样，p=(extreme+1)/(10000+1)，比较时用1e−12容差。零假设下需差值符号可交换。前后观测可能受客户结构/季节影响；统计结果不会直接触发话术发布。

提交任务时冻结全部输入，worker保存完整配对、排除原因、checksum、seed和计算次数。无效输入返回422；重复编号409；样本不足/零方差的任务置failed，提示修复后重新提交；队列故障返回503。单worker启动时恢复queued/running任务。

## 采纳后持续监测

话术获准（Adoption 签核）后可建立监测，原签核保留不变。建立时从评估的冻结快照固化**后测均值**与**顾问范围**（范围外顾问的抽检整批拒绝），阈值可在建监测时设置，之后不可修改；需要调整阈值须新建评估与采纳。

按业务日接收后续抽检，每条记录含抽检编号、顾问、版本、得分，经后台批次作业处理（状态 待算 pending → 可用 done / 失败 failed）：

- **版本规则**：同一抽检编号以更高版本为准，旧版本不覆盖新版；同版本仅在内容完全一致时幂等通过，内容冲突或更低版本整批失败，不产生部分计分。
- **等权聚合**：同一顾问当日多条抽检先等权平均，再对当日有记录的顾问等权求日均分；改善 = 日均分 − 冻结后测均值。
- **连续性**：按业务日扫描，改善连续两个相邻业务日低于阈值即告警，触发日为连续段的第二日；缺测日不产生日行并断开连续性。
- **乱序与迟到**：任何批次完成后全量重算受影响的连续日段（日聚合重建、告警对账）；条件不再成立时自动撤销**未确认**告警，已确认告警的依据（basis JSON）与状态保持原样，仅保留为历史凭据。
- **幂等与恢复**：接收支持 `client_token`，相同令牌返回同一批次，重试不重复计分或告警；worker 启动时把 pending/running 批次重新入队，中断可恢复。
- **并发**：接收重算与确认/撤销在监测级互斥（咨询锁 + PostgreSQL `FOR UPDATE` 行锁），确认拿到的依据即提交时的依据，不与重算混用；确认/撤销仅 admin，撤销须填写原因。

监测页面可追查当前风险（待确认告警）、每日聚合、告警沿革（含依据修订版次、确认/撤销留痕）与最近批次状态，并保留原签核信息。

## 工程与本地开发

Python3.11/FastAPI/SQLAlchemy/SciPy/NumPy/PyJWT、原生ES modules/CSS、Nginx、PostgreSQL16、Redis7。五个服务均有健康检查；backend等待数据库/Redis，worker还等backend，frontend等backend。数据库、Redis、产物用命名卷。Nginx的 `/api/` 转发到后端根路由。只有数据库、后端和前端映射宿主端口。worker心跳位于容器 `/tmp/heartbeat`，结果共享卷 `/artifacts`（本地可用 `ARTIFACT_DIR` 覆盖）。`docker compose down -v --remove-orphans` 清理本项目测试数据。

本地开发可启动db/redis后，在backend安装 requirements，设置 DATABASE_URL/REDIS_URL/JWT_SECRET，`uvicorn src.main:app --reload`；前端建议仍用Nginx代理，也可设置本地同源代理。`backend/src`按routes/controllers/services/models/schemas/middlewares/config/utils分工；`frontend/src`按api/stores/pages/components/hooks/utils/constants/types/router分工。ORM首次建表，`backend/migrations/001_initial.sql` 与 `002_monitoring.sql` 保留对应DDL；不包含在线版本迁移框架，已存在的库需手动执行 002 脚本。

环境变量详见 `.env.example`：COMPOSE_PROJECT_NAME、FRONTEND_PORT、BACKEND_PORT、DB_PORT、DB_PASSWORD、JWT_SECRET、SEED_DEMO、NETWORK_SUBNET。显式子网10.253.115.0/24用于规避当前机器默认池耗尽，可迁移时调整。生产使用需替换演示凭据与JWT密钥。

共享枚举：角色ROLES、任务状态STATES、业务组TEAMS、决定DECISIONS；后端 `src/constants/enums.py`、schemas/business.py 与前端 `src/constants/enums.js`，持久化列见models/entities.py。共用表格、表单字段、状态标签组件；表单hooks与HTML转义工具；请求ID、安全响应头两个中间件，业务写入审计。

范围：逐条表单/API录入，无Excel导入、删除、外部话术发布；采纳在站内签核，监测在站内告警与确认。使用单worker；监测的接收与确认通过监测级锁串行，不做多worker竞争调度。时间/窗口由业务填入说明，不自动验证客户结构。Google Fonts不可用时回退serif/sans-serif。后端验证见 `backend/tests/`（`test_monitoring.py` 覆盖冻结基线、等权聚合、缺测断连、跨日迟到重算、版本规则、幂等重试、中断恢复与告警确认/撤销；`test_race.py` 确定性验证接收与确认的锁语义及两种竞争结局）。许可证 MIT，见 LICENSE。

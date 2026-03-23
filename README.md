# Sequencer Log Platform

面向测序仪多源异构日志的企业级“日志整理及问题反馈系统”。

本项目默认采用：

- 后端：FastAPI
- 前端：Streamlit
- 持久化：SQLite + SQLAlchemy
- 图表：Plotly
- LLM：可配置对接火山引擎 Ark 兼容接口
- 解析模式：插件式 Parser Registry
- 核心场景：测序仪控制、流路、光学、运动、调度、算法、接口通信、metrics/cycle 日志联合分析

---

## 1. 项目能力

### 已实现核心能力

1. 多源日志接入  
   支持单文件、多文件压缩包上传，默认支持：
   - `.csv`
   - `.log`
   - `.txt`
   - `.trace`
   - `.metrics`
   - `.zip`
   - `.7z`
   - `.tar/.gz/.tgz/.bz2`

2. 日志解析与标准化  
   已内置以下解析器：
   - `CsvWorkflowParser`
   - `ServiceLogParser`
   - `ErrorLogParser`
   - `RunErrorParser`
   - `MetricsCsvParser`

3. 统一事件模型  
   统一输出字段包括：
   - `original_time_text`
   - `parsed_datetime`
   - `epoch_ms`
   - `formatted_ms`
   - `component`
   - `cycle_no`
   - `sub_step`
   - `chip_name`
   - `method_name`
   - `error_code`
   - `exception_type`
   - `normalized_signature`
   - `error_family`
   - `severity`

4. 耗时分析  
   - start/end 自动配对
   - cycle/sub-step 耗时提取
   - 跨 cycle 趋势图
   - 超阈值识别

5. 错误分析  
   - error 归一化
   - signature 哈希
   - 高频错误统计
   - Top N 排行
   - 按部件分布

6. LLM 诊断  
   结构化输出：
   ```json
   {
     "root_cause_summary": "",
     "possible_causes": [],
     "affected_modules": [],
     "recommended_checks": [],
     "owner_departments": [],
     "severity": "",
     "confidence": 0.0
   }
   ```

7. 导出能力  
   - 导出统一事件 CSV
   - 导出错误分析 CSV

---

## 2. 项目目录

```text
sequencer_log_platform/
├─ app/
│  ├─ api/
│  │  └─ routes.py
│  ├─ core/
│  │  ├─ logging_config.py
│  │  └─ settings.py
│  ├─ db/
│  │  ├─ base.py
│  │  └─ session.py
│  ├─ models/
│  │  └─ db_models.py
│  ├─ schemas/
│  │  └─ common.py
│  ├─ parsers/
│  │  ├─ base.py
│  │  ├─ registry.py
│  │  ├─ csv_workflow_parser.py
│  │  ├─ service_log_parser.py
│  │  ├─ error_log_parser.py
│  │  ├─ runerror_parser.py
│  │  └─ metrics_csv_parser.py
│  ├─ normalizers/
│  │  └─ event_normalizer.py
│  ├─ correlators/
│  │  └─ pairing.py
│  ├─ detectors/
│  │  └─ error_detection.py
│  ├─ llm/
│  │  ├─ client.py
│  │  └─ prompts.py
│  ├─ repositories/
│  │  └─ task_repository.py
│  ├─ services/
│  │  ├─ ingestion_service.py
│  │  ├─ query_service.py
│  │  ├─ cycle_service.py
│  │  ├─ llm_service.py
│  │  ├─ config_service.py
│  │  └─ export_service.py
│  ├─ utils/
│  │  ├─ files.py
│  │  ├─ rules.py
│  │  ├─ text.py
│  │  └─ timeparse.py
│  └─ main.py
├─ ui/
│  └─ streamlit_app.py
├─ config/
│  ├─ thresholds.yaml
│  ├─ parser_rules.yaml
│  └─ error_rules.yaml
├─ tests/
├─ data/
├─ scripts/
├─ requirements.txt
├─ .env.example
├─ Dockerfile
├─ docker-compose.yml
└─ README.md
```

---

## 3. 安装与本地运行


## 3.0 Windows / 本地启动避坑说明

这版项目已经做了本地启动加固，建议优先使用 `scripts/` 下的启动脚本，而不是直接在任意目录手敲模块路径。

推荐命令：

```powershell
cd D:\VScode1\MyProjects\CycleDash\sequencer_log_platform
python -m pip install -r requirements.txt
python -m scripts.init_db
python -m scripts.run_api
python -m scripts.run_ui
```

这样可以自动处理：

- Windows 下从子目录启动时 `app` 包找不到
- Streamlit 运行时工作目录不是项目根目录
- SQLite 相对路径落错目录
- `.env` 没有从项目根目录正确加载

如果你坚持直接运行原始命令，也必须先 `cd` 到项目根目录。


### 3.1 创建环境

```bash
python -m venv .venv
source .venv/bin/activate
```

Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

### 3.2 安装依赖

```bash
pip install -r requirements.txt
```

### 3.3 初始化数据库

```bash
python -m scripts.init_db
```

### 3.4 配置环境变量

```bash
cp .env.example .env
```

然后按需修改 `.env`。

### 3.5 启动 FastAPI

```bash
python -m scripts.run_api
```

### 3.6 启动 Streamlit

```bash
python -m scripts.run_ui
```

默认访问：

- API 文档：`http://localhost:8000/docs`
- UI：`http://localhost:8501`

---

## 4. Docker 启动

### 4.1 复制环境变量

```bash
cp .env.example .env
```

### 4.2 启动

```bash
docker compose up --build
```

访问：

- FastAPI: `http://localhost:8000`
- Streamlit: `http://localhost:8501`

---

## 5. 使用流程

1. 打开 Streamlit 页面
2. 在“文件上传”页面上传日志文件或压缩包
3. 上传完成后会返回 `task_uuid`
4. 在左侧栏输入 `task_uuid`
5. 依次查看：
   - 首页 / 仪表盘
   - 统一事件流
   - 耗时分析
   - 事件流时间轴
   - 错误分析
   - LLM 诊断
   - 导出

---

## 6. 时间标准化策略

系统兼容以下时间格式：

- `2026/03/18 09:45:18.644`
- `2026/03/18 09:21:30:738`
- `2026-03-18 09:46:49.1052`

统一输出：

- `original_time_text`：保留原始文本
- `parsed_datetime`：Python datetime
- `epoch_ms`：统一毫秒时间戳
- `formatted_ms`：统一格式 `%Y-%m-%d %H:%M:%S.mmm`

### 四位小数秒处理策略

默认策略：**截断到毫秒**

例如：

- `09:46:49.1052` -> `09:46:49.105`

原因：

- 工业日志常混用 3/4/6 位小数
- 下游趋势统计与时间轴以毫秒为主
- 统一截断比混合四舍五入更稳定、更可重复

如需改为四舍五入，可在 `.env` 中设置：

```env
DEFAULT_TIME_ROUNDING=round
```

---

## 7. start/end 配对策略

当前实现的通用配对逻辑支持：

- `start / completed`
- `begin / end`
- `request / success`
- `move / success`
- `fill / completed`
- `setup / done`

优先级：

1. 同一 component
2. 同一 cycle
3. 时间升序最近匹配

无法匹配时，会保留为未闭合步骤记录（`end_epoch_ms` 为空）。

---

## 8. 错误归一化策略

已实现明确算法，不是占位：

1. 提取 `exception type`
2. 拼接 `method_name`
3. 清洗动态内容：
   - 数字
   - 路径
   - 行号
   - 随机 token
   - 长 ID / GUID
4. 生成规范化文本
5. 计算 `sha1_short` 得到 `normalized_signature`
6. 按关键词映射 `error_family`

当前内置问题家族：

- timeout
- connection_lost
- rpc_ice
- db_open_failure
- bad_image_format
- file_io
- movement_stage_failure
- optics_camera_failure
- general_error

---

## 9. LLM 接入说明

在 `.env` 中配置：

```env
LLM_ENABLED=true
LLM_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
LLM_API_KEY=your_api_key
LLM_MODEL=your_model
LLM_TIMEOUT_SECONDS=45
LLM_MAX_RETRIES=3
```

### 调用失败兜底

已实现：

- 超时重试
- 指数退避
- JSON 解析失败降级
- 返回 schema 校验
- 未启用时规则引擎兜底说明

---

## 10. 配置文件说明

### `config/thresholds.yaml`

用于步骤阈值配置，例如：

```yaml
default_threshold_ms: 10000
step_thresholds_ms:
  default:
    b1 fill ir: 45000
    setcameradirection: 3000
```

### `config/parser_rules.yaml`

用于时间格式、cycle 正则、chip 正则、配对规则配置。

### `config/error_rules.yaml`

用于错误归一化和错误家族映射规则。

---

## 11. API 摘要

### 上传分析

`POST /api/v1/tasks/upload`

### 任务列表

`GET /api/v1/tasks`

### 仪表盘

`GET /api/v1/tasks/{task_uuid}/dashboard`

### 事件流

`GET /api/v1/tasks/{task_uuid}/events`

### 步骤耗时

`GET /api/v1/tasks/{task_uuid}/steps`

### 错误簇

`GET /api/v1/tasks/{task_uuid}/errors`

### LLM 诊断

`POST /api/v1/tasks/{task_uuid}/errors/{signature}/analyze`

### 导出事件 CSV

`GET /api/v1/tasks/{task_uuid}/export/events`

### 导出错误 CSV

`GET /api/v1/tasks/{task_uuid}/export/errors`

---

## 12. 自动化测试

运行：

```bash
pytest -q
```

覆盖范围：

- 时间解析
- 解析器路由
- 错误归一化
- start/end 配对
- cycle / chip 提取
- API 健康检查

---

## 13. 页面说明

### 首页 / 仪表盘
展示：
- 文件数
- 总事件数
- 总错误数
- 唯一错误数
- 高频问题 Top N
- 各部件错误分布

### 文件上传
展示：
- 上传入口
- 分析结果
- 历史任务列表

### 统一事件流
支持：
- 表格浏览
- 按 component / level / cycle / chip / keyword 过滤

### 耗时分析
展示：
- step summary 表
- 跨 cycle 耗时趋势图
- 超阈值告警表

### 事件流时间轴
展示：
- 各部件动作甘特图
- 时间跨度
- hover 查看 cycle、step、chip、耗时、阈值状态

### 错误分析
展示：
- 错误簇列表
- 错误家族分布
- Top 20 错误

### LLM 诊断
支持：
- 选择某个错误簇
- 发起模型分析
- 展示中文摘要与结构化 JSON

### 配置页面
支持：
- 查看当前 LLM 配置
- 编辑阈值 YAML 并保存

### 导出
支持：
- 下载统一事件 CSV
- 下载错误分析 CSV

---

## 14. 扩展方式

### 新增日志解析器

1. 在 `app/parsers/` 下新增文件
2. 继承 `BaseParser`
3. 实现：
   - `score(path, head_text)`
   - `parse(path)`
4. 在 `ParserRegistry` 注册

### 新增错误分类规则

编辑：

- `config/error_rules.yaml`
- `app/detectors/error_detection.py`

### 新增图表

修改：

- `ui/streamlit_app.py`

### 切换 PostgreSQL

修改 `.env`：

```env
DATABASE_URL=postgresql+psycopg://user:password@host:5432/dbname
```

然后安装对应驱动即可。

---

## 15. 当前假设与限制

1. 当前 cycle / sub-step / chip_name 提取采用“文件名 + 消息文本 + 正则规则 + 上下文”联合推断，已足以覆盖常见工业日志，但对极端定制日志仍可能需要补充规则。
2. 当前 start/end 配对属于工程实用版本，适合企业内部首版平台；若后续有更强过程建模需求，建议引入状态机或 workflow graph。
3. 当前 RunError 堆栈解析支持多行异常拼接，但对于极复杂嵌套栈可继续增强。
4. 当前 UI 默认内部工具风格，重点在分析效率而非复杂权限体系。
5. 当前上传接口为了保证代码简洁，采用同步处理；若后续文件量极大，建议扩展为 Celery / RQ / Dramatiq 异步任务队列。

---


## 本地启动增强说明

- 支持多文件批量上传，FastAPI 后台异步处理，Streamlit 可查看任务进度。
- `.7z` 解压优先使用 `py7zr`，若本地缺失会在任务状态中返回明确提示。
- Windows 可直接运行：`scripts/start_local.bat` 或 `scripts/start_local.ps1`。
- 若升级了数据库字段（如进度字段），建议删除旧的 `data/sequencer_log_platform.db` 后重新执行 `python -m scripts.init_db`。
- 已基于示例日志样本增加对以下真实特征的识别：`HLAB1078/HLAB1079` 芯片名、`Cycle309`/`S309` 周期号、`OpticalBoard/XYZStage/RobotScheduler/Scanner/StageRunMgr/T100Scheduler` 组件名。



## 本轮新增能力

- 异步任务队列与队列位置显示
- 任务级审计日志表与审计接口
- 更强的最小必要上下文与跨文件同 cycle/同组件关联
- 原始文件列表与原始文件预览
- 错误簇回归趋势（日/周）
- LLM Prompt 模板版本管理
- Excel / JSON / PDF 报告导出

## 升级提醒

若你此前已经使用旧版 SQLite 数据库，请删除 `data/sequencer_log_platform.db` 后重新执行：

```bash
python -m scripts.init_db
```

否则新增字段和表（如任务审计日志、Prompt 版本等）可能不会自动补齐。

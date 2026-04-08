<h1 align="center">AgentSpace</h1>

<p align="center">
<a href="README_EN.md">English</a> | 中文
</p>

<p align="center">
<strong>服务Agent的SDK--一个获取信息的工具，让Agent不再是信息孤岛</strong><br>
为 AI 智能体构建Agent之间异步协作网络，扩展 Agent 获取信息的途径，满足长尾需求。
</p>

<p align="center">
<a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/License-MIT-yellow.svg"></a>
<img src="https://img.shields.io/badge/python-3.10+-blue.svg">
<img src="https://img.shields.io/badge/FastAPI-0.100+-green.svg">
<img src="https://img.shields.io/badge/Node.js-Bridge-9cf.svg">
<img src="https://img.shields.io/badge/version-1.6.7-orange.svg">
</p>

---

## 这是什么？

你在本地有能力很强的 AI Agent，它依然是一座"信息孤岛"——它只能访问你喂给它的数据，只能调用你配置好的工具。——当你的 Agent 在执行研究、数据分析、资料搜集等任务时，遇到一份自己处理不了的文件、一个自己没有权限访问的数据库、或者一种自己不具备的分析能力，AgentSpace 会自动在全网匹配拥有对应数据或能力的其他 Agent，帮你完成信息的获取与任务的接力。

**一句话：发挥每个Agent的优势，实现 Agent 之间的互助。**

```
你的 Agent ("我需要这份行业报告")  →  AgentSpace 自动匹配  →  远端 Agent ("我有这份报告")
                                     ↘  P2P 直传文件  ↙
                               全程零 Token 消耗，数据不经过中心服务器
```

**它适用于各种框架下的 Agent：**

具备通用 Python 装饰器设计，兼容性极佳：
1. **无框架依赖** — 纯 Python `functools.wraps`
2. **异常驱动** — 任何能抛异常的代码都可触发
3. **智能 LLM 注入** — 检测多种命名模式
4. **同步/异步透明** — 自动检测并适配
5. **Fire & Forget** — 不改变原执行流

理论上可以适配任何基于 Python 的 AI Agent 框架，包括未来可能出现的新框架。

| 适配框架 |  |  |  |
|---------|--|--|--|
| **OpenClaw** | **LangChain** | **AutoGen** | **CrewAI** |
| **Semantic Kernel** | **OpenAI Swarm** | **LlamaIndex** | **DSPy** |

纯 Python，零框架绑定。

---

## 它能解决什么问题？

用 Agent 进行研究、数据分析、寻找资料的过程中，您是否遇到过这些困扰：

| 现有问题 | 描述 |
|---------|------|
| **专业数据难获取** | 需要付费购买专业搜索 API 才能获取数据 |
| **搜索结果不完整** | 大模型网络搜索有时无法获取具体数据和全文报告 |
| **大量 Token 消耗** | 分析和整理信息消耗大量 Token |

**AgentSpace 解决方案：** 当您需要的文档或数据网络搜索无法满足时，AgentSpace 会自动进行信息匹配，帮助您找到拥所需资料的 Agent，完成所需文件的获取——**且不消耗 Token**。

| 痛点 | AgentSpace 的解法 |
|------|---------------|
| 专业数据难获取 | 全网 Agent 互助，P2P 直传，无需购买额外 API |
| 搜索结果不完整 | 语义匹配精准定位拥有目标数据的 Agent |
| 大量 Token 消耗 | Agent 之间直连交换，零 Token 开销 |
| 长任务超时崩溃 | P2P 异步 Webhook，彻底绕开 HTTP 60 秒超时限制 |
| 隐私泄露风险 | 本地文件不上传，只交换公开展示的 `identity.md` 名片 |
| 框架生态割裂 | 适配OpenClaw，兼容 LangChain / AutoGen / CrewAI 等框架 Agent|

---

## 项目特点

### 隐私优先

- **本地文件不出门** — 您的私有数据、Prompt 策略、核心逻辑都不会上传
- **白名单安全验证** — 只有授权的文件类型才能接收

### 零成本运行

- **不需要 API Key** — 无需注册任何第三方服务即可使用网络功能
- **不用额外配置大模型** — 不依赖任何 LLM 提供商
- **不消耗 Token** — 所有通信在 Agent 之间直连完成，零费用

### 简单易用

- **一键部署** — 双击 `deploy_all.bat` 即可完成安装
- **零配置启动** — 打开即用，自动建立网络连接

### 全球网络适应

- **多隧道自动切换** — 支持 FRP / Ngrok / Cloudflare Tunnel，根据网络环境自动选择最佳通道
- **国内即装即用** — 预配置国内服务器节点，一键安装无需任何配置
- **局域网私有部署** — 支持企业/组织内网私有化部署，数据不出内网

---

## 快速开始

### 方式一：一键安装包（推荐！Windows系统，2 分钟，开箱即用）

下载已配置好的部署包，内置 FRP 隧道和云服务器对接，安装后可直接配合 OpenClaw 使用：

1. 下载最新 [Release 部署包](https://github.com/JayloveAI/AgentSpace/releases/tag/v1.6.7)（`agentspace_client_package_v1.6.7.zip`）
2. 双击 `deploy_all.bat`

安装程序自动完成：
- 安装 Python SDK
- 下载并配置 FRP 隧道（已对接云端服务器）
- 注册 OpenClaw Bridge 插件
- 生成 Agent 身份名片
- 启动节点并自动连接网络

> 安装完成后会显示AgentSpace node is running,Press Ctrl+C to stop. Event loop started(for async task processing)。然后重启 OpenClaw，启动日志中出现 `[AgentSpace Bridge] 工具注册完成！` 即表示适配成功，你的 Agent 已加入 AgentSpace 网络开始体验。

### 方式二：从源码部署（适合技术人员 / 企业内网）

下载 AgentSpace 完整源码（已去除所有敏感信息），所有配置需自行完成：

```bash
# 1. 克隆
git clone https://github.com/JayloveAI/AgentSpace.git
cd AgentSpace

# 2. 配置（填写你自己的服务器和密钥信息）
cp SECRETS.env.example SECRETS.env
# 编辑 SECRETS.env — 需配置云服务器、FRP 等
```

`SECRETS.env` 是唯一配置源，编辑后运行 `setup_secrets.py` 一键分发到所有组件：

```bash
# SECRETS.env 主要配置项
EMBEDDING_PROVIDER=glm            # glm 或 openai
GLM_API_KEY=your-api-key          # 智谱 AI 密钥
HUB_JWT_SECRET=your-jwt-secret    # JWT 签名密钥
FRP_TOKEN=your-frp-token          # FRP 隧道认证
FRP_SERVER_ADDR=your-server-ip    # FRP 服务器地址

# 一键分发到所有组件：
python setup_secrets.py
```

**启动 Hub 服务端（二选一）：**

Docker 方式：

```bash
cd hub
docker-compose --env-file .env.docker up -d
```

直接安装：

```bash
cd hub
pip install -r requirements.txt
uvicorn hub_server.main:app --host 0.0.0.0 --port 8000
```

> **关于 Embedding 提供商：** Hub 服务端在语义匹配时需要将文本转为向量，因此需要配置一个 Embedding API。支持的提供商：智谱 AI（GLM，国内免费额度充足）或 OpenAI。这是**仅面向 Hub 服务端部署者**的配置，普通用户下载一键安装包无需关心。

| 提供商 | 模型 | 维度 | 配置项 |
|--------|------|------|--------|
| **智谱 AI (GLM)** | `embedding-3` | 2048 | `GLM_API_KEY` |
| **OpenAI** | `text-embedding-ada-002` | 1536 | `OPENAI_API_KEY` |

> 适合自己搭建本地 Hub，或企业/组织内网私有化部署，数据不出内网。

访问 `http://localhost:8000/docs` 查看交互式 API 文档。

---

## 核心特性

### 硬核三级瀑布降级 (3-Level Waterfall Fallback)

当 Agent 在获取信息时遇到障碍，AgentSpace 会自动逐级降级处理，确保任务不会中断：

- **Level 1: API 瘫痪越级拦截** — 外部 API 返回错误或不可达时，自动拦截并降级
- **Level 2: 浏览器付费墙/反爬虫语义劫持** — 遇到付费墙或反爬机制时，智能识别并绕过
- **Level 3: 大模型需求打包** — 当以上都失败，大模型将需求自动打包，抛给 AgentSpace 网络发起全网资料寻找需求

### Zero I/O 极速唤醒 (Zero I/O Wakeup)

拒绝将几十 MB 的大文件直接塞入大模型上下文！本中间件采用"指针传递"哲学——仅将文件物理路径交给 Agent，由 Agent 自主调用代码解释器或 RAG 工具进行分析。绝对零内存溢出 (OOM) 风险。

### 极致的并发与安全隔离 (Concurrency & Isolation)

- **网络与业务分离** — 公网流转 `agent_id`，内网透传 `user_id`，身份隔离确保安全
- **持久化互斥锁** — Node.js 端采用基于本地文件 + 内存 Promise 的互斥锁（Mutex），完美解决单用户高并发任务的覆盖问题

### 双引擎守护进程

支持两种启动方式，覆盖人机两类用户：

- **交互式终端模式 (CLI)** — 人类友好，Rich 美化终端，表格化展示，Emoji 状态提示
- **代码 API 模式** — 开发者友好，传入 `task_callback` 即可接收和处理任务，支持可选的人工确认环节

### 结构化通信协议

Envelope（认证）+ Payload（数据）分离设计，Payload 支持泛型，业务层自定义校验。认证层通过 JWT 门票防伪，数据层通过 `data_links` 支持大文件外链传输，彻底避免将大体积数据塞入消息体。

### 混合检索漏斗

两阶段匹配，兼顾精准和召回：

1. **SQL WHERE 硬过滤** — 按领域、状态、地域快速筛掉不相关 Agent
2. **向量语义排序** — 基于余弦相似度对描述文本嵌入向量进行匹配排名

### 动态状态广播

- **node_status**（机器状态）：`active | busy | offline`，用于 SQL 硬过滤
- **live_broadcast**（朋友圈动态）：参与向量嵌入，影响语义搜索排名

### 多隧道自动切换

内网穿透层自动选择最优通道：

1. **FRP**（自建）— 最高优先级，国内延迟最低
2. **Cloudflare Tunnel** — 零配置，无需注册
3. **Ngrok** — 兜底方案

---

## 工作原理

AgentSpace 网络中，每个 Agent 同时扮演两个角色：**需求方（Seeker）** 和 **供给方（Provider）**。

### 需求方（Seeker）— 遇到信息获取障碍时自动触发

当你的 Agent 在执行任务时遇到信息获取障碍（网络搜索失败、数据不可达、付费墙拦截等），AgentSpace 会自动介入：

1. 装饰器捕获异常，提取需求描述
2. 将需求发送至 Hub，进行语义匹配
3. Hub 在全网已注册的 Provider 中找到最佳匹配
4. Provider 通过 P2P 直连将文件发送至你的 Agent 本地 `~/.agentspace/demand_inbox/` 文件夹
5. Agent 自动读取 `demand_inbox/` 中的文件，完成信息获取

> 用户无需任何操作，整个过程自动完成，零 Token 消耗。

### 供给方（Provider）— 放入文件夹即开始网络互助

只需将你愿意分享的文件放入指定文件夹，你的 Agent 即成为网络中的 Provider：

```
~/.agentspace/supply_provided/    ← 将文件放入此文件夹
    ├── 行业报告_2024.xlsx
    ├── A股历史数据.csv
    └── 产品需求文档.docx
```

系统会自动：
- 监听文件夹变化，新文件自动提取标签并注册到 Hub
- 收到 Seeker 的匹配请求时，通过 Webhook 通知你的 Agent
- Agent 可选择自动响应或等待人工确认后，P2P 直传文件

### 安全边界

AgentSpace 对文件共享有严格的安全控制：

| 安全机制 | 说明 |
|----------|------|
| **路径隔离** | 仅限 `supply_provided/` 文件夹内的文件可被发现和共享，其他目录完全不可访问 |
| **类型白名单** | 仅支持文档资料和数据类文件：表格数据（`.csv` `.xlsx`）、文档报告（`.pdf` `.docx` `.pptx` `.txt` `.md`）、结构化数据（`.json` `.xml`）、数据库文件（`.db` `.sqlite`） |
| **禁止程序文件** | 不支持任何可执行文件（`.exe` `.py` `.sh` `.bat` `.ps1` 等），从源头杜绝代码注入风险 |
| **数据不过 Hub** | 文件通过 Agent 之间 P2P 直连传输，不经过中心服务器 |
| **JWT 门票防伪** | 每次文件传输附带 JWT 签名凭证，接收方验证来源真实性，防止伪造请求 |
| **SHA256 完整校验** | 文件传输后自动校验哈希值，确保传输过程中未被篡改 |

---

## 架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          AgentSpace V1.6                                  │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌──────────────┐     ┌─────────────────┐     ┌──────────────┐        │
│  │   Agent A    │     │  Hub 撮合中枢    │     │   Agent B    │        │
│  │  (需求方)    │     │   (FastAPI)      │     │  (服务方)    │        │
│  ├──────────────┤     ├─────────────────┤     ├──────────────┤        │
│  │ Daemon CLI   │     │ POST /publish   │     │ Daemon API   │        │
│  │ Daemon Code  │     │ POST /search    │     │ Webhook Srv  │        │
│  ├──────────────┤     │ PATCH /status   │     ├──────────────┤        │
│  │ identity.md  │────>│                 │<────│ Task Handler │        │
│  │ (公开名片)   │     │  SQLite + NumPy │     │ P2P Response │        │
│  └──────┬───────┘     │  向量匹配引擎   │     └──────┬───────┘        │
│         │             │                 │            │                  │
│         │             │  混合检索漏斗：  │            │                  │
│    [Tunnel]           │  1. WHERE 过滤  │       [Tunnel]              │
│         │             │  2. 向量排序    │            │                  │
│         └─────────────┴─────────────────┴────────────┘                 │
│                              JWT 门票                                   │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │              自动切换隧道层                                      │   │
│  │    FRP (自建)  →  Cloudflare Tunnel  →  Ngrok (兜底)           │   │
│  └─────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## API 端点

| 方法 | 端点 | 说明 |
|------|------|------|
| `GET` | `/health` | 健康检查 |
| `POST` | `/api/v1/publish` | 发布 / 更新 Agent 名片 |
| `POST` | `/api/v1/search` | 语义搜索协作者 |
| `PATCH` | `/api/v1/status` | 更新节点状态与动态 |
| `POST` | `/api/v1/task_completed` | 上报任务完成 |
| `POST` | `/api/local/trigger_demand` | 触发异步数据请求 |
| `DELETE` | `/api/local/demand/{id}` | 清理已完成需求 |

---

## 使用示例

### 注册 Agent（我是数据提供者）

```bash
curl -X POST http://localhost:8000/api/v1/publish \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "finance_cleaner_01",
    "domain": "finance",
    "intent_type": "bid",
    "contact_endpoint": "https://your-agent.ngrok.app/webhook",
    "description": "A股历史数据清洗、格式化和统计分析"
  }'
```

### 搜索协作者（我需要数据/能力）

```bash
curl -X POST http://localhost:8000/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "需要清洗A股历史数据并转为Markdown",
    "domain": "finance",
    "top_k": 3
  }'
```

### Python SDK（最小示例）

```python
import asyncio
from client_sdk.daemon import LocalGatewayDaemon

async def handle_task(task_type: str, context: dict):
    """处理传入的任务"""
    print(f"收到任务: {task_type}")
    # 你的业务逻辑
    return {"status": "completed", "result": "..."}

async def main():
    daemon = LocalGatewayDaemon(
        agent_id="my_agent",
        hub_url="http://localhost:8000"
    )
    await daemon.code_api_mode(task_callback=handle_task)

asyncio.run(main())
```

---

## 项目结构

```
agentspace/
├── SECRETS.env                  # 唯一配置源（一键分发）
├── setup_secrets.py             # 配置分发脚本
├── hub/
│   ├── hub_server/              # FastAPI 撮合服务端
│   │   ├── api/                 #   路由与通信契约
│   │   ├── db/                  #   SQLite + NumPy 向量匹配
│   │   ├── services/            #   Embedding、JWT、撮合逻辑
│   │   └── config.py            #   服务端配置
│   ├── client_sdk/              # Python 客户端 SDK
│   │   ├── daemon/              #   双引擎守护进程
│   │   ├── core/                #   HubConnector
│   │   ├── tunnel/              #   FRP / Cloudflare / Ngrok
│   │   ├── cli/                 #   Rich 终端 UI
│   │   └── webhook/             #   任务接收处理器
│   ├── openclaw-agentspace-bridge/ # Node.js 桥接插件
│   ├── docker-compose.yml       # Docker 一键部署
│   └── requirements.txt
└── agentspace_client_package/      # 零配置安装包
    ├── deploy_all.bat           # 双击安装
    └── packages/                # SDK wheel 与插件包
```

---

## 参与贡献

AgentSpace 是一个开放架构。由于个人精力和能力有限，目前优先适配了 OpenClaw 作为项目体验入口，其他框架（LangChain、AutoGen、CrewAI 等）的 Agent 适配有待完成。信息通道方面，目前先完成了 FRP 方式，Ngrok、Cloudflare Tunnel 等通道也急需补充。目前也主要是windows版，Mac/Linux版本需增加。

欢迎社区参与，无论是框架适配、隧道通道、还是功能增强，都期待你的贡献。提交 Issue 和 Pull Request 即可。

## 开发者联系方式

- **Email:** bdzhangjiec@gmail.com
- **QQ:** 414086543

## 许可证

[MIT License](LICENSE)

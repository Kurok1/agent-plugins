# 一、输出目录

在项目中维护以下结构：

```text
docs/.code-map/
├── CODEMAP.md
│
├── domain/
│   ├── ...
│
├── flows/
│   ├── ...
│
├── architecture/
│   ├── ...
│
└── dependencies/
    ├── ...
```

根据实际代码仓库生成具体文件。

不要为了满足目录形式而创建没有实际意义的空文档。

---

# 二、核心原则

## 1. CODEMAP 是索引，不是说明书

`docs/CODEMAP.md` 必须保持简洁。

它只负责回答：

* 项目的主要代码入口在哪里？
* 有哪些核心领域概念？
* 有哪些主要业务流程？
* 架构信息在哪里？
* 项目依赖哪些基础设施或外部系统？
* 某类问题下一步应该读取哪个文档？

详细内容必须拆分到对应文档中。

不要把大量架构解释、业务规则、流程说明直接堆积在 `CODEMAP.md`。

---

## 2. 优先提供代码坐标

所有文档应优先告诉 agent：

> **代码在哪里**

然后再解释：

> **代码做什么、为什么这样做**

优先使用：

```text
文件路径
+
Class / Function / Method / Type / Interface / Component / Event 等 Symbol
```

例如：

```text
src/order/services/order.service.ts
→ OrderService.createOrder()
```

不要主要依赖：

```text
src/order/services/order.service.ts:183
```

除非有特殊必要，否则不要使用行号作为长期索引，因为行号容易随代码变更失效。

---

## 3. 不得猜测

所有代码位置、模块关系、调用关系、依赖关系和业务规则必须来自当前代码仓库。

如果无法确认：

* 明确标记 `Unknown` / `Unconfirmed`
* 或不写入结论

不得根据目录名称、文件名称或常见架构习惯虚构实现。

---

## 4. 面向代码修改场景

文档内容应优先支持以下类型的问题：

* “我要修改 XXX，应该从哪里开始？”
* “XXX 的核心逻辑在哪里？”
* “这个状态在哪里发生变化？”
* “这个 API 最终调用到了哪里？”
* “这个事件是谁发布的？”
* “这个事件有哪些消费者？”
* “这个数据最终写入哪个 repository / table？”
* “支付成功之后订单为什么没有变化？”
* “修改这个模块可能影响哪些地方？”

避免写大量无法帮助代码定位的背景描述。

---

# 三、CODEMAP.md

生成：

```text
docs/CODEMAP.md
```

推荐结构：

```md
# Code Map

Repository knowledge index for coding agents.

Use this document to locate the relevant code map before searching
the repository broadly.

## Repository Entry Points

...

## Domain Concepts

...

## Business Flows

...

## Architecture

...

## Dependencies

...
```

---

## 3.1 Repository Entry Points

列出整个项目最主要的代码入口。

例如：

| Runtime / Concern | Entry                |
| ----------------- | -------------------- |
| HTTP Server       | `src/server/main.ts` |
| API Routes        | `src/http/routes/`   |
| Worker            | `src/worker/main.ts` |
| Scheduled Jobs    | `src/jobs/`          |
| CLI               | `src/cli/main.ts`    |
| Database Schema   | `src/db/schema/`     |
| Tests             | `tests/`             |

必须根据实际项目调整。

如果项目是：

* monorepo
* frontend + backend
* multiple services
* worker architecture
* serverless
* CLI
* library

则按照实际运行单元组织 Entry Points。

---

# 四、Domain Concepts

目录：

```text
docs/domain/
```

Domain 文档解决的问题是：

> **业务里的“东西”是什么，它对应哪些代码？**

一个领域通常可以是：

* User
* Account
* Auth
* Permission
* Order
* Payment
* Product
* Subscription
* Workspace
* Project
* Notification

具体领域必须根据实际项目识别。

不要机械地按照代码目录拆 Domain。

Domain 应优先按照**业务语义**划分。

---

## Domain 文档模板

例如：

```text
docs/domain/order.md
```

推荐格式：

```md
# Order

## Concept

一句到三句描述该概念在系统中的含义。

不要写长篇产品背景。

## Primary Source

- `src/order/domain/order.ts`
  - `Order`
  - `OrderStatus`

## Core Symbols

- `Order`
- `OrderStatus`
- `OrderService`
- `OrderRepository`

## Business Rules

### Order status transition

Source:

`src/order/domain/order-state-machine.ts`

Symbols:

- `transitionOrderStatus()`
- `canTransitionTo()`

Rules:

- ...
- ...

## Commands / Operations

### Create Order

`src/order/services/order.service.ts`

→ `OrderService.createOrder()`

### Cancel Order

`src/order/services/order.service.ts`

→ `OrderService.cancelOrder()`

## Persistence

Repository:

`src/order/repositories/order.repository.ts`

Implementation:

`src/order/repositories/postgres-order.repository.ts`

Schema:

`src/db/schema/orders.ts`

## Events

Published:

- `OrderCreated`
- `OrderPaid`
- `OrderCancelled`

Defined in:

`src/order/events/order-events.ts`

## Related Flows

- `../flows/checkout.md`
- `../flows/payment-callback.md`
- `../flows/refund.md`

## Related Domains

- `payment.md`
- `user.md`
```

不同语言、框架和架构应自然调整，不需要强行出现所有字段。

---

# 五、Business Flows

目录：

```text
docs/flows/
```

Flow 文档解决的是：

> **一件业务行为实际经过哪些代码？**

这是跨模块、跨领域的运行路径。

例如：

```text
login.md
registration.md
checkout.md
payment-callback.md
refund.md
user-deletion.md
subscription-renewal.md
```

Flow 不等同于某一个模块。

它描述的是：

```text
Entry
↓
Validation
↓
Application Logic
↓
Domain Logic
↓
Persistence
↓
Event / Queue
↓
Side Effects
↓
Response
```

实际项目不存在的步骤不要强行加入。

---

## Flow 文档模板

```md
# Payment Callback

## Entry

`src/payment/http/payment-webhook.controller.ts`

→ `PaymentWebhookController.handle()`

↓

## Verification

`src/payment/providers/stripe/verify-webhook.ts`

→ `verifyWebhook()`

↓

## Application Service

`src/payment/services/payment-callback.service.ts`

→ `PaymentCallbackService.handle()`

↓

## Payment State Update

`src/payment/domain/payment.ts`

→ `Payment.markSucceeded()`

↓

## Order Update

`src/order/services/order.service.ts`

→ `OrderService.markPaid()`

↓

## Events

Publishes:

`OrderPaid`

Defined:

`src/order/events/order-events.ts`

↓

## Consumers

### Notification

`src/notification/handlers/order-paid.ts`

→ `handleOrderPaid()`

### Analytics

`src/analytics/handlers/order-paid.ts`

→ `trackOrderPaid()`

## Persistence

- Payment: `src/payment/repositories/...`
- Order: `src/order/repositories/...`

## Tests

- `tests/payment/...`
- `tests/e2e/payment-callback.spec.ts`

## Related Domains

- `../domain/payment.md`
- `../domain/order.md`

## Change Impact

修改该流程时重点检查：

- webhook verification
- payment idempotency
- payment state transition
- order state transition
- downstream event consumers
```

Flow 文档应尽量形成清晰的调用链。

---

# 六、Architecture

目录：

```text
docs/architecture/
```

Architecture 文档回答：

> **这些代码为什么这样组织，模块之间是什么关系？**

优先考虑生成：

```text
architecture/
├── overview.md
├── module-boundaries.md
├── data-flow.md
└── event-system.md
```

仅在项目确实存在对应架构时创建。

---

## overview.md

描述：

* 项目运行单元
* 核心模块
* 模块之间的大致关系
* 请求入口
* 数据存储
* 异步系统
* 外部系统

保持高层次。

不要重复 Domain 和 Flow 中已经存在的代码细节。

---

## module-boundaries.md

重点描述：

```text
模块 A
↓ allowed dependency

模块 B

模块 C
✕ should not depend on
模块 A
```

说明：

* 模块 ownership
* dependency direction
* public interface
* internal implementation
* shared layer
* boundary violations if clearly observable

---

## data-flow.md

说明系统中的数据主要如何流动，例如：

```text
HTTP
→ Controller
→ Application Service
→ Domain
→ Repository
→ Database
```

或者：

```text
Producer
→ Kafka
→ Consumer
→ Worker
→ Database
```

必须基于真实代码。

---

## event-system.md

如果项目存在 event / queue / pub-sub，记录：

* Event 定义位置
* Publisher
* Consumer
* Queue / Topic
* Retry
* Dead letter
* Idempotency

如果项目不存在事件系统，不创建此文档。

---

# 七、Dependencies

目录：

```text
docs/dependencies/
```

Dependencies 文档回答：

> **项目依赖哪些基础设施、SDK 或外部系统，以及相关代码在哪里？**

例如：

```text
database.md
redis.md
message-queue.md
stripe.md
s3.md
search.md
email.md
```

---

## Dependency 文档模板

```md
# Redis

## Purpose

Redis 在当前项目中用于：

- caching
- distributed locking
- rate limiting

仅填写实际存在的用途。

## Client Initialization

`src/infra/redis/client.ts`

→ `createRedisClient()`

## Configuration

`src/config/redis.ts`

Environment variables:

- `REDIS_URL`

不要泄露 secret 的实际值。

## Used By

### Authentication

`src/auth/session/...`

### Order Lock

`src/order/...`

## Failure Behavior

如果可以从代码确认：

- retry strategy
- timeout
- fallback
- fail-open / fail-closed

## Related Flows

- `../flows/login.md`
- `../flows/checkout.md`
```

---

# 八、交叉引用

文档之间必须形成链接关系。

例如：

```text
domain/order.md
    ↓
flows/checkout.md
    ↓
domain/payment.md
    ↓
dependencies/stripe.md
```

Domain 应链接相关 Flow。

Flow 应链接相关 Domain 和 Dependency。

Architecture 应在必要时链接相关模块。

Dependencies 应链接主要使用它的 Domain / Flow。

目标是让 agent 可以沿着知识图逐步缩小代码范围，而不是不断回到仓库根目录进行搜索。

---

# 九、分析仓库时的工作方式

生成 CODEMAP 时，按照以下顺序分析：

## Step 1 — Repository Structure

首先识别：

* monorepo / single repo
* applications
* packages
* services
* libraries
* runtime entry points
* test structure
* configuration structure

阅读已有：

* `AGENTS.md`
* `README.md`
* package manifests
* workspace config
* build config

但已有文档只能作为线索。

最终结论应尽量通过代码确认。

---

## Step 2 — Identify Domains

从以下线索识别业务领域：

* domain entities
* service names
* repository names
* API routes
* database models
* events
* tests
* frontend feature names

不要仅按照一级目录名称生成领域。

合并明显属于同一个业务概念的代码。

---

## Step 3 — Identify Major Flows

优先识别用户经常修改或排查的运行链路，例如：

* authentication
* create / update / delete
* checkout
* payment
* callback / webhook
* background job
* async processing
* notification
* import / export
* synchronization

从真实 entry point 向下追踪。

---

## Step 4 — Identify Architecture

识别：

* module boundaries
* dependency direction
* service boundaries
* application/domain/infrastructure layers
* synchronous calls
* asynchronous calls
* persistence boundaries

只记录能从仓库确认的信息。

---

## Step 5 — Identify Dependencies

检查：

* package manifest
* SDK initialization
* configuration
* environment variables
* infrastructure adapters
* clients

区分：

### Internal dependency

仓库内部模块之间的依赖。

### Infrastructure dependency

例如：

* PostgreSQL
* Redis
* Kafka
* S3

### External service dependency

例如：

* Stripe
* GitHub
* Slack
* Google APIs

不要把每一个普通 library 都生成 dependency 文档。

只记录对理解系统运行和修改代码有明显价值的依赖。

---

# 十、文档风格

优先：

```text
Path
→ Symbol
→ Responsibility
→ Relationships
→ Change Impact
```

而不是：

```text
背景
→ 历史
→ 产品说明
→ 大段文字
→ 最后才出现代码位置
```

保持：

* concise
* structured
* navigational
* code-oriented
* verifiable

尽量使用：

* 表格
* bullet list
* 调用链
* 文件路径
* symbol
* cross references

减少长段落。

---

# 十一、避免生成低价值内容

不要生成：

### 1. 文件树复制品

不要简单把整个 `src/` 目录转成 Markdown。

CODEMAP 必须提供**语义索引**。

---

### 2. 每个文件一条说明

不要生成：

```text
foo.ts — foo related logic
bar.ts — bar related logic
```

除非文件确实是重要代码入口。

---

### 3. 可以从文件名直接得到的信息

文档应该增加导航价值，而不是重复文件系统已有的信息。

---

### 4. 大量实现细节

CODEMAP 不是源码替代品。

当 Agent 已经知道应该打开哪个文件时，后续细节应该直接阅读代码。

---

### 5. 不稳定信息

避免：

* 精确行号
* 临时调试信息
* 当前文件长度
* 当前 commit hash
* 容易频繁变化的统计数字

除非有特殊必要。

---

# 十二、判断一条信息是否值得进入 CODEMAP

在写入任何内容前问：

> 这条信息是否能够减少未来 coding agent 为定位相关代码所做的搜索？

如果答案是否定的，通常不应写入 CODEMAP。

优先记录：

* 入口
* owner
* domain
* symbol
* flow
* state transition
* side effect
* dependency
* persistence
* event
* test
* change impact

---

# 十三、CODEMAP 的最终使用路径

最终应支持类似：

```text
User Request

"修改订单支付成功后的状态更新逻辑"

↓

CODEMAP.md

Business Flows
→ Payment Callback

↓

flows/payment-callback.md

Order update:
src/order/services/order.service.ts
→ OrderService.markPaid()

↓

domain/order.md

State transition:
src/order/domain/order-state-machine.ts
→ transitionOrderStatus()

↓

Open source files directly
```

理想情况下，到达相关源码之前只需要读取：

```text
CODEMAP.md
+
1~2 个相关 Map
```

而不是扫描整个 repository。

---

# 十四、完成后的自检

生成或更新文档后，检查：

* [ ] `CODEMAP.md` 是否仍然只是索引，而不是大型说明书
* [ ] 是否列出了主要 runtime / repository entry points
* [ ] 主要领域是否都有对应导航
* [ ] 主要跨模块业务流程是否有 Flow
* [ ] 文件路径是否真实存在
* [ ] Symbol 是否真实存在
* [ ] Flow 是否基于实际调用链
* [ ] 是否避免主要依赖行号
* [ ] Domain 与 Flow 是否互相链接
* [ ] Dependencies 是否只包含重要运行依赖
* [ ] 是否存在大量可以删除而不影响代码导航的信息
* [ ] Agent 能否从一个常见修改需求在 2~3 次文档跳转内定位到核心源码

如果最后一条无法满足，应优先优化导航结构。

---

# 十五、更新已有 CODEMAP

如果上述文档已经存在：

不要默认全部重新生成。

应：

1. 读取现有 CODEMAP。
2. 检查现有路径和 Symbol 是否仍然有效。
3. 检查新增的重要领域、流程和依赖。
4. 删除已经失效的引用。
5. 修正发生漂移的代码位置。
6. 保持已有稳定结构。
7. 尽量减少无意义的 Markdown churn。

目标是维护一个长期稳定、低噪音的代码知识索引，而不是每次生成一套新的项目文档。

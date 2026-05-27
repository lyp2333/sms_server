# SMS 验证码服务平台

一个基于卡密认证的短信验证码接收服务平台，支持 Webhook 接入、自助发卡、实时接收、自动提取验证码等功能。

## 核心功能

- 🔐 **卡密认证**：支持创建、激活、管理访问卡密（1/3/7/15/30 天）
- 📥 **短信接收**：支持来自 SmsForwarder 的 webhook 消息接入
- 🔎 **验证码自动提取**：自动识别短信中的验证码
- 🗂 **历史记录查询**：支持按手机号和时间段查询
- 🔄 **实时更新**：前端自动刷新获取新消息
- 🌐 **多平台兼容**：支持 Web 界面和 API 调用

## 项目结构

```
sms_server
├── backend
│   ├── main.py              # FastAPI 应用入口
│   ├── routes
│   │   └── v1
│   │       ├── api.py       # 短信 API 路由
│   │       └── card.py      # 卡密管理 API 路由
│   ├── services             # 核心业务逻辑
│   ├── models               # 数据库与 Pydantic 模型
│   ├── middlewares          # 日志、限速中间件
│   └── config               # 配置模块
├── frontend
│   ├── templates            # Jinja2 模板
│   │   ├── index.html       # 主页（卡密验证后访问）
│   │   ├── card_login.html  # 卡密登录页
│   │   └── admin_cards.html # 管理面板
│   └── static               # 静态资源
├── data                     # SQLite 数据文件夹
├── .env                     # 环境配置（不上传git）
├── requirements.txt
└── README.md
```

## 快速部署（systemd）

```bash
# 1. 克隆项目
git clone <仓库地址>
cd sms_server

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置环境变量
cp .env.example .env  # 编辑 .env 填入 SECRET_KEY 和 API_KEY

# 4. 安装 systemd 服务
sudo bash sms_service.sh

# 5. 查看服务状态
sudo systemctl status sms-webhook.service

# 6. 查看日志
sudo journalctl -u sms-webhook.service -f
```

## SmsForwarder 配置

在 SmsForwarder 中配置 Webhook：

**回调地址：**
```
https://你的域名/v1/sms/receive
```

**请求 JSON：**
```json
{
  "from": "{{FROM}}",
  "contact_name": "{{CONTACT_NAME}}",
  "phone_area": "{{PHONE_AREA}}",
  "sms": "{{SMS}}",
  "sim_slot": "{{CARD_SLOT}}",
  "sim_sub_id": "{{CARD_SUBID}}",
  "device_name": "{{DEVICE_NAME}}",
  "receive_time": "{{RECEIVE_TIME}}"
}
```

---

## 短信 API

### 接收短信

```bash
POST /v1/sms/receive
```

```json
{
  "from": "+1234567890",
  "contact_name": "验证码服务",
  "sms": "您的验证码是: 123456，请在5分钟内使用。",
  "sim_slot": "13800138000",
  "receive_time": "2023-04-01T12:00:00Z"
}
```

### 查询验证码

```bash
GET /v1/sms/code?phone_number=13800138000
```

### 获取历史记录

```bash
GET /v1/sms/history?limit=10&offset=0
```

### 删除单条记录（需管理员密码或 API Key）

```bash
DELETE /v1/sms/{sms_id}
-H "x-api-key: 你的管理员密码"
```

### 删除全部记录（需管理员密码或 API Key）

```bash
DELETE /v1/sms/history
-H "x-api-key: 你的管理员密码"
```

---

## 卡密管理 API

### 用户登录验证

```bash
POST /v1/card/verify
Content-Type: application/json

{"code": "ABC12345"}
```

登录成功后会写入 Cookie，有效期 7 天。

### 查询卡密状态

```bash
GET /v1/card/status
Cookie: card_session=xxx
```

### 管理员：创建卡密

```bash
POST /v1/card/admin/create
Content-Type: application/json

{"admin_password": "密码", "duration_days": 7, "count": 10}
```

### 管理员：查看所有卡密

```bash
GET /v1/card/admin/list
-H "Content-Type: application/json"
-d {"admin_password": "密码"}
```

### 管理员：删除卡密

```bash
DELETE /v1/card/admin/{code}
-H "Content-Type: application/json"
-d {"admin_password": "密码"}
```

### 管理员：使卡密立即失效

```bash
POST /v1/card/admin/{code}/expire
Content-Type: application/json

{"admin_password": "密码"}
```

### 管理员：延长卡密天数

```bash
POST /v1/card/admin/{code}/extend
Content-Type: application/json

{"admin_password": "密码", "days": 1}
```

### 管理员：清理过期卡密

```bash
POST /v1/card/admin/cleanup
Content-Type: application/json

{"admin_password": "密码"}
```

### 管理员：验证密码

```bash
POST /v1/sms/admin/verify
Content-Type: application/json

{"password": "密码"}
```

---

## 前端界面

| 页面 | 地址 | 说明 |
|------|------|------|
| 卡密登录 | `/?code=ABC12345` | URL 参数直接登录 |
| 管理面板 | `/admin/cards` | 需要管理员密码 |
| 在线文档 | `/docs` | Swagger API 文档 |

---

## 配置说明

主要环境变量（`.env` 文件）：

| 变量 | 说明 |
|------|------|
| `SECRET_KEY` | Cookie 签名密钥（必填） |
| `API_KEY` | API 访问密钥（可选，用于删除操作双重鉴权） |
| `ADMIN_PASSWORD` | 管理员密码（首次设置后存入数据库） |
| `CARD_KEY_CHARSET` | 卡密字符集（默认排除易混淆字符） |

---

## 开发与贡献

欢迎提 issue 或 pull request。

## 许可证

MIT License

# 毕业设计项目

Python 客户端 + Java 服务端。

## 技术栈

- Python 客户端：PySide6
- Java 服务端：Spring Boot 4.1.0、Java 17+、Maven
- 数据库：MySQL 8，连接配置在 `server-java/.env`

## 目录结构

```text
.
├── client-python/   # Python 客户端
└── server-java/     # Java 服务端
```

## 启动顺序

1. 启动服务端

```bash
cd server-java
mvn spring-boot:run
```

2. 启动客户端

```bash
cd client-python
python -m app.main
```

## 服务器地址切换

客户端连接地址在 `client-python/.env` 中配置：

```text
SERVER_BASE_URL=http://127.0.0.1:8080
```

部署到局域网后，把地址改成服务端实际 IP：

```text
SERVER_BASE_URL=http://192.168.1.100:8080
```

## 默认账号

```text
用户名：admin
密码：123456
```

## 登录接口

```text
POST /api/auth/login
```

请求体：

```json
{
  "username": "admin",
  "password": "123456"
}
```

## 注册接口

```text
POST /api/auth/register
```

请求体：

```json
{
  "username": "star",
  "nickname": "星弦用户",
  "phone": "13900000000",
  "email": "star@example.com",
  "password": "123456"
}
```

用户表字段：`id`、`username`、`nickname`、`phone`、`email`、`password_hash`、`created_at`。

密码使用 BCrypt 加密存储。
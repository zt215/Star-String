# Graduation Server

Spring Boot 服务端，提供用户登录和注册接口。

## Requirements

- JDK 17+
- Maven 3.9+

## Run

```bash
mvn spring-boot:run
```

服务监听 `0.0.0.0:8080`。

## Test

```bash
mvn test
```

## Login API

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

## Register API

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

用户表包含 `username`、`nickname`、`phone`、`email`、`password_hash` 等字段，密码使用 BCrypt 加密存储。

## MySQL 配置

启动本机 MySQL 服务并执行 `sql/init.sql`，然后编辑 `.env` 填写实际密码。

测试环境使用 H2 内存数据库，不依赖本机 MySQL。

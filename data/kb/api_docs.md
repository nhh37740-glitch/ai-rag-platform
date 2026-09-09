# API 文档

## 认证
调用接口需在请求头携带 `Authorization: Bearer <token>`。Token 由统一网关签发，有效期 24 小时。

## 速率限制
默认每秒 20 次请求，超出返回 429。

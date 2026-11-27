# 飞书成员会话

网关用飞书确认成员身份，SQLite 保存平台会话。成员选择「飞书登录」后，浏览器在这台设备上最多保持登录 30 天。飞书访问凭证到期时，网页通过原授权范围重新核验，再回到原页面。飞书能复用其登录状态时可直接返回；飞书要求交互时需按提示完成。相同飞书身份沿用原平台会话和关联的 MCP 授权。共用设备可选「仅本次登录」。账户与退出入口为 `/auth/account`。

默认以现有飞书授权范围登录。网关每 5 分钟按需重新核验组织身份，平台会话的 30 天从建立时起算。成员主动退出或确认组织身份失效，会同时停止相应 MCP 授权。等待浏览器续验期间，MCP 暂停读取；成员可在同一设备打开平台完成续验。飞书限流或暂时不可用时保留会话，稍后可以重试。

如应用已发布 `offline_access` 权限并允许刷新用户凭证，维护者可在现有网关配置显式设定 `offline_access: true`（JSON 布尔值）。下一次常规登录将请求该权限，飞书签发刷新凭证后，网关可在后台续验。[飞书刷新用户凭证说明](https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/authentication-management/access-token/refresh-user-access-token)

## 对已有网关应用增量

本目录保存网关源码补丁和完全合成的验收用例。部署时在现有 `auth_service.py` 的副本旁执行以下命令。补丁对应的原文件 SHA-256 为 `0988989fd4fbf5ccf61f279618fee2d5110267c774f6975d04ce2611dbaf6ded`。若网关已更新，请从补丁审阅并合并对应修改。

```sh
sha256sum auth_service.py
git apply --unidiff-zero --check /path/to/feishu-session/session-renewal.patch
git apply --unidiff-zero /path/to/feishu-session/session-renewal.patch
RMP_TEST_GATEWAY="$PWD/auth_service.py" python3 /path/to/feishu-session/verify_sessions.py -v
```

测试覆盖 600 秒访问凭证跨期、并发刷新、重启、组织变更、临时故障、短会话迁移、退出和登录账户切换。续验回调会核对发起请求的浏览器 Cookie 和一次性授权状态。单进程网关启动时自动创建附表，保留原会话表结构。回退可恢复以前的程序并重启，当前数据库保留。

已有短会话首次通过受保护页面的读取核验时，网关会向 Nginx 验证子请求返回一次 `Set-Cookie`。在受保护的页面层转交该响应头，浏览器即可保存新的固定到期时间。部署时检查实际生效 location 中已有的 `add_header` 继承配置。

```nginx
auth_request_set $rmp_session_upgrade $upstream_http_set_cookie;
add_header Set-Cookie $rmp_session_upgrade always;
```

## MCP 会话校验

网关仅在回环地址接收下列内部请求。调用方传入配置中的平台主机名。服务器的反向代理须保证两个内部地址无法由公网路由到网关。

| 请求 | 身份来源 | 结果 |
| --- | --- | --- |
| `GET /internal/mcp/member` | 当前成员的同源会话 Cookie | 已登录返回 204，响应头 `X-RMP-Subject`、`X-RMP-Session-Ref` 供本机服务绑定授权 |
| `POST /internal/mcp/session` | JSON 字段 `subject`、`session_ref` | 有效 204，等待飞书续验 401 并附 `X-RMP-Session-State: reverify`，注销或到期 401，飞书暂时不可用 503 |

内部引用仅在服务器之间传递。日常请求、页面、导出和日志均不应记录 Cookie、飞书凭证或授权绑定值。

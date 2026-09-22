# 容器化与持续集成

## 本地 Docker 启动

默认镜像使用 rule Planner 和 Mock 工具，不需要 API Key，也不会访问外部供应商：

```bash
docker compose up --build
curl http://127.0.0.1:8000/health
```

停止并保留可选模型缓存：

```bash
docker compose down
```

删除服务和模型缓存卷：

```bash
docker compose down --volumes
```

镜像默认不安装 FastEmbed，以保持体积和冷启动可控。需要 dense/hybrid 实验时显式构建 RAG extra：

```bash
INSTALL_EXTRAS='[rag]' KNOWLEDGE_RETRIEVAL=hybrid docker compose up --build
```

Compose 会从项目根目录 `.env` 读取变量并把列出的 LLM/MCP 设置传给容器；`.env` 不会进入 build context，也被 Git 忽略。真实 LLM 模式示例：

```bash
AGENT_PLANNER=llm docker compose up --build
```

不要把密钥写进 Dockerfile、Compose 文件或镜像 build arg。生产环境应使用平台 secret manager，而不是仓库内 `.env`。

## 镜像边界

- 基础镜像为 Python 3.11 slim Bookworm；应用使用 UID/GID 10001 的非 root 用户。
- build context 通过 `.dockerignore` 排除 `.env`、Git、模型缓存、虚拟环境、测试和本地报告。
- 镜像只复制 `pyproject.toml`、README 和 `src`，不包含开发凭据与评测产物。
- 容器提供 `/health` HEALTHCHECK，Compose 默认设置只读根文件系统、`no-new-privileges` 和 64 MB `/tmp`。
- `.cache` 使用独立 named volume，为可选 FastEmbed 模型提供可写缓存。
- 当前会话 Store 在进程内，因此容器固定使用单 worker；水平扩展前必须先迁移到共享存储。

基础镜像 tag 仍是可变引用。正式发布应由 Dependabot/Renovate 定期更新并锁定已验证的 multi-arch digest，同时生成 SBOM 和镜像漏洞扫描报告。

## GitHub Actions

CI 只使用离线 rule + mock，不读取仓库 secrets。工作流包含：

1. Python 3.10、3.11、3.12 兼容性测试；
2. Ruff 静态检查；
3. 全量 pytest，Python 3.11 覆盖率不得低于 85%；
4. Planner 与 BM25 两套离线评测回归；
5. Docker 构建、非 root UID 校验、只读容器启动、健康检查和真实 HTTP API 冒烟。

第三方 Actions 使用官方 release 对应的完整 commit SHA，工作流权限只有 `contents: read`，checkout 不保留凭据。并发配置会取消同一分支上已经过时的运行。

Dependabot 每周检查 Python、GitHub Actions 与 Docker 依赖更新；Actions 更新仍以完整 SHA 合入。交付配置本身也有测试，防止后续修改意外移除非 root、`.env` 排除、只读运行或覆盖率门禁。

CI 当前只构建和验证镜像，不登录 registry、不发布镜像，也不会部署。待 GitHub 仓库建立后，可单独增加受保护的 release workflow；发布权限不应混入 pull request CI。

# AGENTS.md

## 项目定位

本仓库是 Hermes Agent 的 Web Provider 扩展项目，用于提供或替换 Hermes 内置的 `web_search`、`web_extract` 和 deep-crawl 能力。

目标是实现一个 Hermes 可发现、可配置、可测试的 Python 后端插件，供 Hermes 工具层按能力路由调用。

## 技术栈

- 主要语言：Python。
- 目标运行环境：Hermes Agent 插件系统。
- 插件类型：Web search provider backend。
- 推荐 Python 版本：`>=3.9`，与 Hermes 插件生态保持兼容。
- 依赖管理：项目初始化后以 `pyproject.toml` 为准。

## Hermes 插件约定

实现时优先遵守 Hermes Web Provider 插件契约：

- 插件入口提供 `register(ctx)`。
- 在 `register(ctx)` 中注册 provider：`ctx.register_web_search_provider(...)`。
- Provider 继承或兼容 Hermes 的 `WebSearchProvider` 抽象接口。
- Provider 暴露稳定的 `name`，该值用于 Hermes 配置中的后端选择。
- `plugin.yaml` 使用 backend manifest：
  - `kind: backend`
  - `provides_web_providers`
  - `requires_env` 按需声明凭据或服务 URL
- Hermes 配置键按能力拆分：
  - `web.search_backend` 对应 `web_search`
  - `web.extract_backend` 对应 `web_extract` 和 deep-crawl
  - `web.backend` 作为统一后端配置

## Web Provider 能力约定

Provider 按能力显式声明支持范围：

- `supports_search()`：搜索能力。
- `supports_extract()`：网页内容提取能力。
- `crawl()` 或 Hermes 当前版本要求的 crawl 接口：站点递归抓取 / deep-crawl 能力。

返回值保持 Hermes 工具层期望的 envelope 结构。

搜索成功：

```python
{
    "success": True,
    "data": {
        "web": [
            {
                "title": "...",
                "url": "...",
                "description": "...",
                "position": 1,
            }
        ]
    },
}
```

提取成功：

```python
{
    "success": True,
    "data": [
        {
            "url": "...",
            "title": "...",
            "content": "...",
            "raw_content": "...",
            "metadata": {},
        }
    ],
}
```

失败返回：

```python
{"success": False, "error": "human-readable message"}
```

## 可用性与错误处理

- `is_available()` 只做廉价检查，例如环境变量、可选依赖是否存在、本地配置是否完整。
- `is_available()` 保持无网络调用，避免影响 `hermes tools` 等交互界面响应。
- HTTP、SDK、解析、限流等运行时错误转成 `{"success": False, "error": ...}` 或单 URL 的 `error` 字段。
- 错误信息面向用户可理解，避免泄露 API key、token、cookie、授权头和完整请求体。
- 对外部输入做边界检查：URL 列表长度、超时时间、crawl 深度、返回内容大小。
- 对网络请求设置明确 timeout。

## 代码风格

- 使用类型注解，公共函数和 provider 方法保持清晰签名。
- 优先小函数、早返回、显式错误路径。
- 可选依赖在实际使用点或惰性加载路径中导入，避免插件加载阶段失败。
- 保持 provider 逻辑薄而清楚：配置读取、请求发送、响应归一化、错误转换分层处理。
- 引入新依赖前确认它服务于搜索、提取、crawl、解析或测试目标。
- 项目出现格式化或 lint 配置后，以仓库配置为准。
- 推荐默认工具：`ruff format`、`ruff check`、`pytest`。

## 构建、运行与测试

项目初始化后优先以 `pyproject.toml`、README 和 CI 配置中的命令为准。

推荐开发流程：

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
pytest
```

常用检查命令：

```bash
ruff format .
ruff check .
pytest
```

针对单个变更优先运行最窄相关测试，例如：

```bash
pytest tests/unit/test_provider.py -q
```

## 测试要求

核心行为需要覆盖：

- provider 注册入口 `register(ctx)`。
- `name`、`display_name`、`supports_*()`、`is_available()`。
- `search()` 成功、空结果、HTTP 错误、限流、超时。
- `extract()` 单 URL、多 URL、部分失败、长内容、无标题页面。
- crawl / deep-crawl 的深度限制、同域限制、循环链接、失败恢复。
- 响应 envelope 兼容 Hermes 工具层。
- 凭据缺失和配置缺失场景。

测试中 mock 外部网络和第三方 SDK，保持单元测试稳定可复现。

## 安全与隐私

- 凭据只通过环境变量、Hermes 配置或受支持的认证机制读取。
- 日志中屏蔽 API key、Bearer token、cookie、authorization header、完整签名 URL。
- crawl 默认限制深度、页面数量、单页大小和总字节数。
- 对用户提供的 URL 做 scheme 校验，默认只处理 `http` 和 `https`。
- 保留重定向、私网地址、文件协议等 SSRF 风险点的显式处理。

## 提交规范

提交信息采用 Conventional Commits：

- `feat: add hermes web provider scaffold`
- `fix: handle extract timeout`
- `test: cover crawl depth limit`
- `docs: document backend configuration`
- `chore: update tooling`

## Agent 工作约定

- 修改前先检查工作区状态，保护用户已有改动。
- 优先阅读 Hermes 当前文档、相邻实现和仓库内配置。
- 以最小完整改动完成当前任务。
- 保持公共 API、provider `name` 和返回 envelope 稳定。
- 修改代码后运行最相关的格式化、lint 或测试命令。
- 无法运行的检查需要在回复中说明原因。
- 不提交 secrets、tokens、keys、cookies、个人数据或真实服务响应样本。

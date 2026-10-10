"""应用版本号 - 单一来源。

规则：
  - 默认从 1.0.1 开始（手动初始设置）。
  - 每次有破坏性变更以外的改动 → 递增第三位（1.0.1 → 1.0.2 → ...）。
  - 主版本（第一位）/ 次版本（第二位）必须由人工明确说明"更新到 X.Y.0"才会动；
    任何 CI / 自动化 / PR 流程都不允许触碰。

外部覆盖：
  - 部署时通过环境变量 APP_VERSION=1.0.5 覆盖（优先级：env > 本文件）。
"""
from __future__ import annotations

import os

# 单一来源：改这里就等于改整个项目对外显示的版本。
# 提交 PR 前请确认只递增第三位。
__version__ = "1.0.1"

# 仓库信息（用于在线更新 / 拉 GitHub Release）
GITHUB_OWNER = "adminmtan"
GITHUB_REPO = "domainsearch-"

# Docker 镜像（OCI 镜像名 = owner/yuming，仓库名末尾 "-" 在 OCI 不可用）
DOCKER_IMAGE = "ghcr.io/adminmtan/yuming"


def get_version() -> str:
    """返回当前运行版本：env APP_VERSION 优先，否则取 __version__。"""
    env_v = os.environ.get("APP_VERSION", "").strip()
    if env_v:
        return env_v
    return __version__


def parse_semver(v: str) -> tuple[int, int, int] | None:
    """解析 '1.2.3' / 'v1.2.3' → (1,2,3)；解析失败返回 None。"""
    s = v.strip().lstrip("v")
    parts = s.split(".")
    if len(parts) != 3:
        return None
    try:
        return int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        return None


def is_newer(remote: str, local: str) -> bool:
    """remote > local 返回 True（按 semver 元组比较）。"""
    r = parse_semver(remote)
    l = parse_semver(local)
    if r is None or l is None:
        return False
    return r > l

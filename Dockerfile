# 智能域名生成器 Docker 镜像
# 多阶段构建可减少镜像体积；这里用单阶段保持简单，便于 NAS 部署调试。
FROM python:3.12-slim

# 设置环境变量
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=5001

# 安装系统依赖（如需编译器，可在前面加 build-essential）
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 创建非 root 用户并指定 home 目录（gunicorn 需要可写的 HOME，否则启动时 Permission denied）
RUN groupadd -r appuser && useradd -r -g appuser -m -d /home/appuser appuser
ENV HOME=/home/appuser

WORKDIR /app

# 先复制依赖文件，利用层缓存
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY . .

# 静态资源给静态服务读，不需要写入权限
RUN chown -R appuser:appuser /app
USER appuser

EXPOSE 5001

# 健康检查：命中根路径返回 200 即健康
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request, sys; \
        sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:5001/').status == 200 else 1)"

# gunicorn 支持 SSE 流式响应（threads=True）
CMD ["gunicorn", "--bind", "0.0.0.0:5001", "--workers", "1", "--threads", "8", \
     "--timeout", "0", "--access-logfile", "-", "app:app"]

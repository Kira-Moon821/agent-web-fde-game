# FDE 部署包：AI 服务（Python 标准库 API）
# 构建上下文 = 项目根目录，构建文件 = 05-FDE部署/Dockerfile
FROM python:3.13-alpine

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_TOKEN=dev-token

WORKDIR /app

# 运行所需：API 服务 + 公共模块 + 部署产物（第 8 章闸门要在容器内自检部署文件）
COPY 03-代码实战/ ./03-代码实战/
COPY 05-FDE部署/ ./05-FDE部署/

# 非 root 运行（toB 安全评审必查）
RUN addgroup -S app && adduser -S app -G app && chown -R app:app /app
USER app

EXPOSE 8080

# 健康检查：进程活着 + 模型通道可用（本实现为 Mock，真实环境换成 provider ping）
HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request,sys;sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz',timeout=2).status==200 else 1)"

CMD ["python", "03-代码实战/ch07_service/app.py", "8080"]

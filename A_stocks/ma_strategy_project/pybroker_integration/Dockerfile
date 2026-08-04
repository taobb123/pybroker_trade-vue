FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 仅拷贝运行 API 所需内容（.dockerignore 已排除大数据）
COPY . .

EXPOSE 8080

# Railway 注入 PORT；本地 docker 可 -e PORT=8765
CMD ["sh", "-c", "uvicorn workflow_server:app --host 0.0.0.0 --port ${PORT:-8080}"]

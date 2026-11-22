FROM python:3.13-slim
WORKDIR /app
COPY requirements-lock.txt ./
RUN pip install --no-cache-dir -r requirements-lock.txt
COPY . .
EXPOSE 8765
CMD ["python", "-u", "server.py", "--host", "0.0.0.0", "--port", "8765"]

FROM python:3.11-slim
WORKDIR /app
COPY . .
CMD ["python","-m","robot_service.cli","data/example.json"]

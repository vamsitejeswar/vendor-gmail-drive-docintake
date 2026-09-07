FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py gmail_reader.py drive_uploader.py agent_validator.py runbook_generator.py agent_instructions.md ./
CMD ["python", "main.py"]

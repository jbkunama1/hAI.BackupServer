FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bot.py .
RUN python -c "import bot; print('bot import OK')"
ENV PYTHONUNBUFFERED=1
CMD ["python", "bot.py"]

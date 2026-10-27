FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ /app/
RUN mkdir -p /app/config /app/generated

# Build-Pruefungen: Templates vorhanden, Module importierbar (ohne Daten im Image zu hinterlassen)
RUN for f in templates/base.html templates/dashboard.html templates/host_form.html templates/host_detail.html \
             templates/monitoring.html templates/enroll.html templates/settings.html \
             templates/full_backup_template.sh.j2 templates/bootstrap_template.sh.j2 templates/enroll.sh \
             static/style.css; do test -f "/app/$f" || { echo "Datei fehlt im Image: $f"; exit 1; }; done \
 && CONFIG_DIR=/tmp/smoke DB_PATH=/tmp/smoke/t.db GENERATED_DIR=/tmp/smoke/gen python -c "import main; print('main import OK')" \
 && rm -rf /tmp/smoke

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]

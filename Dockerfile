FROM public.ecr.aws/lambda/python:3.12

# Speed up builds and avoid CVEs (optional)
RUN pip install --no-cache-dir --upgrade pip

# Python deps
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Install Chromium for Playwright (includes system libs)
RUN python -m playwright install --with-deps chromium

# App code
COPY handler.py ${LAMBDA_TASK_ROOT}/handler.py

# Lambda entrypoint
CMD [ "handler.lambda_handler" ]

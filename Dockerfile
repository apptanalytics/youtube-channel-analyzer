FROM apify/actor-python:3.11

COPY . .

RUN pip --no-cache-dir install -r requirements.txt

CMD ["python3", "apify_channel_analyzer.py"]

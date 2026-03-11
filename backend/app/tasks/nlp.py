from app.tasks.celery_app import celery_app


@celery_app.task(name="app.tasks.nlp.extract_issues")
def extract_issues(source_id: str):
    return {"status": "queued", "source_id": source_id}

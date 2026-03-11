from app.tasks.celery_app import celery_app
from app.services.storage import storage_client


@celery_app.task(name="app.tasks.exports.export_case")
def export_case(case_id: str, fmt: str):
    content = f"# Export\n\nCase: {case_id}\nFormat: {fmt}\n\n- missing (requires generated artifacts)\n"
    object_name = f"exports/{case_id}.{fmt}"
    storage_client.put_text(object_name, content, content_type="text/plain")
    return {"status": "ready", "case_id": case_id, "format": fmt}

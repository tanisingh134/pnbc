import logging
import uuid
from app.db.session import SessionLocal
from app.models.document import Document, DocumentStatus
from app.services.extraction.pipeline import DocumentProcessingPipeline
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.workers.tasks.process_document_task", bind=True)
def process_document_task(self, document_id: str) -> dict:
    """Asynchronous background worker task to process uploaded document.
    
    Ensures that any failure marks the document as FAILED with an error message,
    preventing documents from getting stuck in PROCESSING.
    """
    logger.info(f"Starting processing for document {document_id}")
    db = SessionLocal()
    try:
        doc_uuid = uuid.UUID(document_id)
        doc = db.get(Document, doc_uuid)
        if not doc:
            logger.error(f"Document {document_id} not found in database")
            return {"status": "NOT_FOUND", "document_id": document_id}

        result = DocumentProcessingPipeline.process_document(db, doc_uuid)
        logger.info(f"Successfully processed document {document_id} with result: {result}")
        return result

    except Exception as exc:
        logger.exception(f"Processing failed for document {document_id}: {exc}")
        try:
            doc_uuid = uuid.UUID(document_id)
            failed_doc = db.get(Document, doc_uuid)
            if failed_doc:
                failed_doc.status = DocumentStatus.FAILED
                failed_doc.error_message = f"Processing error: {str(exc)}"
                db.commit()
        except Exception as inner_exc:
            logger.error(f"Could not persist failure state for {document_id}: {inner_exc}")
        return {
            "status": "FAILED",
            "document_id": document_id,
            "error": str(exc),
        }
    finally:
        db.close()

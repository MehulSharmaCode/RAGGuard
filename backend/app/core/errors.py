"""Application error hierarchy.

Each error carries an HTTP status, a stable machine-readable code, and a message
that is safe to show to API clients (no credentials, paths, or stack traces).
"""

from __future__ import annotations


class AppError(Exception):
    status_code: int = 500
    code: str = "internal_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


# --- Ingestion ---------------------------------------------------------------
class UnsupportedFileError(AppError):
    status_code = 415
    code = "unsupported_file"


class FileTooLargeError(AppError):
    status_code = 413
    code = "file_too_large"


class EmptyDocumentError(AppError):
    status_code = 422
    code = "empty_document"


class DocumentExtractionError(AppError):
    status_code = 422
    code = "extraction_failed"


class DocumentNotFoundError(AppError):
    status_code = 404
    code = "document_not_found"


# --- Embeddings and vector store ---------------------------------------------
class EmbeddingError(AppError):
    status_code = 503
    code = "embedding_unavailable"


class VectorStoreError(AppError):
    status_code = 503
    code = "vector_store_unavailable"


class ConfigurationError(AppError):
    status_code = 500
    code = "configuration_error"


# --- Generation --------------------------------------------------------------
class GenerationConfigError(AppError):
    status_code = 500
    code = "generation_not_configured"


class GenerationUnavailableError(AppError):
    status_code = 503
    code = "generation_unavailable"


class GenerationTimeoutError(AppError):
    status_code = 504
    code = "generation_timeout"


class GenerationRateLimitError(AppError):
    status_code = 429
    code = "generation_rate_limited"


class GenerationUpstreamError(AppError):
    status_code = 502
    code = "generation_upstream_error"


# --- Evaluation reports and experiment tracking (read-only dashboards) ----------
class ReportNotFoundError(AppError):
    status_code = 404
    code = "report_not_found"


class ReportUnreadableError(AppError):
    status_code = 422
    code = "report_unreadable"


class TrackingDependencyMissingError(AppError):
    status_code = 503
    code = "tracking_dependency_missing"


class TrackingUnavailableError(AppError):
    status_code = 503
    code = "tracking_unavailable"


class RunNotFoundError(AppError):
    status_code = 404
    code = "run_not_found"


class ArtifactNotFoundError(AppError):
    status_code = 404
    code = "artifact_not_found"

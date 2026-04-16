from sqlalchemy import Column, String, Integer, Boolean, JSON, DateTime, func
from sqlalchemy.dialects.postgresql import UUID
import uuid

from app.models.database import Base


class APIRequestLog(Base):
    """Log all API requests for analytics."""

    __tablename__ = "api_request_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    endpoint = Column(String(255), nullable=False)  # /api/weather
    params = Column(JSON, default={})  # Query params
    external_api = Column(String(50))  # openweather, null if cached
    cached = Column(Boolean, default=False)
    response_time_ms = Column(Integer)  # Response time in ms
    status = Column(Integer)  # HTTP status code
    error_message = Column(String(500))  # Error message if failed
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    def __repr__(self):
        return f"<APIRequestLog {self.endpoint} - {self.external_api} - cached={self.cached}>"

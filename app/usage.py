from typing import Optional

from sqlalchemy.orm import Session

from app.models import UsageEvent
from app.service_auth import ServiceAuthContext


def record_usage(
    db: Session,
    auth: ServiceAuthContext,
    event_type: str,
    quantity: int = 1,
) -> Optional[UsageEvent]:
    """Record billable workspace usage. Legacy traffic is not billed during migration."""
    if auth.workspace_id is None or auth.tenant_id is None:
        return None

    event = UsageEvent(
        tenant_id=auth.tenant_id,
        workspace_id=auth.workspace_id,
        event_type=event_type,
        quantity=quantity,
    )
    db.add(event)
    return event

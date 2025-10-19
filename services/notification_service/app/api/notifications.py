"""HTTP routes for notification management."""

from __future__ import annotations

from datetime import timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.exc import IntegrityError

from ..dependencies import get_notification_service
from ..schemas import (
    BatchNotificationRequest,
    NotificationCreate,
    NotificationEventResponse,
    NotificationFailRequest,
    NotificationJobDetailResponse,
    NotificationJobListResponse,
    NotificationJobResponse,
    NotificationListResponse,
    NotificationRescheduleRequest,
    NotificationResponse,
    PreferenceResponse,
    PreferenceUpdate,
    TemplateCreate,
    TemplateFilters,
    TemplateListResponse,
    TemplateResponse,
    TemplateUpdate,
)
from ..services import NotificationService, RateLimitExceeded, metadata_from_json

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _serialize_datetime(value):
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _serialize_notification(notification) -> dict[str, object]:
    metadata = metadata_from_json(notification.metadata_json)
    return {
        "id": notification.id,
        "recipient": notification.recipient,
        "channel": notification.channel,
        "subject": notification.subject,
        "body": notification.body,
        "template": notification.template,
        "metadata": metadata,
        "status": notification.status,
        "errorMessage": notification.error_message,
        "sendAfter": _serialize_datetime(notification.send_after),
        "sentAt": _serialize_datetime(notification.sent_at),
        "jobId": notification.job_id,
        "createdAt": notification.created_at,
        "updatedAt": notification.updated_at,
    }


def _serialize_events(notification) -> list[dict[str, object]]:
    return [
        {
            "type": event.type,
            "payload": event.payload,
            "createdAt": event.created_at,
        }
        for event in notification.events
    ]


def _serialize_job(job, *, include_notifications: bool) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": job.id,
        "templateId": job.template_id,
        "status": job.status,
        "scheduledFor": _serialize_datetime(job.scheduled_for),
        "totalCount": job.total_count,
        "processedCount": job.processed_count,
        "errorMessage": job.error_message,
        "createdAt": job.created_at,
        "updatedAt": job.updated_at,
    }
    if include_notifications:
        payload["notifications"] = [
            NotificationResponse.model_validate(_serialize_notification(notification))
            for notification in job.notifications
        ]
    return payload


def _serialize_template(template) -> dict[str, object]:
    metadata = metadata_from_json(template.metadata_json)
    return {
        "id": template.id,
        "name": template.name,
        "channel": template.channel,
        "locale": template.locale,
        "version": template.version,
        "subject": template.subject,
        "body": template.body,
        "metadata": metadata,
        "createdAt": template.created_at,
        "updatedAt": template.updated_at,
    }


@router.post("", response_model=NotificationResponse, status_code=status.HTTP_201_CREATED)
async def create_notification(
    payload: NotificationCreate,
    service: NotificationService = Depends(get_notification_service),
) -> NotificationResponse:
    notification = await service.create_notification(payload)
    return NotificationResponse.model_validate(_serialize_notification(notification))


@router.get("", response_model=NotificationListResponse)
async def list_notifications(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    recipient: str | None = None,
    channel: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    service: NotificationService = Depends(get_notification_service),
) -> NotificationListResponse:
    repository = service.repository
    notifications, total = await repository.list_notifications(
        recipient=recipient,
        channel=channel,
        status=status_filter,
        limit=limit,
        offset=offset,
    )
    items = [NotificationResponse.model_validate(_serialize_notification(notification)) for notification in notifications]
    return NotificationListResponse(items=items, total=total)


@router.post("/batch", response_model=NotificationJobResponse, status_code=status.HTTP_202_ACCEPTED)
async def schedule_batch(
    payload: BatchNotificationRequest,
    service: NotificationService = Depends(get_notification_service),
) -> NotificationJobResponse:
    try:
        job = await service.schedule_batch(payload)
    except RateLimitExceeded:
        await service.repository.session.rollback()
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Rate limit exceeded")
    except ValueError as exc:
        await service.repository.session.rollback()
        message = str(exc)
        if message == "template_not_found":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
        if message == "empty_batch":
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Recipients required")
        raise
    job = await service.get_job(job.id)
    assert job is not None
    return NotificationJobResponse.model_validate(_serialize_job(job, include_notifications=False))


@router.post("/templates", response_model=TemplateResponse, status_code=status.HTTP_201_CREATED)
async def create_template(
    payload: TemplateCreate,
    service: NotificationService = Depends(get_notification_service),
) -> TemplateResponse:
    try:
        template = await service.create_template(payload)
    except IntegrityError:
        await service.repository.session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Template already exists")
    return TemplateResponse.model_validate(_serialize_template(template))


@router.get("/templates", response_model=TemplateListResponse)
async def list_templates(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    name: str | None = None,
    channel: str | None = None,
    locale: str | None = None,
    service: NotificationService = Depends(get_notification_service),
) -> TemplateListResponse:
    filters = TemplateFilters(name=name, channel=channel, locale=locale)
    templates, total = await service.list_templates(filters, limit=limit, offset=offset)
    items = [TemplateResponse.model_validate(_serialize_template(template)) for template in templates]
    return TemplateListResponse(items=items, total=total)


@router.get("/templates/{template_id}", response_model=TemplateResponse)
async def get_template(
    template_id: str,
    service: NotificationService = Depends(get_notification_service),
) -> TemplateResponse:
    template = await service.repository.get_template(template_id)
    if template is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    return TemplateResponse.model_validate(_serialize_template(template))


@router.put("/templates/{template_id}", response_model=TemplateResponse)
async def update_template(
    template_id: str,
    payload: TemplateUpdate,
    service: NotificationService = Depends(get_notification_service),
) -> TemplateResponse:
    template = await service.repository.get_template(template_id)
    if template is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    try:
        updated = await service.update_template(template, payload)
    except IntegrityError:
        await service.repository.session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Template already exists")
    return TemplateResponse.model_validate(_serialize_template(updated))


@router.delete("/templates/{template_id}")
async def delete_template(
    template_id: str,
    service: NotificationService = Depends(get_notification_service),
) -> Response:
    template = await service.repository.get_template(template_id)
    if template is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    await service.repository.delete_template(template)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/jobs", response_model=NotificationJobListResponse)
async def list_jobs(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status_filter: str | None = Query(default=None, alias="status"),
    template_id: str | None = Query(default=None, alias="templateId"),
    service: NotificationService = Depends(get_notification_service),
) -> NotificationJobListResponse:
    jobs, total = await service.list_jobs(
        status=status_filter,
        template_id=template_id,
        limit=limit,
        offset=offset,
    )
    items = [NotificationJobResponse.model_validate(_serialize_job(job, include_notifications=False)) for job in jobs]
    return NotificationJobListResponse(items=items, total=total)


@router.get("/jobs/{job_id}", response_model=NotificationJobDetailResponse)
async def get_job(
    job_id: int,
    service: NotificationService = Depends(get_notification_service),
) -> NotificationJobDetailResponse:
    job = await service.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return NotificationJobDetailResponse.model_validate(_serialize_job(job, include_notifications=True))


@router.get("/{notification_id}", response_model=NotificationResponse)
async def get_notification(
    notification_id: int,
    service: NotificationService = Depends(get_notification_service),
) -> NotificationResponse:
    notification = await service.repository.get_notification(notification_id)
    if notification is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    return NotificationResponse.model_validate(_serialize_notification(notification))


@router.post("/{notification_id}/send", response_model=NotificationResponse)
async def send_notification(
    notification_id: int,
    service: NotificationService = Depends(get_notification_service),
) -> NotificationResponse:
    notification = await service.repository.get_notification(notification_id)
    if notification is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    if notification.status == "sent":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Notification already sent")
    try:
        updated = await service.send_notification(notification)
    except RateLimitExceeded:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Rate limit exceeded")
    return NotificationResponse.model_validate(_serialize_notification(updated))


@router.post("/{notification_id}/fail", response_model=NotificationResponse)
async def fail_notification(
    notification_id: int,
    payload: NotificationFailRequest,
    service: NotificationService = Depends(get_notification_service),
) -> NotificationResponse:
    notification = await service.repository.get_notification(notification_id)
    if notification is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    updated = await service.fail_notification(notification, reason=payload.message)
    return NotificationResponse.model_validate(_serialize_notification(updated))


@router.post("/{notification_id}/reschedule", response_model=NotificationResponse)
async def reschedule_notification(
    notification_id: int,
    payload: NotificationRescheduleRequest,
    service: NotificationService = Depends(get_notification_service),
) -> NotificationResponse:
    notification = await service.repository.get_notification(notification_id)
    if notification is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    updated = await service.reschedule_notification(notification, send_after=payload.send_after)
    return NotificationResponse.model_validate(_serialize_notification(updated))


@router.get("/{notification_id}/events", response_model=list[NotificationEventResponse])
async def get_notification_events(
    notification_id: int,
    service: NotificationService = Depends(get_notification_service),
) -> list[NotificationEventResponse]:
    notification = await service.repository.get_notification(notification_id)
    if notification is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    return [NotificationEventResponse.model_validate(event) for event in _serialize_events(notification)]


@router.delete("/{notification_id}")
async def delete_notification(
    notification_id: int,
    service: NotificationService = Depends(get_notification_service),
) -> Response:
    notification = await service.repository.get_notification(notification_id)
    if notification is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    await service.repository.delete_notification(notification)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/preferences/{customer_id}", response_model=PreferenceResponse)
async def get_preferences(
    customer_id: int,
    service: NotificationService = Depends(get_notification_service),
) -> PreferenceResponse:
    preferences = await service.get_preferences(customer_id)
    return PreferenceResponse(customerId=customer_id, preferences=preferences)  # type: ignore[arg-type]


@router.put("/preferences/{customer_id}", response_model=PreferenceResponse)
async def update_preferences(
    customer_id: int,
    payload: PreferenceUpdate,
    service: NotificationService = Depends(get_notification_service),
) -> PreferenceResponse:
    updated = await service.update_preferences(customer_id, payload.preferences)
    return PreferenceResponse(customerId=customer_id, preferences=updated)  # type: ignore[arg-type]

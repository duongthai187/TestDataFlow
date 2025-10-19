"""HTTP routes for support service operations."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, UploadFile, status

from ..dependencies import (
    get_attachment_storage,
    get_attachment_storage_optional,
    get_event_publisher_optional,
    get_repository,
    get_timeline_aggregator,
)
from ..repository import SupportRepository
from ..schemas import (
    AgentWorkloadResponse,
    AttachmentResponse,
    ConversationCreate,
    ConversationResponse,
    TicketCreate,
    TicketDetailResponse,
    TicketCloseRequest,
    TicketResponse,
)
from ..services import SupportService
from ..storage import AttachmentStorageProtocol
from ..timeline import TimelineAggregatorProtocol

router = APIRouter(prefix="/support", tags=["support"])


@router.post("/cases", response_model=TicketDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_ticket(
    payload: TicketCreate,
    repository: SupportRepository = Depends(get_repository),
    aggregator: TimelineAggregatorProtocol | None = Depends(get_timeline_aggregator),
    storage: AttachmentStorageProtocol | None = Depends(get_attachment_storage_optional),
    event_publisher = Depends(get_event_publisher_optional),
) -> TicketDetailResponse:
    service = SupportService(repository, aggregator, storage, event_publisher)
    ticket = await service.create_ticket(payload)
    return ticket


@router.get("/cases/{ticket_id}", response_model=TicketDetailResponse)
async def get_ticket(
    ticket_id: str,
    include_timeline: bool = Query(default=False, alias="includeTimeline"),
    repository: SupportRepository = Depends(get_repository),
    aggregator: TimelineAggregatorProtocol | None = Depends(get_timeline_aggregator),
    storage: AttachmentStorageProtocol | None = Depends(get_attachment_storage_optional),
    event_publisher = Depends(get_event_publisher_optional),
) -> TicketDetailResponse:
    ticket = await repository.get_ticket(ticket_id)
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    service = SupportService(repository, aggregator, storage, event_publisher)
    return await service.get_ticket(ticket, include_timeline)


@router.post("/cases/{ticket_id}/messages", response_model=ConversationResponse)
async def post_message(
    ticket_id: str,
    payload: ConversationCreate,
    repository: SupportRepository = Depends(get_repository),
    aggregator: TimelineAggregatorProtocol | None = Depends(get_timeline_aggregator),
    storage: AttachmentStorageProtocol | None = Depends(get_attachment_storage_optional),
    event_publisher = Depends(get_event_publisher_optional),
) -> ConversationResponse:
    ticket = await repository.get_ticket(ticket_id)
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    service = SupportService(repository, aggregator, storage, event_publisher)
    return await service.add_message(ticket, payload)


@router.post("/cases/{ticket_id}/status", response_model=TicketResponse)
async def update_status(
    ticket_id: str,
    status_value: str = Query(..., alias="status"),
    assigned_agent_id: str | None = Query(default=None, alias="assignedAgentId"),
    repository: SupportRepository = Depends(get_repository),
    aggregator: TimelineAggregatorProtocol | None = Depends(get_timeline_aggregator),
    storage: AttachmentStorageProtocol | None = Depends(get_attachment_storage_optional),
    event_publisher = Depends(get_event_publisher_optional),
) -> TicketResponse:
    ticket = await repository.get_ticket(ticket_id)
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    service = SupportService(repository, aggregator, storage, event_publisher)
    return await service.update_status(ticket, status=status_value, assigned_agent_id=assigned_agent_id)


@router.post("/cases/{ticket_id}/close", response_model=TicketDetailResponse)
async def close_ticket(
    ticket_id: str,
    payload: TicketCloseRequest | None = Body(default=None),
    repository: SupportRepository = Depends(get_repository),
    aggregator: TimelineAggregatorProtocol | None = Depends(get_timeline_aggregator),
    storage: AttachmentStorageProtocol | None = Depends(get_attachment_storage_optional),
    event_publisher = Depends(get_event_publisher_optional),
) -> TicketDetailResponse:
    ticket = await repository.get_ticket(ticket_id)
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    service = SupportService(repository, aggregator, storage, event_publisher)
    return await service.close_ticket(ticket, payload)


@router.get("/agents/{agent_id}/workload", response_model=AgentWorkloadResponse)
async def get_agent_workload(
    agent_id: str,
    repository: SupportRepository = Depends(get_repository),
) -> AgentWorkloadResponse:
    service = SupportService(repository, None)
    return await service.get_workload(agent_id)


@router.post("/cases/{ticket_id}/timeline/refresh", response_model=TicketDetailResponse)
async def refresh_timeline(
    ticket_id: str,
    repository: SupportRepository = Depends(get_repository),
    aggregator: TimelineAggregatorProtocol | None = Depends(get_timeline_aggregator),
    storage: AttachmentStorageProtocol | None = Depends(get_attachment_storage_optional),
    event_publisher = Depends(get_event_publisher_optional),
) -> TicketDetailResponse:
    ticket = await repository.get_ticket(ticket_id)
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    service = SupportService(repository, aggregator, storage, event_publisher)
    return await service.refresh_timeline(ticket)


@router.post(
    "/cases/{ticket_id}/attachments",
    response_model=AttachmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_attachment(
    ticket_id: str,
    file: UploadFile = File(...),
    repository: SupportRepository = Depends(get_repository),
    aggregator: TimelineAggregatorProtocol | None = Depends(get_timeline_aggregator),
    storage: AttachmentStorageProtocol = Depends(get_attachment_storage),
    event_publisher = Depends(get_event_publisher_optional),
) -> AttachmentResponse:
    ticket = await repository.get_ticket(ticket_id)
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    service = SupportService(repository, aggregator, storage, event_publisher)
    return await service.upload_attachment(ticket, file)


@router.get("/cases/{ticket_id}/attachments", response_model=list[AttachmentResponse])
async def list_attachments(
    ticket_id: str,
    repository: SupportRepository = Depends(get_repository),
    aggregator: TimelineAggregatorProtocol | None = Depends(get_timeline_aggregator),
    storage: AttachmentStorageProtocol | None = Depends(get_attachment_storage_optional),
    event_publisher = Depends(get_event_publisher_optional),
) -> list[AttachmentResponse]:
    ticket = await repository.get_ticket(ticket_id)
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    service = SupportService(repository, aggregator, storage, event_publisher)
    return await service.list_attachments(ticket)

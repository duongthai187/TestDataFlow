"""HTTP routes for fulfillment operations."""

from __future__ import annotations

import json
from json import JSONDecodeError

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from ..dependencies import get_repository
from ..repository import FulfillmentRepository
from ..schemas import (
    ReturnCreate,
    ReturnResponse,
    ShipmentCreate,
    ShipmentEventResponse,
    ShipmentListResponse,
    ShipmentResponse,
    ShipmentStatusUpdate,
    TrackingResponse,
)
from ..services import FulfillmentService

router = APIRouter(prefix="/fulfillment", tags=["fulfillment"])


def _deserialize_payload(raw: str | None) -> dict[str, object]:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except JSONDecodeError:
        return {}


def _serialize_task(task) -> dict[str, object]:
    return {
        "id": task.id,
        "taskType": task.task_type,
        "status": task.status,
        "assignedTo": task.assigned_to,
        "deadline": task.deadline,
        "payload": _deserialize_payload(task.payload_json),
        "createdAt": task.created_at,
        "updatedAt": task.updated_at,
    }


def _serialize_shipment(shipment) -> dict[str, object]:
    return {
        "id": shipment.id,
        "orderId": shipment.order_id,
        "fulfillmentCenterId": shipment.fulfillment_center_id,
        "carrier": shipment.carrier_code,
        "serviceLevel": shipment.service_level,
        "status": shipment.status,
        "trackingNumber": shipment.tracking_number,
        "shippedAt": shipment.shipped_at,
        "deliveredAt": shipment.delivered_at,
        "estimatedDelivery": shipment.estimated_delivery,
        "createdAt": shipment.created_at,
        "updatedAt": shipment.updated_at,
        "tasks": [_serialize_task(task) for task in shipment.tasks],
    }


def _serialize_event(event) -> dict[str, object]:
    return {
        "id": event.id,
        "type": event.type,
        "payload": _deserialize_payload(event.payload),
        "createdAt": event.created_at,
    }


@router.post("/shipments", response_model=ShipmentResponse, status_code=status.HTTP_201_CREATED)
async def create_shipment(
    payload: ShipmentCreate,
    repository: FulfillmentRepository = Depends(get_repository),
) -> ShipmentResponse:
    service = FulfillmentService(repository)
    shipment = await service.create_shipment(payload)
    return ShipmentResponse.model_validate(_serialize_shipment(shipment))


@router.get("/shipments", response_model=ShipmentListResponse)
async def list_shipments(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    order_id: int | None = Query(default=None, alias="orderId", ge=1),
    status_filter: str | None = Query(default=None, alias="status"),
    tracking_number: str | None = Query(default=None, alias="trackingNumber"),
    repository: FulfillmentRepository = Depends(get_repository),
) -> ShipmentListResponse:
    shipments, total = await repository.list_shipments(
        order_id=order_id,
        status=status_filter.lower() if status_filter else None,
        tracking_number=tracking_number,
        limit=limit,
        offset=offset,
    )
    items = [ShipmentResponse.model_validate(_serialize_shipment(shipment)) for shipment in shipments]
    return ShipmentListResponse(items=items, total=total)


@router.get("/shipments/{shipment_id}", response_model=ShipmentResponse)
async def get_shipment(
    shipment_id: int,
    repository: FulfillmentRepository = Depends(get_repository),
) -> ShipmentResponse:
    shipment = await repository.get_shipment(shipment_id)
    if shipment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shipment not found")
    return ShipmentResponse.model_validate(_serialize_shipment(shipment))


@router.post("/shipments/{shipment_id}/status", response_model=ShipmentResponse)
async def update_status(
    shipment_id: int,
    payload: ShipmentStatusUpdate,
    repository: FulfillmentRepository = Depends(get_repository),
) -> ShipmentResponse:
    shipment = await repository.get_shipment(shipment_id)
    if shipment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shipment not found")
    service = FulfillmentService(repository)
    try:
        updated = await service.update_status(shipment, payload)
    except ValueError as exc:  # noqa: PERF203 - map domain errors to HTTP
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return ShipmentResponse.model_validate(_serialize_shipment(updated))


@router.get("/shipments/{shipment_id}/events", response_model=list[ShipmentEventResponse])
async def list_events(
    shipment_id: int,
    repository: FulfillmentRepository = Depends(get_repository),
) -> list[ShipmentEventResponse]:
    shipment = await repository.get_shipment(shipment_id)
    if shipment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shipment not found")
    serialized = [_serialize_event(event) for event in shipment.events]
    return [ShipmentEventResponse.model_validate(event) for event in serialized]


@router.get("/track/{tracking_number}", response_model=TrackingResponse)
async def track_shipment(
    tracking_number: str,
    repository: FulfillmentRepository = Depends(get_repository),
) -> TrackingResponse:
    service = FulfillmentService(repository)
    try:
        shipment = await service.track_shipment(tracking_number)
    except ValueError as exc:  # noqa: PERF203
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    serialized_shipment = _serialize_shipment(shipment)
    events = [_serialize_event(event) for event in shipment.events]
    return TrackingResponse.model_validate({"shipment": serialized_shipment, "events": events})


@router.delete("/shipments/{shipment_id}")
async def delete_shipment(
    shipment_id: int,
    repository: FulfillmentRepository = Depends(get_repository),
) -> Response:
    shipment = await repository.get_shipment(shipment_id)
    if shipment is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    await repository.delete_shipment(shipment)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/returns", response_model=ReturnResponse, status_code=status.HTTP_201_CREATED)
async def create_return(
    payload: ReturnCreate,
    repository: FulfillmentRepository = Depends(get_repository),
) -> ReturnResponse:
    service = FulfillmentService(repository)
    try:
        return_request = await service.create_return(payload)
    except ValueError as exc:  # noqa: PERF203
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return ReturnResponse.model_validate(return_request)


@router.get("/returns/{return_id}", response_model=ReturnResponse)
async def get_return(
    return_id: int,
    repository: FulfillmentRepository = Depends(get_repository),
) -> ReturnResponse:
    return_request = await repository.get_return(return_id)
    if return_request is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Return not found")
    return ReturnResponse.model_validate(return_request)

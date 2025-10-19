"""Customer-facing API routes."""

from __future__ import annotations

from typing import Iterable

from fastapi import APIRouter, Depends, HTTPException, Response, status

from ..dependencies import get_repository
from ..models import CustomerAddress, CustomerProfile
from ..repository import CustomerRepository
from ..schemas import Address, CustomerCreate, CustomerResponse, CustomerSegmentResponse, CustomerUpdate, SegmentAssignment

router = APIRouter(prefix="/customers", tags=["customers"])


def _build_addresses(addresses: Iterable[Address]) -> list[CustomerAddress]:
    return [
        CustomerAddress(
            label=item.label,
            line1=item.line1,
            line2=item.line2,
            city=item.city,
            state=item.state,
            postal_code=item.postal_code,
            country=item.country,
        )
        for item in addresses
    ]


def _serialize_customer(profile: CustomerProfile) -> CustomerResponse:
    payload = {
        "id": profile.id,
        "email": profile.email,
        "full_name": profile.full_name,
        "phone_number": profile.phone_number,
        "preferred_language": profile.preferred_language,
        "addresses": profile.addresses,
        "segments": [segment.segment for segment in profile.segments],
        "created_at": profile.created_at,
        "updated_at": profile.updated_at,
    }
    return CustomerResponse.model_validate(payload, from_attributes=True)


async def _require_customer(customer_id: int, repo: CustomerRepository) -> CustomerProfile:
    profile = await repo.get_customer(customer_id)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
    return profile


@router.post("", response_model=CustomerResponse, status_code=status.HTTP_201_CREATED)
async def create_customer(
    payload: CustomerCreate, repo: CustomerRepository = Depends(get_repository)
) -> CustomerResponse:
    existing = await repo.get_by_email(payload.email)
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    profile = await repo.create_customer(
    email=payload.email,
        full_name=payload.full_name,
        phone_number=payload.phone_number,
        preferred_language=payload.preferred_language,
        addresses=_build_addresses(payload.addresses),
    )
    await repo.session.refresh(profile, attribute_names=["addresses", "segments"])
    return _serialize_customer(profile)


@router.get("/{customer_id}", response_model=CustomerResponse)
async def get_customer(
    customer_id: int, repo: CustomerRepository = Depends(get_repository)
) -> CustomerResponse:
    profile = await _require_customer(customer_id, repo)
    return _serialize_customer(profile)


@router.patch("/{customer_id}", response_model=CustomerResponse)
async def update_customer(
    customer_id: int,
    payload: CustomerUpdate,
    repo: CustomerRepository = Depends(get_repository),
) -> CustomerResponse:
    profile = await _require_customer(customer_id, repo)

    addresses = _build_addresses(payload.addresses) if payload.addresses is not None else None
    await repo.update_customer(
        profile,
        full_name=payload.full_name,
        phone_number=payload.phone_number,
        preferred_language=payload.preferred_language,
        addresses=addresses,
    )
    await repo.session.refresh(profile, attribute_names=["addresses", "segments"])
    return _serialize_customer(profile)


@router.delete("/{customer_id}")
async def delete_customer(
    customer_id: int, repo: CustomerRepository = Depends(get_repository)
) -> Response:
    profile = await _require_customer(customer_id, repo)
    await repo.delete_customer(profile)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{customer_id}/segments", response_model=CustomerSegmentResponse, status_code=status.HTTP_201_CREATED)
async def assign_segment(
    customer_id: int,
    payload: SegmentAssignment,
    repo: CustomerRepository = Depends(get_repository),
) -> CustomerSegmentResponse:
    profile = await _require_customer(customer_id, repo)
    segment = await repo.assign_segment(profile, payload.segment)
    await repo.session.refresh(segment)
    return CustomerSegmentResponse.model_validate(segment, from_attributes=True)


@router.delete("/{customer_id}/segments")
async def clear_segments(
    customer_id: int, repo: CustomerRepository = Depends(get_repository)
) -> Response:
    profile = await _require_customer(customer_id, repo)
    await repo.remove_segments(profile)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

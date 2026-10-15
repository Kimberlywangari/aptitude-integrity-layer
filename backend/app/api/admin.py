"""The recruiter's setup screens: sittings, invitation codes and the question bank.

Every route needs an admin account. Each change is written to the audit log in the same
transaction as the change itself, so there is never an action without its record.
"""

from dataclasses import asdict

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.api.deps import get_clock, require_admin
from app.clock import Clock
from app.db import get_db
from app.errors import ApiError
from app.models import Reviewer
from app.schemas.admin import (
    BankSummaryOut,
    CloseSittingRequest,
    CloseSittingResponse,
    CreateSittingRequest,
    ImportReportOut,
    ImportRequest,
    InviteOut,
    InvitesRequest,
    InvitesResponse,
    RetireResponse,
    SittingCountsOut,
    SittingOut,
    SittingsResponse,
)
from app.services import admin as admin_service
from app.services import question_import
from app.services.staff_auth import record_action

router = APIRouter(prefix="/admin", tags=["admin"])


def _sitting_out(view: admin_service.SittingView) -> SittingOut:
    sitting = view.sitting
    return SittingOut(
        id=sitting.id,
        name=sitting.name,
        opens_at=sitting.opens_at,
        closes_at=sitting.closes_at,
        duration_s=sitting.duration_s,
        question_count=sitting.question_count,
        status=sitting.status,  # type: ignore[arg-type]
        counts=SittingCountsOut(**asdict(view.counts)),
    )


def _refuse_while_a_sitting_is_open(db: Session) -> None:
    """The bank is what open sittings draw from, so it does not change under them."""
    if admin_service.has_open_sitting(db):
        raise ApiError(409, "sitting_open")


# ---------------------------------------------------------------------------------- sittings


@router.get("/sittings", response_model=SittingsResponse)
def list_sittings(
    _: Reviewer = Depends(require_admin), db: Session = Depends(get_db)
) -> SittingsResponse:
    return SittingsResponse(sittings=[_sitting_out(v) for v in admin_service.list_sittings(db)])


@router.post("/sittings", response_model=SittingOut)
def create_sitting(
    body: CreateSittingRequest,
    admin: Reviewer = Depends(require_admin),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> SittingOut:
    sitting = admin_service.create_sitting(
        db,
        name=body.name,
        opens_at=body.opens_at,
        closes_at=body.closes_at,
        duration_s=body.duration_s,
        question_count=body.question_count,
    )
    record_action(db, clock, admin, "admin", f'created sitting "{sitting.name}"')
    view = admin_service.view_of(db, sitting)
    db.commit()
    return _sitting_out(view)


@router.post("/sittings/{sitting_id}/close", response_model=CloseSittingResponse)
def close_sitting(
    sitting_id: int,
    body: CloseSittingRequest | None = None,
    admin: Reviewer = Depends(require_admin),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> CloseSittingResponse:
    force = bool(body and body.force)
    sitting, unfinished = admin_service.close_sitting(db, sitting_id, force=force)
    detail = admin_service.audit_detail_for_close(sitting, unfinished)
    record_action(db, clock, admin, "admin", detail)
    db.commit()
    return CloseSittingResponse(status="closed", forced=unfinished > 0)


# ---------------------------------------------------------------------------------- invitations


@router.post("/invites", response_model=InvitesResponse)
def generate_invites(
    body: InvitesRequest,
    response: Response,
    admin: Reviewer = Depends(require_admin),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> InvitesResponse:
    invites = admin_service.generate_invites(db, body.count)
    record_action(db, clock, admin, "admin", f"generated {len(invites)} invitations")
    db.commit()
    response.headers["Cache-Control"] = "no-store"  # the codes exist in the clear only here
    return InvitesResponse(invites=[InviteOut(candidate_id=c, code=code) for c, code in invites])


# ---------------------------------------------------------------------------------- the bank


@router.get("/questions/summary", response_model=BankSummaryOut)
def questions_summary(
    _: Reviewer = Depends(require_admin), db: Session = Depends(get_db)
) -> BankSummaryOut:
    return BankSummaryOut.model_validate(asdict(admin_service.bank_summary(db)))


@router.post("/questions/import", response_model=ImportReportOut)
def import_questions(
    body: ImportRequest,
    admin: Reviewer = Depends(require_admin),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> ImportReportOut:
    _refuse_while_a_sitting_is_open(db)
    result = question_import.import_summary(db, body.filename, body.summary_csv, body.bank_csv)
    detail = f"imported {result.imported} of {result.rows} questions from {body.filename}"
    if result.rejected:
        detail += f" ({len(result.rejected)} rejected)"
    record_action(db, clock, admin, "admin", detail)
    db.commit()
    return ImportReportOut.model_validate(asdict(result))


@router.post("/questions/retire-synthetic", response_model=RetireResponse)
def retire_synthetic(
    admin: Reviewer = Depends(require_admin),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> RetireResponse:
    _refuse_while_a_sitting_is_open(db)
    removed, kept = admin_service.retire_synthetic(db)
    detail = f"removed {removed} placeholder questions"
    if kept:
        detail += f" ({kept} kept: an earlier session used them)"
    record_action(db, clock, admin, "admin", detail)
    db.commit()
    return RetireResponse(removed=removed, kept=kept)

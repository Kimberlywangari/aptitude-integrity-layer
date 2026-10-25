"""The recruiter's setup screens: sittings, invitation codes and the question bank.

Every route needs an admin account. Each change is written to the audit log in the same
transaction as the change itself, so there is never an action without its record.
"""

from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.deps import get_clock, get_video_store, require_admin
from app.clock import Clock
from app.config import Settings, get_settings
from app.db import get_db
from app.errors import ApiError
from app.models import EmailOutbox, Reviewer, Sitting
from app.schemas.admin import (
    AiCategoryOut,
    AiStatusResponse,
    BankSummaryOut,
    CloseSittingRequest,
    CloseSittingResponse,
    CreateSittingRequest,
    DeleteSittingRequest,
    DeleteSittingResponse,
    EmailTextOut,
    ExtractedTextResponse,
    ImportReportOut,
    ImportRequest,
    InviteListResponse,
    InviteOut,
    InvitesRequest,
    InvitesResponse,
    InviteStatusOut,
    ListProblemOut,
    MailStatusResponse,
    PersonOut,
    PreviewListRequest,
    PreviewListResponse,
    QuestionListResponse,
    QuestionRowOut,
    ResultsPlanResponse,
    RetireResponse,
    RetryPapersResponse,
    SampleRequest,
    SampleResponse,
    SendResultsRequest,
    SendResultsResponse,
    SittingCandidateOut,
    SittingCountsOut,
    SittingDetailResponse,
    SittingOut,
    SittingsResponse,
    TestMailRequest,
)
from app.services import admin as admin_service
from app.services import documents, mail, question_import, results
from app.services.qgen.categories import CATEGORIES, MAX_PER_CATEGORY, MAX_TOTAL
from app.services.qgen.writers import check_available
from app.services.staff_auth import record_action
from app.services.video.store import VideoStore

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
        blueprint=sitting.blueprint,
        question_mode=sitting.question_mode,  # type: ignore[arg-type]
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


@router.get("/sittings/{sitting_id}", response_model=SittingDetailResponse)
def sitting_detail(
    sitting_id: int,
    _: Reviewer = Depends(require_admin),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> SittingDetailResponse:
    """One sitting, with everyone invited to it and where each person is."""
    sitting = db.get(Sitting, sitting_id)
    if sitting is None:
        raise ApiError(404, "sitting_not_found")
    return SittingDetailResponse(
        sitting=_sitting_out(admin_service.view_of(db, sitting)),
        candidates=[
            SittingCandidateOut.model_validate(asdict(c))
            for c in admin_service.sitting_candidates(db, sitting, clock)
        ],
    )


@router.post("/sittings", response_model=SittingOut)
def create_sitting(
    body: CreateSittingRequest,
    admin: Reviewer = Depends(require_admin),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
    settings: Settings = Depends(get_settings),
) -> SittingOut:
    if body.question_mode == "ai":
        # fail now, in front of the admin, rather than later in front of a candidate
        ready, detail = check_available(settings)
        if not ready:
            raise ApiError(503, "question_writer_unavailable", detail=detail)
    sitting = admin_service.create_sitting(
        db,
        name=body.name,
        opens_at=body.opens_at,
        closes_at=body.closes_at,
        question_count=body.question_count,
        per_section=body.per_section,
        question_mode=body.question_mode,
    )
    how = " (questions written by AI)" if sitting.question_mode == "ai" else ""
    record_action(db, clock, admin, "admin", f'created sitting "{sitting.name}"{how}')
    view = admin_service.view_of(db, sitting)
    db.commit()
    return _sitting_out(view)


@router.post("/sittings/{sitting_id}/retry-papers", response_model=RetryPapersResponse)
def retry_papers(
    sitting_id: int,
    admin: Reviewer = Depends(require_admin),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
    settings: Settings = Depends(get_settings),
) -> RetryPapersResponse:
    """Start writing again for the candidates of an AI sitting whose questions failed or have
    been waited for longer than the limit."""
    restarted = admin_service.retry_papers(db, sitting_id, clock, settings.question_wait_limit_s)
    record_action(db, clock, admin, "admin", f"restarted {restarted} unfinished papers")
    db.commit()
    admin_service.launch_papers(db, sitting_id)
    return RetryPapersResponse(restarted=restarted)


@router.post("/sittings/{sitting_id}/delete", response_model=DeleteSittingResponse)
def delete_sitting(
    sitting_id: int,
    body: DeleteSittingRequest,
    admin: Reviewer = Depends(require_admin),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
    store: VideoStore = Depends(get_video_store),
) -> DeleteSittingResponse:
    """Remove a sitting with its candidates, answers, evidence and recordings. Cannot be undone,
    so the sitting's name has to be typed, and one with a test running is refused."""
    sitting = db.get(Sitting, sitting_id)
    name = sitting.name if sitting is not None else ""
    result = admin_service.delete_sitting(db, sitting_id, body.confirm_name, clock)
    record_action(
        db,
        clock,
        admin,
        "admin",
        f'deleted sitting "{name}": {result.sessions} sessions ({result.finished} finished), '
        f"{result.decisions} decision records, {result.candidates} candidates, "
        f"{result.questions} written questions",
    )
    db.commit()
    for session_id in result.session_ids:  # after the commit: no row points at these any more
        store.delete_session(session_id)
    return DeleteSittingResponse(
        sessions=result.sessions, candidates=result.candidates, questions=result.questions
    )


@router.post("/sittings/{sitting_id}/close", response_model=CloseSittingResponse)
def close_sitting(
    sitting_id: int,
    body: CloseSittingRequest | None = None,
    admin: Reviewer = Depends(require_admin),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> CloseSittingResponse:
    force = bool(body and body.force)
    sitting, unfinished = admin_service.close_sitting(db, sitting_id, force=force, clock=clock)
    detail = admin_service.audit_detail_for_close(sitting, unfinished)
    record_action(db, clock, admin, "admin", detail)
    db.commit()
    return CloseSittingResponse(status="closed", forced=unfinished > 0)


# ---------------------------------------------------------------------------------- AI questions


@router.get("/ai-questions/status", response_model=AiStatusResponse)
def ai_status(
    _: Reviewer = Depends(require_admin), settings: Settings = Depends(get_settings)
) -> AiStatusResponse:
    """Which model writes the questions, whether it looks reachable, and the seven categories."""
    ready, detail = check_available(settings)
    return AiStatusResponse(
        provider=settings.question_provider,
        model=settings.question_model,
        available=ready,
        detail=detail,
        max_per_category=MAX_PER_CATEGORY,
        max_total=MAX_TOTAL,
        categories=[
            AiCategoryOut(key=c.key, label=c.label, brief=c.brief) for c in CATEGORIES.values()
        ],
    )


@router.post("/ai-questions/sample", response_model=SampleResponse)
def ai_sample(
    body: SampleRequest,
    _: Reviewer = Depends(require_admin),
    settings: Settings = Depends(get_settings),
) -> SampleResponse:
    """Write one real question, every check included, and show it with its answer. Nothing is
    stored. It takes as long as the model takes, which on a slow computer is minutes."""
    ready, detail = check_available(settings)
    if not ready:
        raise ApiError(503, "question_writer_unavailable", detail=detail)
    result = admin_service.sample_question(
        body.category, admin_service.writer_for(settings), body.difficulty, settings.question_solves
    )
    return SampleResponse.model_validate(asdict(result))


# ---------------------------------------------------------------------------------- invitations


@router.get("/invites", response_model=InviteListResponse)
def list_invites(
    sitting: int | None = None,
    _: Reviewer = Depends(require_admin),
    db: Session = Depends(get_db),
) -> InviteListResponse:
    rows, total = admin_service.list_invites(db, sitting_id=sitting)
    return InviteListResponse(
        invites=[InviteStatusOut.model_validate(asdict(row)) for row in rows], total=total
    )


@router.post("/invites/{candidate_id}/reissue", response_model=InviteOut)
def reissue_invite(
    candidate_id: str,
    response: Response,
    admin: Reviewer = Depends(require_admin),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
    settings: Settings = Depends(get_settings),
) -> InviteOut:
    code = admin_service.reissue_invite(db, candidate_id, clock, settings)
    record_action(db, clock, admin, "admin", f"issued a new code for {candidate_id}")
    db.commit()
    mail.launch_sending(clock)  # a candidate with an email is sent the new invitation
    response.headers["Cache-Control"] = "no-store"  # the code exists in the clear only here
    return InviteOut(candidate_id=candidate_id, code=code)


@router.post("/invites", response_model=InvitesResponse)
def generate_invites(
    body: InvitesRequest,
    response: Response,
    admin: Reviewer = Depends(require_admin),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
    settings: Settings = Depends(get_settings),
) -> InvitesResponse:
    sitting = admin_service.sitting_for_invites(db, body.sitting_id)
    if body.list_text is not None:
        people, problems = admin_service.read_list(db, sitting, body.list_text)
        if problems or not people:  # all or nothing: one bad line creates no one
            raise ApiError(
                422, "list_has_problems", problems=[asdict(p) for p in problems], found=len(people)
            )
        invites = admin_service.generate_invites(db, len(people), sitting, people)
        admin_service.queue_invitations(db, clock, settings, sitting, invites, people)
        out = [
            InviteOut(candidate_id=c, code=code, name=p.name, email=p.email)
            for (c, code), p in zip(invites, people, strict=True)
        ]
    else:
        if body.count is None:
            raise ApiError(422, "invalid_count", min=1, max=admin_service.MAX_INVITES)
        invites = admin_service.generate_invites(db, body.count, sitting)
        out = [InviteOut(candidate_id=c, code=code) for c, code in invites]
    # counts only: the audit log never carries a name or an address
    record_action(
        db, clock, admin, "admin", f'generated {len(invites)} invitations for "{sitting.name}"'
    )
    db.commit()
    if body.list_text is not None:
        mail.launch_sending(clock)
    response.headers["Cache-Control"] = "no-store"  # the codes exist in the clear only here
    return InvitesResponse(invites=out, sitting_id=sitting.id, sitting_name=sitting.name)


@router.post("/invites/preview", response_model=PreviewListResponse)
def preview_list(
    body: PreviewListRequest,
    _: Reviewer = Depends(require_admin),
    db: Session = Depends(get_db),
) -> PreviewListResponse:
    """Read the pasted list and say what is wrong with it, without creating anyone."""
    sitting = admin_service.sitting_for_invites(db, body.sitting_id)
    people, problems = admin_service.read_list(db, sitting, body.list_text)
    return PreviewListResponse(
        people=[PersonOut(line=p.line, name=p.name, email=p.email) for p in people],
        problems=[ListProblemOut.model_validate(asdict(p)) for p in problems],
        sitting_id=sitting.id,
        sitting_name=sitting.name,
    )


# ---------------------------------------------------------------------------------- mail


@router.get("/mail", response_model=MailStatusResponse)
def mail_status(
    _: Reviewer = Depends(require_admin),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> MailStatusResponse:
    counts = dict(
        db.execute(select(EmailOutbox.status, func.count()).group_by(EmailOutbox.status)).all()
    )
    return MailStatusResponse(
        set_up=mail.mail_is_set_up(settings),
        from_address=mail.mask(settings.mail_from) or None,
        queued=counts.get("queued", 0),
        sent=counts.get("sent", 0),
        failed=counts.get("failed", 0),
    )


@router.post("/mail/test")
def send_test_mail(
    body: TestMailRequest,
    admin: Reviewer = Depends(require_admin),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
    settings: Settings = Depends(get_settings),
) -> dict[str, bool]:
    """Send one email now, to the address given, to check the mail settings. Not queued."""
    mailer = mail.get_mailer(settings)
    if mailer is None:
        raise ApiError(409, "mail_not_set_up")
    subject, text = mail.render("test")
    try:
        mailer.send(body.to.strip(), subject, text)
    except mail.MailError as problem:
        raise ApiError(502, "mail_failed", detail=str(problem)) from problem
    record_action(db, clock, admin, "admin", "sent a test email")
    db.commit()
    return {"sent": True}


@router.post("/mail/retry")
def retry_failed_mail(
    admin: Reviewer = Depends(require_admin),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict[str, int]:
    """Give every email that ran out of tries three more, and start sending."""
    count = mail.requeue_failed(db)
    record_action(db, clock, admin, "admin", f"asked for {count} failed emails to be tried again")
    db.commit()
    mail.launch_sending(clock)
    return {"requeued": count}


# ---------------------------------------------------------------------------------- results


def _sitting_or_404(db: Session, sitting_id: int) -> Sitting:
    sitting = db.get(Sitting, sitting_id)
    if sitting is None:
        raise ApiError(404, "sitting_not_found")
    return sitting


@router.get("/sittings/{sitting_id}/results", response_model=ResultsPlanResponse)
def results_plan(
    sitting_id: int,
    _: Reviewer = Depends(require_admin),
    db: Session = Depends(get_db),
) -> ResultsPlanResponse:
    """Who would get which result email if the admin pressed send now, and the wording."""
    plan = results.plan(db, _sitting_or_404(db, sitting_id))
    return ResultsPlanResponse(
        sitting_closed=plan.sitting_closed,
        passed=len(plan.passed),
        not_passed=len(plan.not_passed),
        held_back=plan.held_back,
        sent_passed=plan.sent_passed,
        sent_not_passed=plan.sent_not_passed,
        did_not_finish=plan.did_not_finish,
        without_email=plan.without_email,
        preview_passed=EmailTextOut(**results.preview("passed")),
        preview_not_passed=EmailTextOut(**results.preview("not_passed")),
    )


@router.post("/sittings/{sitting_id}/results/send", response_model=SendResultsResponse)
def send_results(
    sitting_id: int,
    body: SendResultsRequest,
    admin: Reviewer = Depends(require_admin),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> SendResultsResponse:
    sitting = _sitting_or_404(db, sitting_id)
    queued = results.send(db, clock, sitting, body.kind)
    label = "pass" if body.kind == "passed" else "not-passed"
    record_action(db, clock, admin, "admin", f'queued {queued} {label} emails for "{sitting.name}"')
    db.commit()
    mail.launch_sending(clock)
    return SendResultsResponse(queued=queued)


# ---------------------------------------------------------------------------------- documents


@router.post("/extract-text", response_model=ExtractedTextResponse)
async def extract_text(
    request: Request,
    want: Literal["text", "table"] = "text",
    _: Reviewer = Depends(require_admin),
) -> ExtractedTextResponse:
    """The written content of an uploaded file of any common kind (PDF, Word, Excel, slides,
    OpenDocument, RTF, HTML, text), for the invite list and the question import. The file is the
    request body, read once, never stored, and its kind comes from its bytes, not its name."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > documents.MAX_BYTES:
        raise documents.refuse("file_too_large", 413, max_mb=documents.MAX_BYTES // 1_048_576)
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > documents.MAX_BYTES:  # no length given, or a lie: stop reading
            raise documents.refuse("file_too_large", 413, max_mb=documents.MAX_BYTES // 1_048_576)
    found = await run_in_threadpool(documents.extract, bytes(data), want)
    return ExtractedTextResponse(text=found.text, kind=found.kind)


# ---------------------------------------------------------------------------------- the bank


@router.get("/questions", response_model=QuestionListResponse)
def list_questions(
    section: str | None = None,
    limit: int = 100,
    offset: int = 0,
    _: Reviewer = Depends(require_admin),
    db: Session = Depends(get_db),
) -> QuestionListResponse:
    rows, total = admin_service.list_questions(db, section, limit, offset)
    return QuestionListResponse(
        questions=[QuestionRowOut.model_validate(asdict(row)) for row in rows], total=total
    )


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
    detail = f"removed {removed} practice questions"
    if kept:
        detail += f" ({kept} kept: an earlier session used them)"
    record_action(db, clock, admin, "admin", detail)
    db.commit()
    return RetireResponse(removed=removed, kept=kept)

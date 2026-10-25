from sqlalchemy import ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Candidate(Base):
    """A candidate, known everywhere by `id` alone.

    `full_name` and `email` exist for two jobs only: the invitation and result emails, and the
    admin's own list. Nothing else reads them: not packets, not the AI, not the review screens, not
    events, flags or audit text (the tests in test_privacy_of_names.py keep it that way). They are
    deleted with the sitting. Candidates made without them (practice, old invitations) log in with
    the code alone; the others log in with a password they choose (see services/login.py).
    """

    __tablename__ = "candidates"
    __table_args__ = (
        # one invitation per email within a sitting; many sittings may invite the same person
        Index(
            "uq_candidates_sitting_email",
            "sitting_id",
            "email",
            unique=True,
            postgresql_where=text("email is not null"),
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    invite_token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    # The sitting this invitation was made for: its code starts that sitting's paper, whatever
    # else is open. None for invitations made before sittings had their own, which start the
    # newest open sitting.
    sitting_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("sittings.id"), index=True
    )
    full_name: Mapped[str | None] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(254), index=True)  # lower case
    # bcrypt hash of the password the candidate chose at their first sign-in. None until then, and
    # again after an admin sends a new link. Only for a candidate that has an email.
    password_hash: Mapped[str | None] = mapped_column(String(100))

"""Helpers shared by the recording, packet and ranking tests: a candidate who drives the HTTP API,
and tiny WebM files built byte by byte so no ffmpeg is needed to test the chunk pipeline."""

import hashlib

from app.models import Question, SessionQuestion, TestSession

# ------------------------------------------------------------------------------- tiny WebM


def _id_bytes(element_id: int) -> bytes:
    return element_id.to_bytes((element_id.bit_length() + 7) // 8, "big")


def _size_bytes(size: int) -> bytes:
    for length in range(1, 9):
        if size < (1 << (7 * length)) - 1:
            return ((1 << (7 * length)) | size).to_bytes(length, "big")
    raise ValueError("too large")


def element(element_id: int, body: bytes) -> bytes:
    return _id_bytes(element_id) + _size_bytes(len(body)) + body


UNKNOWN_SIZE = b"\x01\xff\xff\xff\xff\xff\xff\xff"


def track_entry(kind: int) -> bytes:
    return element(0xAE, element(0xD7, b"\x01") + element(0x83, bytes([kind])))


def webm_header(*, video: bool = True, audio: bool = True, unknown_segment: bool = True) -> bytes:
    """What a browser recorder's first chunk starts with: the EBML header, a Segment, Info,
    Tracks and the first Cluster."""
    ebml = element(0x1A45DFA3, element(0x4282, b"webm"))
    tracks = b"".join(track_entry(kind) for kind, on in ((1, video), (2, audio)) if on)
    body = element(0x1549A966, element(0x2AD7B1, b"\x0f\x42\x40"))  # Info: timestamp scale
    body += element(0x1654AE6B, tracks)
    body += element(0x1F43B675, element(0xE7, b"\x00"))  # first Cluster
    segment_id = _id_bytes(0x18538067)
    if unknown_segment:
        return ebml + segment_id + UNKNOWN_SIZE + body
    return ebml + segment_id + _size_bytes(len(body)) + body


def media_chunk(seed: int, size: int = 400) -> bytes:
    """A later chunk: cluster data only, no container header."""
    filler = hashlib.sha256(str(seed).encode()).digest() * (size // 32 + 1)
    return element(0x1F43B675, element(0xE7, b"\x00") + filler[:size])


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --------------------------------------------------------------------------------- a candidate


class Live:
    """One candidate driving the real HTTP API with a fake clock."""

    def __init__(self, client, db, invite_token: str) -> None:
        self.client = client
        self.db = db
        self.invite_token = invite_token
        self.session_id = ""
        self.headers: dict[str, str] = {}

    def start(self) -> "Live":
        response = self.client.post("/api/session/start", json={"token": self.invite_token})
        assert response.status_code == 200, response.text
        body = response.json()
        self.session_id = body["session_id"]
        self.headers = {"Authorization": f"Bearer {body['access_token']}"}
        return self

    def url(self, tail: str) -> str:
        return f"/api/session/{self.session_id}/{tail}"

    def begin(self):
        return self.client.post(self.url("begin"), json={"accepted": True}, headers=self.headers)

    def question(self):
        return self.client.get(self.url("question"), headers=self.headers)

    def finish(self, chunks_total: int | None = None):
        body = None if chunks_total is None else {"chunks_total": chunks_total}
        return self.client.post(self.url("finish"), json=body, headers=self.headers)

    def precheck(self, **overrides):
        body = {
            "camera_ok": True,
            "mic_ok": True,
            "notifications_off_confirmed": True,
            "fullscreen_ok": True,
            "browser": {"name": "Chrome", "version": "141"},
            "device_labels": {"camera": "Integrated Webcam", "mic": "Microphone Array"},
            "mic_peak": 0.2,
            "video_size": {"width": 320, "height": 240},
        }
        body.update(overrides)
        return self.client.post("/api/precheck/result", json=body, headers=self.headers)

    def events(self, *events, headers=None):
        return self.client.post(
            "/api/events", json={"events": list(events)}, headers=headers or self.headers
        )

    def heartbeat(self):
        return self.client.post("/api/heartbeat", headers=self.headers)

    def put_chunk(
        self, seq: int, data: bytes, *, segment: int = 0, digest: str | None = None, headers=None
    ):
        send = dict(headers or self.headers)
        send["X-Chunk-SHA256"] = digest if digest is not None else sha(data)
        send["X-Chunk-Segment"] = str(segment)
        return self.client.put(
            f"/api/chunks/{self.session_id}/{seq}",
            content=data,
            headers={**send, "Content-Type": "application/octet-stream"},
        )

    def manifest(self, headers=None):
        return self.client.get(
            f"/api/chunks/{self.session_id}/manifest", headers=headers or self.headers
        )

    def session(self) -> TestSession:
        self.db.expire_all()
        return self.db.get(TestSession, self.session_id)

    def answer_one(self, clock, position: int, seconds: float = 20.0) -> bool:
        """Answer question `position` correctly after `seconds`. True once the test is over."""
        row = self.db.get(SessionQuestion, (self.session_id, position))
        question = self.db.get(Question, row.question_id)
        option_id = next(o.id for o in question.options if o.label == question.correct_option)
        clock.advance(seconds)
        return self.client.post(
            self.url("answer"),
            json={"position": position, "option_id": option_id},
            headers=self.headers,
        ).json()["done"]

    def answer_everything(self, clock, seconds_each: float = 20.0) -> None:
        """Answer every question correctly, `seconds_each` apart."""
        while True:
            response = self.question()
            if response.status_code != 200:
                return
            if self.answer_one(clock, response.json()["position"], seconds_each):
                return


# ---------------------------------------------------------------------------------- packets


def sample_packet() -> dict:
    """A small evidence packet of the shape the packet builder produces, for tests of the fact
    checker, the prompts and the adapters, none of which need a database."""
    from app.services.packets import build_facts

    flags = [
        {
            "id": "F1",
            "kind": "COPY_ATTEMPT",
            "server_ts": "2026-10-28T09:05:10Z",
            "elapsed_s": 310,
            "question_number": 9,
            "detail": {"target": "question_text", "length": 212},
        },
        {
            "id": "F2",
            "kind": "LONG_HOLD_CORRECT",
            "server_ts": "2026-10-28T09:18:45Z",
            "elapsed_s": 1125,
            "question_number": 22,
            "detail": {"time_s": 212, "own_median_s": 38, "focus_lost_s": 90},
        },
    ]
    packet = {
        "candidate_id": "cand-007",
        "flags": flags,
        "questions": [
            {"number": 9, "section": "numerical", "difficulty": "hard"},
            {"number": 22, "section": "logical", "difficulty": "medium"},
        ],
        "vs_sitting": {"pace_percentile": 8, "spread_percentile": 3, "score_percentile": 91},
        "score": 8,
        "pace_s_per_q": 21,
        "fullscreen_exits": [],
        "precheck": {
            "notifications_off_confirmed": True,
            "fullscreen_ok": True,
            "browser": "Chrome 141",
        },
        "innocent_signals": [{"id": "I1", "kind": "reload", "elapsed_s": 400}],
        "mic_silence": [
            {"id": "M1", "start_s": 600, "end_s": 700, "duration_s": 100, "layers": ["browser"]}
        ],
        "video_anchor": "2026-10-28T09:00:00+00:00",
    }
    packet["facts"] = build_facts(packet)
    return packet


def good_assessment(packet: dict, **overrides) -> dict:
    """An assessment that passes the fact check against `packet`."""
    answer = {
        "candidate_id": packet["candidate_id"],
        "flags_support_each_other": "partly",
        "innocent_explanation": {"present": True, "evidence_ids": ["I1"]},
        "strength": 3,
        "explanation": (
            "F1 is a copy attempt on Q9 and F2 is a 212 s hold on Q22. "
            "A reload at 400 s may matter."
        ),
        "cited": {
            "flag_ids": ["F1", "F2"],
            "question_numbers": [9, 22],
            "times_s": [212, 38],
            "counts": {"flags": 2},
        },
    }
    answer.update(overrides)
    return answer

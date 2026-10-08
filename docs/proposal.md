Proposal
Aptitude Test Integrity Layer for the Cytonn Recruitment Process

Prepared by: Kimberly Njoroge, Software and AI Engineering Intern
To be approved by: Douglas Mburu, Senior Software Engineer, Cytonn

The Full Solution

Securing the session

•  Safe Exam Browser locks the test screen. The server accepts answers only from a veriﬁed Safe Exam Browser session and

rejects the rest. Copying, pasting and screenshots are blocked, and every blocked attempt is logged.

•  Candidate device requirement: the test must be taken on a Windows or Mac computer or an iPad with a working webcam

and microphone. Safe Exam Browser does not run on Android phones or Chromebooks, so candidates using them cannot sit
the test. This is shown to candidates before they register.

•  Webcam and microphone are recorded for every candidate. The test does not start until the camera and microphone work,

and the candidate may retry within the session. If the camera drops mid-test or the upload is incomplete, the event is
logged and the candidate may ﬁle a complaint, which a person reviews. These cases do not disqualify.

•  Video is recorded at low resolution in short chunks, about 80 MB an hour, saved on the device ﬁrst, then uploaded in order
with retries, resuming for up to 48 hours after the test. Candidates are told the expected data use and advised to use Wi-Fi.
•  Answer options shuffled per candidate, an integrity statement before the test, and a self-report question on technical issues

afterwards.

Fair papers

•  Each paper is drawn to a blueprint: the recruiter's chosen number of questions per section, spread across easy, medium and
hard using Cytonn's difficulty tags or past success rates. Papers stay different for every candidate but become comparable,
which also makes timing checks fair.(if time allows)

What is logged and ﬂagged.

•  Action-level logging (not keylogging) of answers, skips, focus loss and return, copy attempts on question text (length only,
never the text) and idle time. Events are timestamped by the server, and a heartbeat every 10 seconds reveals if logging is
blocked, which is ﬂagged as a logging problem. Because candidates cannot go back, time per question is exact. Dropped
connections and page reloads are shown to the reviewer as context, not ﬂagged.

•  Flags for focus loss, copy attempts, a question held open far longer than the candidate's own typical time and then

answered correctly (stronger if the window lost focus during it), and runs of correct answers straight after a focus loss or a
long gap with no activity. A lone focus loss counts for little on its own.

•  Compared with the same sitting only, and only above a minimum group size of about 8, after the sitting closes: overall pace

(average time per question) and the spread of answer times, such as nearly every answer in the same narrow band, that sit far
from the typical in either direction.

•  Using the per-question summary from past sittings: answers correct far faster than a question's usual time, especially on

hard questions.

Making sense of the ﬂags

•  For every ﬂagged candidate, all their ﬂags are bundled into one evidence packet: the ﬂags with timestamps and question

numbers, question details (section, and difficulty where known), how the candidate compares with their sitting, the
candidate's score and overall pace, and anything that could explain the ﬂags innocently, such as a dropped connection, a
page reload or the candidate's own self-report. Score and pace are shown as context only and are never ﬂagged on their
own, because strong candidates are often both fast and accurate. The packet uses the candidate ID, never the name.

•  A local AI model, running on Ollama, assesses each packet: whether the ﬂags support each other, whether the logs offer an

innocent explanation, and how strong the overall picture is. It ranks the ﬂagged candidates and writes a short explanation as
strict JSON. A fact check rejects any ﬂag, question number, time or count that is not in the packet, and after one retry that
candidate falls back to rule-based order, so no one is lost.

•  Simple rules rank the ﬂagged candidates, both before the AI step is built and whenever it fails. The rules count how many
different kinds of ﬂag a candidate has and how close together they are in time, and weight copy attempts, and a question
held open far longer than the candidate's own typical time and then answered correctly, above a lone focus loss. The AI only
ranks and explains. It never gives a verdict, does not disqualify anyone, sets no score threshold and does not set anyone
aside, so every ﬂagged candidate still reaches a reviewer.

•  The AI sits behind one interface, so it can switch from local Ollama models to the Claude API if Cytonn pays for it later. The

system is built with FastAPI, PostgreSQL, React and Docker.

Review

•  A reviewer queue ordered by rank, where each ﬂag links to the moment in the candidate's video, starting 5 seconds before it.
Video review covers ﬂagged moments and the shortlisted candidates. Every decision needs a written reason, every decision
and video view is logged, and videos are deleted 30 days after the review decision.

Not part of this layer

•  Automated analysis of faces, voices, expressions or mouse movement, keylogging, answer-similarity comparison between

candidates, and watermarking of question screens. (Out of scope for now)

•  Automatic rejection, identity veriﬁcation against the ID copy, per-question timers, changes to the test format, and any link

into Cytonn's recruitment system. (Out of scope for now)

•  Verifying every request, including heartbeats and video chunks; testing on a Mac and an iPad (only Windows is tested in this

build); and a check for questions whose success rate jumps, which would suggest a leak. (Out of scope for now)

Every ﬂag is evidence for a human reviewer, never an automatic rejection. Only two outcomes are automatic: the test does not
start until the camera and microphone work, and requests not sent from a veriﬁed Safe Exam Browser session are rejected. The
cash cost is close to zero: the tools are free, the AI runs locally, and video storage is under Ksh 5 per candidate before deletion.
Known limits remain: a candidate photographing the screen with a phone, a second device or person kept out of frame, help
through a hidden earpiece, steady low-level cheating that avoids timing outliers, and questions memorised and shared after the
test. These are reduced, not eliminated.

How We Will Know It Works
Measured in a pilot sitting at the end of week 3 with 12 to 16 volunteers, at least 8 honest and 6 following scripted cheating. With
a group this small the rates are indicative, not proof. A criterion that depends on an "If time allows" item applies only if that item
is built.

Criterion

How it is tested

Rule-based checks catch scripted actions

Scripted tests, one run inside real Safe Exam Browser, OBS
virtual camera, a muted microphone

Honest volunteers wrongly ﬂagged

Pilot, plus a synthetic honest cohort

Planted cheating caught

Planted cheaters ranked in the top third

Pilot

Pilot

Target

100%

At most 1 in 10

At least 8 in 10

At least 8 in 10

Flag lands near the moment in the video

An observer logs the real time of 5 or 6 planted actions

Within 2 seconds

AI explanations match the logs

Automatic fact check, then checked by hand

100%

No video chunks lost after upload

Simulated drops, and two volunteers offline for 2 minutes

Zero missing

Papers match the blueprint

Validator

Deletion works

Test with backdated decisions

AI step runs on the available laptop

Timed in the pilot

500 of 500 generated papers

Video gone 30 days after the
decision

Under 2 minutes per ﬂagged
candidate (proposed)

What I Will Need From Cytonn

•  Douglas to set up Safe Exam Browser on Cytonn's side once it works locally.
•  A per-question summary from past sittings, with no candidate-level data: question ID, section, correct option, difficulty tag,

number of candidates, percentage correct, and median and 25th and 75th percentile times. If that is not possible, the
question bank export and the stored record of my own test sittings.

•  The typical number of candidates in a sitting, and the result format the recruitment pipeline expects.
•  Agreement to blueprint-based papers, and acceptance of the device requirement and of who it excludes.
•  Volunteers for the pilot.
•  Sign-off for production use: a data protection impact assessment, consent wording, storage location and the 30-day

retention period. These do not block the volunteer pilot.

What I Will Do In The Next 3 Weeks

•  • Week 1 (8 to 14 October): scaffold and synthetic seed data; test recording and local storage inside Safe Exam Browser (day

2); test ﬂow with the server timer; action logger and heartbeat; rule-based ﬂags with scripted tests.

•  • Week 2 (15 to 21 October): pre-check page; recording and resilient upload; question data ingested, or the synthetic fallback

conﬁrmed; evidence packets and rule-based ranking; cohort checks. If time allows: the blueprint paper generator.

•  • Week 3 (22 to 28 October): per-question check; Ollama ranking with fact check; reviewer queue with video at ﬂagged

moments; 30-day deletion; pilot and measurement.

•  • Week 4, day 1 (29 October): handover walkthrough with Douglas, then integration questions and bug ﬁxes only.

Signature

Kimberly Njoroge
Software and AI Engineering Intern, Vunoh
Prepared by
Date: _______________

Signature

Douglas Mburu
Senior Software Engineer, Cytonn
To be reviewed by
Date: _______________


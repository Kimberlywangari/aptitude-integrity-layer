# Setting up email (invitations and results)

The system sends three kinds of email: the invitation, the "you passed" email and the "you did not
pass" email. It sends them through a mailbox you give it (SMTP). Until you do, nothing is sent: emails
wait in a queue and the admin page says "Mail is not set up yet".

You do this once, in `.env` (the file at the top of the project; it is never committed). Five values:

```
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=you@gmail.com
SMTP_PASSWORD=<an app password, not your normal password>
MAIL_FROM=you@gmail.com
```

`MAIL_FROM_NAME` (default "Cytonn Aptitude Test") is the name candidates see beside the address.
After editing `.env`, restart the API (see the end of this page). The Invitations page then shows a
"Send a test email" box: send one to yourself before you invite anyone.

## Option A: a personal Gmail account (the quickest)

1. Turn on 2-Step Verification for the Google account (myaccount.google.com, Security).
2. Still under Security, search for **App passwords**. Make one called "aptitude". Google shows a
   16-character password once. That is `SMTP_PASSWORD` (type it without spaces).
3. Fill in the five values above with `smtp.gmail.com`, port `587`, and the Gmail address twice.
4. Limits: a personal Gmail may send about 500 emails a day. Fine for a pilot, too small for a big
   sitting. Candidates will see your Gmail address as the sender.

## Option B: a work Microsoft 365 mailbox (your company's own domain, and so on)

Host `smtp.office365.com`, port `587`, the full mailbox address as user and sender. Many companies
switch "SMTP AUTH" off, and then every attempt fails with an authentication error. Ask the IT
administrator to enable **Authenticated SMTP** for that one mailbox (Microsoft 365 admin centre, the
mailbox's Mail apps), and to say if the account needs an app password because of multi-factor sign-in.
If they will not, use Option A for the pilot.

## When you move to Cytonn's own mail

Change the same five values to what Cytonn's IT gives you (their SMTP host, port, a service account
and the address that account may send as). Nothing else in the project changes. Restart the API. Use
"Send a test email" again. A mailbox that is only for this system, with a name such as
`aptitude@cytonn.com`, is better than a person's own.

## Where the settings go

- On this laptop: `.env` in the project folder.
- In Docker on a server (`docker-compose.prod.yml`): the same names in the server's `.env`. The compose
  file passes them to the API and the worker.

## If something does not work

| What the page says | Usual cause |
|--------------------|-------------|
| "Mail is not set up yet" | `SMTP_HOST` or `MAIL_FROM` is empty, or the API was not restarted |
| Test email: "535 ... not accepted" | Wrong password, or Gmail without an app password, or Microsoft SMTP AUTH off |
| Test email: "Connection refused" or "timed out" | Wrong host or port, or a firewall blocks port 587 |
| Emails "Waiting to send" for a long time | Mail is not set up, or the server is slow; they go out in a minute once it works |
| "N emails could not be sent" | Three tries failed. Fix the cause, then press **Try them again** |
| Emails arrive in spam | Normal for a personal account sending many at once. Ask candidates to check spam; a company mailbox is better |

An email cannot be taken back once sent, so the result emails ask you to confirm first, and each
person is sent at most one invitation, one pass email or one not-passed email.

## Who sees what

Names and email addresses are stored only to send these emails and to show the admin who was invited.
Reviewers and the AI only ever see the candidate ID (`cand-007`). The wording of the three emails is
in `backend/app/mail_templates/` (`invite.txt`, `passed.txt`, `not_passed.txt`); edit the text there.
The emails never mention flags, video, review or AI.

## Restarting after a change (Windows, this laptop)

Stop the API (the window running uvicorn) and start it again, or ask Claude to restart it. In Docker:
`docker compose up -d --build`.

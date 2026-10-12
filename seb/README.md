# Safe Exam Browser: config and key verification

This folder holds what is needed to launch the test inside SEB. Real config files (`*.seb`) are
git-ignored because they can contain keys and passwords.

## Making the config (D1 step 9, D2 step 3)

1. Open **SEB Config Tool** (installed with SEB 3.10.2).
2. Set **Start URL** to the page you want to test:
   - D2 spike: `http://localhost:5173/spike/index.html`
   - D3 onwards: `http://localhost:5173/`
3. Set **Quit URL** to `http://localhost:5173/spike/quit.html` (for the spike's check 10).
4. Turn on camera and microphone capture, turn off clipboard use, turn off Print Screen, and
   turn on "send Browser Exam Key / Config Key in the HTTP headers".
5. Save as `seb/exam.seb` and open that file (double-click, or `SafeExamBrowser.exe` with the
   file path).

Label names differ between SEB versions, so match by meaning. They are usually under the tabs
**General** (Start URL), **Browser** (camera, microphone, clipboard), **Exam** (Browser Exam Key,
header option, Quit URL), **Security** (Print Screen, clipboard) and **Hooked Keys**.

Record in `docs/spikes/seb-findings.md` exactly which option you changed and what it did.

## How the server verifies a request

SEB adds a header to every request it makes:

| Header | Meaning |
|---|---|
| `X-SafeExamBrowser-RequestHash` | SHA-256 of (absolute request URL + **Browser Exam Key**) |
| `X-SafeExamBrowser-ConfigKeyHash` | SHA-256 of (absolute request URL + **Config Key**) |

`backend/app/core/seb.py` rebuilds the URL as `PUBLIC_BASE_URL + path + query`, hashes it with
each key in `SEB_ALLOWED_KEYS`, and accepts the request if either header matches. Consequences:

- `PUBLIC_BASE_URL` must be exactly what the browser's address bar shows (scheme, host, port).
  Behind a proxy the proxy must keep the path and query unchanged.
- The **Browser Exam Key** changes whenever the config file or the SEB version changes; the
  **Config Key** changes only with the config. Which one to rely on is decided by the D2 spike
  and written in `docs/spikes/seb-findings.md`.
- Anyone who holds a key can forge the header. The check proves "this request came from a
  browser started with our config", not more. That is listed as a known limit.

`SEB_MODE` in `.env`: `off` (never blocks), `log` (never blocks, logs mismatches), `enforce`
(403 `seb_required`). Use `log` first, once the keys are in `SEB_ALLOWED_KEYS`.

## Finding the keys

Three ways, use whichever works and write down which one:

1. Config Tool, **Exam** tab: shows the Browser Exam Key and, after saving, the Config Key.
2. Spike page: the "SafeExamBrowser JS API" lines show `configKey` and `browserExamKey` as SEB
   computes them for that page URL.
3. Spike page: paste a candidate key into "extra key to test" and press **Ping**. The echo route
   says which header (if any) it reproduces for the exact URL the server rebuilt. This is the
   proof that matters.

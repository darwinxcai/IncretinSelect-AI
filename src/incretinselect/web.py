"""Dependency-free local web interface for IncretinSelect-AI."""

from __future__ import annotations

import argparse
import html
import json
import sys
import threading
import urllib.parse
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Sequence

from incretinselect.cli import EXAMPLE_SEQUENCE
from incretinselect.product import ProductError, model_info, predict

MAX_REQUEST_BYTES = 16_384

STYLE = """
:root { color-scheme: light; --ink:#10211a; --muted:#52635b; --line:#d7e2dc;
  --leaf:#276b4c; --pale:#eff7f2; --warn:#fff2cf; --danger:#a53b2b;
  --danger-pale:#fff2ef; }
* { box-sizing:border-box; }
body { margin:0; font-family:Inter,ui-sans-serif,system-ui,-apple-system,sans-serif;
  color:var(--ink); background:linear-gradient(145deg,#f5faf6,#eaf3ef); }
main { width:min(980px,calc(100% - 32px)); margin:38px auto 64px; }
.hero { background:#123b2b; color:white; padding:34px; border-radius:22px;
  box-shadow:0 18px 42px #173b2b21; }
.eyebrow { letter-spacing:.12em; text-transform:uppercase; font-size:.75rem; opacity:.72; }
h1 { margin:.45rem 0 .7rem; font-size:clamp(2rem,5vw,3.4rem); line-height:1; }
.hero p { max-width:760px; line-height:1.55; color:#d9ebe1; }
.warning { margin-top:18px; padding:13px 16px; background:var(--warn); color:#533e08;
  border-left:5px solid #d7a81b; border-radius:10px; line-height:1.45; }
.panel { margin-top:20px; padding:26px; background:#fff; border:1px solid var(--line);
  border-radius:18px; box-shadow:0 12px 30px #284d3d10; }
label { display:block; font-weight:750; margin-bottom:9px; }
textarea { width:100%; min-height:88px; resize:vertical; padding:15px; border:2px solid #b8cbc1;
  border-radius:12px; font:600 1rem/1.5 ui-monospace,SFMono-Regular,Consolas,monospace;
  letter-spacing:.035em; }
textarea:focus { outline:3px solid #b9e0ca; border-color:var(--leaf); }
.hint { margin:8px 0 0; color:var(--muted); font-size:.9rem; line-height:1.45; }
button { margin-top:16px; border:0; border-radius:11px; padding:12px 19px; background:var(--leaf);
  color:white; font-weight:750; font-size:1rem; cursor:pointer; }
button:hover { background:#1f583e; }
.error { border-color:#efb7ad; background:#fff5f3; color:var(--danger); }
.grid { display:grid; grid-template-columns:repeat(3,1fr); gap:14px; margin-top:16px; }
.card { border:1px solid var(--line); border-radius:14px; padding:19px; background:var(--pale); }
.card h3 { margin:0 0 8px; font-size:.95rem; color:var(--muted); }
.value { font-size:1.65rem; font-weight:800; color:#184c37; }
.sub { margin-top:5px; color:var(--muted); font-size:.86rem; line-height:1.35; }
.sequence { overflow-wrap:anywhere; padding:11px; border-radius:9px; background:#f3f5f4;
  font:600 .92rem ui-monospace,SFMono-Regular,Consolas,monospace; }
.tier { display:inline-block; border-radius:99px; padding:5px 10px; background:#dcefe3;
  color:#1b563b; font-size:.82rem; font-weight:800; }
.tier-caution { background:#fff0c2; color:#735500; }
.tier-danger { background:#f9d7d1; color:#7c291d; }
.stop { margin-top:18px; padding:17px 18px; background:var(--danger-pale); color:#721f15;
  border:2px solid #d97262; border-left-width:7px; border-radius:12px; line-height:1.48; }
.stop strong { display:block; font-size:1.08rem; }
.stop ul { margin-bottom:0; }
h2 { margin:0 0 9px; }
ul { padding-left:1.25rem; }
li { margin:.52rem 0; line-height:1.45; }
.fine { color:var(--muted); font-size:.84rem; line-height:1.5; }
code { background:#edf2ef; border-radius:5px; padding:.1rem .32rem; }
@media (max-width:720px) { .grid { grid-template-columns:1fr; } .hero,.panel { padding:20px; } }
"""


def _fmt(value: float) -> str:
    if value >= 10000 or value < 0.001:
        return f"{value:.3e}"
    return f"{value:.3f}".rstrip("0").rstrip(".")


def _result_html(result: dict[str, Any]) -> str:
    p = result["predictions"]
    app = result["applicability"]
    model = result["model"]
    warnings = "".join(f"<li>{html.escape(item)}</li>" for item in result["warnings"])
    nearest = ", ".join(app["nearest_reference_ids"])
    residue_count = int(result["input"]["standard_residue_count"])
    ranking_supported = app["tier"] == "close_analogue" and residue_count >= 26
    if app["tier"] == "close_analogue":
        tier_class = "tier"
    elif app["tier"] == "distant_analogue":
        tier_class = "tier tier-caution"
    else:
        tier_class = "tier tier-danger"

    stop_reasons: list[str] = []
    if app["tier"] != "close_analogue":
        stop_reasons.append(str(app["summary"]))
    if residue_count < 26:
        stop_reasons.append(
            "The sequence contains fewer than 26 standard residues, below the modeled "
            "30-column core length range."
        )
    stop_html = ""
    if not ranking_supported:
        reason_items = "".join(
            f"<li>{html.escape(reason)}</li>" for reason in stop_reasons
        )
        stop_html = f"""
      <div class="stop" role="alert" data-ranking-supported="false">
        <strong>Do not use this output to rank experiments.</strong>
        <ul>{reason_items}</ul>
        <p>Treat the numbers as an out-of-scope model calculation, not as decision evidence.</p>
      </div>"""
    return f"""
    <section class="panel" aria-live="polite">
      <h2>Sequence-only functional-potency estimate</h2>
      <div class="sequence">{html.escape(result['input']['aligned_sequence'])}</div>
      <div class="grid">
        <article class="card"><h3>GLP-1R cAMP EC50</h3>
          <div class="value">{_fmt(p['glp1r']['ec50_pm'])} pM</div>
          <div class="sub">{_fmt(p['glp1r']['ec50_nm'])} nM · log10(pM) {p['glp1r']['log10_ec50_pm']:.4f}</div>
        </article>
        <article class="card"><h3>GCGR cAMP EC50</h3>
          <div class="value">{_fmt(p['gcgr']['ec50_pm'])} pM</div>
          <div class="sub">{_fmt(p['gcgr']['ec50_nm'])} nM · log10(pM) {p['gcgr']['log10_ec50_pm']:.4f}</div>
        </article>
        <article class="card"><h3>EC50 balance: GCGR / GLP-1R</h3>
          <div class="value">{_fmt(p['selectivity']['ec50_fold_ratio'])}-fold</div>
          <div class="sub">{html.escape(p['selectivity']['interpretation'])}</div>
        </article>
      </div>
      <div class="warning"><strong>How to read EC50:</strong> lower predicted EC50 means greater
        functional potency in this cell assay. It does not mean tighter binding or greater efficacy.</div>
    </section>
    <section class="panel">
      <h2>Applicability assessment</h2>
      <p><span class="{tier_class}">{html.escape(app['tier'])}</span></p>
      <p><strong>Nearest aligned identity:</strong> {app['nearest_aligned_identity'] * 100:.1f}%
         ({html.escape(nearest)})</p>
      <p>{html.escape(app['summary'])}</p>
      <p class="fine">{html.escape(app['threshold_note'])}</p>
      {stop_html}
    </section>
    <section class="panel">
      <h2>Scientific limitations</h2><ul>{warnings}</ul>
      <p class="fine">Model {html.escape(model['artifact_id'])} v{html.escape(model['artifact_version'])}<br>
      Artifact SHA-256: <code>{html.escape(model['artifact_sha256'])}</code></p>
    </section>
    """


def render_page(sequence: str = EXAMPLE_SEQUENCE, result: dict[str, Any] | None = None, error: str = "") -> str:
    """Render the complete offline page; exposed for deterministic smoke tests."""

    detail = _result_html(result) if result is not None else ""
    error_html = (
        f'<section class="panel error"><strong>Input rejected:</strong> {html.escape(error)}</section>'
        if error
        else ""
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>IncretinSelect-AI</title><style>{STYLE}</style></head>
<body><main>
  <header class="hero"><div class="eyebrow">Local · frozen model · research only</div>
    <h1>IncretinSelect-AI</h1>
    <p>Estimate GLP-1R and GCGR functional potency for an incretin-like peptide sequence
       in the modeled cell-based cAMP assay. This tool supports early hypothesis triage;
       it does not establish binding, efficacy, safety, or clinical activity.</p>
  </header>
  <div class="warning"><strong>Required input:</strong> one already-aligned 30-position core.
    Use the 20 standard amino-acid letters and <code>-</code> for an alignment gap. The app
    deliberately does not guess alignments, trim tails, or encode chemical modifications.</div>
  <section class="panel"><form method="post" action="/predict">
    <label for="sequence">30-column aligned peptide sequence</label>
    <textarea id="sequence" name="sequence" required maxlength="256" spellcheck="false">{html.escape(sequence)}</textarea>
    <p class="hint">Whitespace and lowercase are normalized. FASTA headers, wrong lengths,
      ambiguous residues, Aib, lipidation, and other noncanonical chemistry are rejected.</p>
    <button type="submit">Generate research estimate</button>
  </form></section>
  {error_html}{detail}
  <section class="panel"><h2>Validation context</h2>
    <p>The software converts a compatible aligned sequence into reproducible point estimates
      for hypothesis generation. Development error was approximately 4.2-fold for GCGR,
      11.7-fold for GLP-1R, and 13.7-fold for balance. These are dataset-level summaries,
      not confidence intervals for an individual sequence. Results on the separate
      15-peptide evaluation set were mixed.</p>
    <p class="fine">Runs entirely on this computer. No sequence is sent to an external service.</p>
  </section>
</main></body></html>"""


class ProductHandler(BaseHTTPRequestHandler):
    server_version = "IncretinSelectLocal/1.0"

    def _send(self, content: str, status: HTTPStatus = HTTPStatus.OK, content_type: str = "text/html; charset=utf-8") -> None:
        body = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; "
            "base-uri 'none'; frame-ancestors 'none'",
        )
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = urllib.parse.urlsplit(self.path).path
        if path == "/":
            self._send(render_page())
        elif path == "/healthz":
            info = model_info()
            self._send(
                json.dumps({"status": "ok", "artifact_sha256": info["artifact_sha256"]}) + "\n",
                content_type="application/json; charset=utf-8",
            )
        else:
            self._send("Not found\n", HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8")

    def do_POST(self) -> None:  # noqa: N802
        if urllib.parse.urlsplit(self.path).path != "/predict":
            self._send("Not found\n", HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_REQUEST_BYTES:
            self._send(
                render_page(error="Request is empty or too large."),
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            )
            return
        try:
            body = self.rfile.read(length).decode("utf-8", errors="strict")
            fields = urllib.parse.parse_qs(body, keep_blank_values=True, strict_parsing=False)
        except (UnicodeDecodeError, ValueError):
            self._send(
                render_page(error="Request body is not valid UTF-8 form data."),
                HTTPStatus.BAD_REQUEST,
            )
            return
        sequence = fields.get("sequence", [""])[0]
        try:
            result = predict(sequence)
        except ProductError as exc:
            self._send(render_page(sequence=sequence, error=str(exc)), HTTPStatus.BAD_REQUEST)
            return
        self._send(render_page(sequence=result["input"]["aligned_sequence"], result=result))

    def log_message(self, format: str, *args: object) -> None:
        print(f"[{self.log_date_time_string()}] {format % args}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="incretin-web",
        description="Run the dependency-free IncretinSelect web app on this computer.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1).")
    parser.add_argument("--port", type=int, default=8000, help="TCP port (default: 8000).")
    parser.add_argument("--open", action="store_true", help="Open the app in the default browser.")
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Load the model, render an example, and exit without starting a server.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.smoke_test:
        result = predict(EXAMPLE_SEQUENCE)
        page = render_page(result=result)
        if (
            "Sequence-only functional-potency estimate" not in page
            or result["model"]["artifact_id"] not in page
        ):
            raise RuntimeError("Web smoke test failed")
        print(
            f"ok: rendered {len(page)} bytes with "
            f"{result['model']['artifact_id']} v{result['model']['artifact_version']}"
        )
        return 0
    if not 0 <= args.port <= 65535:
        raise SystemExit("port must be between 0 and 65535")
    if args.host not in {"127.0.0.1", "localhost"}:
        raise SystemExit(
            "v1 intentionally permits only --host 127.0.0.1 or localhost; "
            "the app has no authentication and must not be exposed to a network"
        )
    model_info()  # fail before opening a listening socket if the artifact is invalid
    try:
        server = ThreadingHTTPServer((args.host, args.port), ProductHandler)
    except OSError as exc:
        suggested_port = 8001 if args.port != 8001 else 8002
        print(
            f"error: could not start the local app on {args.host}:{args.port}: {exc}. "
            f"The port may already be in use; try --port {suggested_port}.",
            file=sys.stderr,
        )
        return 2
    host, port = server.server_address[:2]
    url_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else str(host)
    url = f"http://{url_host}:{port}/"
    print(f"IncretinSelect-AI is running at {url}")
    print("Press Ctrl+C to stop. Sequences stay on this computer.")
    if args.open:
        threading.Timer(0.3, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping IncretinSelect-AI.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

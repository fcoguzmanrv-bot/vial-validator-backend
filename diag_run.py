"""
Script de diagnostico — modo dual:

  Modo 1 (default): diagnostico de filtro de observaciones (paginas 138-144)
  Modo 2 (--drainage): diagnostico de tuberias de drenaje

Ejecutar:
    .venv\Scripts\python.exe diag_run.py              # geometria
    .venv\Scripts\python.exe diag_run.py --drainage   # drenaje

El resultado del LLM se cachea en diag_cache.json (o diag_cache_drainage.json).
Borrar el .json correspondiente para forzar nueva llamada al LLM.
"""
import asyncio
import io
import json
import sys

# UTF-8 en stdout/stderr para evitar UnicodeEncodeError en Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(levelname)s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
for noisy in ("httpx", "httpcore", "anthropic", "pdfplumber", "urllib3", "pdfminer"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

from pathlib import Path
import pdfplumber
import anthropic as _anthropic
from dotenv import load_dotenv

load_dotenv()

from app.services.pdf_service import clean_extracted_text, parse_page_range
from app.schemas.aashto import AASHTOObservation
from app.services.validation_rules import apply_all_rules
from app.providers.prompts import SYSTEM_PROMPT, USER_TEMPLATE
from app.core.config import settings

# ── Configuracion por modo ────────────────────────────────────────────────────
DRAINAGE_MODE = "--drainage" in sys.argv

PDF_PATH   = Path("MVP/CDP-ROA-DWG-00008[00]Roadway and Drainage Design, Segments 3 and 4.pdf")
CACHE_FILE = Path("diag_cache_drainage.json" if DRAINAGE_MODE else "diag_cache.json")
MAX_TOKENS = 16000

PARAMS = {
    "functional_class": "Freeway Urban",
    "speed_mainline":   "60",
    "speed_ramps":      "45",
    "speed_collector":  "45",
    "speed_loops":      "30",
    "emax":             "6",
    "context":          "Urban",
}

# Palabras clave para detectar paginas de drenaje
_DRAINAGE_KEYWORDS = [
    "drainage structure", "drain pipe", "cross drain", "storm drain",
    "summary of drainage", "pipe slope", "pipe size", "culvert",
    "906", "907",  # numeros de estructura target
]


# ── Utilidades ────────────────────────────────────────────────────────────────
def _sep(char="=", n=80): print(char * n)


def _extract_text(
    pdf_path: Path,
    page_range: str,
    force_vision_pages: "set[int] | None" = None,
) -> tuple[str, list[int], list[dict]]:
    """Returns (text, pages_used, vision_pages) — mirrors extract_text_from_pdf logic."""
    from app.services.pdf_service import should_use_vision, render_page_to_base64

    try:
        import fitz as _fitz  # noqa: F401
        has_fitz = True
    except ImportError:
        has_fitz = False

    pdf_bytes = pdf_path.read_bytes()
    vision_pages: list[dict] = []

    with pdfplumber.open(str(pdf_path)) as pdf:
        total = len(pdf.pages)
        indices = parse_page_range(page_range, total)
        texts: list[str] = []
        for i in indices:
            raw = pdf.pages[i].extract_text() or ""
            cleaned = clean_extracted_text(raw)
            forced = force_vision_pages and (i + 1) in force_vision_pages
            if has_fitz and should_use_vision(i + 1, cleaned, force_vision_pages):
                img_b64 = render_page_to_base64(pdf_bytes, i + 1)
                vision_pages.append({"page_number": i + 1, "image_b64": img_b64})
                reason = "forzado" if forced else "texto insuficiente"
                texts.append(f"[PÁGINA {i+1}: contenido en imagen — Vision activo ({reason})]")
                print(f"      [Vision] Página {i+1}: {reason} → imagen PNG")
            else:
                texts.append(cleaned)
    return "\n\n".join(texts), [i + 1 for i in indices], vision_pages


def _scan_drainage_pages(pdf_path: Path) -> list[int]:
    """Escanea el PDF y devuelve paginas que contienen palabras clave de drenaje."""
    hits: list[int] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for i, page in enumerate(pdf.pages):
            raw = (page.extract_text() or "").lower()
            if any(kw.lower() in raw for kw in _DRAINAGE_KEYWORDS):
                hits.append(i + 1)  # 1-based
    return hits


async def _call_llm_raw(text: str) -> tuple[list[AASHTOObservation], str, int]:
    """
    Llama al LLM directamente y devuelve (observaciones, stop_reason, tokens_usados).
    Permite inspeccionar stop_reason para detectar max_tokens.
    """
    from app.providers.anthropic_provider import _TOOL  # type: ignore

    client = _anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    user_msg = USER_TEMPLATE.format(
        functional_class=PARAMS["functional_class"],
        speed_mainline=PARAMS["speed_mainline"],
        speed_ramps=PARAMS["speed_ramps"],
        speed_collector=PARAMS["speed_collector"],
        speed_loops=PARAMS["speed_loops"],
        emax=PARAMS["emax"],
        context=PARAMS["context"],
        text=text,
    )

    response = await client.messages.create(
        model=settings.ANTHROPIC_MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        tools=[_TOOL],
        tool_choice={"type": "tool", "name": "report_observations"},
        messages=[{"role": "user", "content": user_msg}],
    )

    stop_reason   = response.stop_reason
    tokens_used   = response.usage.output_tokens

    tool_block = next((b for b in response.content if b.type == "tool_use"), None)
    if tool_block is None:
        return [], stop_reason, tokens_used

    items = tool_block.input.get("observations", [])
    obs: list[AASHTOObservation] = []
    for item in items:
        if isinstance(item, dict):
            obs.append(AASHTOObservation(**item))
        elif isinstance(item, str):
            try:
                obs.append(AASHTOObservation(**json.loads(item)))
            except Exception:
                pass  # item malformado — ignorar
    return obs, stop_reason, tokens_used


def _print_obs_table(observations: list[AASHTOObservation], title: str) -> None:
    _sep()
    print(f"  {title}  ({len(observations)} observaciones)")
    _sep()
    print(f"  {'#':<4}  {'complies':<8}  {'severity':<14}  parameter")
    print(f"  {'-'*4}  {'-'*8}  {'-'*14}  {'-'*50}")
    for i, obs in enumerate(observations, 1):
        c = "True " if obs.complies else "False"
        s = obs.severity or "None"
        print(f"  {i:<4}  {c:<8}  {s:<14}  {obs.parameter}")


# ── Main ──────────────────────────────────────────────────────────────────────
async def main_drainage() -> None:
    if not PDF_PATH.exists():
        print(f"ERROR: PDF no encontrado en {PDF_PATH.resolve()}")
        sys.exit(1)

    # 1. Rango de paginas de drenaje (Cross Drain Information table)
    DRAINAGE_PAGE_RANGE = "128-130"
    FORCE_VISION = {128}   # página 128 tiene la tabla CAD de Cross Drain Information
    print(f"\n[1/5] Usando rango de paginas de drenaje: {DRAINAGE_PAGE_RANGE}  |  Force-Vision: {sorted(FORCE_VISION)}")
    with pdfplumber.open(str(PDF_PATH)) as pdf:
        total_pages = len(pdf.pages)
    print(f"      PDF tiene {total_pages} paginas en total.")
    page_range_str = DRAINAGE_PAGE_RANGE
    selected = []
    for part in DRAINAGE_PAGE_RANGE.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            selected.extend(range(int(a), int(b) + 1))
        else:
            selected.append(int(part))

    # 2. Extraccion de texto (con deteccion de Vision fallback + paginas forzadas)
    print(f"\n[2/5] Extrayendo texto de paginas seleccionadas...")
    text, pages, vision_pages = _extract_text(PDF_PATH, page_range_str, FORCE_VISION)
    print(f"      Paginas efectivas: {pages}  |  Caracteres texto: {len(text):,}")
    print(f"      Vision fallback: {len(vision_pages)} paginas → {[v['page_number'] for v in vision_pages]}")
    print(f"      Tokens estimados (aprox): ~{len(text)//4:,}")

    # Muestra de texto de las primeras 3 paginas
    _sep("-")
    print("  MUESTRA DE TEXTO LIMPIO (primeras 3 paginas del rango)")
    _sep("-")
    with pdfplumber.open(str(PDF_PATH)) as pdf:
        for p in selected[:3]:
            raw = pdf.pages[p - 1].extract_text() or ""
            clean = clean_extracted_text(raw)
            mode = "[VISION]" if any(v["page_number"] == p for v in vision_pages) else "[texto]"
            print(f"\n  [--- PAGINA {p} {mode} ({len(clean)} chars) ---]")
            lines = [l for l in clean.splitlines() if l.strip()][:80]
            for line in lines:
                print(f"  {line}")
            if len([l for l in clean.splitlines() if l.strip()]) > 80:
                print(f"  ... ({len([l for l in clean.splitlines() if l.strip()]) - 80} lineas mas)")

    _sep("-")

    # 3. LLM texto (con cache)
    if CACHE_FILE.exists():
        print(f"\n[3/5] Cargando desde cache ({CACHE_FILE})...")
        cached = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        raw_obs     = [AASHTOObservation(**item) for item in cached["observations"]]
        stop_reason = cached.get("stop_reason", "desconocido")
        tokens_used = cached.get("tokens_used", 0)
        print(f"      {len(raw_obs)} observaciones. stop_reason={stop_reason!r}, tokens={tokens_used}")
    else:
        print(f"\n[3/5] Llamando al LLM texto (max_tokens={MAX_TOKENS}, puede tardar 30-90 s)...")
        raw_obs, stop_reason, tokens_used = await _call_llm_raw(text)
        print(f"      LLM devolvio {len(raw_obs)} observaciones.")
        print(f"      stop_reason : {stop_reason!r}")
        print(f"      tokens usados (output): {tokens_used}")

        if stop_reason == "max_tokens":
            print("      ADVERTENCIA: respuesta truncada por max_tokens.")
            print(f"      Considerar: (a) reducir rango de paginas, o (b) subir max_tokens (actual: {MAX_TOKENS}).")

        CACHE_FILE.write_text(
            json.dumps({
                "stop_reason":  stop_reason,
                "tokens_used":  tokens_used,
                "observations": [o.model_dump() for o in raw_obs],
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"      Guardado en {CACHE_FILE}.")

    # 4. Vision fallback: llamadas LLM por pagina con imagen
    vision_obs: list[AASHTOObservation] = []
    if vision_pages:
        from app.providers.anthropic_provider import AnthropicProvider
        provider = AnthropicProvider()
        print(f"\n[4/5] Vision fallback: {len(vision_pages)} pagina(s) con imagen...")
        for vp in vision_pages:
            print(f"      Analizando pagina {vp['page_number']} via Vision...")
            page_obs = await provider.validate_vision_pages([vp], PARAMS)
            print(f"      → {len(page_obs)} observaciones.")
            vision_obs.extend(page_obs)
    else:
        print(f"\n[4/5] Vision fallback: no se activo para ninguna pagina.")

    # 5. Aplicar reglas y mostrar observaciones de tuberias
    print(f"\n[5/5] Aplicando reglas deterministicas...")
    all_raw = list(raw_obs) + vision_obs
    observations = apply_all_rules(all_raw)

    pipe_obs = [o for o in observations
                if any(kw in (o.parameter or "").lower()
                       for kw in ("tuberia", "tubería", "pipe", "drain pipe",
                                  "cross drain", "hidraulica", "hidráulica"))]

    _sep()
    print(f"  STOP REASON (texto): {stop_reason!r}   |   TOKENS OUTPUT: {tokens_used}")
    print(f"  Vision obs: {len(vision_obs)}   |   Total obs pre-reglas: {len(all_raw)}")
    _sep()

    if not pipe_obs:
        print("\n  No se generaron observaciones de tuberias o capacidad hidraulica.")
        print("  - Si Vision se activo, revisa si la imagen contiene la tabla de datos.")
        print("  - Si Vision no se activo, el texto era suficiente pero sin datos de tuberias.")
    else:
        _sep("-")
        print(f"  OBSERVACIONES DE TUBERIAS/HIDRAULICA ({len(pipe_obs)} detectadas)")
        _sep("-")
        for obs in pipe_obs:
            print(f"  parameter   : {obs.parameter}")
            print(f"  found_value : {obs.found_value}")
            print(f"  complies    : {obs.complies}")
            print(f"  severity    : {obs.severity}")
            print(f"  observation : {(obs.observation or '')[:300]}")
            print()

    _print_obs_table(observations, "TODAS LAS OBSERVACIONES (post-reglas)")

    report_obs = [o for o in observations if not (o.complies and o.severity == "informativo")]
    print(f"\n  report_obs final: {len(report_obs)} observaciones (excluidas {len(observations)-len(report_obs)} informativas).")
    print("\nDiagnostico completado.\n")


async def main_geometry() -> None:
    """Modo geometria — identico al diag_run.py anterior."""
    PAGE_RANGE = "138-144"

    if not PDF_PATH.exists():
        print(f"ERROR: PDF no encontrado en {PDF_PATH.resolve()}")
        sys.exit(1)

    print(f"\n[1/3] Extrayendo paginas {PAGE_RANGE}...")
    text, pages, vision_pages = _extract_text(PDF_PATH, PAGE_RANGE)
    print(f"      Paginas: {pages}  |  Caracteres: {len(text):,}  |  Vision fallback: {len(vision_pages)} paginas")

    if CACHE_FILE.exists():
        print(f"\n[2/3] Cargando desde cache ({CACHE_FILE})...")
        cached = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        if isinstance(cached, list):
            # cache viejo (solo lista de obs)
            raw_obs     = [AASHTOObservation(**item) for item in cached]
            stop_reason = "desconocido (cache sin metadatos)"
            tokens_used = 0
        else:
            raw_obs     = [AASHTOObservation(**item) for item in cached["observations"]]
            stop_reason = cached.get("stop_reason", "desconocido")
            tokens_used = cached.get("tokens_used", 0)
        print(f"      {len(raw_obs)} observaciones. stop_reason={stop_reason!r}, tokens={tokens_used}")
    else:
        print(f"\n[2/3] Llamando al LLM (max_tokens={MAX_TOKENS})...")
        raw_obs, stop_reason, tokens_used = await _call_llm_raw(text)
        print(f"      {len(raw_obs)} observaciones devueltas.")
        print(f"      stop_reason : {stop_reason!r}")
        print(f"      tokens usados (output): {tokens_used}")
        CACHE_FILE.write_text(
            json.dumps({
                "stop_reason":  stop_reason,
                "tokens_used":  tokens_used,
                "observations": [o.model_dump() for o in raw_obs],
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    print(f"\n[3/3] Aplicando reglas deterministicas...")
    observations = apply_all_rules(list(raw_obs))

    report_obs = [o for o in observations if not (o.complies and o.severity == "informativo")]
    excl       = len(observations) - len(report_obs)

    _sep()
    print(f"  STOP REASON: {stop_reason!r}   |   TOKENS OUTPUT: {tokens_used}")
    _sep()
    print(f"  Total obs: {len(observations)}  |  report_obs: {len(report_obs)}  |  excluidas: {excl}")
    print("\nDiagnostico completado.\n")


if __name__ == "__main__":
    if DRAINAGE_MODE:
        asyncio.run(main_drainage())
    else:
        asyncio.run(main_geometry())

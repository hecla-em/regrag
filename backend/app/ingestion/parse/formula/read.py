"""The formula model call: one inline image in, whether it is a formula and its LaTeX out."""

import base64

import litellm

from app.core.config import config
from app.core.llm.errors import llm_retry, parse_model_answer, wrap_provider_errors
from app.core.llm.keys import api_key_for
from app.ingestion.parse.formula.models import FormulaReading
from app.ingestion.parse.models import ParsedImage

FORMULA_PROMPT = """You read images taken from EU legislation.

Decide whether the image is a mathematical formula, equation, or symbol. A logo, stamp, \
signature, diagram, chart or photograph is not.

If it is, transcribe it to LaTeX exactly as drawn. Keep every subscript, superscript and \
Greek letter as written, keep the decimal comma (0,05), and use \\text{} for words. Do not \
simplify, rearrange or evaluate it. Write it on one line with no $ or other delimiters.

If it is not, set is_formula to false and latex to null."""


def data_uri(image: ParsedImage) -> str:
    """The image as a data URI, under the media type providers accept: EUR-Lex writes image/jpg."""
    media_type = "image/jpeg" if image.media_type == "image/jpg" else image.media_type
    return f"data:{media_type};base64,{base64.b64encode(image.content).decode()}"


@llm_retry
@wrap_provider_errors("formula read")
async def read_formula(image: ParsedImage) -> FormulaReading:
    """One vision call deciding whether the image is a formula and, if so, transcribing it."""
    response = await litellm.acompletion(
        model=config.FORMULA_MODEL,
        api_key=api_key_for(config.FORMULA_MODEL),
        messages=[
            {"role": "system", "content": FORMULA_PROMPT},
            {
                "role": "user",
                "content": [{"type": "image_url", "image_url": {"url": data_uri(image)}}],
            },
        ],
        response_format=FormulaReading,
        max_tokens=config.FORMULA_MAX_TOKENS,
        timeout=config.FORMULA_TIMEOUT,
    )
    choice = response.choices[0]
    return parse_model_answer(
        FormulaReading,
        choice.message.content or "",
        label="formula read",
        stopped_on=choice.finish_reason,
    )

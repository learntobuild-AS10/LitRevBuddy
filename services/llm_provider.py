from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from abc import ABC, abstractmethod

from openai import OpenAI

from models.story import PaperStory


DEFAULT_OPENAI_MODEL = "gpt-5.6-luna"
DEFAULT_CLAUDE_CODE_MODEL = "sonnet"
DEFAULT_OPENROUTER_MODEL = "openrouter/free"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class LLMProviderError(RuntimeError):
    pass


class StoryLLMProvider(ABC):
    name: str
    model: str

    @abstractmethod
    def generate(self, *, system_prompt: str, user_prompt: str) -> PaperStory:
        raise NotImplementedError


def claude_code_available() -> bool:
    return shutil.which("claude") is not None


def _extract_json_object(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("~~~"):
        text = re.sub(r"^~~~(?:json)?\\s*", "", text, flags=re.I)
        text = re.sub(r"\\s*~~~$", "", text)
    try:
        json.loads(text)
        return text
    except json.JSONDecodeError:
        match = re.search(r"\\{.*\\}", text, flags=re.S)
        if not match:
            raise LLMProviderError("Claude returned a response that did not contain valid story JSON.")
        return match.group(0)


class ClaudeCodeStoryProvider(StoryLLMProvider):
    """Local-only provider that uses an authenticated Claude Code installation."""

    name = "claude_code"

    def __init__(self, *, model: str = DEFAULT_CLAUDE_CODE_MODEL):
        executable = shutil.which("claude")
        if not executable:
            raise LLMProviderError(
                "Claude Code is not installed or is not on PATH. Install Claude Code and sign in with your Claude subscription first."
            )
        self.executable = executable
        self.model = model or DEFAULT_CLAUDE_CODE_MODEL

    def generate(self, *, system_prompt: str, user_prompt: str) -> PaperStory:
        schema = json.dumps(PaperStory.model_json_schema(), separators=(",", ":"))
        prompt = (
            f"{user_prompt}\\n\\n"
            "Return ONLY one JSON object matching this JSON Schema exactly. "
            "Do not wrap it in Markdown or add commentary.\\n\\n"
            f"JSON SCHEMA:\\n{schema}"
        )

        env = os.environ.copy()
        env.pop("ANTHROPIC_API_KEY", None)

        command = [
            self.executable,
            "-p",
            "--output-format",
            "json",
            "--max-turns",
            "1",
            "--model",
            self.model,
            "--system-prompt",
            system_prompt,
        ]

        try:
            completed = subprocess.run(
                command,
                input=prompt,
                text=True,
                capture_output=True,
                timeout=240,
                env=env,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise LLMProviderError("Claude Code timed out while generating the story.") from exc
        except OSError as exc:
            raise LLMProviderError(f"Claude Code could not be started: {exc}") from exc

        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            raise LLMProviderError(
                "Claude Code generation failed. Make sure claude works in your terminal and is signed in to your Claude subscription."
                + (f" Details: {detail[:600]}" if detail else "")
            )

        try:
            wrapper = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise LLMProviderError("Claude Code returned invalid wrapper JSON.") from exc

        if wrapper.get("is_error"):
            raise LLMProviderError(str(wrapper.get("result") or "Claude Code reported an error."))

        result_text = wrapper.get("result")
        if not isinstance(result_text, str):
            raise LLMProviderError("Claude Code returned no story result.")

        try:
            return PaperStory.model_validate_json(_extract_json_object(result_text))
        except Exception as exc:
            raise LLMProviderError(f"Claude returned story JSON that did not match the required schema: {exc}") from exc


class OpenAIStoryProvider(StoryLLMProvider):
    name = "openai"

    def __init__(self, *, api_key: str, model: str = DEFAULT_OPENAI_MODEL):
        if not api_key:
            raise LLMProviderError("OPENAI_API_KEY is not configured.")
        self.model = model or DEFAULT_OPENAI_MODEL
        self.client = OpenAI(api_key=api_key)

    def generate(self, *, system_prompt: str, user_prompt: str) -> PaperStory:
        try:
            response = self.client.responses.parse(
                model=self.model,
                input=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                text_format=PaperStory,
            )
        except Exception as exc:
            raise LLMProviderError(f"Story generation failed: {exc}") from exc

        story = response.output_parsed
        if story is None:
            raise LLMProviderError("The model returned no structured story.")
        return story


class OpenRouterStoryProvider(StoryLLMProvider):
    """Hosted provider for the public demo, using OpenRouter's free-model router."""

    name = "openrouter"

    def __init__(
        self,
        *,
        api_key: str,
        model: str = DEFAULT_OPENROUTER_MODEL,
        site_url: str = "",
        site_name: str = "LitRevBuddy",
    ):
        if not api_key:
            raise LLMProviderError(
                "An OpenRouter API key is required. Add OPENROUTER_API_KEY to Streamlit secrets "
                "or enter a personal free key in Generation settings."
            )
        self.model = model or DEFAULT_OPENROUTER_MODEL
        self.client = OpenAI(
            api_key=api_key,
            base_url=OPENROUTER_BASE_URL,
            default_headers={
                **({"HTTP-Referer": site_url} if site_url else {}),
                "X-Title": site_name,
            },
        )

    def generate(self, *, system_prompt: str, user_prompt: str) -> PaperStory:
        schema = json.dumps(PaperStory.model_json_schema(), separators=(",", ":"))
        schema_prompt = (
            f"{user_prompt}\n\n"
            "Return ONLY one valid JSON object matching the supplied JSON Schema. "
            "Do not use Markdown fences or add commentary.\n\n"
            f"JSON SCHEMA:\n{schema}"
        )

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": schema_prompt},
                ],
                temperature=0.2,
            )
        except Exception as exc:
            raise LLMProviderError(
                "Free story generation failed. The shared/free quota may be busy or exhausted; "
                f"try again later or use your own OpenRouter key. Details: {exc}"
            ) from exc

        try:
            result_text = response.choices[0].message.content
        except Exception as exc:
            raise LLMProviderError("OpenRouter returned no story content.") from exc

        if not isinstance(result_text, str) or not result_text.strip():
            raise LLMProviderError("OpenRouter returned an empty story response.")

        try:
            return PaperStory.model_validate_json(_extract_json_object(result_text))
        except Exception as exc:
            raise LLMProviderError(
                f"The free model returned JSON that did not match the required story schema: {exc}"
            ) from exc

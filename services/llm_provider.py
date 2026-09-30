from __future__ import annotations

from abc import ABC, abstractmethod

from openai import OpenAI

from models.story import PaperStory


DEFAULT_OPENAI_MODEL = "gpt-5.6-luna"


class LLMProviderError(RuntimeError):
    pass


class StoryLLMProvider(ABC):
    name: str
    model: str

    @abstractmethod
    def generate(self, *, system_prompt: str, user_prompt: str) -> PaperStory:
        raise NotImplementedError


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

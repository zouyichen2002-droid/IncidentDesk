"""Mistral embeddings through its OpenAI-compatible API (1024 dimensions)."""

from langchain_openai import OpenAIEmbeddings

from app.conf.app_config import EmbeddingConfig, app_config


class EmbeddingClientManager:
    def __init__(self, config: EmbeddingConfig):
        self.client = None
        self.config = config

    def init(self):
        self.client = OpenAIEmbeddings(
            model=self.config.model,
            base_url=app_config.llm.base_url,
            api_key=app_config.llm.api_key,
            check_embedding_ctx_length=False,
            model_kwargs={"encoding_format": "float"},
            request_timeout=45,
            max_retries=2,
        )


embedding_client_manager = EmbeddingClientManager(app_config.embedding)

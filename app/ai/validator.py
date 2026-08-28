import json
from typing import TypeVar

from pydantic import BaseModel, ValidationError

TModel = TypeVar("TModel", bound=BaseModel)


class AIJsonValidator:
    def validate(self, raw_json: str, model: type[TModel]) -> tuple[TModel | None, str | None]:
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            payload = json.loads(raw_json)
        except json.JSONDecodeError as error:
            logger.warning(f"JSONDecodeError: {error}\nRaw JSON length: {len(raw_json)}\nRaw JSON: {raw_json}")
            return None, str(error)
        try:
            return model.model_validate(payload), None
        except ValidationError as error:
            logger.warning(f"ValidationError: {error}\nRaw JSON length: {len(raw_json)}\nRaw JSON: {raw_json}")
            return None, str(error)

from app.domain.ai import AgentRole, PromptTemplate


class PromptManager:
    def __init__(self, templates: tuple[PromptTemplate, ...] = ()) -> None:
        self._templates = {
            (template.role, template.template_id): template for template in templates
        }

    def register(self, template: PromptTemplate) -> None:
        self._templates[(template.role, template.template_id)] = template

    def get(self, role: AgentRole, template_id: str) -> PromptTemplate | None:
        return self._templates.get((role, template_id))

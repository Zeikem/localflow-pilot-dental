from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class WorkflowStep:
    key: str
    prompt: str
    kind: str = "text"
    choices: tuple[str, ...] = ()
    required: bool = True


@dataclass(frozen=True)
class WorkflowResult:
    current_step: str | None
    answers: dict[str, Any]
    reply: str
    completed: bool = False


class WorkflowConfigError(ValueError):
    pass


class InvalidAnswer(ValueError):
    pass


def load_steps(spec: dict) -> list[WorkflowStep]:
    raw_steps = spec.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise WorkflowConfigError("workflow_spec.steps debe ser una lista no vacía")

    steps: list[WorkflowStep] = []
    seen: set[str] = set()

    for item in raw_steps:
        key = str(item.get("key", "")).strip()
        prompt = str(item.get("prompt", "")).strip()
        kind = str(item.get("kind", "text")).strip()
        choices = tuple(str(x).strip() for x in item.get("choices", []))

        if not key or not prompt:
            raise WorkflowConfigError("Cada paso necesita key y prompt")
        if key in seen:
            raise WorkflowConfigError(f"Paso duplicado: {key}")
        if kind not in {"text", "choice"}:
            raise WorkflowConfigError(f"Tipo no soportado: {kind}")
        if kind == "choice" and not choices:
            raise WorkflowConfigError(f"El paso {key} necesita choices")

        seen.add(key)
        steps.append(
            WorkflowStep(
                key=key,
                prompt=prompt,
                kind=kind,
                choices=choices,
                required=bool(item.get("required", True)),
            )
        )
    return steps


def render_question(step: WorkflowStep) -> str:
    if step.kind != "choice":
        return step.prompt

    options = "\n".join(f"{i + 1}. {choice}" for i, choice in enumerate(step.choices))
    return f"{step.prompt}\n{options}"


def normalize_answer(step: WorkflowStep, value: str) -> str:
    value = value.strip()

    if not value and step.required:
        raise InvalidAnswer("Necesito una respuesta para continuar.")

    if step.kind == "text":
        return value

    if value.isdigit():
        idx = int(value) - 1
        if 0 <= idx < len(step.choices):
            return step.choices[idx]

    lowered = value.casefold()
    for choice in step.choices:
        if lowered == choice.casefold():
            return choice

    raise InvalidAnswer("Elige una de las opciones disponibles.")


class ConversationEngine:
    @staticmethod
    def _next_unanswered(
        steps: list[WorkflowStep],
        answers: dict[str, Any],
        *,
        after_index: int = -1,
    ) -> WorkflowStep | None:
        for step in steps[after_index + 1:]:
            if step.key not in answers:
                return step
        return None

    @staticmethod
    def _completed(spec: dict, answers: dict[str, Any]) -> WorkflowResult:
        completion = spec.get(
            "completion_message",
            "Gracias. Ya tengo tus datos. Enseguida continuamos con tu solicitud.",
        )
        return WorkflowResult(
            current_step=None,
            answers=answers,
            reply=str(completion),
            completed=True,
        )

    def process(
        self,
        spec: dict,
        current_step: str | None,
        answers: dict[str, Any] | None,
        user_text: str,
    ) -> WorkflowResult:
        steps = load_steps(spec)
        answers = dict(answers or {})

        # Primer contacto: no consumimos el saludo como respuesta. Si el
        # intérprete ya obtuvo servicio/urgencia del texto, saltamos esos pasos.
        if current_step is None:
            first = self._next_unanswered(steps, answers)
            if first is None:
                return self._completed(spec, answers)
            return WorkflowResult(
                current_step=first.key,
                answers=answers,
                reply=render_question(first),
                completed=False,
            )

        index_by_key = {step.key: idx for idx, step in enumerate(steps)}
        if current_step not in index_by_key:
            raise WorkflowConfigError(f"current_step desconocido: {current_step}")

        step_idx = index_by_key[current_step]
        step = steps[step_idx]

        try:
            answers[step.key] = normalize_answer(step, user_text)
        except InvalidAnswer as exc:
            return WorkflowResult(
                current_step=step.key,
                answers=answers,
                reply=f"{exc}\n\n{render_question(step)}",
                completed=False,
            )

        next_step = self._next_unanswered(steps, answers, after_index=step_idx)
        if next_step is None:
            return self._completed(spec, answers)

        return WorkflowResult(
            current_step=next_step.key,
            answers=answers,
            reply=render_question(next_step),
            completed=False,
        )

import unittest

from app.domain.workflow import ConversationEngine


SPEC = {
    "completion_message": "Listo.",
    "steps": [
        {"key": "nombre", "prompt": "¿Nombre?"},
        {
            "key": "servicio",
            "prompt": "¿Servicio?",
            "kind": "choice",
            "choices": ["Valoración", "Limpieza"],
        },
    ],
}


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.engine = ConversationEngine()

    def test_first_message_is_not_consumed_as_name(self):
        result = self.engine.process(SPEC, None, {}, "Hola")
        self.assertEqual(result.current_step, "nombre")
        self.assertEqual(result.answers, {})
        self.assertEqual(result.reply, "¿Nombre?")

    def test_choice_accepts_number(self):
        first = self.engine.process(SPEC, None, {}, "Hola")
        second = self.engine.process(SPEC, first.current_step, first.answers, "Adrián")
        third = self.engine.process(SPEC, second.current_step, second.answers, "2")

        self.assertTrue(third.completed)
        self.assertEqual(third.answers["nombre"], "Adrián")
        self.assertEqual(third.answers["servicio"], "Limpieza")
        self.assertEqual(third.reply, "Listo.")

    def test_invalid_choice_reprompts(self):
        first = self.engine.process(SPEC, None, {}, "Hola")
        second = self.engine.process(SPEC, first.current_step, first.answers, "Adrián")
        invalid = self.engine.process(SPEC, second.current_step, second.answers, "999")

        self.assertFalse(invalid.completed)
        self.assertEqual(invalid.current_step, "servicio")
        self.assertIn("Elige una de las opciones", invalid.reply)


if __name__ == "__main__":
    unittest.main()

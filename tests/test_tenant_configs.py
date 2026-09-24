import json
import unittest
from pathlib import Path

from app.services.scheduling import validate_schedule_spec


CONFIG_DIR = Path(__file__).resolve().parent.parent / "tenant_configs"


class TenantConfigTests(unittest.TestCase):
    def test_all_demo_configs_have_valid_schedule_and_service_mapping(self):
        paths = sorted(CONFIG_DIR.glob("*.json"))
        self.assertGreaterEqual(len(paths), 3)

        for path in paths:
            data = json.loads(path.read_text(encoding="utf-8"))
            workflow = data["workflow_spec"]
            schedule = workflow["schedule"]
            validate_schedule_spec(schedule)

            service_step = next(
                step for step in workflow["steps"] if step["key"] == "servicio"
            )
            labels = {
                str(service.get("label", service["key"])).casefold()
                for service in schedule["services"]
            }
            for choice in service_step["choices"]:
                if choice.casefold() == "otro":
                    continue
                self.assertIn(
                    choice.casefold(),
                    labels,
                    msg=f"{path.name}: choice sin servicio de agenda: {choice}",
                )


if __name__ == "__main__":
    unittest.main()

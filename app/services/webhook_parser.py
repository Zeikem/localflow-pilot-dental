from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class InboundWhatsAppMessage:
    message_id: str
    phone_number_id: str
    wa_id: str
    message_type: str
    text: str | None
    raw: dict[str, Any]


def extract_inbound_messages(payload: dict[str, Any]) -> list[InboundWhatsAppMessage]:
    result: list[InboundWhatsAppMessage] = []

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            metadata = value.get("metadata", {})
            phone_number_id = str(metadata.get("phone_number_id", "")).strip()
            if not phone_number_id:
                continue

            contacts = {
                str(c.get("wa_id")): c
                for c in value.get("contacts", [])
                if c.get("wa_id")
            }

            for message in value.get("messages", []):
                message_id = str(message.get("id", "")).strip()
                wa_id = str(message.get("from", "")).strip()
                message_type = str(message.get("type", "")).strip()
                if not message_id or not wa_id:
                    continue

                text = None
                if message_type == "text":
                    text = (message.get("text") or {}).get("body")

                result.append(
                    InboundWhatsAppMessage(
                        message_id=message_id,
                        phone_number_id=phone_number_id,
                        wa_id=wa_id,
                        message_type=message_type or "unknown",
                        text=text,
                        raw={
                            "message": message,
                            "contact": contacts.get(wa_id),
                            "metadata": metadata,
                        },
                    )
                )

    return result

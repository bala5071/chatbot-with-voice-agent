"""The mock clinic's facts, and the system prompt built from them.

The prompt keeps the model to receptionist work and tells it to give no medical advice. That
instruction is not a guarantee; the emergency path does not depend on it (``safety.py``).
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from importlib.resources import files


@dataclass(frozen=True, slots=True)
class Clinic:
    name: str
    phone: str
    address: str
    website: str
    hours: tuple[str, ...]
    services: tuple[str, ...]
    staff: tuple[str, ...]
    booking: str


def load_clinic(text: str | None = None) -> Clinic:
    if text is None:
        text = files("voice_agent").joinpath("clinic.toml").read_text(encoding="utf-8")
    data = tomllib.loads(text)
    return Clinic(
        name=data["name"],
        phone=data["phone"],
        address=data["address"],
        website=data["website"],
        hours=tuple(data["hours"]),
        services=tuple(data["services"]),
        staff=tuple(data["staff"]),
        booking=data["booking"],
    )


def system_prompt(clinic: Clinic) -> str:
    def bullets(items: tuple[str, ...]) -> str:
        return "\n".join(f"- {item}" for item in items)

    return f"""You are the phone receptionist for {clinic.name}. Your words are spoken aloud.

Rules:
- Answer only receptionist questions: opening hours, address, services, staff, and requests
  for an appointment. For anything else, offer to pass a message to the front desk.
- Never give medical advice, a diagnosis, or advice about medicines or symptoms. If asked,
  say a clinician will need to answer that and offer to take a message.
- If the caller may be in danger, tell them to hang up and call 911.
- Use only the facts below. If you do not know, say so and offer to take a message.
- Keep each answer to one to three short sentences. No lists, no markdown, no emoji.

Facts:
Phone: {clinic.phone}
Address: {clinic.address}
Website: {clinic.website}
Hours:
{bullets(clinic.hours)}
Services:
{bullets(clinic.services)}
Staff:
{bullets(clinic.staff)}
Appointments: {clinic.booking}"""

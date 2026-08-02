"""Disclosure shown before any screenshot leaves the machine.

Deliberately a blocking dialog with an explicit accept, not a toast and not a
settings toggle: the image is about to be handed to whichever AI the user
picked, and a syllabus screenshot routinely carries their name and school.
That is worth one interruption per provider.

The copy names the provider it is actually about. Agreeing to send an image to
a local server on your own machine is not agreeing to send it to a company, so
consent is recorded per provider and asked again when the provider changes.
"""
from __future__ import annotations

from PySide6.QtWidgets import QVBoxLayout, QWidget

from qfluentwidgets import BodyLabel, CaptionLabel, MessageBoxBase, StrongBodyLabel

from ... import ai_provider, settings


def _paragraph(text: str, parent: QWidget) -> BodyLabel:
    label = BodyLabel(text, parent)
    label.setWordWrap(True)
    return label


class ImportPrivacyDialog(MessageBoxBase):
    """Explains where the screenshot goes, for one specific provider."""

    def __init__(self, parent, provider: ai_provider.Provider, destination: str):
        super().__init__(parent)
        self._provider = provider

        self.titleLabel = StrongBodyLabel("Before you import a screenshot", self)
        self.viewLayout.addWidget(self.titleLabel)

        content = QWidget(self)
        body = QVBoxLayout(content)
        body.setContentsMargins(0, 0, 4, 0)
        body.setSpacing(10)

        body.addWidget(_paragraph(
            f"To read your schedule, EarlyBird sends the image to {destination}.",
            content
        ))

        note = _paragraph(provider.privacy_note, content)
        note.setTextColor("#B7791F", "#E0A63A")
        body.addWidget(note)

        body.addWidget(_paragraph(
            "A syllabus screenshot often shows your name, your school, and "
            "classes you aren't importing — crop those out first if you'd "
            "rather not send them.", content
        ))

        body.addWidget(_paragraph(
            "EarlyBird never saves the screenshot. It's discarded as soon as "
            "you confirm or cancel the review step.", content
        ))

        footnote = CaptionLabel(
            "Nothing is added to your classes until you review and confirm "
            "each row.", content
        )
        footnote.setWordWrap(True)
        footnote.setTextColor("#6B7280", "#9CA3AF")
        body.addWidget(footnote)

        self.viewLayout.addWidget(content)

        self.widget.setMinimumWidth(520)
        # Says what the button does rather than "OK" - the consequence is
        # worth naming on the button itself.
        self.yesButton.setText("Send and continue")
        self.cancelButton.setText("Cancel")


def _destination(provider: ai_provider.Provider, base_url: str) -> str:
    """How to describe where the image is going, in one phrase."""
    if provider.needs_base_url:
        return base_url.strip() or "the server you configured"
    return provider.label


def ensure_consent(parent) -> bool:
    """Show the disclosure once per provider; True if importing may proceed."""
    config = settings.get_ai_config()
    provider = ai_provider.get(config["provider"])

    if settings.get_import_privacy_accepted_for() == provider.id:
        return True

    destination = _destination(provider, config["base_url"])
    if ImportPrivacyDialog(parent, provider, destination).exec():
        settings.save_import_privacy_accepted_for(provider.id)
        return True
    return False

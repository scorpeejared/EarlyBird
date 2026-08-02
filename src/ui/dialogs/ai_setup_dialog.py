"""Pick which AI reads screenshots, and supply your own credentials for it."""
from __future__ import annotations

from PySide6.QtWidgets import QVBoxLayout, QWidget

from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    ComboBox,
    LineEdit,
    MessageBoxBase,
    StrongBodyLabel,
)

from ... import ai_provider, secret_store, settings
from .. import theme


def _caption(text: str, parent: QWidget) -> CaptionLabel:
    label = CaptionLabel(text, parent)
    label.setWordWrap(True)
    label.setTextColor("#6B7280", "#9CA3AF")
    return label


class AiSetupDialog(MessageBoxBase):
    """Provider, model, server address and key. Saves on accept."""

    def __init__(self, parent):
        super().__init__(parent)

        self.titleLabel = StrongBodyLabel("Choose which AI reads your screenshots", self)
        self.viewLayout.addWidget(self.titleLabel)

        content = QWidget(self)
        body = QVBoxLayout(content)
        body.setContentsMargins(0, 0, 4, 0)
        body.setSpacing(10)

        intro = BodyLabel(
            "EarlyBird doesn't include an AI of its own — you bring your own "
            "account, and the key stays on this computer.", content
        )
        intro.setWordWrap(True)
        body.addWidget(intro)

        config = settings.get_ai_config()

        self._ids = list(ai_provider.PROVIDERS)
        self.provider_combo = ComboBox(self)
        self.provider_combo.addItems([ai_provider.PROVIDERS[i].label for i in self._ids])
        current = config["provider"] if config["provider"] in self._ids else ai_provider.DEFAULT_PROVIDER
        self.provider_combo.setCurrentIndex(self._ids.index(current))
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        body.addWidget(CaptionLabel("Provider", content))
        body.addWidget(self.provider_combo)

        self.model_edit = LineEdit(self)
        self.model_edit.setText(config["model"])
        body.addWidget(CaptionLabel("Model", content))
        body.addWidget(self.model_edit)
        self.model_hint = _caption("", content)
        body.addWidget(self.model_hint)

        self.base_url_label = CaptionLabel("Server address", content)
        self.base_url_edit = LineEdit(self)
        self.base_url_edit.setText(config["base_url"])
        self.base_url_edit.setPlaceholderText("http://localhost:11434/v1")
        body.addWidget(self.base_url_label)
        body.addWidget(self.base_url_edit)
        self.base_url_hint = _caption(
            "Any server that speaks OpenAI's chat API — OpenRouter, Groq, or a "
            "local one like Ollama or LM Studio.", content
        )
        body.addWidget(self.base_url_hint)

        self.key_label = CaptionLabel("", content)
        self.key_edit = LineEdit(self)
        self.key_edit.setEchoMode(LineEdit.Password)
        self.key_edit.setClearButtonEnabled(True)
        self.key_edit.setPlaceholderText("Paste your API key")
        body.addWidget(self.key_label)
        body.addWidget(self.key_edit)

        self.key_link = BodyLabel(content)
        self.key_link.setOpenExternalLinks(True)
        self.key_link.setWordWrap(True)
        body.addWidget(self.key_link)

        self.storage_note = CaptionLabel(content)
        self.storage_note.setWordWrap(True)
        if secret_store.is_secure():
            self.storage_note.setText(
                "Keys are stored in your operating system's credential "
                "manager, not in the app's settings file."
            )
            self.storage_note.setTextColor("#6B7280", "#9CA3AF")
        else:
            self.storage_note.setText(
                "⚠ No credential manager is available on this machine, so the "
                "key will be saved as plain text in the app's data folder. "
                "Anyone with access to this computer could read it."
            )
            self.storage_note.setTextColor(theme.WARNING, "#E0A63A")
        body.addWidget(self.storage_note)

        self.viewLayout.addWidget(content)

        self.widget.setMinimumWidth(560)
        self.yesButton.setText("Save")
        self.cancelButton.setText("Cancel")

        self._on_provider_changed(self.provider_combo.currentIndex())

    # ---------- internals ----------

    def _selected_provider(self) -> ai_provider.Provider:
        return ai_provider.PROVIDERS[self._ids[self.provider_combo.currentIndex()]]

    def _on_provider_changed(self, _index: int) -> None:
        provider = self._selected_provider()

        show_url = provider.needs_base_url
        for widget in (self.base_url_label, self.base_url_edit, self.base_url_hint):
            widget.setVisible(show_url)

        self.key_label.setText(provider.key_label)
        # Show whatever key is already saved for this provider, so switching
        # back and forth doesn't lose it.
        self.key_edit.setText(secret_store.get_key(provider.id))

        if provider.key_url:
            self.key_link.setText(f"Get a key at {theme.link_html(provider.key_url, provider.key_url)}")
            self.key_link.show()
        else:
            self.key_link.hide()

        if provider.default_model:
            self.model_edit.setPlaceholderText(provider.default_model)
            self.model_hint.setText(f"Leave blank to use {provider.default_model}.")
        else:
            self.model_edit.setPlaceholderText("e.g. llama3.2-vision")
            self.model_hint.setText("Required — the model must be able to read images.")

    def validate(self) -> bool:
        provider = self._selected_provider()
        key = self.key_edit.text().strip()
        model = self.model_edit.text().strip()
        base_url = self.base_url_edit.text().strip()

        if provider.key_required and not key:
            return False
        if provider.needs_base_url and not base_url:
            return False
        if not provider.default_model and not model:
            return False

        secret_store.save_key(provider.id, key)
        settings.save_ai_config(provider=provider.id, model=model, base_url=base_url)
        return True


def is_configured() -> bool:
    """True when the selected provider has everything it needs to run."""
    config = settings.get_ai_config()
    provider = ai_provider.get(config["provider"])
    if provider.key_required and not secret_store.has_key(provider.id):
        return False
    if provider.needs_base_url and not config["base_url"].strip():
        return False
    return bool(config["model"].strip() or provider.default_model)


def ensure_configured(parent) -> bool:
    """True when an AI is ready, prompting for setup if needed."""
    if is_configured():
        return True
    return bool(AiSetupDialog(parent).exec())

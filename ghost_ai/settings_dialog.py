"""
Settings dialog for Ghost AI.
Provides UI to configure API keys, provider endpoints, models, and system prompts.
Strictly maintains the standard ArrowCursor across all widgets.
"""

from typing import Optional, Dict, Any
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QComboBox,
    QTextEdit,
    QPushButton,
    QFrame,
    QWidget,
)

from .config import (
    load_config,
    save_config,
    PROVIDER_PRESETS,
    DEFAULT_CONFIG,
    DEFAULT_SYSTEM_PROMPT,
)
from .ai_service import AIChatWorker


class SettingsDialog(QDialog):
    """Configuration modal for AI providers, API keys, and models."""

    settings_saved = Signal(dict)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Ghost AI - Settings")
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setFixedWidth(380)

        self._config = load_config()
        self._test_worker: Optional[AIChatWorker] = None

        self._init_ui()
        self._load_values()

    def _init_ui(self) -> None:
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(10, 10, 10, 10)

        # Card container with sleek stealth dark glass background
        card = QFrame(self)
        card.setObjectName("SettingsCard")
        card.setStyleSheet(
            """
            QFrame#SettingsCard {
                background-color: rgba(24, 24, 27, 0.96);
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 10px;
            }
            QLabel {
                color: #e4e4e7;
                font-size: 11px;
                font-family: "Segoe UI", -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
            }
            QLabel.hint {
                color: #a1a1aa;
                font-size: 10px;
            }
            QLineEdit, QComboBox, QTextEdit {
                background-color: rgba(39, 39, 42, 0.8);
                color: #f4f4f5;
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 6px;
                padding: 5px 8px;
                font-size: 11px;
                selection-background-color: #3b82f6;
            }
            QLineEdit:focus, QComboBox:focus, QTextEdit:focus {
                border: 1px solid #3b82f6;
                background-color: rgba(39, 39, 42, 0.95);
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            QComboBox QAbstractItemView {
                background-color: #18181b;
                color: #f4f4f5;
                selection-background-color: #3b82f6;
                border: 1px solid rgba(255, 255, 255, 0.1);
            }
            QPushButton {
                background-color: rgba(63, 63, 70, 0.6);
                color: #f4f4f5;
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: rgba(82, 82, 91, 0.8);
            }
            QPushButton#PrimaryBtn {
                background-color: #2563eb;
                border: 1px solid #3b82f6;
                color: #ffffff;
            }
            QPushButton#PrimaryBtn:hover {
                background-color: #1d4ed8;
            }
            """
        )
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 14, 16, 16)
        card_layout.setSpacing(10)

        # Header with Title and Close button
        header = QHBoxLayout()
        title_lbl = QLabel("⚙  Ghost AI Settings", card)
        title_lbl.setStyleSheet("font-size: 13px; font-weight: 700; color: #f4f4f5;")
        header.addWidget(title_lbl)
        header.addStretch()

        close_btn = QPushButton("×", card)
        close_btn.setFixedSize(20, 20)
        close_btn.setCursor(Qt.CursorShape.ArrowCursor)
        close_btn.setStyleSheet(
            "background: transparent; border: none; font-size: 16px; color: #a1a1aa; padding-bottom: 2px;"
        )
        close_btn.clicked.connect(self.reject)
        header.addWidget(close_btn)
        card_layout.addLayout(header)

        # Divider
        divider = QFrame(card)
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setStyleSheet("background-color: rgba(255, 255, 255, 0.08);")
        card_layout.addWidget(divider)

        # Provider Selector
        prov_lbl = QLabel("AI Provider:", card)
        prov_lbl.setStyleSheet("font-weight: 600;")
        card_layout.addWidget(prov_lbl)

        self.provider_cb = QComboBox(card)
        self.provider_cb.setCursor(Qt.CursorShape.ArrowCursor)
        for prov_name in PROVIDER_PRESETS.keys():
            self.provider_cb.addItem(prov_name)
        self.provider_cb.currentTextChanged.connect(self._on_provider_changed)
        card_layout.addWidget(self.provider_cb)

        # API Key
        key_lbl = QLabel("API Key:", card)
        key_lbl.setStyleSheet("font-weight: 600;")
        card_layout.addWidget(key_lbl)

        key_box = QHBoxLayout()
        key_box.setSpacing(6)
        self.api_key_edit = QLineEdit(card)
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setPlaceholderText("sk-...")
        self.api_key_edit.setCursor(Qt.CursorShape.ArrowCursor)
        key_box.addWidget(self.api_key_edit)

        self.show_key_btn = QPushButton("👁", card)
        self.show_key_btn.setFixedSize(28, 26)
        self.show_key_btn.setCursor(Qt.CursorShape.ArrowCursor)
        self.show_key_btn.setToolTip("Show / Hide Key")
        self.show_key_btn.clicked.connect(self._toggle_show_key)
        key_box.addWidget(self.show_key_btn)
        card_layout.addLayout(key_box)

        # Model Name
        model_lbl = QLabel("Model:", card)
        model_lbl.setStyleSheet("font-weight: 600;")
        card_layout.addWidget(model_lbl)

        self.model_cb = QComboBox(card)
        self.model_cb.setEditable(True)
        self.model_cb.setCursor(Qt.CursorShape.ArrowCursor)
        card_layout.addWidget(self.model_cb)

        # Base URL
        url_lbl = QLabel("Base Endpoint URL:", card)
        url_lbl.setStyleSheet("font-weight: 600;")
        card_layout.addWidget(url_lbl)

        self.base_url_edit = QLineEdit(card)
        self.base_url_edit.setCursor(Qt.CursorShape.ArrowCursor)
        card_layout.addWidget(self.base_url_edit)

        # System Prompt
        sys_lbl = QLabel("System Prompt:", card)
        sys_lbl.setStyleSheet("font-weight: 600;")
        card_layout.addWidget(sys_lbl)

        self.sys_prompt_edit = QTextEdit(card)
        self.sys_prompt_edit.setFixedHeight(54)
        self.sys_prompt_edit.setCursor(Qt.CursorShape.ArrowCursor)
        card_layout.addWidget(self.sys_prompt_edit)

        # Status / Feedback Label
        self.status_lbl = QLabel("", card)
        self.status_lbl.setWordWrap(True)
        self.status_lbl.setStyleSheet("font-size: 10px; color: #a1a1aa;")
        card_layout.addWidget(self.status_lbl)

        # Action Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        self.test_btn = QPushButton("Test", card)
        self.test_btn.setCursor(Qt.CursorShape.ArrowCursor)
        self.test_btn.clicked.connect(self._on_test_connection)
        btn_layout.addWidget(self.test_btn)

        btn_layout.addStretch()

        cancel_btn = QPushButton("Cancel", card)
        cancel_btn.setCursor(Qt.CursorShape.ArrowCursor)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        save_btn = QPushButton("Save", card)
        save_btn.setObjectName("PrimaryBtn")
        save_btn.setCursor(Qt.CursorShape.ArrowCursor)
        save_btn.clicked.connect(self._on_save_clicked)
        btn_layout.addWidget(save_btn)

        card_layout.addLayout(btn_layout)
        outer_layout.addWidget(card)

    def _load_values(self) -> None:
        """Populate inputs from saved configuration."""
        prov = self._config.get("provider", "OpenAI")
        idx = self.provider_cb.findText(prov)
        if idx >= 0:
            self.provider_cb.setCurrentIndex(idx)
        else:
            self.provider_cb.setCurrentText(prov)

        self.api_key_edit.setText(self._config.get("api_key", ""))
        self.base_url_edit.setText(self._config.get("base_url", "https://api.openai.com/v1"))
        self._populate_models_for_provider(prov)
        self.model_cb.setCurrentText(self._config.get("model", "gpt-4o-mini"))
        self.sys_prompt_edit.setText(self._config.get("system_prompt", DEFAULT_SYSTEM_PROMPT))

    def _on_provider_changed(self, provider_name: str) -> None:
        """Update defaults when switching providers."""
        preset = PROVIDER_PRESETS.get(provider_name)
        if preset:
            self.base_url_edit.setText(preset["base_url"])
            self._populate_models_for_provider(provider_name)
            self.model_cb.setCurrentText(preset["default_model"])

    def _populate_models_for_provider(self, provider_name: str) -> None:
        """Fill model dropdown with recommended models."""
        self.model_cb.clear()
        preset = PROVIDER_PRESETS.get(provider_name)
        if preset and "models" in preset:
            for m in preset["models"]:
                self.model_cb.addItem(m)

    def _toggle_show_key(self) -> None:
        if self.api_key_edit.echoMode() == QLineEdit.EchoMode.Password:
            self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Normal)
            self.show_key_btn.setText("🔒")
        else:
            self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
            self.show_key_btn.setText("👁")

    def _on_test_connection(self) -> None:
        """Perform a quick test ping."""
        self.status_lbl.setStyleSheet("font-size: 10px; color: #60a5fa;")
        self.status_lbl.setText("Testing connection...")
        self.test_btn.setEnabled(False)

        test_config = {
            "provider": self.provider_cb.currentText(),
            "api_key": self.api_key_edit.text().strip(),
            "base_url": self.base_url_edit.text().strip(),
            "model": self.model_cb.currentText().strip(),
            "system_prompt": "Respond with 'OK'",
            "temperature": 0.0,
            "stream": False,
        }

        test_messages = [{"role": "user", "content": "ping"}]
        self._test_worker = AIChatWorker(test_messages, test_config)
        self._test_worker.finished.connect(self._on_test_success)
        self._test_worker.error.connect(self._on_test_error)
        self._test_worker.start()

    def _on_test_success(self, response: str) -> None:
        self.test_btn.setEnabled(True)
        self.status_lbl.setStyleSheet("font-size: 10px; color: #4ade80;")
        self.status_lbl.setText("✓ Connection successful! AI is ready.")

    def _on_test_error(self, err_msg: str) -> None:
        self.test_btn.setEnabled(True)
        self.status_lbl.setStyleSheet("font-size: 10px; color: #f87171;")
        short_err = err_msg.splitlines()[0] if err_msg else "Unknown error"
        self.status_lbl.setText(f"✗ Failed: {short_err}")

    def _stop_test_worker(self) -> None:
        """Safely terminate any pending background test worker."""
        if self._test_worker and self._test_worker.isRunning():
            try:
                self._test_worker.cancel()
                self._test_worker.wait(500)
            except Exception:
                pass

    def closeEvent(self, event) -> None:
        self._stop_test_worker()
        super().closeEvent(event)

    def reject(self) -> None:
        self._stop_test_worker()
        super().reject()

    def accept(self) -> None:
        self._stop_test_worker()
        super().accept()

    def _on_save_clicked(self) -> None:
        """Save settings and close."""
        self._config["provider"] = self.provider_cb.currentText()
        self._config["api_key"] = self.api_key_edit.text().strip()
        self._config["base_url"] = self.base_url_edit.text().strip()
        self._config["model"] = self.model_cb.currentText().strip()
        self._config["system_prompt"] = self.sys_prompt_edit.toPlainText().strip()

        save_config(self._config)
        self.settings_saved.emit(self._config)
        self.accept()

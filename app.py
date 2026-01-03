import json
import os
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Qt
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QProgressBar,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from pipeline import run_pipeline


class WorkerSignals(QObject):
    log = Signal(str)
    error = Signal(str)
    finished = Signal(dict)


class PipelineWorker(QRunnable):
    def __init__(self, params, signals):
        super().__init__()
        self.params = params
        self.signals = signals

    def run(self):
        try:
            result = run_pipeline(self.params, self.signals.log.emit)
        except Exception as exc:  # pragma: no cover - GUI thread boundary
            self.signals.error.emit(str(exc))
            return
        self.signals.finished.emit(result)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Snappy Cut - Parakeet TDT")
        self.thread_pool = QThreadPool.globalInstance()

        self.input_path = QLineEdit()
        self.output_path = QLineEdit()
        self.filler_words = QLineEdit(
            "um, uh, uhh, umm, erm, ah, aah, like, you know, sort of, kind of"
        )

        self.aggression = QSlider()
        self.aggression.setOrientation(Qt.Horizontal)
        self.aggression.setMinimum(0)
        self.aggression.setMaximum(100)
        self.aggression.setValue(60)

        self.aggression_label = QLabel()

        self.handle_ms = QSpinBox()
        self.handle_ms.setRange(0, 500)
        self.handle_ms.setValue(100)
        self.handle_ms.setSuffix(" ms")

        self.breath_ms = QSpinBox()
        self.breath_ms.setRange(0, 500)
        self.breath_ms.setValue(120)
        self.breath_ms.setSuffix(" ms")

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)

        browse_in = QPushButton("Choose input")
        browse_in.clicked.connect(self.choose_input)

        browse_out = QPushButton("Choose output")
        browse_out.clicked.connect(self.choose_output)

        self.run_btn = QPushButton("Process")
        self.run_btn.clicked.connect(self.run_pipeline)

        layout = QVBoxLayout()
        form = QFormLayout()

        input_row = QHBoxLayout()
        input_row.addWidget(self.input_path)
        input_row.addWidget(browse_in)
        form.addRow("Input MP4", input_row)

        output_row = QHBoxLayout()
        output_row.addWidget(self.output_path)
        output_row.addWidget(browse_out)
        form.addRow("Output MP4", output_row)

        form.addRow("Aggressiveness", self.aggression)
        form.addRow("Aggressiveness details", self.aggression_label)
        form.addRow("Handle size", self.handle_ms)
        form.addRow("Breathing space", self.breath_ms)
        form.addRow("Filler words", self.filler_words)

        layout.addLayout(form)
        layout.addWidget(self.run_btn)
        layout.addWidget(self.progress)
        layout.addWidget(self.log)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        self.aggression.valueChanged.connect(self.update_aggression_label)
        self.update_aggression_label()

    def choose_input(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Video", "", "Video Files (*.mp4 *.mov *.m4v)"
        )
        if path:
            self.input_path.setText(path)
            if not self.output_path.text():
                output = str(Path(path).with_name(Path(path).stem + "_snappy.mp4"))
                self.output_path.setText(output)

    def choose_output(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save MP4", "", "Video Files (*.mp4)"
        )
        if path:
            self.output_path.setText(path)

    def update_aggression_label(self):
        settings = self.derive_silence_settings(self.aggression.value())
        self.aggression_label.setText(
            f"silence <= {settings['min_silence']:.2f}s, threshold {settings['silence_db']} dB"
        )

    def run_pipeline(self):
        input_path = self.input_path.text().strip()
        output_path = self.output_path.text().strip()
        if not input_path or not output_path:
            QMessageBox.warning(self, "Missing paths", "Please select input and output paths.")
            return

        settings = self.derive_silence_settings(self.aggression.value())
        params = {
            "input_path": input_path,
            "output_path": output_path,
            "silence_db": settings["silence_db"],
            "min_silence": settings["min_silence"],
            "handle_ms": self.handle_ms.value(),
            "breath_ms": self.breath_ms.value(),
            "filler_words": [w.strip() for w in self.filler_words.text().split(",") if w.strip()],
        }

        self.log.clear()
        self.progress.setVisible(True)
        self.run_btn.setEnabled(False)

        signals = WorkerSignals()
        signals.log.connect(self.log.appendPlainText)
        signals.error.connect(self.on_error)
        signals.finished.connect(self.on_finished)

        worker = PipelineWorker(params, signals)
        self.thread_pool.start(worker)

    def on_error(self, message):
        self.progress.setVisible(False)
        self.run_btn.setEnabled(True)
        QMessageBox.critical(self, "Error", message)

    def on_finished(self, result):
        self.progress.setVisible(False)
        self.run_btn.setEnabled(True)
        summary = json.dumps(result, indent=2)
        self.log.appendPlainText("\nDone! Summary:\n" + summary)
        QMessageBox.information(self, "Complete", "Your snappy video is ready.")

    @staticmethod
    def derive_silence_settings(aggression_value):
        min_db = -40
        max_db = -20
        silence_db = int(max_db - (aggression_value / 100) * (max_db - min_db))

        max_silence = 0.65
        min_silence = 0.20
        min_silence_len = max_silence - (aggression_value / 100) * (max_silence - min_silence)
        return {"silence_db": silence_db, "min_silence": round(min_silence_len, 2)}


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.resize(900, 600)
    window.show()
    sys.exit(app.exec())

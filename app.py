import json
import os
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QHeaderView,
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
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pipeline import preview_captions, run_pipeline


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


class CaptionPreviewWorker(QRunnable):
    def __init__(self, params, signals):
        super().__init__()
        self.params = params
        self.signals = signals

    def run(self):
        try:
            result = preview_captions(self.params, self.signals.log.emit)
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
        self.output_path.editingFinished.connect(self.handle_output_edited)
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
        self.handle_ms.setValue(200)
        self.handle_ms.setSuffix(" ms")

        self.breath_ms = QSpinBox()
        self.breath_ms.setRange(0, 500)
        self.breath_ms.setValue(120)
        self.breath_ms.setSuffix(" ms")

        self.pause_floor_ms = QSpinBox()
        self.pause_floor_ms.setRange(80, 500)
        self.pause_floor_ms.setValue(180)
        self.pause_floor_ms.setSuffix(" ms")

        self.audio_fade_ms = QSpinBox()
        self.audio_fade_ms.setRange(0, 200)
        self.audio_fade_ms.setValue(50)
        self.audio_fade_ms.setSuffix(" ms")

        self.save_transcript = QCheckBox("Save transcript")
        self.save_transcript.setChecked(True)

        self.transcript_path = QLineEdit()
        self.transcript_auto = True
        self.transcript_path.textEdited.connect(self.disable_transcript_auto)

        self.captions_enabled = QCheckBox("Enable captions (embedded + SRT)")
        self.captions_enabled.setChecked(True)
        self.caption_path = QLineEdit()
        self.caption_auto = True
        self.caption_path.textEdited.connect(self.disable_caption_auto)

        self.caption_table = QTableWidget(0, 3)
        self.caption_table.setHorizontalHeaderLabels(["Start", "End", "Caption text"])
        self.caption_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.caption_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.caption_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)

        browse_in = QPushButton("Choose input")
        browse_in.clicked.connect(self.choose_input)

        browse_out = QPushButton("Choose output")
        browse_out.clicked.connect(self.choose_output)

        browse_transcript = QPushButton("Choose transcript")
        browse_transcript.clicked.connect(self.choose_transcript)

        browse_caption = QPushButton("Choose captions")
        browse_caption.clicked.connect(self.choose_caption_path)

        refresh_captions = QPushButton("Generate / Refresh captions")
        refresh_captions.clicked.connect(self.generate_caption_preview)
        self.refresh_captions_btn = refresh_captions

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

        transcript_row = QHBoxLayout()
        transcript_row.addWidget(self.transcript_path)
        transcript_row.addWidget(browse_transcript)
        form.addRow(self.save_transcript, transcript_row)

        caption_row = QHBoxLayout()
        caption_row.addWidget(self.caption_path)
        caption_row.addWidget(browse_caption)
        form.addRow(self.captions_enabled, caption_row)

        form.addRow("Aggressiveness", self.aggression)
        form.addRow("Aggressiveness details", self.aggression_label)
        form.addRow("Handle size", self.handle_ms)
        form.addRow("Pause floor", self.pause_floor_ms)
        form.addRow("Breathing space (legacy)", self.breath_ms)
        form.addRow("Audio fade", self.audio_fade_ms)
        form.addRow("Filler words", self.filler_words)

        layout.addLayout(form)
        layout.addWidget(self.refresh_captions_btn)
        layout.addWidget(self.caption_table)
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
                self.maybe_set_transcript_path(output)
                self.maybe_set_caption_path(output)

    def choose_output(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save MP4", "", "Video Files (*.mp4)"
        )
        if path:
            self.output_path.setText(path)
            self.maybe_set_transcript_path(path)
            self.maybe_set_caption_path(path)

    def handle_output_edited(self):
        self.maybe_set_transcript_path(self.output_path.text().strip())
        self.maybe_set_caption_path(self.output_path.text().strip())

    def choose_transcript(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Transcript", "", "Text Files (*.txt)"
        )
        if path:
            self.transcript_auto = False
            self.transcript_path.setText(path)

    def disable_transcript_auto(self):
        self.transcript_auto = False

    def disable_caption_auto(self):
        self.caption_auto = False

    def maybe_set_transcript_path(self, output_path):
        if not self.transcript_auto or not output_path:
            return
        base = Path(output_path)
        transcript = base.with_suffix(".txt")
        self.transcript_path.setText(str(transcript))

    def maybe_set_caption_path(self, output_path):
        if not self.caption_auto or not output_path:
            return
        base = Path(output_path)
        caption = base.with_suffix(".srt")
        self.caption_path.setText(str(caption))

    def choose_caption_path(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Captions (SRT)", "", "SubRip Files (*.srt)"
        )
        if path:
            self.caption_auto = False
            self.caption_path.setText(path)

    def update_aggression_label(self):
        settings = self.derive_silence_settings(self.aggression.value())
        self.aggression_label.setText(
            f"cuts pauses > {settings['min_silence']:.2f}s when below {settings['silence_db']} dB"
        )

    def run_pipeline(self):
        input_path = self.input_path.text().strip()
        output_path = self.output_path.text().strip()
        if not input_path or not output_path:
            QMessageBox.warning(self, "Missing paths", "Please select input and output paths.")
            return

        if self.captions_enabled.isChecked() and not self.caption_path.text().strip():
            self.maybe_set_caption_path(output_path)

        settings = self.derive_silence_settings(self.aggression.value())
        params = {
            "input_path": input_path,
            "output_path": output_path,
            "silence_db": settings["silence_db"],
            "min_silence": settings["min_silence"],
            "handle_ms": self.handle_ms.value(),
            "breath_ms": self.breath_ms.value(),
            "pause_floor_ms": self.pause_floor_ms.value(),
            "audio_fade_ms": self.audio_fade_ms.value(),
            "filler_words": [w.strip() for w in self.filler_words.text().split(",") if w.strip()],
            "save_transcript": self.save_transcript.isChecked(),
            "transcript_path": self.transcript_path.text().strip(),
            "captions_enabled": self.captions_enabled.isChecked(),
            "caption_srt_path": self.caption_path.text().strip(),
            "caption_segments_override": self.collect_caption_segments(),
        }

        self.log.clear()
        self.progress.setVisible(True)
        self.run_btn.setEnabled(False)
        self.refresh_captions_btn.setEnabled(False)

        signals = WorkerSignals()
        signals.log.connect(self.log.appendPlainText)
        signals.error.connect(self.on_error)
        signals.finished.connect(self.on_finished)

        worker = PipelineWorker(params, signals)
        self.thread_pool.start(worker)

    def on_error(self, message):
        self.progress.setVisible(False)
        self.run_btn.setEnabled(True)
        self.refresh_captions_btn.setEnabled(True)
        QMessageBox.critical(self, "Error", message)

    def on_finished(self, result):
        self.progress.setVisible(False)
        self.run_btn.setEnabled(True)
        self.refresh_captions_btn.setEnabled(True)
        summary = json.dumps(result, indent=2)
        self.log.appendPlainText("\nDone! Summary:\n" + summary)
        QMessageBox.information(self, "Complete", "Your snappy video is ready.")

    def generate_caption_preview(self):
        input_path = self.input_path.text().strip()
        if not input_path:
            QMessageBox.warning(self, "Missing input", "Please select an input video first.")
            return

        settings = self.derive_silence_settings(self.aggression.value())
        params = {
            "input_path": input_path,
            "silence_db": settings["silence_db"],
            "min_silence": settings["min_silence"],
            "handle_ms": self.handle_ms.value(),
            "breath_ms": self.breath_ms.value(),
            "pause_floor_ms": self.pause_floor_ms.value(),
            "filler_words": [w.strip() for w in self.filler_words.text().split(",") if w.strip()],
        }

        self.progress.setVisible(True)
        self.run_btn.setEnabled(False)
        self.refresh_captions_btn.setEnabled(False)
        self.log.appendPlainText("Generating caption preview...")

        signals = WorkerSignals()
        signals.log.connect(self.log.appendPlainText)
        signals.error.connect(self.on_error)
        signals.finished.connect(self.on_caption_preview_finished)

        worker = CaptionPreviewWorker(params, signals)
        self.thread_pool.start(worker)

    def on_caption_preview_finished(self, result):
        self.progress.setVisible(False)
        self.run_btn.setEnabled(True)
        self.refresh_captions_btn.setEnabled(True)
        segments = result.get("segments", [])
        self.populate_caption_table(segments)
        self.log.appendPlainText(f"Caption preview ready with {len(segments)} segments.")

    def populate_caption_table(self, segments):
        self.caption_table.setRowCount(0)
        for segment in segments:
            row = self.caption_table.rowCount()
            self.caption_table.insertRow(row)

            start = float(segment.get("start", 0.0))
            end = float(segment.get("end", start + 0.12))
            text = str(segment.get("text", "")).strip()

            start_item = QTableWidgetItem(self.format_seconds(start))
            start_item.setData(Qt.UserRole, start)
            start_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)

            end_item = QTableWidgetItem(self.format_seconds(end))
            end_item.setData(Qt.UserRole, end)
            end_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)

            text_item = QTableWidgetItem(text)

            self.caption_table.setItem(row, 0, start_item)
            self.caption_table.setItem(row, 1, end_item)
            self.caption_table.setItem(row, 2, text_item)

    def collect_caption_segments(self):
        segments = []
        for row in range(self.caption_table.rowCount()):
            start_item = self.caption_table.item(row, 0)
            end_item = self.caption_table.item(row, 1)
            text_item = self.caption_table.item(row, 2)
            if not start_item or not end_item or not text_item:
                continue
            text = text_item.text().strip()
            if not text:
                continue
            start = start_item.data(Qt.UserRole)
            end = end_item.data(Qt.UserRole)
            if start is None or end is None:
                continue
            segments.append({"start": float(start), "end": float(end), "text": text})
        return segments

    @staticmethod
    def format_seconds(value):
        total_ms = max(0, int(round(value * 1000)))
        hours = total_ms // 3_600_000
        minutes = (total_ms % 3_600_000) // 60_000
        seconds = (total_ms % 60_000) / 1000.0
        return f"{hours:02d}:{minutes:02d}:{seconds:06.3f}"

    @staticmethod
    def derive_silence_settings(aggression_value):
        quiet_floor_db = -40
        speech_edge_db = -28
        silence_db = int(
            quiet_floor_db + (aggression_value / 100) * (speech_edge_db - quiet_floor_db)
        )

        long_pause = 0.90
        short_pause = 0.35
        min_silence_len = long_pause - (aggression_value / 100) * (long_pause - short_pause)
        return {"silence_db": silence_db, "min_silence": round(min_silence_len, 2)}


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.resize(900, 600)
    window.show()
    sys.exit(app.exec())
